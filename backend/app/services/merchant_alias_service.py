from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import MerchantAlias
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.optimistic_concurrency import (
    claim_row_with_token,
)
from app.services.resource_audit import record_resource_action
from app.services.soft_delete_policy import is_within_undo_window
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
    """Live (not soft-deleted) alias by public_id. Normal get/patch/delete
    operate on live rows only; soft-deleted rows are reached via
    :func:`_get_soft_deleted_alias_by_public_id` for undo."""
    return db.scalar(
        ledger_scoped_select(MerchantAlias, tenant_id)
        .where(MerchantAlias.public_id == public_id)
        .where(MerchantAlias.deleted_at.is_(None))
        .limit(1)
    )


def _get_soft_deleted_alias_by_public_id(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> MerchantAlias | None:
    return db.scalar(
        ledger_scoped_select(MerchantAlias, tenant_id)
        .where(MerchantAlias.public_id == public_id)
        .where(MerchantAlias.deleted_at.is_not(None))
        .limit(1)
    )


def _get_alias_by_key(
    db: Session,
    *,
    tenant_id: str,
    alias_key: str,
) -> MerchantAlias | None:
    """Alias by key INCLUDING soft-deleted rows.

    Uniqueness intentionally spans soft-deleted rows: the DB keeps the
    ``(tenant_id, alias_key)`` unique constraint, so a soft-deleted key stays
    reserved during its undo window. Creating it again returns 409 until the
    row is undone or purged — which also guarantees undo never resurrects a
    duplicate key.
    """
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
            ledger_scoped_select(MerchantAlias, tenant_id)
            .where(MerchantAlias.deleted_at.is_(None))
            .order_by(
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
    expected_row_version: int,
    canonical_merchant: str | None = None,
    alias: str | None = None,
    enabled: bool | None = None,
    commit: bool = True,
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
        expected_row_version=expected_row_version,
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
    if commit:
        db.commit()
    # Force the read-back to hit the DB: claim_row_with_token's default
    # synchronize_session="auto" can't sync the in-session row on PostgreSQL
    # (aware timestamptz vs the naive OCC predicate), so with expire_on_commit
    # =False the identity-map row would return the pre-update value (ADR-0041).
    db.expire_all()
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
    expected_row_version: int,
    commit: bool = True,
) -> None:
    """ADR-0038 undo: atomic optimistic-concurrency SOFT delete.

    ``UPDATE merchant_aliases SET deleted_at = now, updated_at = now WHERE id,
    tenant_id, updated_at = expected``. The row is hidden from every read but
    recoverable via :func:`undo_delete_merchant_alias` until cleanup purges it
    past the retention window. ``rowcount == 0`` disambiguates 404 vs 409
    exactly like the hard delete it replaces; the ``ObjectDeletedError`` guard
    handles a concurrent-delete race.
    """
    try:
        item_id = item.id
        item_tenant_id = item.tenant_id
        item_public_id = item.public_id
    except ObjectDeletedError as exc:
        raise AppError("merchant_alias_not_found", status_code=404) from exc

    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        MerchantAlias,
        pk_id=item_id,
        tenant_id=item_tenant_id,
        expected_row_version=expected_row_version,
        set_values={"deleted_at": now, "updated_at": now},
    )
    if rowcount != 1:
        db.rollback()
        current = _get_alias_by_public_id(
            db, tenant_id=item_tenant_id, public_id=item_public_id
        )
        if current is None:
            raise AppError("merchant_alias_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)
    if commit:
        db.commit()


def undo_delete_merchant_alias(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    actor_account_id: int | None = None,
) -> MerchantAlias:
    """ADR-0038 undo: restore a soft-deleted alias within its retention window.

    Clears ``deleted_at`` and appends a ``ledger_audit_logs`` ``action='undo'``
    row. 404 if the alias isn't currently soft-deleted (never existed, already
    live, or already purged). Because create is blocked while a soft-deleted
    holder reserves the key, no live row can hold the same key at undo time;
    the live-holder guard below is defensive belt-and-braces.
    """
    item = _get_soft_deleted_alias_by_public_id(
        db, tenant_id=tenant_id, public_id=public_id
    )
    if item is None:
        raise AppError("merchant_alias_not_found", status_code=404)
    if not is_within_undo_window(item.deleted_at):
        # 超过保留窗口:逻辑上应已被 cleanup purge,即使 purge 滞后也不再可恢复(与 purge 语义一致)。
        raise AppError("merchant_alias_not_found", status_code=404)
    live_holder = db.scalar(
        ledger_scoped_select(MerchantAlias, tenant_id)
        .where(MerchantAlias.alias_key == item.alias_key)
        .where(MerchantAlias.deleted_at.is_(None))
        .limit(1)
    )
    if live_holder is not None:
        raise AppError("merchant_alias_conflict", status_code=409)
    # ADR-0038 PR-B: atomic restore. ``UPDATE ... SET deleted_at=NULL WHERE id,
    # tenant_id, deleted_at IS NOT NULL`` so two concurrent undos can't both
    # clear it and double-write the audit log — rowcount==0 means a peer undo
    # (or a cleanup purge) already won; collapse to 404 like the other
    # not-restorable cases. Replaces the prior SELECT-then-write.
    now = now_utc()
    rowcount = db.execute(
        update(MerchantAlias)
        .where(MerchantAlias.id == item.id)
        .where(MerchantAlias.tenant_id == tenant_id)
        .where(MerchantAlias.deleted_at.is_not(None))
        .values(
            deleted_at=None,
            updated_at=now,
            row_version=MerchantAlias.row_version + 1,
        )
    ).rowcount
    if rowcount != 1:
        db.rollback()
        raise AppError("merchant_alias_not_found", status_code=404)
    record_resource_action(
        db,
        ledger_id=tenant_id,
        action="undo",
        resource_type="merchant_alias",
        resource_public_id=public_id,
        actor_account_id=actor_account_id,
    )
    db.commit()
    db.refresh(item)
    return item


def enabled_merchant_alias_map(db: Session, *, tenant_id: str) -> dict[str, str]:
    return {
        item.alias_key: item.canonical_merchant
        for item in db.scalars(
            ledger_scoped_select(MerchantAlias, tenant_id)
            .where(MerchantAlias.enabled == True)  # noqa: E712
            .where(MerchantAlias.deleted_at.is_(None))
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
