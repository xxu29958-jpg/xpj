"""Owner Console pairing-code creation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Device, Ledger, LedgerMember
from app.services.identity_service import (
    PairingCodeResult,
    create_pairing_code,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction

__all__ = [
    "PairingCodeResult",
    "RecoveryDeviceChoice",
    "do_create_pairing_code",
    "list_recovery_device_choices",
]


@dataclass(frozen=True)
class RecoveryDeviceChoice:
    public_id: str
    device_name: str
    platform: str
    is_revoked: bool


def list_recovery_device_choices(
    db: Session,
    *,
    account_id: int | None,
) -> list[RecoveryDeviceChoice]:
    if account_id is None:
        return []
    devices = db.scalars(
        select(Device)
        .where(Device.account_id == account_id)
        .where(Device.platform == "android")
        .order_by(Device.revoked_at.desc().nulls_last(), Device.created_at.desc())
    )
    return [
        RecoveryDeviceChoice(
            public_id=device.public_id,
            device_name=device.device_name,
            platform=device.platform,
            is_revoked=device.revoked_at is not None,
        )
        for device in devices
    ]


def _recovery_device_id(
    db: Session,
    *,
    account_id: int,
    public_id: str | None,
) -> int | None:
    clean_public_id = (public_id or "").strip()
    if not clean_public_id:
        return None
    device_id = db.scalar(
        select(Device.id)
        .where(Device.public_id == clean_public_id)
        .where(Device.account_id == account_id)
        .where(Device.platform == "android")
        .limit(1)
    )
    if device_id is None:
        raise AppError("invalid_request", "要恢复的设备不存在。", status_code=404)
    return device_id


def _require_owner_pairing_authority(
    db: Session,
    *,
    ledger_id: str,
    account_id: int,
) -> None:
    authorized_ledger_id = db.scalar(
        select(Ledger.ledger_id)
        .join(
            LedgerMember,
            (LedgerMember.ledger_id == Ledger.ledger_id)
            & (LedgerMember.account_id == account_id),
        )
        .where(Ledger.ledger_id == ledger_id)
        .where(Ledger.owner_account_id == account_id)
        .where(Ledger.archived_at.is_(None))
        .where(LedgerMember.role == "owner")
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )
    if authorized_ledger_id is None:
        raise AppError(
            "invalid_request",
            "账本拥有者身份不一致，已停止生成绑定码。",
            status_code=409,
        )


def do_create_pairing_code(
    db: Session,
    *,
    ledger_id: str,
    account_id: int,
    ttl_minutes: int = 15,
    recovery_device_public_id: str | None = None,
) -> PairingCodeResult:
    lock_bootstrap_owner_transaction(db)
    _require_owner_pairing_authority(
        db,
        ledger_id=ledger_id,
        account_id=account_id,
    )
    return create_pairing_code(
        db,
        ledger_id=ledger_id,
        account_id=account_id,
        recovery_device_id=_recovery_device_id(
            db,
            account_id=account_id,
            public_id=recovery_device_public_id,
        ),
        ttl_minutes=ttl_minutes,
    )
