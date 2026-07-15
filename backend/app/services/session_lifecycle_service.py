"""Session, token, and short-lived credential lifecycle helpers.

This module owns the low-level invariants around one-shot credentials and
ledger-scoped auth tokens. Business services still decide permissions and
roles; they call these helpers for the shared atomic state transitions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuthToken, Device, PairingCode, UploadLink
from app.services.session_credential_lock import (
    lock_and_revalidate_credential_mint_context,
    lock_bootstrap_owner_transaction,
)
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext

PairingConsumeResult = Literal["consumed", "used", "expired"]
PAIRING_CODE_DIGITS = 8
PAIRING_CODE_HASH_ITERATIONS = 120_000
PAIRING_CODE_HASH_SALT = b"ticketbox-pairing-code-v2"
ENROLLMENT_ATTEMPT_SECRET_CONTEXT = b"ticketbox/device-enrollment/v1/attempt-secret\0"
ENROLLMENT_SESSION_TOKEN_CONTEXT = b"ticketbox/device-enrollment/v1/session-token\0"
SESSION_REFRESH_SECRET_CONTEXT = b"ticketbox/session-refresh/v1/attempt-secret\0"
SESSION_REFRESH_TOKEN_CONTEXT = b"ticketbox/session-refresh/v1/session-token\0"
ATTEMPT_SECRET_BYTES = 32
# Cross-runtime protocol identifiers: never change a v1 context in place.
BOOTSTRAP_ADMIN_TOKEN_CONTEXT = b"ticketbox/bootstrap-owner/v1/admin-token"
BOOTSTRAP_UPLOAD_KEY_CONTEXT = b"ticketbox/bootstrap-owner/v1/upload-key"
BOOTSTRAP_PAIRING_CODE_CONTEXT = b"ticketbox/bootstrap-owner/v1/pairing-code"
BOOTSTRAP_SECRET_MIN_BYTES = 32


@dataclass(frozen=True)
class AppTokenExpiryWindow:
    expires_at: datetime | None
    soft_refresh_after: datetime | None


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def hash_pairing_code(code: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        code.strip().encode("utf-8"),
        PAIRING_CODE_HASH_SALT,
        PAIRING_CODE_HASH_ITERATIONS,
    ).hex()


def _decode_attempt_secret(secret: str) -> bytes:
    """Decode and verify the canonical 256-bit attempt proof."""

    try:
        raw = base64.urlsafe_b64decode(secret.encode("ascii") + b"=")
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("invalid attempt secret") from exc
    canonical = _base64url_without_padding(raw)
    if len(raw) != ATTEMPT_SECRET_BYTES or not hmac.compare_digest(canonical, secret):
        raise ValueError("invalid attempt secret")
    return raw


def _hash_attempt_secret(secret: str, *, context: bytes) -> str:
    return hashlib.sha256(context + _decode_attempt_secret(secret)).hexdigest()


def _derive_attempt_token(secret: str, attempt_id: str, *, context: bytes) -> str:
    raw = _decode_attempt_secret(secret)
    try:
        attempt_bytes = UUID(attempt_id).bytes
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid attempt id") from exc
    digest = hmac.new(raw, context + attempt_bytes, hashlib.sha256).digest()
    return f"tbx_{_base64url_without_padding(digest)}"


def hash_enrollment_attempt_secret(secret: str) -> str:
    """Hash a canonical high-entropy attempt proof for persistence."""

    return _hash_attempt_secret(
        secret,
        context=ENROLLMENT_ATTEMPT_SECRET_CONTEXT,
    )


def derive_enrollment_session_token(secret: str, attempt_id: str) -> str:
    """Derive the stable session result for one recoverable enrollment."""

    return _derive_attempt_token(
        secret,
        attempt_id,
        context=ENROLLMENT_SESSION_TOKEN_CONTEXT,
    )


def hash_session_refresh_attempt_secret(secret: str) -> str:
    return _hash_attempt_secret(secret, context=SESSION_REFRESH_SECRET_CONTEXT)


def derive_session_refresh_token(secret: str, attempt_id: str) -> str:
    return _derive_attempt_token(
        secret,
        attempt_id,
        context=SESSION_REFRESH_TOKEN_CONTEXT,
    )


def _derive_bootstrap_digest(secret: str, *, context: bytes) -> bytes:
    secret_bytes = secret.encode("utf-8")
    if len(secret_bytes) < BOOTSTRAP_SECRET_MIN_BYTES:
        raise ValueError("bootstrap secret must contain at least 32 UTF-8 bytes")
    return hmac.new(secret_bytes, context, hashlib.sha256).digest()


def _base64url_without_padding(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def derive_bootstrap_admin_token(secret: str) -> str:
    digest = _derive_bootstrap_digest(
        secret,
        context=BOOTSTRAP_ADMIN_TOKEN_CONTEXT,
    )
    return f"tbx_{_base64url_without_padding(digest)}"


def derive_bootstrap_upload_key(secret: str) -> str:
    digest = _derive_bootstrap_digest(
        secret,
        context=BOOTSTRAP_UPLOAD_KEY_CONTEXT,
    )
    return f"upl_{_base64url_without_padding(digest)}"


def derive_bootstrap_pairing_code(secret: str) -> str:
    digest = _derive_bootstrap_digest(
        secret,
        context=BOOTSTRAP_PAIRING_CODE_CONTEXT,
    )
    value = int.from_bytes(digest, byteorder="big", signed=False)
    return f"{value % (10**PAIRING_CODE_DIGITS):0{PAIRING_CODE_DIGITS}d}"


def new_pairing_code() -> str:
    return f"{secrets.randbelow(10**PAIRING_CODE_DIGITS):0{PAIRING_CODE_DIGITS}d}"


def new_session_token() -> str:
    return f"tbx_{secrets.token_urlsafe(32)}"


def new_upload_key() -> str:
    return f"upl_{secrets.token_urlsafe(32)}"


def app_token_expiry_window(issued_at: datetime) -> AppTokenExpiryWindow:
    """Return the configured app-token expiry contract for a newly issued token."""

    from app.config import get_settings

    cfg = get_settings()
    if cfg.app_token_ttl_days <= 0:
        return AppTokenExpiryWindow(expires_at=None, soft_refresh_after=None)
    expires_at = issued_at + timedelta(days=cfg.app_token_ttl_days)
    soft_refresh_after = app_token_soft_refresh_after(expires_at)
    return AppTokenExpiryWindow(
        expires_at=expires_at,
        soft_refresh_after=soft_refresh_after,
    )


def app_token_soft_refresh_after(expires_at: datetime | None) -> datetime | None:
    """Reconstruct the refresh threshold for an unchanged app session."""

    if expires_at is None:
        return None
    from app.config import get_settings

    refresh_days = max(get_settings().app_token_refresh_window_days, 0)
    return expires_at - timedelta(days=refresh_days) if refresh_days > 0 else None


def upload_link_expires_at(issued_at: datetime) -> datetime:
    """Return the hard expiry timestamp for newly issued UploadLinks."""

    from app.config import get_settings

    return issued_at + timedelta(days=max(get_settings().upload_link_ttl_days, 1))


def issue_auth_token(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    scope: str,
    expires_at: datetime | None = None,
    token_value: str | None = None,
) -> str:
    token = token_value if token_value is not None else new_session_token()
    db.add(
        AuthToken(
            token_hash=hash_secret(token),
            account_id=account_id,
            device_id=device_id,
            ledger_id=ledger_id,
            scope=scope,
            expires_at=expires_at,
        )
    )
    db.flush()
    return token


def issue_upload_link(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    default_timezone: str | None,
    expires_at: datetime,
    upload_key_value: str | None = None,
) -> str:
    upload_key = upload_key_value if upload_key_value is not None else new_upload_key()
    db.add(
        UploadLink(
            token_hash=hash_secret(upload_key),
            account_id=account_id,
            device_id=device_id,
            ledger_id=ledger_id,
            default_timezone=default_timezone,
            expires_at=expires_at,
        )
    )
    db.flush()
    return upload_key


def consume_pairing_code(
    db: Session,
    *,
    pairing_id: int,
    expected_code_hash: str,
    used_at: datetime | None = None,
) -> PairingConsumeResult:
    used_at = used_at or now_utc()
    result = db.execute(
        update(PairingCode)
        .where(PairingCode.id == pairing_id)
        .where(PairingCode.code_hash == expected_code_hash)
        .where(PairingCode.used_at.is_(None))
        .where(PairingCode.expires_at > used_at)
        .values(used_at=used_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        return "consumed"
    refreshed = db.scalar(
        select(PairingCode)
        .where(PairingCode.id == pairing_id)
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if refreshed is None or refreshed.code_hash != expected_code_hash:
        return "expired"
    expires_at = ensure_utc(refreshed.expires_at) or refreshed.expires_at
    if expires_at <= used_at:
        return "expired"
    if refreshed.used_at is not None:
        return "used"
    return "expired"


def revoke_active_tokens(
    db: Session,
    *,
    revoked_at: datetime | None = None,
    account_ids: list[int] | tuple[int, ...] | set[int] | None = None,
    account_id: int | None = None,
    device_id: int | None = None,
    ledger_id: str | None = None,
    scope: str | None = None,
) -> int:
    lock_bootstrap_owner_transaction(db)
    revoked_at = revoked_at or now_utc()
    statement = update(AuthToken).where(AuthToken.revoked_at.is_(None))
    if account_ids is not None:
        ids = list(account_ids)
        if not ids:
            return 0
        statement = statement.where(AuthToken.account_id.in_(ids))
    if account_id is not None:
        statement = statement.where(AuthToken.account_id == account_id)
    if device_id is not None:
        statement = statement.where(AuthToken.device_id == device_id)
    if ledger_id is not None:
        statement = statement.where(AuthToken.ledger_id == ledger_id)
    if scope is not None:
        statement = statement.where(AuthToken.scope == scope)
    result = db.execute(
        statement.values(revoked_at=revoked_at, grace_until=None).execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def revoke_web_session_token(db: Session, *, token_value: str, revoked_at: datetime | None = None) -> bool:
    """Revoke a /web logout cookie if (and only if) it backs an active web session.

    The /web ``__Host-session`` cookie is the only place a scope=app
    token gets attached to a ``platform="web"`` device. Other tokens
    (Android pairing, upload links) must never be silently revoked from
    a /web cookie value, so the check is strict: scope=app + device
    present + ``device.platform == "web"`` + token not already revoked.

    Returns ``True`` when this call revoked the token, ``False`` when
    nothing matched. Always commits.
    """
    lock_bootstrap_owner_transaction(db)
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value)).limit(1))
    if row is None or row.revoked_at is not None or row.scope != "app":
        return False
    device = db.get(Device, row.device_id)
    if device is None or (device.platform or "").strip().lower() != "web":
        return False
    row.revoked_at = revoked_at or now_utc()
    row.grace_until = None
    db.commit()
    return True


def revoke_token_value(
    db: Session,
    *,
    token_value: str,
    revoked_at: datetime | None = None,
    scope: str | None = None,
) -> int:
    lock_bootstrap_owner_transaction(db)
    revoked_at = revoked_at or now_utc()
    statement = (
        update(AuthToken).where(AuthToken.token_hash == hash_secret(token_value)).where(AuthToken.revoked_at.is_(None))
    )
    if scope is not None:
        statement = statement.where(AuthToken.scope == scope)
    result = db.execute(
        statement.values(revoked_at=revoked_at, grace_until=None).execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def rotate_app_token_for_ledger(
    db: Session,
    *,
    auth: AuthContext,
    current_token_value: str,
    account_id: int,
    device_id: int,
    target_ledger_id: str,
    rotated_at: datetime | None = None,
    expires_at: datetime | None = None,
    allow_grace: bool = False,
) -> tuple[str, datetime]:
    # Exposure recovery and normal app-token replacement share one transaction
    # lock. Authentication happened before this service call, so re-read the
    # exact credential id+hash under the lock before revoking or minting.
    if hash_secret(current_token_value) != auth.credential_hash:
        raise AppError("invalid_token", status_code=401)
    locked_auth = lock_and_revalidate_credential_mint_context(db, auth)
    if (
        locked_auth is None
        or locked_auth.scope != "app"
        or locked_auth.account_id != account_id
        or locked_auth.device_id != device_id
    ):
        raise AppError("invalid_token", status_code=401)
    rotated_at = rotated_at or now_utc()
    current_hash = hash_secret(current_token_value)
    from app.config import get_settings

    grace_seconds = max(get_settings().app_token_rotation_grace_seconds, 0) if allow_grace else 0
    grace_until = rotated_at + timedelta(seconds=grace_seconds) if grace_seconds > 0 else None

    result = db.execute(
        update(AuthToken)
        .where(AuthToken.id == locked_auth.credential_id)
        .where(AuthToken.token_hash == current_hash)
        .where(AuthToken.account_id == account_id)
        .where(AuthToken.device_id == device_id)
        .where(AuthToken.scope == "app")
        .where(AuthToken.revoked_at.is_(None))
        .values(revoked_at=rotated_at, grace_until=grace_until)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise AppError("invalid_token", status_code=401)

    new_token = issue_auth_token(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=target_ledger_id,
        scope="app",
        expires_at=expires_at,
    )
    return new_token, rotated_at
