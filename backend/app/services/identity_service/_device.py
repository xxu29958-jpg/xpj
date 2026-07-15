"""Device creation + auth token / upload link / pairing code issuance."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, Device, LedgerMember, PairingCode
from app.services.identity_service._models import (
    PAIRING_CODE_TTL_MINUTES,
    PairingCodeResult,
)
from app.services.identity_service._seed import _clean_name, _ledger_by_id
from app.services.session_credential_lock import lock_and_revalidate_credential_mint_context
from app.services.session_lifecycle_service import (
    hash_pairing_code,
    issue_auth_token,
    issue_upload_link,
    new_pairing_code,
    upload_link_expires_at,
)
from app.services.time_service import now_utc, to_iso
from app.tenants import AuthContext

PAIRING_CODE_CANDIDATE_COUNT = 16


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
    token_value: str | None = None,
) -> str:
    return issue_auth_token(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        scope=scope,
        expires_at=expires_at,
        token_value=token_value,
    )


def _create_upload_link(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    default_timezone: str | None,
    upload_key_value: str | None = None,
) -> str:
    issued_at = now_utc()
    return issue_upload_link(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        default_timezone=default_timezone,
        expires_at=upload_link_expires_at(issued_at),
        upload_key_value=upload_key_value,
    )


def _new_unique_pairing_code(db: Session) -> tuple[str, str]:
    candidates = [
        (code := new_pairing_code(), hash_pairing_code(code))
        for _ in range(PAIRING_CODE_CANDIDATE_COUNT)
    ]
    existing_hashes = set(
        db.scalars(
            select(PairingCode.code_hash).where(PairingCode.code_hash.in_({code_hash for _, code_hash in candidates}))
        )
    )
    for code, code_hash in candidates:
        if code_hash not in existing_hashes:
            return code, code_hash
    raise AppError("server_error", status_code=500)


def _create_pairing_code(
    db: Session,
    *,
    ledger_id: str,
    account_id: int | None,
    created_by_device_id: int | None = None,
    device_name_hint: str | None = None,
    recovery_device_id: int | None = None,
    ttl_minutes: int = PAIRING_CODE_TTL_MINUTES,
    pairing_code_value: str | None = None,
) -> PairingCodeResult:
    ledger = _ledger_by_id(db, ledger_id)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invalid_request", status_code=422)
    account = db.get(Account, account_id) if account_id is not None else None
    if account is None or account.disabled_at is not None:
        raise AppError("invalid_request", "当前成员身份需要修复。", status_code=409)
    membership_id = db.scalar(
        select(LedgerMember.id)
        .where(LedgerMember.ledger_id == ledger.ledger_id)
        .where(LedgerMember.account_id == account.id)
        .where(LedgerMember.disabled_at.is_(None))
    )
    if membership_id is None:
        raise AppError("permission_denied", status_code=403)
    if recovery_device_id is not None:
        recovery_device = db.scalar(
            select(Device.id)
            .where(Device.id == recovery_device_id)
            .where(Device.account_id == account.id)
            .limit(1)
        )
        if recovery_device is None:
            raise AppError("invalid_request", "要恢复的设备不存在。", status_code=404)
    ttl = max(1, min(ttl_minutes, 60))
    expires_at = now_utc() + timedelta(minutes=ttl)
    if pairing_code_value is None:
        code, code_hash = _new_unique_pairing_code(db)
    else:
        code = pairing_code_value
        code_hash = hash_pairing_code(code)
    pairing = PairingCode(
        code_hash=code_hash,
        ledger_id=ledger.ledger_id,
        account_id=account_id,
        created_by_device_id=created_by_device_id,
        recovery_device_id=recovery_device_id,
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
    recovery_device_id: int | None = None,
    ttl_minutes: int = PAIRING_CODE_TTL_MINUTES,
    auth: AuthContext | None = None,
) -> PairingCodeResult:
    locked_auth = lock_and_revalidate_credential_mint_context(db, auth)
    if locked_auth is not None and (
        locked_auth.ledger_id != ledger_id or locked_auth.account_id != account_id
    ):
        raise AppError("invalid_token", status_code=401)
    result = _create_pairing_code(
        db,
        ledger_id=ledger_id,
        account_id=account_id,
        created_by_device_id=locked_auth.device_id if locked_auth is not None else None,
        device_name_hint=device_name_hint,
        recovery_device_id=recovery_device_id,
        ttl_minutes=ttl_minutes,
    )
    db.commit()
    return result
