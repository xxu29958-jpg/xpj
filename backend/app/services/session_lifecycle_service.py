"""Session, token, and short-lived credential lifecycle helpers.

This module owns the low-level invariants around one-shot credentials and
ledger-scoped auth tokens. Business services still decide permissions and
roles; they call these helpers for the shared atomic state transitions.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import secrets
from typing import Literal

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuthToken, PairingCode, UploadLink
from app.services.time_service import now_utc


PairingConsumeResult = Literal["consumed", "used", "expired"]
PAIRING_CODE_DIGITS = 8
PAIRING_CODE_HASH_ITERATIONS = 120_000
PAIRING_CODE_HASH_SALT = b"ticketbox-pairing-code-v2"


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def hash_pairing_code(code: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        code.strip().encode("utf-8"),
        PAIRING_CODE_HASH_SALT,
        PAIRING_CODE_HASH_ITERATIONS,
    ).hex()


def new_pairing_code() -> str:
    return f"{secrets.randbelow(10 ** PAIRING_CODE_DIGITS):0{PAIRING_CODE_DIGITS}d}"


def new_session_token() -> str:
    return f"tbx_{secrets.token_urlsafe(32)}"


def new_upload_key() -> str:
    return f"upl_{secrets.token_urlsafe(32)}"


def issue_auth_token(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    scope: str,
) -> str:
    token = new_session_token()
    db.add(
        AuthToken(
            token_hash=hash_secret(token),
            account_id=account_id,
            device_id=device_id,
            ledger_id=ledger_id,
            scope=scope,
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
) -> str:
    upload_key = new_upload_key()
    db.add(
        UploadLink(
            token_hash=hash_secret(upload_key),
            account_id=account_id,
            device_id=device_id,
            ledger_id=ledger_id,
            default_timezone=default_timezone,
        )
    )
    db.flush()
    return upload_key


def consume_pairing_code(
    db: Session,
    *,
    pairing_id: int,
    used_at: datetime | None = None,
) -> PairingConsumeResult:
    used_at = used_at or now_utc()
    result = db.execute(
        update(PairingCode)
        .where(PairingCode.id == pairing_id)
        .where(PairingCode.used_at.is_(None))
        .where(PairingCode.expires_at > used_at)
        .values(used_at=used_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        return "consumed"
    refreshed = db.get(PairingCode, pairing_id)
    if refreshed is not None and refreshed.used_at is not None:
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
        statement.values(revoked_at=revoked_at).execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def rotate_app_token_for_ledger(
    db: Session,
    *,
    current_token_value: str,
    account_id: int,
    device_id: int,
    target_ledger_id: str,
    rotated_at: datetime | None = None,
) -> tuple[str, datetime]:
    rotated_at = rotated_at or now_utc()
    current_hash = hash_secret(current_token_value)

    result = db.execute(
        update(AuthToken)
        .where(AuthToken.token_hash == current_hash)
        .where(AuthToken.account_id == account_id)
        .where(AuthToken.device_id == device_id)
        .where(AuthToken.scope == "app")
        .where(AuthToken.revoked_at.is_(None))
        .values(revoked_at=rotated_at)
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
    )
    return new_token, rotated_at
