"""Device management: list / revoke / rename / delete admin devices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    Device,
    PairingCode,
    UploadLink,
    UploadLinkDailyUsage,
    UploadLinkRemoteAttempt,
)
from app.services.admin_service._dtos import DeviceSummary
from app.services.identity_service._bootstrap_exposure_guard import (
    assert_bootstrap_sensitive_mutation_allowed,
)
from app.services.session_credential_lock import (
    lock_and_revalidate_credential_mint_context,
    lock_bootstrap_owner_transaction,
)
from app.services.session_lifecycle_service import revoke_pairing_capabilities_for_device
from app.services.time_service import now_utc, to_iso
from app.tenants import AuthContext


@dataclass(frozen=True)
class DeviceCleanupResult:
    retention_days: int
    scanned: int
    deleted_devices: int
    deleted_tokens: int
    deleted_upload_links: int


@dataclass(frozen=True)
class _DeviceCleanupCounts:
    devices: int = 0
    tokens: int = 0
    upload_links: int = 0


def device_public_id(db: Session, device_id: int | None) -> str:
    """Public id for a device id, or '' when unknown. Lets routes resolve the
    current device's public id without importing the ORM model directly
    (ENGINEERING_RULES §1: presentation layer goes through a service)."""
    if device_id is None:
        return ""
    device = db.get(Device, device_id)
    return device.public_id if device is not None else ""


def _device_summary(
    db: Session,
    device: Device,
) -> DeviceSummary:
    account = db.get(Account, device.account_id)
    return DeviceSummary(
        public_id=device.public_id,
        device_name=device.device_name,
        platform=device.platform,
        account_name=account.display_name if account is not None else "",
        # Device is Account-scoped. AuthToken.ledger_id is only the mutable
        # N-1 compatibility default and must never masquerade as ownership.
        ledger_id=None,
        ledger_name=None,
        created_at=to_iso(device.created_at),
        last_seen_at=to_iso(device.last_seen_at),
        revoked_at=to_iso(device.revoked_at),
    )


def _active_device_dependents_exist(
    db: Session,
    device_id: int,
) -> bool:
    token_match = exists().where(AuthToken.device_id == device_id).where(AuthToken.revoked_at.is_(None))
    link_match = exists().where(UploadLink.device_id == device_id).where(UploadLink.revoked_at.is_(None))
    return bool(db.scalar(select(token_match)) or db.scalar(select(link_match)))


def _any_device_dependents_exist(
    db: Session,
    device_id: int,
) -> bool:
    token_match = exists().where(AuthToken.device_id == device_id)
    link_match = exists().where(UploadLink.device_id == device_id)
    return bool(db.scalar(select(token_match)) or db.scalar(select(link_match)))


def _active_recovery_pairing_exists(
    db: Session,
    device_id: int,
    *,
    checked_at: datetime | None = None,
) -> bool:
    checked_at = checked_at or now_utc()
    return bool(
        db.scalar(
            select(
                exists()
                .where(PairingCode.recovery_device_id == device_id)
                .where(PairingCode.used_at.is_(None))
                .where(PairingCode.revoked_at.is_(None))
                .where(PairingCode.expires_at > checked_at)
            )
        )
    )


def _lock_account_scope(
    db: Session,
    *,
    auth: AuthContext | None,
    actor_account_id: int | None,
) -> int:
    locked_auth = lock_and_revalidate_credential_mint_context(db, auth)
    if locked_auth is not None:
        if actor_account_id is not None and actor_account_id != locked_auth.account_id:
            raise AppError("invalid_token", status_code=401)
        actor_account_id = locked_auth.account_id
    if actor_account_id is None:
        raise AppError("permission_denied", status_code=403)
    return actor_account_id


def list_devices(db: Session, *, account_id: int) -> list[DeviceSummary]:
    """Return the authenticated Account's devices, independent of ledger default."""

    device_stmt = (
        select(Device)
        .where(Device.account_id == account_id)
        .order_by(Device.id.asc())
    )
    devices = list(db.scalars(device_stmt))
    if not devices:
        return []

    account = db.get(Account, account_id)

    summaries: list[DeviceSummary] = []
    for device in devices:
        summaries.append(
            DeviceSummary(
                public_id=device.public_id,
                device_name=device.device_name,
                platform=device.platform,
                account_name=account.display_name if account is not None else "",
                ledger_id=None,
                ledger_name=None,
                created_at=to_iso(device.created_at),
                last_seen_at=to_iso(device.last_seen_at),
                revoked_at=to_iso(device.revoked_at),
            )
        )
    return summaries


