from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, MerchantAlias, MerchantCatalog, RecurringItem
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.soft_delete_policy import is_within_recycle_bin_window
from app.services.time_service import now_utc

_WRITABLE_STATUSES = {"active", "hidden"}


@dataclass(frozen=True)
class MerchantCatalogView:
    public_id: str
    display_name: str
    merchant_key: str
    status: str
    merged_into_public_id: str | None
    usage_count: int
    row_version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True)
class MerchantCatalogMergeView:
    source: MerchantCatalogView
    target: MerchantCatalogView
    created_alias_public_id: str | None


def clean_merchant_catalog_name(value: str | None) -> tuple[str, str]:
    display = display_merchant(value)
    key = normalize_merchant(display)
    if not display or not key or len(display) > 255 or len(key) > 255:
        raise AppError("invalid_request", "Merchant name is required.", status_code=422)
    return display, key


def clean_merchant_catalog_status(value: str | None) -> str:
    status = (value or "active").strip().lower()
    if status not in _WRITABLE_STATUSES:
        raise AppError("invalid_request", "Merchant status is invalid.", status_code=422)
    return status


def list_merchant_catalog(
    db: Session,
    *,
    tenant_id: str,
    include_hidden: bool = True,
) -> list[MerchantCatalogView]:
    usage_counts = _usage_counts_by_merchant_key(db, tenant_id=tenant_id)
    stmt = (
        ledger_scoped_select(MerchantCatalog, tenant_id)
        .where(MerchantCatalog.deleted_at.is_(None))
        .order_by(
            MerchantCatalog.display_name.asc(),
            MerchantCatalog.id.asc(),
        )
    )
    if not include_hidden:
        stmt = stmt.where(MerchantCatalog.status == "active")
    rows = db.scalars(stmt)
    return [_catalog_view(item, usage_counts=usage_counts) for item in rows]


def get_merchant_catalog(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> MerchantCatalogView:
    item = _live_catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if item is None:
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
    return _catalog_view(
        item,
        usage_counts=_usage_counts_by_merchant_key(db, tenant_id=tenant_id),
    )


def create_merchant_catalog(
    db: Session,
    *,
    tenant_id: str,
    display_name: str | None,
    status: str | None = "active",
) -> MerchantCatalogView:
    clean_name, key = clean_merchant_catalog_name(display_name)
    clean_status = clean_merchant_catalog_status(status)
    _ensure_key_available(db, tenant_id=tenant_id, merchant_key=key)

    now = now_utc()
    item = MerchantCatalog(
        tenant_id=tenant_id,
        display_name=clean_name,
        merchant_key=key,
        status=clean_status,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _catalog_view(
        item,
        usage_counts=_usage_counts_by_merchant_key(db, tenant_id=tenant_id),
    )


def update_merchant_catalog(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    display_name: str | None = None,
    status: str | None = None,
) -> MerchantCatalogView:
    item = _live_catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if item is None:
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)

    set_values: dict[str, object] = {"updated_at": now_utc()}
    if display_name is not None:
        clean_name, key = clean_merchant_catalog_name(display_name)
        if key != item.merchant_key:
            _ensure_catalog_has_no_live_config_references(
                db,
                tenant_id=tenant_id,
                item=item,
            )
        _ensure_key_available(
            db,
            tenant_id=tenant_id,
            merchant_key=key,
            current_id=item.id,
        )
        set_values["display_name"] = clean_name
        set_values["merchant_key"] = key
    if status is not None:
        set_values["status"] = clean_merchant_catalog_status(status)

    rowcount = claim_row_with_token(
        db,
        MerchantCatalog,
        pk_id=item.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values=set_values,
        extra_where=(MerchantCatalog.deleted_at.is_(None),),
    )
    if rowcount != 1:
        db.rollback()
        current = _catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
        if current is None or current.deleted_at is not None:
            raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.commit()
    return _refreshed_view(db, tenant_id=tenant_id, public_id=public_id)


def delete_merchant_catalog(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
) -> MerchantCatalogView:
    item = _live_catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if item is None:
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
    _ensure_catalog_can_be_deleted(db, tenant_id=tenant_id, item=item)

    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        MerchantCatalog,
        pk_id=item.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"deleted_at": now, "updated_at": now},
        extra_where=(MerchantCatalog.deleted_at.is_(None),),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
        if current is None or current.deleted_at is not None:
            raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.commit()
    return _refreshed_view(db, tenant_id=tenant_id, public_id=public_id)


