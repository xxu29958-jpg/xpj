from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import MerchantAlias, MerchantCatalog, RecurringItem
from app.services.optimistic_concurrency import claim_row_with_token

WRITABLE_STATUSES = ("active", "hidden")


def ensure_key_available(
    db: Session,
    *,
    tenant_id: str,
    merchant_key: str,
    current_id: int | None = None,
) -> None:
    existing = _catalog_by_key(db, tenant_id=tenant_id, merchant_key=merchant_key)
    if existing is not None and existing.id != current_id:
        raise AppError(
            "state_conflict",
            "Merchant already exists.",
            status_code=409,
            details=_merchant_catalog_conflict_details(existing),
        )


def ensure_catalog_can_be_deleted(
    db: Session,
    *,
    tenant_id: str,
    item: MerchantCatalog,
) -> None:
    ensure_catalog_has_no_live_config_references(
        db,
        tenant_id=tenant_id,
        item=item,
    )


def ensure_catalog_has_no_live_config_references(
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


def ensure_source_alias_available(
    db: Session,
    *,
    tenant_id: str,
    source: MerchantCatalog,
    target: MerchantCatalog,
) -> None:
    if source.merchant_key == target.merchant_key:
        raise AppError("invalid_request", "Source and target merchants must differ.", status_code=422)
    details = alias_conflict_details_by_key(
        db,
        tenant_id=tenant_id,
        alias_key=source.merchant_key,
    )
    if details is not None:
        raise AppError("state_conflict", status_code=409, details=details)


def claim_catalog_merge_pair(
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
                MerchantCatalog.status.in_(tuple(WRITABLE_STATUSES)),
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


def create_source_alias_for_merge(
    db: Session,
    *,
    tenant_id: str,
    source: MerchantCatalog,
    target: MerchantCatalog,
    now: datetime,
) -> str:
    source_alias_key = source.merchant_key
    alias = MerchantAlias(
        tenant_id=tenant_id,
        canonical_merchant=target.display_name,
        canonical_key=target.merchant_key,
        alias=source.display_name,
        alias_key=source_alias_key,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    db.add(alias)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        details = alias_conflict_details_by_key(
            db,
            tenant_id=tenant_id,
            alias_key=source_alias_key,
        )
        raise AppError("state_conflict", status_code=409, details=details) from exc
    return alias.public_id


def alias_conflict_details_by_key(
    db: Session,
    *,
    tenant_id: str,
    alias_key: str,
) -> dict[str, object] | None:
    existing = _alias_by_key(db, tenant_id=tenant_id, alias_key=alias_key)
    if existing is None:
        return None
    return _merchant_alias_conflict_details(existing)


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


def _alias_by_key(
    db: Session,
    *,
    tenant_id: str,
    alias_key: str,
) -> MerchantAlias | None:
    return db.scalar(
        ledger_scoped_select(MerchantAlias, tenant_id)
        .where(MerchantAlias.alias_key == alias_key)
        .limit(1)
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


def _merchant_catalog_conflict_details(item: MerchantCatalog) -> dict[str, object]:
    return {
        "conflict_merchant_public_id": item.public_id,
        "conflict_merchant_row_version": item.row_version,
        "conflict_merchant_display_name": item.display_name,
        "conflict_merchant_status": item.status,
        "conflict_merchant_deleted": item.deleted_at is not None,
    }


def _merchant_alias_conflict_details(item: MerchantAlias) -> dict[str, object]:
    return {
        "conflict_alias_public_id": item.public_id,
        "conflict_alias_row_version": item.row_version,
        "conflict_alias_enabled": item.enabled,
        "conflict_alias_deleted": item.deleted_at is not None,
    }
