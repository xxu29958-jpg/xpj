"""UploadLink management: list / create / rotate / revoke / delete iPhone upload links."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, Device, Ledger, UploadLink
from app.services.admin_service._dtos import UploadLinkSecret, UploadLinkSummary
from app.services.identity_service import (
    _ensure_device,
    hash_secret,
    new_upload_key,
)
from app.services.time_service import now_utc, to_iso


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
