"""Web credential authentication, with separate identity and ledger admission."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device
from app.services.identity_service._auth import (
    _auth_context_from_parts,
    _context_parts_from_token,
    _principal_from_token,
)
from app.services.identity_service._models import WebSessionAuthResult
from app.services.session_lifecycle_service import WEB_SESSION_TTL_SECONDS, hash_secret
from app.services.time_service import ensure_utc, now_utc
from app.tenants import SessionPrincipal


def live_web_device_public_ids(db: Session, *, account_id: int) -> set[str]:
    """Read browser-session availability without changing credentials or devices."""
    checked_at = now_utc()
    legacy_cutoff = checked_at - timedelta(seconds=WEB_SESSION_TTL_SECONDS)
    return set(db.scalars(
        select(Device.public_id)
        .join(AuthToken, AuthToken.device_id == Device.id)
        .join(Account, Account.id == Device.account_id)
        .where(Device.account_id == account_id, AuthToken.account_id == account_id)
        .where(Account.disabled_at.is_(None), Device.revoked_at.is_(None))
        .where(Device.platform == "web", AuthToken.scope == "app")
        .where(AuthToken.revoked_at.is_(None))
        .where(
            (AuthToken.expires_at > checked_at)
            | (AuthToken.expires_at.is_(None) & (AuthToken.created_at > legacy_cutoff))
        )
        .distinct()
    ))


def _load_web_session_token(
    db: Session,
    token_value: str,
    *,
    ttl_seconds: int,
) -> AuthToken:
    """Load the live Web credential without selecting a ledger."""
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

    now = now_utc()
    expires_at = ensure_utc(token.expires_at)
    if expires_at is None:
        issued_at = ensure_utc(token.created_at) or token.created_at
        expires_at = issued_at + timedelta(seconds=ttl_seconds)
    if expires_at <= now:
        token.revoked_at = now
        db.commit()
        raise AppError("invalid_token", status_code=401)
    return token


def authenticate_web_session_principal(
    db: Session,
    token_value: str,
    *,
    ttl_seconds: int,
) -> SessionPrincipal:
    """Prove Web identity for joining a ledger, independent of old membership."""
    token = _load_web_session_token(db, token_value, ttl_seconds=ttl_seconds)
    principal, _ = _principal_from_token(db, token)
    return principal


def authenticate_web_session_token(
    db: Session,
    token_value: str,
    *,
    ttl_seconds: int,
) -> WebSessionAuthResult:
    """Authenticate a browser cookie and its current ledger permissions."""
    token = _load_web_session_token(db, token_value, ttl_seconds=ttl_seconds)
    account, device, ledger, role = _context_parts_from_token(db, token)
    return WebSessionAuthResult(
        auth=_auth_context_from_parts(token, account, device, ledger, role),
        refreshed=False,
    )
