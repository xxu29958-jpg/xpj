from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import MerchantAlias
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.optimistic_concurrency import (
    claim_row_with_token,
    delete_row_with_token,
)
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
    expected_updated_at: datetime,
    canonical_merchant: str | None = None,
    alias: str | None = None,
    enabled: bool | None = None,
) -> MerchantAlias:
    """ADR-0038 PR-2e: atomic optimistic-concurrency PATCH.

    Validates the new alias / canonical (uniqueness, non-self-alias) then
    runs ``UPDATE merchant_aliases SET ..., updated_at = now WHERE id,
    tenant_id, updated_at = expected``. ``rowcount == 0`` disambiguates:

    - row vanished / no longer visible → 404 ``merchant_alias_not_found``
    - else → 409 ``state_conflict``

    Snapshots identity + default-source fields up front. If a concurrent
    session deleted this row already, the ORM instance may be in the
    "deleted" state; surface that as 404 rather than an opaque
    SQLAlchemy error during the UPDATE WHERE build. Same shape as
    :func:`update_rule`.
    """
    try:
        item_id = item.id
        item_tenant_id = item.tenant_id
        item_public_id = item.public_id
        canonical_display = item.canonical_merchant
        canonical_key = item.canonical_key
        alias_display = item.alias
        alias_key = item.alias_key
    except ObjectDeletedError as exc:
        raise AppError("merchant_alias_not_found", status_code=404) from exc

    if canonical_merchant is not None:
        canonical_display, canonical_key = _clean_merchant(canonical_merchant)
    if alias is not None:
        alias_display, alias_key = _clean_merchant(alias)
    if alias_key == canonical_key:
        raise AppError("invalid_request", "别名不能和标准商家相同。", status_code=422)
    _ensure_alias_available(
        db,
        tenant_id=item_tenant_id,
        alias_key=alias_key,
        current_id=item_id,
    )

    set_values: dict[str, object] = {
        "canonical_merchant": canonical_display,
        "canonical_key": canonical_key,
        "alias": alias_display,
        "alias_key": alias_key,
        "updated_at": now_utc(),
    }
    if enabled is not None:
        set_values["enabled"] = enabled

    rowcount = claim_row_with_token(
        db,
        MerchantAlias,
        pk_id=item_id,
        tenant_id=item_tenant_id,
        expected_updated_at=expected_updated_at,
        set_values=set_values,
    )
    if rowcount != 1:
        db.rollback()
        current = _get_alias_by_public_id(
            db, tenant_id=item_tenant_id, public_id=item_public_id
        )
        if current is None:
            raise AppError("merchant_alias_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.commit()
    refreshed = _get_alias_by_public_id(
        db, tenant_id=item_tenant_id, public_id=item_public_id
    )
    # rowcount == 1 means the row exists and was just updated; the follow-
    # up find cannot return None unless something else deleted the row
    # between our UPDATE and this SELECT.
    assert refreshed is not None
    return refreshed


def delete_merchant_alias(
    db: Session,
    item: MerchantAlias,
    *,
    expected_updated_at: datetime,
) -> None:
    """ADR-0038 PR-2e: atomic optimistic-concurrency DELETE.

    ``DELETE FROM merchant_aliases WHERE id, tenant_id, updated_at =
    expected``. ``rowcount == 0`` disambiguates 404 vs 409 the same way
    :func:`update_merchant_alias` does. Same ``ObjectDeletedError`` guard
    as :func:`update_merchant_alias` and :func:`delete_rule` so a
    concurrent-delete race is reported as 404 rather than an opaque
    SQLAlchemy error.
    """
    try:
        item_id = item.id
        item_tenant_id = item.tenant_id
        item_public_id = item.public_id
    except ObjectDeletedError as exc:
        raise AppError("merchant_alias_not_found", status_code=404) from exc

    rowcount = delete_row_with_token(
        db,
        MerchantAlias,
        pk_id=item_id,
        tenant_id=item_tenant_id,
        expected_updated_at=expected_updated_at,
    )
    if rowcount != 1:
        db.rollback()
        current = _get_alias_by_public_id(
            db, tenant_id=item_tenant_id, public_id=item_public_id
        )
        if current is None:
            raise AppError("merchant_alias_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)
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
