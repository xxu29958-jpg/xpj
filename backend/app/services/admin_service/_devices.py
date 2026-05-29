"""Device management: list / revoke / rename / delete admin devices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, UploadLink
from app.services.admin_service._dtos import DeviceSummary
from app.services.time_service import now_utc, to_iso


@dataclass(frozen=True)
class DeviceCleanupResult:
    retention_days: int
    scanned: int
    deleted_devices: int
    deleted_tokens: int
    deleted_upload_links: int


def device_public_id(db: Session, device_id: int | None) -> str:
    """Public id for a device id, or '' when unknown. Lets routes resolve the
    current device's public id without importing the ORM model directly
    (ENGINEERING_RULES §1: presentation layer goes through a service)."""
    if device_id is None:
        return ""
    device = db.get(Device, device_id)
    return device.public_id if device is not None else ""


def _device_with_relations(
    db: Session,
    device: Device,
    *,
    ledger_ids: set[str] | None = None,
) -> DeviceSummary:
    account = db.get(Account, device.account_id)
    # A device's nominal ledger is its most recently used active auth_token's
    # ledger; if none, fall back to the most recent token of any state.
    token_statement = select(AuthToken).where(AuthToken.device_id == device.id)
    if ledger_ids is not None:
        token_statement = token_statement.where(AuthToken.ledger_id.in_(ledger_ids))
    token = db.scalar(
        token_statement
        .order_by(AuthToken.last_used_at.desc().nullslast(), AuthToken.id.desc())
        .limit(1)
    )
    ledger_id: str | None = None
    ledger_name: str | None = None
    if token is not None:
        ledger_id = token.ledger_id
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == token.ledger_id).limit(1))
        if ledger is not None:
            ledger_name = ledger.name
    return DeviceSummary(
        public_id=device.public_id,
        device_name=device.device_name,
        platform=device.platform,
        account_name=account.display_name if account is not None else "",
        ledger_id=ledger_id,
        ledger_name=ledger_name,
        created_at=to_iso(device.created_at),
        last_seen_at=to_iso(device.last_seen_at),
        revoked_at=to_iso(device.revoked_at),
    )


def _linked_to_allowed_ledger(db: Session, device_id: int, ledger_ids: set[str] | None) -> bool:
    if ledger_ids is None:
        return True
    if not ledger_ids:
        return False
    token_match = db.scalar(
        select(
            exists()
            .where(AuthToken.device_id == device_id)
            .where(AuthToken.ledger_id.in_(ledger_ids))
        )
    )
    link_match = db.scalar(
        select(
            exists()
            .where(UploadLink.device_id == device_id)
            .where(UploadLink.ledger_id.in_(ledger_ids))
        )
    )
    return bool(token_match or link_match)


def _active_device_dependents_exist(
    db: Session,
    device_id: int,
    *,
    ledger_ids: set[str] | None = None,
    outside_scope: bool = False,
) -> bool:
    token_match = exists().where(AuthToken.device_id == device_id).where(AuthToken.revoked_at.is_(None))
    link_match = exists().where(UploadLink.device_id == device_id).where(UploadLink.revoked_at.is_(None))
    if ledger_ids is not None:
        if not ledger_ids:
            return False
        if outside_scope:
            token_match = token_match.where(AuthToken.ledger_id.not_in(ledger_ids))
            link_match = link_match.where(UploadLink.ledger_id.not_in(ledger_ids))
        else:
            token_match = token_match.where(AuthToken.ledger_id.in_(ledger_ids))
            link_match = link_match.where(UploadLink.ledger_id.in_(ledger_ids))
    return bool(db.scalar(select(token_match)) or db.scalar(select(link_match)))


def _any_device_dependents_exist(
    db: Session,
    device_id: int,
    *,
    ledger_ids: set[str] | None = None,
    outside_scope: bool = False,
) -> bool:
    token_match = exists().where(AuthToken.device_id == device_id)
    link_match = exists().where(UploadLink.device_id == device_id)
    if ledger_ids is not None:
        if not ledger_ids:
            return False
        if outside_scope:
            token_match = token_match.where(AuthToken.ledger_id.not_in(ledger_ids))
            link_match = link_match.where(UploadLink.ledger_id.not_in(ledger_ids))
        else:
            token_match = token_match.where(AuthToken.ledger_id.in_(ledger_ids))
            link_match = link_match.where(UploadLink.ledger_id.in_(ledger_ids))
    return bool(db.scalar(select(token_match)) or db.scalar(select(link_match)))


def list_devices(db: Session, *, ledger_ids: set[str] | None = None) -> list[DeviceSummary]:
    """Return device summaries in a small fixed number of queries.

    The per-device variant ``_device_with_relations`` is still used by
    revoke/rename which already start from a single Device. For the list path,
    re-using it created N+1 (one token query + one ledger query per device);
    here we batch token, account, and ledger lookups so the cost is constant
    in the number of rows.
    """

    device_stmt = select(Device).order_by(Device.id.asc())
    if ledger_ids is not None:
        if not ledger_ids:
            return []
        token_device_ids = select(AuthToken.device_id).where(AuthToken.ledger_id.in_(ledger_ids))
        link_device_ids = select(UploadLink.device_id).where(UploadLink.ledger_id.in_(ledger_ids))
        device_stmt = device_stmt.where(Device.id.in_(token_device_ids) | Device.id.in_(link_device_ids))
    devices = list(db.scalars(device_stmt))
    if not devices:
        return []

    device_ids = [d.id for d in devices]
    account_ids = list({d.account_id for d in devices})

    token_stmt = (
        select(AuthToken)
        .where(AuthToken.device_id.in_(device_ids))
        .order_by(AuthToken.last_used_at.desc().nullslast(), AuthToken.id.desc())
    )
    if ledger_ids is not None:
        token_stmt = token_stmt.where(AuthToken.ledger_id.in_(ledger_ids))
    latest_token_by_device: dict[int, AuthToken] = {}
    for token in db.scalars(token_stmt):
        # Stream is already ordered most-recent-first; first hit per device wins.
        latest_token_by_device.setdefault(token.device_id, token)

    accounts_by_id = {
        a.id: a
        for a in db.scalars(select(Account).where(Account.id.in_(account_ids)))
    }

    ledger_id_set = {t.ledger_id for t in latest_token_by_device.values()}
    ledgers_by_id: dict[str, Ledger] = (
        {
            ledger.ledger_id: ledger
            for ledger in db.scalars(select(Ledger).where(Ledger.ledger_id.in_(ledger_id_set)))
        }
        if ledger_id_set
        else {}
    )

    summaries: list[DeviceSummary] = []
    for device in devices:
        account = accounts_by_id.get(device.account_id)
        token = latest_token_by_device.get(device.id)
        ledger_id: str | None = None
        ledger_name: str | None = None
        if token is not None:
            ledger_id = token.ledger_id
            ledger = ledgers_by_id.get(token.ledger_id)
            if ledger is not None:
                ledger_name = ledger.name
        summaries.append(
            DeviceSummary(
                public_id=device.public_id,
                device_name=device.device_name,
                platform=device.platform,
                account_name=account.display_name if account is not None else "",
                ledger_id=ledger_id,
                ledger_name=ledger_name,
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
    ledger_ids: set[str] | None = None,
) -> Device:
    device = db.scalar(select(Device).where(Device.public_id == public_id).limit(1))
    if device is None or not _linked_to_allowed_ledger(db, device.id, ledger_ids):
        raise AppError("invalid_request", "设备不存在。", status_code=404)
    return device


def revoke_device(
    db: Session,
    *,
    public_id: str,
    current_device_public_id: str,
    ledger_ids: set[str] | None = None,
) -> DeviceSummary:
    if public_id == current_device_public_id:
        raise AppError(
            "invalid_request",
            "不能停用当前正在使用的管理员设备，请先用本地脚本切换。",
            status_code=409,
        )
    device = _device_by_public_id(db, public_id, ledger_ids=ledger_ids)
    now = now_utc()
    if device.revoked_at is None and ledger_ids is None:
        device.revoked_at = now
    token_update = update(AuthToken).where(AuthToken.device_id == device.id).where(AuthToken.revoked_at.is_(None))
    link_update = update(UploadLink).where(UploadLink.device_id == device.id).where(UploadLink.revoked_at.is_(None))
    if ledger_ids is not None:
        token_update = token_update.where(AuthToken.ledger_id.in_(ledger_ids))
        link_update = link_update.where(UploadLink.ledger_id.in_(ledger_ids))
    db.execute(token_update.values(revoked_at=now))
    db.execute(link_update.values(revoked_at=now))
    if device.revoked_at is None and not _active_device_dependents_exist(
        db,
        device.id,
        ledger_ids=ledger_ids,
        outside_scope=True,
    ):
        device.revoked_at = now
    db.commit()
    db.refresh(device)
    return _device_with_relations(db, device, ledger_ids=ledger_ids)


def rename_device(
    db: Session,
    *,
    public_id: str,
    new_name: str,
    ledger_ids: set[str] | None = None,
) -> DeviceSummary:
    name = (new_name or "").strip()
    if not name or len(name) > 120:
        raise AppError("invalid_request", "设备名称需在 1-120 字符之间。", status_code=422)
    device = _device_by_public_id(db, public_id, ledger_ids=ledger_ids)
    device.device_name = name
    db.commit()
    db.refresh(device)
    return _device_with_relations(db, device, ledger_ids=ledger_ids)


def delete_device(
    db: Session,
    *,
    public_id: str,
    current_device_public_id: str,
    ledger_ids: set[str] | None = None,
) -> None:
    """Permanently remove a device row and its dependents.

    Only allowed for devices that have been revoked first; the active admin
    device cannot be deleted. Cascade-deletes :class:`AuthToken` and
    :class:`UploadLink` rows referencing this device. ``Expense`` has no FK
    to :class:`Device` and is left untouched.
    """
    if public_id == current_device_public_id:
        raise AppError(
            "invalid_request",
            "不能删除当前正在使用的管理员设备。",
            status_code=409,
        )
    device = _device_by_public_id(db, public_id, ledger_ids=ledger_ids)
    if device.revoked_at is None and (
        ledger_ids is None or _active_device_dependents_exist(db, device.id, ledger_ids=ledger_ids)
    ):
        raise AppError(
            "invalid_request",
            "请先停用该设备再删除，避免误删活跃绑定。",
            status_code=409,
        )
    if _active_device_dependents_exist(db, device.id, ledger_ids=ledger_ids):
        raise AppError(
            "invalid_request",
            "请先停用该设备再删除，避免误删活跃绑定。",
            status_code=409,
        )
    token_delete = AuthToken.__table__.delete().where(AuthToken.device_id == device.id)
    link_delete = UploadLink.__table__.delete().where(UploadLink.device_id == device.id)
    if ledger_ids is not None:
        token_delete = token_delete.where(AuthToken.ledger_id.in_(ledger_ids))
        link_delete = link_delete.where(UploadLink.ledger_id.in_(ledger_ids))
    db.execute(token_delete)
    db.execute(link_delete)
    if not _any_device_dependents_exist(db, device.id, ledger_ids=ledger_ids, outside_scope=True):
        db.delete(device)
    db.commit()


def cleanup_revoked_devices(
    db: Session,
    *,
    tenant_id: str,
    retention_days: int | None = None,
    batch_size: int = 500,
) -> DeviceCleanupResult:
    keep_days = (
        max(get_settings().device_cleanup_retention_days, 0)
        if retention_days is None
        else max(int(retention_days), 0)
    )
    cutoff = now_utc() - timedelta(days=keep_days)
    scoped_token_devices = select(AuthToken.device_id).where(AuthToken.ledger_id == tenant_id)
    scoped_link_devices = select(UploadLink.device_id).where(UploadLink.ledger_id == tenant_id)
    active_token = exists().where(AuthToken.device_id == Device.id).where(AuthToken.revoked_at.is_(None))
    active_link = exists().where(UploadLink.device_id == Device.id).where(UploadLink.revoked_at.is_(None))
    outside_token = exists().where(AuthToken.device_id == Device.id).where(AuthToken.ledger_id != tenant_id)
    outside_link = exists().where(UploadLink.device_id == Device.id).where(UploadLink.ledger_id != tenant_id)
    candidate_ids = list(
        db.scalars(
            select(Device.id)
            .where(Device.revoked_at.is_not(None))
            .where(Device.revoked_at <= cutoff)
            .where(
                or_(
                    Device.id.in_(scoped_token_devices),
                    Device.id.in_(scoped_link_devices),
                )
            )
            .where(~active_token)
            .where(~active_link)
            .where(~outside_token)
            .where(~outside_link)
            .order_by(Device.revoked_at.asc(), Device.id.asc())
            .limit(max(1, min(int(batch_size), 5000)))
        )
    )

    deleted_devices = 0
    deleted_tokens = 0
    deleted_upload_links = 0
    if candidate_ids:
        # Re-assert eligibility at delete time. A candidate's credentials are
        # all revoked at scan time, but a concurrent writer could create a fresh
        # active token/link for that device id between the scan and here; only
        # purge revoked rows, and only drop the device when nothing references
        # it any more, so the race can never destroy a live credential.
        token_result = db.execute(
            AuthToken.__table__.delete()
            .where(AuthToken.device_id.in_(candidate_ids))
            .where(AuthToken.revoked_at.is_not(None))
        )
        link_result = db.execute(
            UploadLink.__table__.delete()
            .where(UploadLink.device_id.in_(candidate_ids))
            .where(UploadLink.revoked_at.is_not(None))
        )
        device_result = db.execute(
            Device.__table__.delete()
            .where(Device.id.in_(candidate_ids))
            .where(~exists().where(AuthToken.device_id == Device.id))
            .where(~exists().where(UploadLink.device_id == Device.id))
        )
        deleted_tokens = int(token_result.rowcount or 0)
        deleted_upload_links = int(link_result.rowcount or 0)
        deleted_devices = int(device_result.rowcount or 0)
    if deleted_devices or deleted_tokens or deleted_upload_links:
        db.commit()
    return DeviceCleanupResult(
        retention_days=keep_days,
        scanned=len(candidate_ids),
        deleted_devices=deleted_devices,
        deleted_tokens=deleted_tokens,
        deleted_upload_links=deleted_upload_links,
    )
