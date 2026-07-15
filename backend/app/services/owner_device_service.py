"""Account-scoped device management for the Android owner flow.

A Device authenticates one Account; it does not belong to whichever ledger the
session most recently selected. Ledger owners remove another person's access by
changing Membership, never by revoking that person's device globally. The local
Owner Console keeps its separate installation-admin surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AuthToken,
    Device,
    LedgerMember,
    PairingCode,
    UploadLink,
    UploadLinkDailyUsage,
    UploadLinkRemoteAttempt,
)
from app.services.admin_service._dtos import DeviceSummary
from app.services.identity_service import PairingCodeResult, create_pairing_code
from app.services.identity_service._bootstrap_exposure_guard import (
    assert_bootstrap_sensitive_mutation_allowed,
)
from app.services.session_credential_lock import (
    lock_and_revalidate_mutation_actor,
    lock_and_revalidate_session_principal,
)
from app.services.time_service import now_utc, to_iso
from app.tenants import AuthContext, SessionPrincipal


@dataclass(frozen=True)
class MyDevice:
    summary: DeviceSummary
    is_current: bool


def require_account_device_ledger_route(
    db: Session,
    principal: SessionPrincipal,
    ledger_id: str,
) -> SessionPrincipal:
    """Preserve the legacy ledger path without making it session authority."""

    membership_id = db.scalar(
        select(LedgerMember.id)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == principal.account_id)
        .limit(1)
    )
    if membership_id is None:
        raise AppError("ledger_not_found", status_code=404)
    return principal


def _current_public_id(db: Session, principal: SessionPrincipal) -> str:
    device = db.get(Device, principal.device_id)
    return device.public_id if device is not None else ""


def _account_device(db: Session, account_id: int, public_id: str) -> Device:
    device = db.scalar(
        select(Device)
        .where(Device.public_id == public_id)
        .where(Device.account_id == account_id)
        .limit(1)
    )
    if device is None:
        raise AppError("invalid_request", "设备不存在。", status_code=404)
    return device


def _summary(principal: SessionPrincipal, device: Device) -> DeviceSummary:
    return DeviceSummary(
        public_id=device.public_id,
        device_name=device.device_name,
        platform=device.platform,
        account_name=principal.account_name,
        ledger_id=None,
        ledger_name=None,
        created_at=to_iso(device.created_at),
        last_seen_at=to_iso(device.last_seen_at),
        revoked_at=to_iso(device.revoked_at),
    )


def _lock_principal_device_mutation(
    db: Session,
    principal: SessionPrincipal,
    public_id: str,
) -> Device:
    locked_principal = lock_and_revalidate_session_principal(db, principal)
    if locked_principal is None:
        raise AppError("invalid_token", status_code=401)
    device = _account_device(db, locked_principal.account_id, public_id)
    assert_bootstrap_sensitive_mutation_allowed(
        db,
        actor_account_id=locked_principal.account_id,
        target_device_id=device.id,
    )
    return device


def _lock_ledger_device_mutation(
    db: Session,
    auth: AuthContext,
    public_id: str,
) -> Device:
    lock_and_revalidate_mutation_actor(
        db,
        auth,
        actor_account_id=auth.account_id,
        ledger_id=auth.ledger_id,
    )
    device = _account_device(db, auth.account_id, public_id)
    assert_bootstrap_sensitive_mutation_allowed(
        db,
        actor_account_id=auth.account_id,
        target_device_id=device.id,
    )
    return device


def _as_my_device(summary: DeviceSummary, current_public_id: str) -> MyDevice:
    return MyDevice(summary=summary, is_current=summary.public_id == current_public_id)


def list_my_devices(db: Session, principal: SessionPrincipal) -> list[MyDevice]:
    current = _current_public_id(db, principal)
    devices = list(
        db.scalars(
            select(Device)
            .where(Device.account_id == principal.account_id)
            .order_by(Device.id.asc())
        )
    )
    return [_as_my_device(_summary(principal, device), current) for device in devices]


def rename_my_device(
    db: Session,
    principal: SessionPrincipal,
    *,
    public_id: str,
    new_name: str,
) -> MyDevice:
    name = (new_name or "").strip()
    if not name or len(name) > 120:
        raise AppError(
            "invalid_request",
            "设备名称需在 1-120 字符之间。",
            status_code=422,
        )
    device = _lock_principal_device_mutation(db, principal, public_id)
    device.device_name = name
    db.commit()
    db.refresh(device)
    return _as_my_device(
        _summary(principal, device),
        _current_public_id(db, principal),
    )


def revoke_my_device(
    db: Session,
    principal: SessionPrincipal,
    *,
    public_id: str,
) -> MyDevice:
    current = _current_public_id(db, principal)
    if public_id == current:
        # Owner copy for the self-revoke guard (the shared admin_service copy
        # talks about local admin scripts). Revoking the device you're on would
        # log you out mid-action; do it from another device or sign out.
        raise AppError(
            "invalid_request",
            "不能停用当前正在使用的设备。请在另一台设备上操作，或直接退出登录。",
            status_code=409,
        )
    device = _lock_principal_device_mutation(db, principal, public_id)
    revoked_at = now_utc()
    if device.revoked_at is None:
        device.revoked_at = revoked_at
    db.execute(
        update(AuthToken)
        .where(AuthToken.device_id == device.id)
        .where(AuthToken.revoked_at.is_(None))
        .values(revoked_at=revoked_at, grace_until=None)
    )
    db.execute(
        update(UploadLink)
        .where(UploadLink.device_id == device.id)
        .where(UploadLink.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )
    db.commit()
    db.refresh(device)
    return _as_my_device(_summary(principal, device), current)


def delete_my_device(
    db: Session,
    principal: SessionPrincipal,
    *,
    public_id: str,
) -> None:
    """Permanently remove one of the Account's already-revoked devices."""
    current = _current_public_id(db, principal)
    if public_id == current:
        raise AppError(
            "invalid_request",
            "不能删除当前正在使用的设备。请在另一台设备上操作。",
            status_code=409,
        )
    device = _lock_principal_device_mutation(db, principal, public_id)
    if device.revoked_at is None:
        raise AppError(
            "invalid_request",
            "请先停用该设备再删除，避免误删活跃绑定。",
            status_code=409,
        )
    active_recovery = db.scalar(
        select(PairingCode.id)
        .where(PairingCode.recovery_device_id == device.id)
        .where(PairingCode.used_at.is_(None))
        .where(PairingCode.expires_at > now_utc())
        .limit(1)
    )
    if active_recovery is not None:
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
    db.delete(device)
    db.commit()


def create_my_pairing_code(
    db: Session,
    auth: AuthContext,
    *,
    device_name_hint: str | None,
    ttl_minutes: int,
    recovery_device_public_id: str | None = None,
) -> PairingCodeResult:
    recovery_device_id: int | None = None
    if recovery_device_public_id is not None:
        device = _lock_ledger_device_mutation(
            db,
            auth,
            recovery_device_public_id,
        )
        if device.id == auth.device_id:
            raise AppError(
                "invalid_request",
                "当前设备仍在使用，无需恢复。",
                status_code=409,
            )
        current_device = db.get(Device, auth.device_id)
        if current_device is None or device.platform != current_device.platform:
            raise AppError("device_recovery_platform_mismatch", status_code=409)
        recovery_device_id = device.id
    return create_pairing_code(
        db,
        ledger_id=auth.ledger_id,
        account_id=auth.account_id,
        device_name_hint=device_name_hint,
        recovery_device_id=recovery_device_id,
        ttl_minutes=ttl_minutes,
        auth=auth,
    )
