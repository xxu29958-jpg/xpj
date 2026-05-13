from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import MerchantAlias
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.time_service import now_utc


def _clean_merchant(value: str | None) -> tuple[str, str]:
    display = display_merchant(value)
    key = normalize_merchant(display)
    if not display or not key:
        raise AppError("invalid_request", status_code=422)
    return display, key


def _get_alias_by_public_id(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> MerchantAlias | None:
    return db.scalar(
        ledger_scoped_select(MerchantAlias, tenant_id)
        .where(MerchantAlias.public_id == public_id)
        .limit(1)
    )


def _get_alias_by_key(
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


def _ensure_alias_available(
    db: Session,
    *,
    tenant_id: str,
    alias_key: str,
    current_id: int | None = None,
) -> None:
    existing = _get_alias_by_key(db, tenant_id=tenant_id, alias_key=alias_key)
    if existing is not None and existing.id != current_id:
        raise AppError("merchant_alias_conflict", status_code=409)


def list_merchant_aliases(db: Session, tenant_id: str) -> list[MerchantAlias]:
    return list(
        db.scalars(
            ledger_scoped_select(MerchantAlias, tenant_id).order_by(
                MerchantAlias.canonical_key.asc(),
                MerchantAlias.alias_key.asc(),
                MerchantAlias.id.asc(),
            )
        )
    )


def create_merchant_alias(
    db: Session,
    *,
    tenant_id: str,
    canonical_merchant: str,
    alias: str,
    enabled: bool = True,
) -> MerchantAlias:
    canonical_display, canonical_key = _clean_merchant(canonical_merchant)
    alias_display, alias_key = _clean_merchant(alias)
    if alias_key == canonical_key:
        raise AppError("invalid_request", "别名不能和标准商家相同。", status_code=422)
    _ensure_alias_available(db, tenant_id=tenant_id, alias_key=alias_key)

    now = now_utc()
    item = MerchantAlias(
        tenant_id=tenant_id,
        canonical_merchant=canonical_display,
        canonical_key=canonical_key,
        alias=alias_display,
        alias_key=alias_key,
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_merchant_alias(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> MerchantAlias:
    item = _get_alias_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if item is None:
        raise AppError("merchant_alias_not_found", status_code=404)
    return item


def update_merchant_alias(
    db: Session,
    item: MerchantAlias,
    *,
    canonical_merchant: str | None = None,
    alias: str | None = None,
    enabled: bool | None = None,
) -> MerchantAlias:
    canonical_display = item.canonical_merchant
    canonical_key = item.canonical_key
    alias_display = item.alias
    alias_key = item.alias_key

    if canonical_merchant is not None:
        canonical_display, canonical_key = _clean_merchant(canonical_merchant)
    if alias is not None:
        alias_display, alias_key = _clean_merchant(alias)
    if alias_key == canonical_key:
        raise AppError("invalid_request", "别名不能和标准商家相同。", status_code=422)
    _ensure_alias_available(
        db,
        tenant_id=item.tenant_id,
        alias_key=alias_key,
        current_id=item.id,
    )

    item.canonical_merchant = canonical_display
    item.canonical_key = canonical_key
    item.alias = alias_display
    item.alias_key = alias_key
    if enabled is not None:
        item.enabled = enabled
    item.updated_at = now_utc()
    db.commit()
    db.refresh(item)
    return item


def delete_merchant_alias(db: Session, item: MerchantAlias) -> None:
    db.delete(item)
    db.commit()


def enabled_merchant_alias_map(db: Session, *, tenant_id: str) -> dict[str, str]:
    return {
        item.alias_key: item.canonical_merchant
        for item in db.scalars(
            ledger_scoped_select(MerchantAlias, tenant_id)
            .where(MerchantAlias.enabled == True)  # noqa: E712
            .order_by(MerchantAlias.alias_key.asc(), MerchantAlias.id.asc())
        )
    }


def canonical_merchant_for(
    merchant: str | None,
    *,
    alias_map: dict[str, str],
) -> str:
    display = display_merchant(merchant)
    key = normalize_merchant(display)
    if not key:
        return display
    return alias_map.get(key, display)


def resolve_canonical_merchant(
    db: Session,
    *,
    tenant_id: str,
    merchant: str | None,
) -> str:
    return canonical_merchant_for(
        merchant,
        alias_map=enabled_merchant_alias_map(db, tenant_id=tenant_id),
    )