def merge_merchant_catalog(
    db: Session,
    *,
    tenant_id: str,
    source_public_id: str,
    expected_row_version: int,
    target_public_id: str,
    target_row_version: int,
    alias_policy: str,
    rewrite_historical_expenses: bool = False,
) -> MerchantCatalogMergeView:
    if rewrite_historical_expenses:
        raise AppError(
            "invalid_request",
            "Merchant catalog merge does not rewrite historical expenses.",
            status_code=422,
        )
    if source_public_id == target_public_id:
        raise AppError("invalid_request", "Source and target merchants must differ.", status_code=422)

    source = _live_catalog_by_public_id(
        db,
        tenant_id=tenant_id,
        public_id=source_public_id,
    )
    if source is None:
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
    target = _live_catalog_by_public_id(
        db,
        tenant_id=tenant_id,
        public_id=target_public_id,
    )
    if target is None:
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
    if source.status not in _WRITABLE_STATUSES or target.status != "active":
        raise AppError("state_conflict", status_code=409)

    _ensure_catalog_has_no_live_config_references(
        db,
        tenant_id=tenant_id,
        item=source,
    )
    if alias_policy == "create_source_alias":
        _ensure_source_alias_available(
            db,
            tenant_id=tenant_id,
            source=source,
            target=target,
        )

    _claim_catalog_merge_pair(
        db,
        tenant_id=tenant_id,
        source=source,
        target=target,
        expected_row_version=expected_row_version,
        target_row_version=target_row_version,
        now=now_utc(),
    )

    created_alias_public_id: str | None = None
    if alias_policy == "create_source_alias":
        now = now_utc()
        alias = MerchantAlias(
            tenant_id=tenant_id,
            canonical_merchant=target.display_name,
            canonical_key=target.merchant_key,
            alias=source.display_name,
            alias_key=source.merchant_key,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        db.add(alias)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise AppError("state_conflict", status_code=409) from exc
        created_alias_public_id = alias.public_id

    db.commit()
    db.expire_all()
    return MerchantCatalogMergeView(
        source=_refreshed_view(db, tenant_id=tenant_id, public_id=source_public_id),
        target=_refreshed_view(db, tenant_id=tenant_id, public_id=target_public_id),
        created_alias_public_id=created_alias_public_id,
    )


def restore_merchant_catalog(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
) -> MerchantCatalogView:
    item = _catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if item is None or item.deleted_at is None:
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
    if not is_within_recycle_bin_window(item.deleted_at):
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
    live_holder = db.scalar(
        ledger_scoped_select(MerchantCatalog, tenant_id)
        .where(MerchantCatalog.merchant_key == item.merchant_key)
        .where(MerchantCatalog.deleted_at.is_(None))
        .where(MerchantCatalog.id != item.id)
        .limit(1)
    )
    if live_holder is not None:
        raise AppError("state_conflict", status_code=409)

    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        MerchantCatalog,
        pk_id=item.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"deleted_at": None, "updated_at": now},
        extra_where=(MerchantCatalog.deleted_at.is_not(None),),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
        if current is None or current.deleted_at is None:
            raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.commit()
    return _refreshed_view(db, tenant_id=tenant_id, public_id=public_id)


