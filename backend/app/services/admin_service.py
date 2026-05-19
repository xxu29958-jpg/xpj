"""Admin service helpers for v0.3.1-alpha2 device & UploadLink management.

These helpers are called from :mod:`app.routes.admin`. They never return raw
secrets except for newly minted upload keys (which is the one-shot reveal flow
that the contract explicitly allows when creating or rotating a link).

Important guarantees:

* The current admin's own device cannot be revoked by accident — the caller
  must enforce that. The service raises if the public id is unknown or already
  revoked.
* Revoking a device atomically revokes every active ``AuthToken`` and
  ``UploadLink`` for that device.
* Rotating an upload link revokes the old link and returns the new key once.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, UploadLink
from app.services.identity_service import (
    _ensure_device,
    hash_secret,
    new_upload_key,
)
from app.services.time_service import now_utc, to_iso


@dataclass(frozen=True)
class DeviceSummary:
    public_id: str
    device_name: str
    platform: str
    account_name: str
    ledger_id: str | None
    ledger_name: str | None
    created_at: str | None
    last_seen_at: str | None
    revoked_at: str | None


@dataclass(frozen=True)
class UploadLinkSummary:
    public_id: str
    ledger_id: str
    ledger_name: str
    account_name: str
    device_name: str
    default_timezone: str | None
    masked_url_path: str
    last_used_at: str | None
    revoked_at: str | None
    created_at: str | None


@dataclass(frozen=True)
class UploadLinkSecret:
    """One-shot reveal returned by create / rotate. Never persisted."""

    public_id: str
    upload_url_path: str
    default_timezone: str | None


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


def _upload_link_summary(db: Session, link: UploadLink) -> UploadLinkSummary:
    ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == link.ledger_id).limit(1))
    account = db.get(Account, link.account_id)
    device = db.get(Device, link.device_id)
    return UploadLinkSummary(
        public_id=link.public_id,
        ledger_id=link.ledger_id,
        ledger_name=ledger.name if ledger is not None else link.ledger_id,
        account_name=account.display_name if account is not None else "",
        device_name=device.device_name if device is not None else "",
        default_timezone=link.default_timezone,
        # Lists / dashboards must NEVER show the full upload key — only the
        # public_id is safe to reveal repeatedly.
        masked_url_path="/u/***",
        last_used_at=to_iso(link.last_used_at),
        revoked_at=to_iso(link.revoked_at),
        created_at=to_iso(link.created_at),
    )


def list_upload_links(db: Session, *, ledger_ids: set[str] | None = None) -> list[UploadLinkSummary]:
    """Batched companion to :func:`list_devices`.

    ``_upload_link_summary`` issues one ledger / account / device select per
    link; that's fine for create/rotate which already start from a single
    UploadLink, but for the list path we fan out one query per row. This
    function fetches the parent rows in three batches instead.
    """

    statement = select(UploadLink).order_by(UploadLink.id.asc())
    if ledger_ids is not None:
        if not ledger_ids:
            return []
        statement = statement.where(UploadLink.ledger_id.in_(ledger_ids))
    links = list(db.scalars(statement))
    if not links:
        return []

    ledger_id_set = {link.ledger_id for link in links}
    account_ids = list({link.account_id for link in links})
    device_ids = list({link.device_id for link in links})

    ledgers_by_id = {
        ledger.ledger_id: ledger
        for ledger in db.scalars(select(Ledger).where(Ledger.ledger_id.in_(ledger_id_set)))
    }
    accounts_by_id = {
        a.id: a for a in db.scalars(select(Account).where(Account.id.in_(account_ids)))
    }
    devices_by_id = {
        d.id: d for d in db.scalars(select(Device).where(Device.id.in_(device_ids)))
    }

    summaries: list[UploadLinkSummary] = []
    for link in links:
        ledger = ledgers_by_id.get(link.ledger_id)
        account = accounts_by_id.get(link.account_id)
        device = devices_by_id.get(link.device_id)
        summaries.append(
            UploadLinkSummary(
                public_id=link.public_id,
                ledger_id=link.ledger_id,
                ledger_name=ledger.name if ledger is not None else link.ledger_id,
                account_name=account.display_name if account is not None else "",
                device_name=device.device_name if device is not None else "",
                default_timezone=link.default_timezone,
                # Lists / dashboards must NEVER show the full upload key — only the
                # public_id is safe to reveal repeatedly.
                masked_url_path="/u/***",
                last_used_at=to_iso(link.last_used_at),
                revoked_at=to_iso(link.revoked_at),
                created_at=to_iso(link.created_at),
            )
        )
    return summaries


def _upload_link_by_public_id(
    db: Session,
    public_id: str,
    *,
    ledger_ids: set[str] | None = None,
) -> UploadLink:
    link = db.scalar(select(UploadLink).where(UploadLink.public_id == public_id).limit(1))
    if link is None or (ledger_ids is not None and link.ledger_id not in ledger_ids):
        raise AppError("invalid_request", "上传链接不存在。", status_code=404)
    return link


def create_upload_link(
    db: Session,
    *,
    ledger_id: str,
    admin_account_id: int,
    default_timezone: str | None,
    ledger_ids: set[str] | None = None,
) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    if ledger_ids is not None and ledger_id not in ledger_ids:
        raise AppError("invalid_request", "账本不存在。", status_code=404)
    ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id).limit(1))
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invalid_request", "账本不存在。", status_code=404)
    # Each UploadLink is anchored on a synthetic device entry so the device
    # column stays meaningful (a revoked device should kill its links).
    device = _ensure_device(db, admin_account_id, "iPhone 快捷指令", "ios")
    upload_key = new_upload_key()
    link = UploadLink(
        public_id=_new_public_id(db),
        token_hash=hash_secret(upload_key),
        account_id=admin_account_id,
        device_id=device.id,
        ledger_id=ledger_id,
        default_timezone=default_timezone,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    summary = _upload_link_summary(db, link)
    secret = UploadLinkSecret(
        public_id=link.public_id,
        upload_url_path=_upload_url_path(upload_key, default_timezone),
        default_timezone=default_timezone,
    )
    return summary, secret


def rotate_upload_link(
    db: Session, *, public_id: str, ledger_ids: set[str] | None = None
) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    link = _upload_link_by_public_id(db, public_id, ledger_ids=ledger_ids)
    if link.revoked_at is not None:
        raise AppError(
            "invalid_request",
            "上传链接已停用，不能继续轮换。",
            status_code=409,
        )
    now = now_utc()
    link.revoked_at = now
    new_key = new_upload_key()
    new_link = UploadLink(
        public_id=_new_public_id(db),
        token_hash=hash_secret(new_key),
        account_id=link.account_id,
        device_id=link.device_id,
        ledger_id=link.ledger_id,
        default_timezone=link.default_timezone,
    )
    db.add(new_link)
    db.commit()
    db.refresh(new_link)
    summary = _upload_link_summary(db, new_link)
    secret = UploadLinkSecret(
        public_id=new_link.public_id,
        upload_url_path=_upload_url_path(new_key, new_link.default_timezone),
        default_timezone=new_link.default_timezone,
    )
    return summary, secret


def revoke_upload_link(
    db: Session,
    *,
    public_id: str,
    ledger_ids: set[str] | None = None,
) -> UploadLinkSummary:
    link = _upload_link_by_public_id(db, public_id, ledger_ids=ledger_ids)
    if link.revoked_at is None:
        link.revoked_at = now_utc()
        db.commit()
        db.refresh(link)
    return _upload_link_summary(db, link)


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


def delete_upload_link(
    db: Session,
    *,
    public_id: str,
    ledger_ids: set[str] | None = None,
) -> None:
    """Permanently remove an UploadLink row.

    Only allowed for already-revoked links so we never delete a key that an
    iPhone Shortcut might still be using.
    """
    link = _upload_link_by_public_id(db, public_id, ledger_ids=ledger_ids)
    if link.revoked_at is None:
        raise AppError(
            "invalid_request",
            "请先停用该上传链接再删除。",
            status_code=409,
        )
    db.delete(link)
    db.commit()


def _new_public_id(db: Session) -> str:
    from uuid import uuid4

    while True:
        candidate = str(uuid4())
        if (
            db.scalar(
                select(UploadLink.id).where(UploadLink.public_id == candidate).limit(1)
            )
            is None
        ):
            return candidate


def _upload_url_path(upload_key: str, default_timezone: str | None) -> str:
    tz = (default_timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
    from urllib.parse import quote

    return f"/u/{upload_key}?tz={quote(tz, safe='/')}"
