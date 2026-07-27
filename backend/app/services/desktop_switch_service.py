"""Desktop two-phase ledger switch: stage a pending credential (218-E).

The Desktop switch mirrors desktop pairing: ``switch/prepare`` stages the
client-derived ``desktop_pending`` value on the target ledger, the
``DesktopActivationAttempt`` receipt makes a response-loss replay return the
same staging instead of minting a second credential, and only
``activate_desktop_session`` can promote it. The authenticated source
session stays live and usable until the activation supersedes it (or it is
explicitly revoked).
"""

from __future__ import annotations

import hmac
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuthToken, DesktopActivationAttempt, Device, Ledger, LedgerMember
from app.services.desktop_activation_service import (
    DESKTOP_PENDING_SCOPE,
    DESKTOP_PLATFORM,
    find_live_pending_token,
    stage_desktop_pending_token,
)
from app.services.ledger_contracts import DesktopLedgerSwitchPrepareResult
from app.services.ledger_service import _lock_ledger_switch_context
from app.services.session_lifecycle_service import (
    derive_desktop_activation_token,
    hash_desktop_activation_attempt_secret,
    hash_secret,
    revoke_token_value,
)
from app.services.time_service import ensure_utc, now_utc, to_iso
from app.tenants import DEFAULT_TENANT_ID, AuthContext, SessionPrincipal


def _stage_or_replay_switch_pending(
    db: Session,
    *,
    locked_principal: SessionPrincipal,
    ledger: Ledger,
    device: Device,
    activation_attempt_id: str,
    activation_attempt_secret: str,
    checked_at: datetime,
) -> tuple[str, datetime | None]:
    """Return the client-derived pending value + staging expiry.

    First call stages; a response-loss replay with the same attempt proof
    returns the committed staging unchanged. A foreign proof or a dead
    (superseded/expired) staging fails closed — the client retries with a
    fresh attempt.
    """
    try:
        secret_hash = hash_desktop_activation_attempt_secret(activation_attempt_secret)
        pending_value = derive_desktop_activation_token(activation_attempt_secret, activation_attempt_id)
    except ValueError as exc:
        raise AppError("invalid_token", status_code=401) from exc

    attempt = db.scalar(
        select(DesktopActivationAttempt)
        .where(DesktopActivationAttempt.public_id == activation_attempt_id)
        .with_for_update()
        .limit(1)
    )
    if attempt is None:
        staged = stage_desktop_pending_token(
            db,
            account_id=locked_principal.account_id,
            device_id=device.id,
            ledger_id=ledger.ledger_id,
            attempt_public_id=activation_attempt_id,
            activation_secret=activation_attempt_secret,
            # Lineage for unpair: a session revoke must find and kill the
            # replacements this source credential staged (promoted or not).
            previous_token_id=locked_principal.credential_id,
            issued_at=checked_at,
        )
        return pending_value, staged.expires_at
    if (
        not hmac.compare_digest(attempt.secret_hash, secret_hash)
        or attempt.account_id != locked_principal.account_id
        or attempt.device_id != device.id
        or attempt.ledger_id != ledger.ledger_id
    ):
        raise AppError("invalid_token", status_code=401)
    pending = find_live_pending_token(db, session_token_hash=hash_secret(pending_value))
    if pending is None or pending.id != attempt.token_id:
        raise AppError("invalid_token", status_code=401)
    attempt.last_issued_at = checked_at
    return pending_value, pending.expires_at


