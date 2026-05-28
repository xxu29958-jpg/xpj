"""Authentication: session token / web cookie session / upload link."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember, UploadLink
from app.services.identity_service._models import WebSessionAuthResult
from app.services.session_lifecycle_service import hash_secret
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext

ACTIVITY_REFRESH_MIN_INTERVAL_SECONDS = 60


def _role_for(db: Session, ledger_id: str, account_id: int) -> str:
    member = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )
    if member is None:
        raise AppError("invalid_token", status_code=401)
    return member.role


def _context_parts_from_ids(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
) -> tuple[Account, Device, Ledger, str]:
    row = db.execute(
        select(Account, Device, Ledger, LedgerMember.role)
        .where(Account.id == account_id)
        .where(Account.disabled_at.is_(None))
        .where(Device.id == device_id)
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
        raise AppError("invalid_token", status_code=401)
    account, device, ledger, role = row
    return account, device, ledger, str(role)


def _context_parts_from_token(db: Session, token: AuthToken) -> tuple[Account, Device, Ledger, str]:
    return _context_parts_from_ids(
        db,
        account_id=token.account_id,
        device_id=token.device_id,
        ledger_id=token.ledger_id,
    )


def _auth_context_from_parts(
    token: AuthToken, account: Account, device: Device, ledger: Ledger, role: str
) -> AuthContext:
    return AuthContext(
        account_id=account.id,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_id=device.id,
        device_name=device.device_name,
        role=role,
        scope=token.scope,
    )


def _refresh_token_activity(
    db: Session,
    token: AuthToken,
    device: Device,
    *,
    now: datetime,
    min_interval_seconds: int = ACTIVITY_REFRESH_MIN_INTERVAL_SECONDS,
) -> bool:
    last_used_at = ensure_utc(token.last_used_at)
    last_seen_at = ensure_utc(device.last_seen_at)
    if (
        min_interval_seconds > 0
        and last_used_at is not None
        and last_seen_at is not None
        and last_used_at + timedelta(seconds=min_interval_seconds) > now
        and last_seen_at + timedelta(seconds=min_interval_seconds) > now
    ):
        return False
    token.last_used_at = now
    device.last_seen_at = now
    db.commit()
    return True


def _context_from_token(db: Session, token: AuthToken) -> AuthContext:
    account, device, ledger, role = _context_parts_from_token(db, token)
    context = _auth_context_from_parts(token, account, device, ledger, role)
    now = now_utc()
    _refresh_token_activity(db, token, device, now=now)
    return context


def _refresh_upload_link_activity(
    db: Session,
    link: UploadLink,
    device: Device,
    *,
    now: datetime,
    min_interval_seconds: int = ACTIVITY_REFRESH_MIN_INTERVAL_SECONDS,
) -> bool:
    last_used_at = ensure_utc(link.last_used_at)
    last_seen_at = ensure_utc(device.last_seen_at)
    if (
        min_interval_seconds > 0
        and last_used_at is not None
        and last_seen_at is not None
        and last_used_at + timedelta(seconds=min_interval_seconds) > now
        and last_seen_at + timedelta(seconds=min_interval_seconds) > now
    ):
        return False
    link.last_used_at = now
    device.last_seen_at = now
    db.commit()
    return True


def authenticate_session_token(db: Session, token_value: str, allowed_scopes: set[str]) -> AuthContext:
    token_hash = hash_secret(token_value)
    token = db.scalar(
        select(AuthToken).where(AuthToken.token_hash == token_hash).where(AuthToken.revoked_at.is_(None)).limit(1)
    )
    if token is None or token.scope not in allowed_scopes:
        raise AppError("invalid_token", status_code=401)
    now = now_utc()
    expires_at = ensure_utc(token.expires_at)
    if expires_at is not None and expires_at <= now:
        token.revoked_at = now
        db.commit()
        raise AppError("invalid_token", status_code=401)
    return _context_from_token(db, token)


def authenticate_web_session_token(
    db: Session,
    token_value: str,
    *,
    ttl_seconds: int,
) -> WebSessionAuthResult:
    """Authenticate a browser cookie session with a fixed server-side TTL."""
    token_hash = hash_secret(token_value)
    token = db.scalar(
        select(AuthToken)
        .join(Device, Device.id == AuthToken.device_id)
        .where(AuthToken.token_hash == token_hash)
        .where(AuthToken.revoked_at.is_(None))
        .where(AuthToken.scope == "app")
        .where(Device.platform == "web")
        .limit(1)
    )
    if token is None:
        raise AppError("invalid_token", status_code=401)

    account, device, ledger, role = _context_parts_from_token(db, token)
    now = now_utc()
    expires_at = ensure_utc(token.expires_at)
    if expires_at is None:
        issued_at = ensure_utc(token.created_at) or token.created_at
        expires_at = issued_at + timedelta(seconds=ttl_seconds)
    if expires_at <= now:
        token.revoked_at = now
        db.commit()
        raise AppError("invalid_token", status_code=401)
    return WebSessionAuthResult(
        auth=_auth_context_from_parts(token, account, device, ledger, role),
        refreshed=False,
    )


def find_active_upload_link(db: Session, *, upload_key: str) -> UploadLink | None:
    """Raw active-link lookup keyed by ``upload_key`` hash.

    Returns ``None`` for unknown/revoked keys so callers can decide the
    failure surface (the public iOS Shortcut path responds 401; admin
    flows might 404 instead). The full
    :func:`authenticate_upload_link` builds on this and adds
    account/device/ledger sanity checks.
    """
    return db.scalar(
        select(UploadLink)
        .where(UploadLink.token_hash == hash_secret(upload_key))
        .where(UploadLink.revoked_at.is_(None))
        .limit(1)
    )


def authenticate_upload_link(db: Session, upload_key: str) -> AuthContext:
    link = find_active_upload_link(db, upload_key=upload_key)
    if link is None:
        raise AppError("invalid_token", status_code=401)
    now = now_utc()
    expires_at = ensure_utc(link.expires_at)
    if expires_at is None or expires_at <= now:
        link.revoked_at = now
        db.commit()
        raise AppError("invalid_token", status_code=401)
    account, device, ledger, role = _context_parts_from_ids(
        db,
        account_id=link.account_id,
        device_id=link.device_id,
        ledger_id=link.ledger_id,
    )
    context = AuthContext(
        account_id=account.id,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_id=device.id,
        device_name=device.device_name,
        role=role,
        scope="upload",
    )
    _refresh_upload_link_activity(db, link, device, now=now)
    return context


def upload_link_default_timezone(db: Session, upload_key: str) -> str | None:
    link = db.scalar(
        select(UploadLink)
        .where(UploadLink.token_hash == hash_secret(upload_key))
        .where(UploadLink.revoked_at.is_(None))
        .limit(1)
    )
    return link.default_timezone if link is not None else None
