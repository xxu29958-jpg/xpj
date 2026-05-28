"""Device creation + auth token / upload link / pairing code issuance."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Device, PairingCode
from app.services.identity_service._models import (
    PAIRING_CODE_TTL_MINUTES,
    PairingCodeResult,
)
from app.services.identity_service._seed import _clean_name, _ledger_by_id
from app.services.session_lifecycle_service import (
    hash_pairing_code,
    issue_auth_token,
    issue_upload_link,
    new_pairing_code,
    upload_link_expires_at,
)
from app.services.time_service import now_utc, to_iso


def _create_device(db: Session, account_id: int, device_name: str, platform: str) -> Device:
    device = Device(
        account_id=account_id,
        device_name=_clean_name(device_name, "未命名设备"),
        platform=_clean_name(platform, "unknown").lower()[:32],
    )
    db.add(device)
    db.flush()
    return device


def _create_auth_token(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    scope: str,
    expires_at: datetime | None = None,
) -> str:
    return issue_auth_token(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        scope=scope,
        expires_at=expires_at,
    )


def _create_upload_link(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    default_timezone: str | None,
) -> str:
    issued_at = now_utc()
    return issue_upload_link(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        default_timezone=default_timezone,
        expires_at=upload_link_expires_at(issued_at),
    )


def _create_pairing_code(
    db: Session,
    *,
    ledger_id: str,
    account_id: int | None,
    device_name_hint: str | None = None,
    ttl_minutes: int = PAIRING_CODE_TTL_MINUTES,
) -> PairingCodeResult:
    ledger = _ledger_by_id(db, ledger_id)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invalid_request", status_code=422)
    ttl = max(1, min(ttl_minutes, 60))
    expires_at = now_utc() + timedelta(minutes=ttl)
    while True:
        code = new_pairing_code()
        code_hash = hash_pairing_code(code)
        if db.scalar(select(PairingCode.id).where(PairingCode.code_hash == code_hash).limit(1)) is None:
            break
    pairing = PairingCode(
        code_hash=code_hash,
        ledger_id=ledger.ledger_id,
        account_id=account_id,
        device_name_hint=_clean_name(device_name_hint, "") or None,
        expires_at=expires_at,
    )
    db.add(pairing)
    db.flush()
    return PairingCodeResult(pairing_code=code, ledger_name=ledger.name, expires_at=to_iso(expires_at) or "")


def create_pairing_code(
    db: Session,
    *,
    ledger_id: str,
    account_id: int | None,
    device_name_hint: str | None = None,
    ttl_minutes: int = PAIRING_CODE_TTL_MINUTES,
) -> PairingCodeResult:
    result = _create_pairing_code(
        db,
        ledger_id=ledger_id,
        account_id=account_id,
        device_name_hint=device_name_hint,
        ttl_minutes=ttl_minutes,
    )
    db.commit()
    return result