def _catalog_by_public_id(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> MerchantCatalog | None:
    return db.scalar(
        ledger_scoped_select(MerchantCatalog, tenant_id)
        .where(MerchantCatalog.public_id == public_id)
        .limit(1)
    )


def _live_catalog_by_public_id(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> MerchantCatalog | None:
    return db.scalar(
        ledger_scoped_select(MerchantCatalog, tenant_id)
        .where(MerchantCatalog.public_id == public_id)
        .where(MerchantCatalog.deleted_at.is_(None))
        .limit(1)
    )


def _catalog_by_key(
    db: Session,
    *,
    tenant_id: str,
    merchant_key: str,
) -> MerchantCatalog | None:
    return db.scalar(
        ledger_scoped_select(MerchantCatalog, tenant_id)
        .where(MerchantCatalog.merchant_key == merchant_key)
        .limit(1)
    )


def _ensure_key_available(
    db: Session,
    *,
    tenant_id: str,
    merchant_key: str,
    current_id: int | None = None,
) -> None:
    existing = _catalog_by_key(db, tenant_id=tenant_id, merchant_key=merchant_key)
    if existing is not None and existing.id != current_id:
        raise AppError("state_conflict", "Merchant already exists.", status_code=409)


def _ensure_catalog_can_be_deleted(
    db: Session,
    *,
    tenant_id: str,
    item: MerchantCatalog,
) -> None:
    _ensure_catalog_has_no_live_config_references(
        db,
        tenant_id=tenant_id,
        item=item,
    )


def _ensure_catalog_has_no_live_config_references(
    db: Session,
    *,
    tenant_id: str,
    item: MerchantCatalog,
) -> None:
    if db.scalar(
        ledger_scoped_select(MerchantAlias, tenant_id)
        .where(MerchantAlias.enabled.is_(True))
        .where(MerchantAlias.deleted_at.is_(None))
        .where(MerchantAlias.canonical_key == item.merchant_key)
        .limit(1)
    ):
        raise AppError(
            "state_conflict",
            "Merchant is still used by an enabled alias.",
            status_code=409,
        )
    if db.scalar(
        ledger_scoped_select(RecurringItem, tenant_id)
        .where(RecurringItem.status.in_(("active", "paused")))
        .where(RecurringItem.merchant_key == item.merchant_key)
        .limit(1)
    ):
        raise AppError(
            "state_conflict",
            "Merchant is still used by an active recurring item.",
            status_code=409,
        )


def _ensure_source_alias_available(
    db: Session,
    *,
    tenant_id: str,
    source: MerchantCatalog,
    target: MerchantCatalog,
) -> None:
    if source.merchant_key == target.merchant_key:
        raise AppError("invalid_request", "Source and target merchants must differ.", status_code=422)
    existing = db.scalar(
        ledger_scoped_select(MerchantAlias, tenant_id)
        .where(MerchantAlias.alias_key == source.merchant_key)
        .limit(1)
    )
    if existing is not None:
        raise AppError("state_conflict", status_code=409)


def _claim_catalog_merge_pair(
    db: Session,
    *,
    tenant_id: str,
    source: MerchantCatalog,
    target: MerchantCatalog,
    expected_row_version: int,
    target_row_version: int,
    now: datetime,
) -> None:
    claim_specs = [
        {
            "item": source,
            "public_id": source.public_id,
            "expected_row_version": expected_row_version,
            "set_values": {
                "status": "merged",
                "merged_into_public_id": target.public_id,
                "updated_at": now,
            },
            "extra_where": (
                MerchantCatalog.deleted_at.is_(None),
                MerchantCatalog.status.in_(tuple(_WRITABLE_STATUSES)),
            ),
        },
        {
            "item": target,
            "public_id": target.public_id,
            "expected_row_version": target_row_version,
            "set_values": {"updated_at": now},
            "extra_where": (
                MerchantCatalog.deleted_at.is_(None),
                MerchantCatalog.status == "active",
            ),
        },
    ]
    for spec in sorted(claim_specs, key=lambda item: item["item"].id):
        claimed = claim_row_with_token(
            db,
            MerchantCatalog,
            pk_id=spec["item"].id,
            tenant_id=tenant_id,
            expected_row_version=spec["expected_row_version"],
            set_values=spec["set_values"],
            extra_where=spec["extra_where"],
        )
        if claimed != 1:
            db.rollback()
            _raise_catalog_merge_claim_error(
                db,
                tenant_id=tenant_id,
                public_id=spec["public_id"],
            )


def _raise_catalog_merge_claim_error(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> None:
    current = _catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if current is None or current.deleted_at is not None:
        raise AppError("not_found", "Merchant catalog entry was not found.", status_code=404)
    raise AppError("state_conflict", status_code=409)


def _refreshed_view(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> MerchantCatalogView:
    db.expire_all()
    refreshed = _catalog_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    assert refreshed is not None
    return _catalog_view(
        refreshed,
        usage_counts=_usage_counts_by_merchant_key(db, tenant_id=tenant_id),
    )


def _catalog_view(
    item: MerchantCatalog,
    *,
    usage_counts: dict[str, int],
) -> MerchantCatalogView:
    return MerchantCatalogView(
        public_id=item.public_id,
        display_name=item.display_name,
        merchant_key=item.merchant_key,
        status=item.status,
        merged_into_public_id=item.merged_into_public_id,
        usage_count=int(usage_counts.get(item.merchant_key, 0)),
        row_version=item.row_version,
        created_at=item.created_at,
        updated_at=item.updated_at,
        deleted_at=item.deleted_at,
    )


def _usage_counts_by_merchant_key(
    db: Session,
    *,
    tenant_id: str,
) -> dict[str, int]:
    rows = db.execute(
        select(Expense.merchant, func.count(Expense.id))
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.merchant.is_not(None))
        .group_by(Expense.merchant)
    )
    counts: dict[str, int] = {}
    for raw_merchant, count in rows:
        key = normalize_merchant(raw_merchant)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + int(count or 0)
    return counts
