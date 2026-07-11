"""Serialize credential minting with bootstrap exposure recovery."""

from __future__ import annotations

from datetime import datetime
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
    """Serialize bootstrap rotation and credential minting in this transaction."""
    # The advisory lock is the first lock in every credential lifecycle
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