def prepare_desktop_ledger_switch(
    db: Session,
    *,
    principal: SessionPrincipal,
    target_ledger_id: str,
    activation_attempt_id: str,
    activation_attempt_secret: str,
) -> DesktopLedgerSwitchPrepareResult:
    """Stage a ``desktop_pending`` credential on the target ledger.

    A replay with a foreign attempt proof, or one whose staged credential was
    superseded/expired, fails closed: the client retries with a fresh attempt.
    """
    locked_principal, ledger, membership, device = _lock_ledger_switch_context(
        db,
        principal=principal,
        account_id=principal.account_id,
        device_id=principal.device_id,
        target_ledger_id=target_ledger_id,
    )
    if (device.platform or "") != DESKTOP_PLATFORM:
        raise AppError("invalid_token", status_code=401)
    # A graced (revoked, in rotation window) desktop credential must never
    # stage a replacement: its holder could otherwise activate a fresh 90-day
    # session and supersede the legitimate successor. The source credential is
    # already under the credential lock, so require it to be unrevoked here.
    source_token = db.get(AuthToken, locked_principal.credential_id)
    if source_token is None or source_token.revoked_at is not None:
        raise AppError("invalid_token", status_code=401)
    pending_value, pending_expires_at = _stage_or_replay_switch_pending(
        db,
        locked_principal=locked_principal,
        ledger=ledger,
        device=device,
        activation_attempt_id=activation_attempt_id,
        activation_attempt_secret=activation_attempt_secret,
        checked_at=now_utc(),
    )
    db.commit()

    return DesktopLedgerSwitchPrepareResult(
        session_token=pending_value,
        account_public_id=locked_principal.account_public_id,
        device_public_id=device.public_id,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        role=str(membership.role),
        is_default=(ledger.ledger_id == DEFAULT_TENANT_ID),
        created_at=to_iso(ledger.created_at),
        archived_at=to_iso(ledger.archived_at),
        account_name=locked_principal.account_name,
        device_name=device.device_name,
        activation_expires_at=to_iso(ensure_utc(pending_expires_at)),
    )


def revalidate_desktop_session_under_lock(db: Session, session_auth) -> str:
    """Revalidate the bridged desktop principal in the handler's transaction.

    The middleware authenticated the bearer in its own session and stashed a
    detached AuthContext; a membership disable/demote, or a device/token
    revocation landing between that check and a mutation's commit, must not
    let the write through. Re-read token row, device, and membership under
    FOR UPDATE in the same transaction the handler will commit. Returns the
    live membership role so the caller can refresh the (frozen) context.
    """
    row = db.execute(
        select(AuthToken, Device, LedgerMember)
        .where(AuthToken.id == session_auth.credential_id)
        .where(AuthToken.revoked_at.is_(None))
        .where(Device.id == AuthToken.device_id)
        .where(Device.revoked_at.is_(None))
        .where(LedgerMember.ledger_id == session_auth.ledger_id)
        .where(LedgerMember.account_id == session_auth.account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .with_for_update()
        .limit(1)
    ).first()
    if row is None:
        raise AppError("invalid_token", status_code=401)
    token, _device, membership = row
    expires_at = ensure_utc(token.expires_at)
    if expires_at is not None and expires_at <= now_utc():
        token.revoked_at = now_utc()
        token.grace_until = None
        db.commit()
        raise AppError("invalid_token", status_code=401)
    return str(membership.role)


def revoke_desktop_app_session(
    db: Session,
    *,
    auth: AuthContext,
    token_value: str,
) -> None:
    """Revoke the presented credential, its staged pending rows, and promoted
    replacements whose receipt names it as predecessor. Other lineages and the
    device stay untouched.
    """

    if (
        auth.scope != "app"
        or auth.credential_hash is None
        or not hmac.compare_digest(hash_secret(token_value), auth.credential_hash)
    ):
        raise AppError("invalid_token", status_code=401)
    revoked = revoke_token_value(db, token_value=token_value, scope="app")
    if revoked != 1:
        db.rollback()
        raise AppError("invalid_token", status_code=401)
    promoted_ids = select(DesktopActivationAttempt.token_id).where(
        DesktopActivationAttempt.previous_token_id == auth.credential_id,
        DesktopActivationAttempt.activated_at.is_not(None),
    )
    replacement_rows = db.scalars(
        select(AuthToken)
        .where(
            AuthToken.account_id == auth.account_id,
            AuthToken.device_id == auth.device_id,
            AuthToken.revoked_at.is_(None),
            (AuthToken.scope == DESKTOP_PENDING_SCOPE) | AuthToken.id.in_(promoted_ids),
        )
        .with_for_update()
    ).all()
    staged_at = now_utc()
    for replacement in replacement_rows:
        replacement.revoked_at = staged_at
        replacement.grace_until = None
    db.commit()
