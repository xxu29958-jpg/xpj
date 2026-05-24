"""Pair a device using a pairing code → issue session token."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, PairingCode
from app.services.identity_service._auth import _role_for
from app.services.identity_service._device import _create_auth_token, _ensure_device
from app.services.identity_service._models import (
    WEB_SESSION_TTL_SECONDS,
    PairingResult,
)
from app.services.identity_service._pairing_throttle import (
    _check_pairing_attempt_limit,
    _clear_pairing_failures,
    _reject_pairing,
)
from app.services.identity_service._seed import _ledger_by_id
from app.services.session_lifecycle_service import (
    consume_pairing_code,
    hash_pairing_code,
)
from app.services.time_service import ensure_utc, now_utc


def pair_device(
    db: Session,
    *,
    pairing_code: str,
    device_name: str,
    platform: str,
    remote_id: str | None = None,
) -> PairingResult:
    _check_pairing_attempt_limit(remote_id)
    code_hash = hash_pairing_code(pairing_code.strip())
    pairing = db.scalar(select(PairingCode).where(PairingCode.code_hash == code_hash).limit(1))
    if pairing is None:
        _reject_pairing(remote_id, "invalid_pairing_code", 401)
    if pairing.used_at is not None:
        _reject_pairing(remote_id, "pairing_code_used", 409)
    if (ensure_utc(pairing.expires_at) or pairing.expires_at) <= now_utc():
        _reject_pairing(remote_id, "pairing_code_expired", 410)

    ledger = _ledger_by_id(db, pairing.ledger_id)
    if ledger is None or ledger.archived_at is not None:
        _reject_pairing(remote_id, "invalid_pairing_code", 401)
    account_id = pairing.account_id or ledger.owner_account_id
    account = db.get(Account, account_id)
    if account is None or account.disabled_at is not None:
        _reject_pairing(remote_id, "invalid_pairing_code", 401)
    role = _role_for(db, ledger.ledger_id, account.id)

    used_at = now_utc()
    consume_result = consume_pairing_code(db, pairing_id=pairing.id, used_at=used_at)
    if consume_result != "consumed":
        db.rollback()
        if consume_result == "used":
            _reject_pairing(remote_id, "pairing_code_used", 409)
        _reject_pairing(remote_id, "pairing_code_expired", 410)

    device = _ensure_device(db, account.id, device_name, platform)
    token_expires_at = (
        used_at + timedelta(seconds=WEB_SESSION_TTL_SECONDS)
        if (platform or "").strip().lower() == "web"
        else None
    )
    token = _create_auth_token(
        db,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        scope="app",
        expires_at=token_expires_at,
    )
    db.commit()
    _clear_pairing_failures(remote_id)
    return PairingResult(
        session_token=token,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=role,
    )