def _device_by_public_id(
    db: Session,
    public_id: str,
    *,
    account_id: int,
) -> Device:
    device = db.scalar(
        select(Device)
        .where(Device.public_id == public_id)
        .where(Device.account_id == account_id)
        .limit(1)
    )
    if device is None:
        raise AppError("invalid_request", "设备不存在。", status_code=404)
    return device


def revoke_device(
    db: Session,
    *,
    public_id: str,
    current_device_public_id: str,
    auth: AuthContext | None,
    actor_account_id: int | None,
) -> DeviceSummary:
    account_id = _lock_account_scope(
        db,
        auth=auth,
        actor_account_id=actor_account_id,
    )
    if public_id == current_device_public_id:
        raise AppError(
            "invalid_request",
            "不能停用当前正在使用的管理员设备，请先用本地脚本切换。",
            status_code=409,
        )
    device = _device_by_public_id(db, public_id, account_id=account_id)
    assert_bootstrap_sensitive_mutation_allowed(
        db,
        actor_account_id=account_id,
        target_device_id=device.id,
    )
    now = now_utc()
    if device.revoked_at is None:
        device.revoked_at = now
    token_update = update(AuthToken).where(AuthToken.device_id == device.id).where(AuthToken.revoked_at.is_(None))
    link_update = update(UploadLink).where(UploadLink.device_id == device.id).where(UploadLink.revoked_at.is_(None))
    db.execute(token_update.values(revoked_at=now, grace_until=None))
    db.execute(link_update.values(revoked_at=now))
    revoke_pairing_capabilities_for_device(
        db,
        device_id=device.id,
        revoked_at=now,
    )
    db.commit()
    db.refresh(device)
    return _device_summary(db, device)


def rename_device(
    db: Session,
    *,
    public_id: str,
    new_name: str,
    auth: AuthContext | None,
    actor_account_id: int | None,
) -> DeviceSummary:
    name = (new_name or "").strip()
    if not name or len(name) > 120:
        raise AppError("invalid_request", "设备名称需在 1-120 字符之间。", status_code=422)
    account_id = _lock_account_scope(
        db,
        auth=auth,
        actor_account_id=actor_account_id,
    )
    device = _device_by_public_id(db, public_id, account_id=account_id)
    assert_bootstrap_sensitive_mutation_allowed(
        db,
        actor_account_id=account_id,
        target_device_id=device.id,
    )
    device.device_name = name
    db.commit()
    db.refresh(device)
    return _device_summary(db, device)


def delete_device(
    db: Session,
    *,
    public_id: str,
    current_device_public_id: str,
    auth: AuthContext | None,
    actor_account_id: int | None,
) -> None:
    """Permanently remove one already-revoked Account device."""
    account_id = _lock_account_scope(
        db,
        auth=auth,
        actor_account_id=actor_account_id,
    )
    if public_id == current_device_public_id:
        raise AppError(
            "invalid_request",
            "不能删除当前正在使用的管理员设备。",
            status_code=409,
        )
    device = _device_by_public_id(db, public_id, account_id=account_id)
    assert_bootstrap_sensitive_mutation_allowed(
        db,
        actor_account_id=account_id,
        target_device_id=device.id,
    )
    if device.revoked_at is None:
        raise AppError(
            "invalid_request",
            "请先停用该设备再删除，避免误删活跃绑定。",
            status_code=409,
        )
    if _active_device_dependents_exist(db, device.id):
        raise AppError(
            "invalid_request",
            "请先停用该设备再删除，避免误删活跃绑定。",
            status_code=409,
        )
    if _active_recovery_pairing_exists(db, device.id):
        raise AppError(
            "invalid_request",
            "该设备有尚未使用的恢复绑定码，请先完成恢复或等待绑定码过期。",
            status_code=409,
        )
    db.execute(
        update(PairingCode)
        .where(PairingCode.recovery_device_id == device.id)
        .values(recovery_device_id=None)
    )
    upload_link_ids = select(UploadLink.id).where(UploadLink.device_id == device.id)
    db.execute(
        delete(UploadLinkDailyUsage).where(
            UploadLinkDailyUsage.upload_link_id.in_(upload_link_ids)
        )
    )
    db.execute(
        delete(UploadLinkRemoteAttempt).where(
            UploadLinkRemoteAttempt.upload_link_id.in_(upload_link_ids)
        )
    )
    db.execute(delete(AuthToken).where(AuthToken.device_id == device.id))
    db.execute(delete(UploadLink).where(UploadLink.device_id == device.id))
    if not _any_device_dependents_exist(db, device.id):
        db.delete(device)
    db.commit()


def _cleanup_retention_days(retention_days: int | None) -> int:
    if retention_days is not None:
        return max(int(retention_days), 0)
    return max(get_settings().device_cleanup_retention_days, 0)


