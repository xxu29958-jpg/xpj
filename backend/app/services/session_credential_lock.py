"""Serialize authenticated identity mutations with bootstrap recovery."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext

_BOOTSTRAP_OWNER_LOCK_CONTEXT = b"ticketbox/bootstrap-owner/v1/global-transaction-lock"
_BOOTSTRAP_OWNER_LOCK_ID = int.from_bytes(
    sha256(_BOOTSTRAP_OWNER_LOCK_CONTEXT).digest()[:8],
    byteorder="big",
    signed=True,
)


def lock_bootstrap_owner_transaction(db: Session) -> None:
    """Serialize bootstrap rotation and sensitive identity writes."""
    # The advisory lock is the first lock in every credential/identity lifecycle
    # transaction.  Suppress autoflush so pending ORM changes cannot acquire a
    # row lock before this global ordering point.
    with db.no_autoflush:
        db.execute(select(func.pg_advisory_xact_lock(_BOOTSTRAP_OWNER_LOCK_ID)))


def _token_is_usable(token: AuthToken, *, checked_at: datetime) -> bool:
    if token.activation_state != "active":
        return False
    if token.revoked_at is not None:
        grace_until = ensure_utc(token.grace_until)
        if token.scope != "app" or grace_until is None or grace_until <= checked_at:
            return False
    expires_at = ensure_utc(token.expires_at)
    return expires_at is None or expires_at > checked_at


def _reload_auth_context(db: Session, token: AuthToken) -> AuthContext:
    row = db.execute(
        select(Account, Device, Ledger, LedgerMember.role)
        .where(Account.id == token.account_id)
        .where(Account.disabled_at.is_(None))
        .where(Device.id == token.device_id)
        .where(Device.account_id == Account.id)
        .where(Device.revoked_at.is_(None))
        .where(Ledger.ledger_id == token.ledger_id)
        .where(Ledger.archived_at.is_(None))
        .where(LedgerMember.ledger_id == Ledger.ledger_id)
        .where(LedgerMember.account_id == Account.id)
        .where(LedgerMember.disabled_at.is_(None))
        .execution_options(populate_existing=True)
        .limit(1)
    ).first()
    if row is None:
        raise AppError("invalid_token", status_code=401)
    account, device, ledger, role = row
    return AuthContext(
        account_id=account.id,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_id=device.id,
        device_name=device.device_name,
        role=str(role),
        scope=token.scope,
        credential_id=token.id,
        credential_hash=token.token_hash,
    )


def lock_and_revalidate_credential_mint_context(
    db: Session,
    auth: AuthContext | None,
) -> AuthContext | None:
    """Acquire the bootstrap lock and revalidate the exact authenticated row."""
    lock_bootstrap_owner_transaction(db)
    if auth is None:
        return None
    if auth.credential_id is None or not auth.credential_hash:
        raise AppError("invalid_token", status_code=401)
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.id == auth.credential_id)
        .where(AuthToken.token_hash == auth.credential_hash)
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if token is None or not _token_is_usable(token, checked_at=now_utc()):
        raise AppError("invalid_token", status_code=401)
    refreshed = _reload_auth_context(db, token)
    if refreshed != auth:
        raise AppError("invalid_token", status_code=401)
    return refreshed


def _lock_and_revalidate_product_session_principal(
    db: Session,
    auth: AuthContext,
    *,
    platform: str,
    fallback_ttl_seconds: int | None,
) -> AuthContext:
    """Revalidate a platform-bound product principal under the lifecycle lock.

    Middleware authentication happens before FastAPI parses a request body.
    A token, device, or membership can change while a slow form is still being
    uploaded, so an unsafe product handler must not authorize from that stale
    snapshot. The caller keeps this transaction open through the business
    mutation commit/rollback.

    Role and display-name changes are deliberately refreshed. Credential,
    account, device, ledger, scope, and platform bindings are immutable for an
    in-flight principal and therefore fail closed when they disagree.
    """
    if platform not in {"desktop", "web"}:
        raise AppError("invalid_token", status_code=401)
    if auth.scope != "app" or auth.credential_id is None or not auth.credential_hash:
        raise AppError("invalid_token", status_code=401)

    lock_bootstrap_owner_transaction(db)
    token = db.scalar(
        select(AuthToken)
        .join(Device, Device.id == AuthToken.device_id)
        .where(AuthToken.id == auth.credential_id)
        .where(AuthToken.token_hash == auth.credential_hash)
        .where(AuthToken.scope == "app")
        .where(AuthToken.activation_state == "active")
        .where(AuthToken.revoked_at.is_(None))
        .where(Device.platform == platform)
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if token is None:
        raise AppError("invalid_token", status_code=401)

    checked_at = now_utc()
    expires_at = ensure_utc(token.expires_at)
    if fallback_ttl_seconds is not None and expires_at is None:
        issued_at = ensure_utc(token.created_at) or token.created_at
        expires_at = issued_at + timedelta(seconds=fallback_ttl_seconds)
    if expires_at is not None and expires_at <= checked_at:
        token.revoked_at = checked_at
        token.grace_until = None
        db.commit()
        raise AppError("invalid_token", status_code=401)

    refreshed = _reload_auth_context(db, token)
    if (
        refreshed.scope != auth.scope
        or refreshed.credential_id != auth.credential_id
        or refreshed.credential_hash != auth.credential_hash
        or refreshed.account_id != auth.account_id
        or refreshed.device_id != auth.device_id
        or refreshed.ledger_id != auth.ledger_id
    ):
        raise AppError("invalid_token", status_code=401)
    return refreshed


def lock_and_revalidate_web_session_principal(
    db: Session,
    auth: AuthContext,
    *,
    platform: str,
    ttl_seconds: int,
) -> AuthContext:
    """Revalidate a Web-surface principal at an unsafe command boundary."""
    return _lock_and_revalidate_product_session_principal(
        db,
        auth,
        platform=platform,
        fallback_ttl_seconds=ttl_seconds,
    )


def lock_and_revalidate_desktop_session_principal(
    db: Session,
    auth: AuthContext,
) -> AuthContext:
    """Revalidate an exact live Desktop principal before a business write."""
    return _lock_and_revalidate_product_session_principal(
        db,
        auth,
        platform="desktop",
        fallback_ttl_seconds=None,
    )


def lock_and_revalidate_mutation_actor(
    db: Session,
    auth: AuthContext | None,
    *,
    actor_account_id: int | None,
    ledger_id: str | None = None,
) -> AuthContext | None:
    """Revalidate a network credential and bind it to the mutation actor.

    ``auth=None`` is reserved for explicit loopback/internal callers such as the
    Owner Console. It still acquires the global lifecycle lock so those writes
    serialize with bootstrap recovery.
    """
    locked_auth = lock_and_revalidate_credential_mint_context(db, auth)
    if locked_auth is None:
        return None
    if actor_account_id is None or locked_auth.account_id != actor_account_id:
        raise AppError("invalid_token", status_code=401)
    if ledger_id is not None and locked_auth.ledger_id != ledger_id:
        raise AppError("invalid_token", status_code=401)
    return locked_auth
