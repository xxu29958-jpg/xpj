"""Serialize authenticated identity mutations with bootstrap recovery."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext, SessionPrincipal

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
    if token.revoked_at is not None:
        grace_until = ensure_utc(token.grace_until)
        if token.scope != "app" or grace_until is None or grace_until <= checked_at:
            return False
    expires_at = ensure_utc(token.expires_at)
    return expires_at is None or expires_at > checked_at


def _reload_auth_context(
    db: Session,
    token: AuthToken,
    *,
    selected_ledger_id: str | None = None,
) -> AuthContext:
    ledger_id = selected_ledger_id or token.ledger_id
    row = db.execute(
        select(Account, Device, Ledger, LedgerMember.role)
        .where(Account.id == token.account_id)
        .where(Account.disabled_at.is_(None))
        .where(Device.id == token.device_id)
        .where(Device.account_id == Account.id)
        .where(Device.revoked_at.is_(None))
        .where(Ledger.ledger_id == ledger_id)
        .where(Ledger.archived_at.is_(None))
        .where(LedgerMember.ledger_id == Ledger.ledger_id)
        .where(LedgerMember.account_id == Account.id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    ).first()
    if row is None:
        _reload_session_principal(db, token)
        raise AppError("ledger_forbidden", status_code=403)
    account, device, ledger, role = row
    return AuthContext(
        account_id=account.id,
        account_public_id=account.public_id,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_id=device.id,
        device_public_id=device.public_id,
        device_name=device.device_name,
        role=str(role),
        scope=token.scope,
        credential_id=token.id,
        credential_hash=token.token_hash,
    )


def _same_auth_binding(left: AuthContext, right: AuthContext) -> bool:
    return (
        left.account_id,
        left.account_public_id,
        left.ledger_id,
        left.device_id,
        left.device_public_id,
        left.scope,
        left.credential_id,
        left.credential_hash,
    ) == (
        right.account_id,
        right.account_public_id,
        right.ledger_id,
        right.device_id,
        right.device_public_id,
        right.scope,
        right.credential_id,
        right.credential_hash,
    )


def _same_session_binding(left: SessionPrincipal, right: SessionPrincipal) -> bool:
    return (
        left.account_id,
        left.account_public_id,
        left.device_id,
        left.device_public_id,
        left.scope,
        left.credential_id,
        left.credential_hash,
    ) == (
        right.account_id,
        right.account_public_id,
        right.device_id,
        right.device_public_id,
        right.scope,
        right.credential_id,
        right.credential_hash,
    )


def _reload_session_principal(
    db: Session,
    token: AuthToken,
) -> SessionPrincipal:
    row = db.execute(
        select(Account, Device)
        .where(Account.id == token.account_id)
        .where(Account.disabled_at.is_(None))
        .where(Device.id == token.device_id)
        .where(Device.account_id == Account.id)
        .where(Device.revoked_at.is_(None))
        .limit(1)
    ).first()
    if row is None:
        raise AppError("invalid_token", status_code=401)
    account, device = row
    return SessionPrincipal(
        account_id=account.id,
        account_public_id=account.public_id,
        account_name=account.display_name,
        device_id=device.id,
        device_public_id=device.public_id,
        device_name=device.device_name,
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
    refreshed = _reload_auth_context(
        db,
        token,
        selected_ledger_id=auth.ledger_id,
    )
    if not _same_auth_binding(refreshed, auth):
        raise AppError("invalid_token", status_code=401)
    if refreshed.role != auth.role:
        raise AppError("permission_denied", status_code=403)
    return refreshed


def lock_and_revalidate_session_principal(
    db: Session,
    principal: SessionPrincipal | None,
) -> SessionPrincipal | None:
    """Lock and revalidate a ledger-independent Account/Device principal."""

    lock_bootstrap_owner_transaction(db)
    if principal is None:
        return None
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.id == principal.credential_id)
        .where(AuthToken.token_hash == principal.credential_hash)
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if token is None or not _token_is_usable(token, checked_at=now_utc()):
        raise AppError("invalid_token", status_code=401)
    refreshed = _reload_session_principal(db, token)
    if not _same_session_binding(refreshed, principal):
        raise AppError("invalid_token", status_code=401)
    return refreshed


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
        raise AppError("ledger_forbidden", status_code=403)
    return locked_auth
