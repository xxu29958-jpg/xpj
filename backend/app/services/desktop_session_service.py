"""Two-phase Desktop app-session preparation and activation.

The Manager must durably store a replacement bearer before it can displace
the current bearer.  A prepared token is therefore hash-only in PostgreSQL,
short-lived, and deliberately rejected by every ordinary app authenticator.
Possession of that pending bearer authorizes only this module's activation
transition.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember
from app.services.identity_service._models import (
    DESKTOP_PENDING_TOKEN_TTL_SECONDS,
    DesktopSessionResult,
)
from app.services.session_credential_lock import (
    lock_and_revalidate_credential_mint_context,
    lock_bootstrap_owner_transaction,
)
from app.services.session_lifecycle_service import (
    app_token_expiry_window,
    hash_secret,
    issue_auth_token,
)
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext


def _load_live_principal(
    db: Session,
    token: AuthToken,
) -> tuple[Account, Device, Ledger, LedgerMember]:
    row = db.execute(
        select(Account, Device, Ledger, LedgerMember)
        .where(Account.id == token.account_id)
        .where(Account.disabled_at.is_(None))
        .where(Device.id == token.device_id)
        .where(Device.account_id == Account.id)
        .where(Device.revoked_at.is_(None))
        .where(Device.platform == "desktop")
        .where(Ledger.ledger_id == token.ledger_id)
        .where(Ledger.archived_at.is_(None))
        .where(LedgerMember.ledger_id == Ledger.ledger_id)
        .where(LedgerMember.account_id == Account.id)
        .where(LedgerMember.disabled_at.is_(None))
        .with_for_update()
        .limit(1)
    ).first()
    if row is None:
        raise AppError("invalid_token", status_code=401)
    return row


def _soft_refresh_after(expires_at):
    result = None
    if expires_at is not None:
        from app.config import get_settings

        refresh_days = max(get_settings().app_token_refresh_window_days, 0)
        if refresh_days > 0:
            result = expires_at - timedelta(days=refresh_days)
    return result


def _result(
    account: Account,
    device: Device,
    ledger: Ledger,
    membership: LedgerMember,
    *,
    expires_at,
    activation_required: bool,
) -> DesktopSessionResult:
    return DesktopSessionResult(
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=membership.role,
        expires_at=expires_at,
        soft_refresh_after=(None if activation_required else _soft_refresh_after(expires_at)),
        activation_required=activation_required,
    )


def prepare_desktop_ledger_switch(
    db: Session,
    *,
    auth: AuthContext,
    target_ledger_id: str,
) -> tuple[str, DesktopSessionResult]:
    """Mint pending B while leaving the authenticated active A untouched."""

    locked_auth = lock_and_revalidate_credential_mint_context(db, auth)
    if locked_auth is None or locked_auth.scope != "app":
        raise AppError("invalid_token", status_code=401)
    device = db.scalar(
        select(Device)
        .where(Device.id == locked_auth.device_id)
        .where(Device.account_id == locked_auth.account_id)
        .where(Device.revoked_at.is_(None))
        .where(Device.platform == "desktop")
        .with_for_update()
        .limit(1)
    )
    if device is None:
        raise AppError("invalid_token", status_code=401)
    account = db.get(Account, locked_auth.account_id)
    if account is None or account.disabled_at is not None:
        raise AppError("invalid_token", status_code=401)
    ledger = db.scalar(
        select(Ledger)
        .where(Ledger.ledger_id == target_ledger_id)
        .where(Ledger.archived_at.is_(None))
        .with_for_update()
        .limit(1)
    )
    membership = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == target_ledger_id)
        .where(LedgerMember.account_id == locked_auth.account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .with_for_update()
        .limit(1)
    )
    if ledger is None or membership is None:
        raise AppError("ledger_forbidden", status_code=403)

    prepared_at = now_utc()
    # A response-lost prepare from the same Desktop device cannot be recovered
    # locally, so retire it before returning a single new candidate.  Active A
    # is explicitly excluded and remains usable until activation.
    db.execute(
        update(AuthToken)
        .where(AuthToken.device_id == device.id)
        .where(AuthToken.scope == "app")
        .where(AuthToken.activation_state == "pending")
        .where(AuthToken.revoked_at.is_(None))
        .values(revoked_at=prepared_at, grace_until=None)
        .execution_options(synchronize_session=False)
    )
    pending_expires_at = prepared_at + timedelta(seconds=DESKTOP_PENDING_TOKEN_TTL_SECONDS)
    token_value = issue_auth_token(
        db,
        account_id=locked_auth.account_id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        scope="app",
        activation_state="pending",
        expires_at=pending_expires_at,
    )
    result = _result(
        account,
        device,
        ledger,
        membership,
        expires_at=pending_expires_at,
        activation_required=True,
    )
    db.commit()
    return token_value, result


def _load_activation_token(
    db: Session,
    token_hash: str,
) -> tuple[AuthToken, datetime, datetime | None]:
    lock_bootstrap_owner_transaction(db)
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == token_hash)
        .where(AuthToken.scope == "app")
        .execution_options(populate_existing=True)
        .with_for_update()
        .limit(1)
    )
    if token is None or token.revoked_at is not None:
        raise AppError("invalid_token", status_code=401)

    checked_at = now_utc()
    expires_at = ensure_utc(token.expires_at)
    created_at = ensure_utc(token.created_at)
    pending_deadline = (
        created_at + timedelta(seconds=DESKTOP_PENDING_TOKEN_TTL_SECONDS) if created_at is not None else None
    )
    expiry_invalid = expires_at is not None and expires_at <= checked_at
    if token.activation_state == "pending":
        expiry_invalid = (
            expires_at is None or pending_deadline is None or expires_at > pending_deadline or expires_at <= checked_at
        )
    if expiry_invalid:
        token.revoked_at = checked_at
        token.grace_until = None
        db.commit()
        raise AppError("invalid_token", status_code=401)
    return token, checked_at, expires_at


def _load_live_previous_desktop_token(
    db: Session,
    previous_hash: str | None,
    checked_at: datetime,
) -> AuthToken | None:
    if previous_hash is None:
        return None
    candidate = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == previous_hash)
        .where(AuthToken.scope == "app")
        .where(AuthToken.activation_state == "active")
        .execution_options(populate_existing=True)
        .with_for_update()
        .limit(1)
    )
    if candidate is None:
        return None
    previous_device = db.get(Device, candidate.device_id)
    if (
        previous_device is not None
        and (previous_device.platform or "").strip().lower() != "desktop"
        and candidate.revoked_at is None
    ):
        raise AppError("invalid_token", status_code=401)
    previous_expires_at = ensure_utc(candidate.expires_at)
    if candidate.revoked_at is None and (previous_expires_at is None or previous_expires_at > checked_at):
        return candidate
    return None


def _activate_pending_token(
    db: Session,
    *,
    token: AuthToken,
    previous: AuthToken | None,
    checked_at: datetime,
    account: Account,
    device: Device,
    ledger: Ledger,
    membership: LedgerMember,
) -> DesktopSessionResult:
    db.execute(
        update(AuthToken)
        .where(AuthToken.device_id == token.device_id)
        .where(AuthToken.scope == "app")
        .where(AuthToken.id != token.id)
        .where(AuthToken.revoked_at.is_(None))
        .values(revoked_at=checked_at, grace_until=None)
        .execution_options(synchronize_session=False)
    )
    if previous is not None and previous.device_id != token.device_id:
        previous.revoked_at = checked_at
        previous.grace_until = None
    active_expiry = app_token_expiry_window(checked_at)
    token.activation_state = "active"
    token.expires_at = active_expiry.expires_at
    token.last_used_at = checked_at
    device.last_seen_at = checked_at
    db.commit()
    return DesktopSessionResult(
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=membership.role,
        expires_at=active_expiry.expires_at,
        soft_refresh_after=active_expiry.soft_refresh_after,
        activation_required=False,
    )


def activate_desktop_session(
    db: Session,
    *,
    token_value: str,
    previous_token_value: str | None = None,
) -> DesktopSessionResult:
    """Activate pending B and revoke this device's previous app sessions.

    Replaying the exact still-active B is idempotent.  A B that has expired or
    has since been superseded is never resurrected.
    """

    token_hash = hash_secret(token_value)
    previous_hash = hash_secret(previous_token_value) if previous_token_value is not None else None
    if previous_hash is not None and hmac.compare_digest(
        token_hash,
        previous_hash,
    ):
        raise AppError(
            "desktop_identity_rotation_required",
            "待激活凭证不能与当前桌面凭证相同。",
            status_code=409,
        )

    token, checked_at, expires_at = _load_activation_token(db, token_hash)
    account, device, ledger, membership = _load_live_principal(db, token)
    previous = _load_live_previous_desktop_token(db, previous_hash, checked_at)

    if token.activation_state == "active":
        # Exact response-loss replay: B remains active and the predecessor may
        # already be revoked by the first committed activation.
        result = _result(
            account,
            device,
            ledger,
            membership,
            expires_at=expires_at,
            activation_required=False,
        )
        db.commit()
        return result
    if token.activation_state != "pending":
        raise AppError("invalid_token", status_code=401)
    return _activate_pending_token(
        db,
        token=token,
        previous=previous,
        checked_at=checked_at,
        account=account,
        device=device,
        ledger=ledger,
        membership=membership,
    )


__all__ = [
    "activate_desktop_session",
    "prepare_desktop_ledger_switch",
]