def _revoked_device_candidate_ids(
    db: Session,
    *,
    account_id: int | None,
    cutoff: datetime,
    checked_at: datetime,
    batch_size: int,
) -> list[int]:
    active_token = exists().where(AuthToken.device_id == Device.id).where(AuthToken.revoked_at.is_(None))
    active_link = exists().where(UploadLink.device_id == Device.id).where(UploadLink.revoked_at.is_(None))
    active_recovery = (
        exists()
        .where(PairingCode.recovery_device_id == Device.id)
        .where(PairingCode.used_at.is_(None))
        .where(PairingCode.revoked_at.is_(None))
        .where(PairingCode.expires_at > checked_at)
    )
    candidate_statement = (
        select(Device.id)
        .where(Device.revoked_at.is_not(None))
        .where(Device.revoked_at <= cutoff)
        .where(~active_token)
        .where(~active_link)
        .where(~active_recovery)
        .order_by(Device.revoked_at.asc(), Device.id.asc())
        .limit(max(1, min(int(batch_size), 5000)))
    )
    if account_id is not None:
        candidate_statement = candidate_statement.where(Device.account_id == account_id)
    return list(db.scalars(candidate_statement))


def _delete_revoked_device_candidates(
    db: Session,
    *,
    candidate_ids: list[int],
    checked_at: datetime,
) -> _DeviceCleanupCounts:
    if not candidate_ids:
        return _DeviceCleanupCounts()
    candidate_link_ids = select(UploadLink.id).where(
        UploadLink.device_id.in_(candidate_ids)
    )
    db.execute(
        delete(UploadLinkDailyUsage).where(
            UploadLinkDailyUsage.upload_link_id.in_(candidate_link_ids)
        )
    )
    db.execute(
        delete(UploadLinkRemoteAttempt).where(
            UploadLinkRemoteAttempt.upload_link_id.in_(candidate_link_ids)
        )
    )
    db.execute(
        update(PairingCode)
        .where(PairingCode.recovery_device_id.in_(candidate_ids))
        .where(
            (PairingCode.used_at.is_not(None))
            | (PairingCode.revoked_at.is_not(None))
            | (PairingCode.expires_at <= checked_at)
        )
        .values(recovery_device_id=None)
    )
    token_result = db.execute(
        delete(AuthToken)
        .where(AuthToken.device_id.in_(candidate_ids))
        .where(AuthToken.revoked_at.is_not(None))
    )
    link_result = db.execute(
        delete(UploadLink)
        .where(UploadLink.device_id.in_(candidate_ids))
        .where(UploadLink.revoked_at.is_not(None))
    )
    device_result = db.execute(
        delete(Device)
        .where(Device.id.in_(candidate_ids))
        .where(~exists().where(AuthToken.device_id == Device.id))
        .where(~exists().where(UploadLink.device_id == Device.id))
        .where(
            ~exists()
            .where(PairingCode.recovery_device_id == Device.id)
            .where(PairingCode.used_at.is_(None))
            .where(PairingCode.revoked_at.is_(None))
            .where(PairingCode.expires_at > checked_at)
        )
    )
    return _DeviceCleanupCounts(
        devices=int(device_result.rowcount or 0),
        tokens=int(token_result.rowcount or 0),
        upload_links=int(link_result.rowcount or 0),
    )


def cleanup_revoked_devices(
    db: Session,
    *,
    account_id: int | None = None,
    retention_days: int | None = None,
    batch_size: int = 500,
) -> DeviceCleanupResult:
    # Credential issuance, recovery-code creation and cleanup share one
    # database-backed lifecycle lock. Cleanup must never race a recovery that
    # is making an old Device authoritative again.
    lock_bootstrap_owner_transaction(db)
    keep_days = _cleanup_retention_days(retention_days)
    checked_at = now_utc()
    candidate_ids = _revoked_device_candidate_ids(
        db,
        account_id=account_id,
        cutoff=checked_at - timedelta(days=keep_days),
        checked_at=checked_at,
        batch_size=batch_size,
    )
    # Eligibility is re-asserted in the delete statements. The lifecycle lock
    # excludes known issuers; the predicates also defend future call paths.
    deleted = _delete_revoked_device_candidates(
        db,
        candidate_ids=candidate_ids,
        checked_at=checked_at,
    )
    if deleted.devices or deleted.tokens or deleted.upload_links:
        db.commit()
    else:
        db.rollback()
    return DeviceCleanupResult(
        retention_days=keep_days,
        scanned=len(candidate_ids),
        deleted_devices=deleted.devices,
        deleted_tokens=deleted.tokens,
        deleted_upload_links=deleted.upload_links,
    )
