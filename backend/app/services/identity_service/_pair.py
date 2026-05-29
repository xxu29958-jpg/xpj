"""Pair a device using a pairing code → issue session token."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Account, AuthToken, Device, PairingCode
from app.services.identity_service._auth import _role_for
from app.services.identity_service._device import _create_auth_token, _create_device
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
    app_token_expiry_window,
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
    _check_pairing_attempt_limit(db, remote_id)
    code_hash = hash_pairing_code(pairing_code.strip())
    pairing = db.scalar(select(PairingCode).where(PairingCode.code_hash == code_hash).limit(1))
    if pairing is None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    if pairing.used_at is not None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    if (ensure_utc(pairing.expires_at) or pairing.expires_at) <= now_utc():
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)

    ledger = _ledger_by_id(db, pairing.ledger_id)
    if ledger is None or ledger.archived_at is not None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    account_id = pairing.account_id or ledger.owner_account_id
    account = db.get(Account, account_id)
    if account is None or account.disabled_at is not None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    role = _role_for(db, ledger.ledger_id, account.id)

    used_at = now_utc()
    consume_result = consume_pairing_code(db, pairing_id=pairing.id, used_at=used_at)
    if consume_result != "consumed":
        db.rollback()
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)

    device = _create_device(db, account.id, device_name, platform)
    # Web cookie sessions stay capped at WEB_SESSION_TTL_SECONDS (existing
    # contract). Non-web app tokens honor APP_TOKEN_TTL_DAYS so v1.1
    # clients can silently rotate before expiry; 0 keeps the historical
    # "never expires" semantics for environments that opt out.
    platform_value = device.platform
    if platform_value == "web":
        token_expires_at: datetime | None = used_at + timedelta(seconds=WEB_SESSION_TTL_SECONDS)
    else:
        expiry = app_token_expiry_window(used_at)
        token_expires_at = expiry.expires_at
    _revoke_same_platform_app_tokens(
        db,
        account_id=account.id,
        ledger_id=ledger.ledger_id,
        platform=platform_value,
        revoked_at=used_at,
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
    _clear_pairing_failures(db, remote_id)
    soft_refresh_after = None
    if platform_value != "web":
        soft_refresh_after = app_token_expiry_window(used_at).soft_refresh_after
    return PairingResult(
        session_token=token,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=role,
        expires_at=token_expires_at,
        soft_refresh_after=soft_refresh_after,
    )


def _revoke_same_platform_app_tokens(
    db: Session,
    *,
    account_id: int,
    ledger_id: str,
    platform: str,
    revoked_at: datetime,
) -> int:
    """Conservatively replace only old app tokens on the same platform."""

    platform_value = (platform or "unknown").strip().lower()[:32]
    device_ids = select(Device.id).where(Device.account_id == account_id).where(Device.platform == platform_value)
    result = db.execute(
        update(AuthToken)
        .where(AuthToken.account_id == account_id)
        .where(AuthToken.ledger_id == ledger_id)
        .where(AuthToken.scope == "app")
        .where(AuthToken.revoked_at.is_(None))
        .where(AuthToken.device_id.in_(device_ids))
        .values(revoked_at=revoked_at, grace_until=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)
