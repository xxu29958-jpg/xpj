"""Manual commands for the user-owned fixed-expense registry."""

from __future__ import annotations

from datetime import date

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import RecurringItem
from app.money_contract import MoneySign, ensure_money_minor
from app.services.currency_binding_service import resolve_write_capability
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    claim_idempotent_request,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.merchant_service import normalize_merchant
from app.services.recurring_merchant_capacity import ensure_recurring_merchant_storage_shape
from app.services.time_service import now_utc

CREATE_RECURRING_OPERATION = "create_recurring_item"


def raise_recurring_item_conflict(item: RecurringItem) -> None:
    raise AppError(
        "recurring_item_conflict",
        status_code=409,
        details={"public_id": item.public_id, "status": item.status},
    )


def _clean_merchant(value: str | None) -> tuple[str, str]:
    merchant_name = (value or "").strip()
    merchant_key = normalize_merchant(merchant_name)
    if not merchant_name or not merchant_key:
        raise AppError("recurring_merchant_required", status_code=422)
    ensure_recurring_merchant_storage_shape(
        merchant_name=merchant_name,
        merchant_key=merchant_key,
    )
    return merchant_name, merchant_key


def _existing_by_key(
    db: Session,
    *,
    tenant_id: str,
    merchant_key: str,
    exclude_public_id: str | None = None,
) -> RecurringItem | None:
    statement = ledger_scoped_select(RecurringItem, tenant_id).where(
        RecurringItem.merchant_key == merchant_key,
        RecurringItem.frequency == "monthly",
    )
    if exclude_public_id is not None:
        statement = statement.where(RecurringItem.public_id != exclude_public_id)
    return db.scalar(statement.limit(1))


def _get_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
    item = db.scalar(
        ledger_scoped_select(RecurringItem, tenant_id).where(RecurringItem.public_id == public_id).limit(1)
    )
    if item is None:
        raise AppError("recurring_item_not_found", status_code=404)
    return item


def _classify_create_claim(outcome: IdempotencyOutcome) -> None:
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)


def _claim_create_intent(
    db: Session,
    *,
    tenant_id: str,
    idempotency_key: str | None,
    merchant: str,
    baseline_amount_cents: int,
    next_expected_date: date | None,
) -> IdempotencyOutcome:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    request_body = {
        "merchant": merchant,
        "baseline_amount_cents": baseline_amount_cents,
        "next_expected_date": next_expected_date.isoformat() if next_expected_date else None,
    }
    outcome = claim_idempotency_key(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        operation=CREATE_RECURRING_OPERATION,
        request_fingerprint=fingerprint_request(
            operation=CREATE_RECURRING_OPERATION,
            target_id=None,
            body=request_body,
            expected_row_version=None,
        ),
        target_type="recurring_item",
    )
    _classify_create_claim(outcome)
    return outcome


def _replayed_create(
    db: Session,
    *,
    tenant_id: str,
    outcome: IdempotencyOutcome,
) -> RecurringItem | None:
    if outcome.kind is not IdempotencyOutcomeKind.HIT:
        return None
    if not outcome.row.resource_id:
        raise AppError("server_error", status_code=500)
    return _get_item(db, tenant_id=tenant_id, public_id=outcome.row.resource_id)


def _new_manual_item(
    db: Session,
    *,
    tenant_id: str,
    merchant: str,
    baseline_amount_cents: int,
    next_expected_date: date | None,
) -> RecurringItem:
    merchant_name, merchant_key = _clean_merchant(merchant)
    amount_cents = ensure_money_minor(
        baseline_amount_cents,
        sign=MoneySign.POSITIVE,
        label="recurring.manual_baseline",
    )
    existing = _existing_by_key(db, tenant_id=tenant_id, merchant_key=merchant_key)
    if existing is not None:
        raise_recurring_item_conflict(existing)
    now = now_utc()
    return RecurringItem(
        tenant_id=tenant_id,
        merchant_key=merchant_key,
        merchant_name=merchant_name,
        frequency="monthly",
        baseline_amount_cents=amount_cents,
        # The legacy column is non-null. occurrence_count=0 + source=manual are
        # the honesty contract: consumers must not label this seed as observed.
        last_amount_cents=amount_cents,
        occurrence_count=0,
        last_seen_at=None,
        next_expected_date=next_expected_date,
        status="active",
        confidence=None,
        source="manual",
        created_at=now,
        updated_at=now,
    )


def _insert_manual_item(db: Session, *, tenant_id: str, item: RecurringItem) -> None:
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        raced = _existing_by_key(db, tenant_id=tenant_id, merchant_key=item.merchant_key)
        if raced is not None:
            raise_recurring_item_conflict(raced)
        raise


def create_manual_recurring_item(
    db: Session,
    *,
    tenant_id: str,
    idempotency_key: str | None,
    merchant: str,
    baseline_amount_cents: int,
    next_expected_date: date | None,
) -> RecurringItem:
    """Create one manual monthly commitment and durably replay the same intent."""
    outcome = _claim_create_intent(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        merchant=merchant,
        baseline_amount_cents=baseline_amount_cents,
        next_expected_date=next_expected_date,
    )
    replayed = _replayed_create(db, tenant_id=tenant_id, outcome=outcome)
    if replayed is not None:
        return replayed
    item = _new_manual_item(
        db,
        tenant_id=tenant_id,
        merchant=merchant,
        baseline_amount_cents=baseline_amount_cents,
        next_expected_date=next_expected_date,
    )
    resolve_write_capability(db)
    _insert_manual_item(db, tenant_id=tenant_id, item=item)
    mark_idempotency_succeeded(
        db,
        outcome.row,
        resource_type="recurring_item",
        resource_id=item.public_id,
    )
    db.commit()
    return item


def _merchant_updates(
    db: Session,
    *,
    current: RecurringItem,
    tenant_id: str,
    public_id: str,
    merchant: str | None,
    provided: bool,
) -> dict[str, object]:
    if not provided:
        return {}
    merchant_name, merchant_key = _clean_merchant(merchant)
    if current.source == "candidate" and merchant_key != current.merchant_key:
        raise AppError("recurring_observed_merchant_immutable", status_code=409)
    duplicate = _existing_by_key(
        db,
        tenant_id=tenant_id,
        merchant_key=merchant_key,
        exclude_public_id=public_id,
    )
    if duplicate is not None:
        raise_recurring_item_conflict(duplicate)
    if merchant_name == current.merchant_name and merchant_key == current.merchant_key:
        return {}
    return {"merchant_name": merchant_name, "merchant_key": merchant_key}


def _baseline_updates(
    current: RecurringItem,
    *,
    baseline_amount_cents: int | None,
    provided: bool,
) -> dict[str, object]:
    if not provided:
        return {}
    amount_cents = ensure_money_minor(
        baseline_amount_cents,
        sign=MoneySign.POSITIVE,
        label="recurring.manual_baseline",
    )
    if amount_cents == current.baseline_amount_cents:
        return {}
    values: dict[str, object] = {"baseline_amount_cents": amount_cents}
    if current.source == "manual" and current.occurrence_count == 0 and current.last_seen_at is None:
        # ``last_amount_cents`` predates manual commitments and remains
        # non-null in storage. Before any observation exists it is only a
        # compatibility seed, not provenance, so keep it aligned with the
        # user-owned baseline. Once observations exist, never rewrite it.
        values["last_amount_cents"] = amount_cents
    return values


def _ensure_editable_revision(item: RecurringItem, *, expected_row_version: int) -> None:
    if item.status == "archived" or item.archived_at is not None:
        raise AppError(
            "recurring_item_archived",
            status_code=409,
            details={"public_id": item.public_id, "status": item.status},
        )
    if item.row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)


def _collect_update_values(
    db: Session,
    *,
    current: RecurringItem,
    tenant_id: str,
    public_id: str,
    merchant: str | None,
    merchant_provided: bool,
    baseline_amount_cents: int | None,
    baseline_provided: bool,
    next_expected_date: date | None,
    next_expected_date_provided: bool,
) -> dict[str, object]:
    values = _merchant_updates(
        db,
        current=current,
        tenant_id=tenant_id,
        public_id=public_id,
        merchant=merchant,
        provided=merchant_provided,
    )
    values.update(
        _baseline_updates(
            current,
            baseline_amount_cents=baseline_amount_cents,
            provided=baseline_provided,
        )
    )
    if next_expected_date_provided and next_expected_date != current.next_expected_date:
        values["next_expected_date"] = next_expected_date
    if not values:
        raise AppError("recurring_item_no_changes", status_code=422)
    values.update(updated_at=now_utc(), row_version=current.row_version + 1)
    return values


def _execute_update(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    values: dict[str, object],
) -> int:
    with db.begin_nested():
        result = db.execute(
            update(RecurringItem)
            .where(RecurringItem.tenant_id == tenant_id)
            .where(RecurringItem.public_id == public_id)
            .where(RecurringItem.status != "archived")
            .where(RecurringItem.archived_at.is_(None))
            .where(RecurringItem.row_version == expected_row_version)
            .values(**values)
        )
        db.flush()
    return result.rowcount or 0


def _raise_duplicate_after_integrity_error(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    merchant: str | None,
    merchant_provided: bool,
) -> None:
    if not merchant_provided:
        return
    duplicate = _existing_by_key(
        db,
        tenant_id=tenant_id,
        merchant_key=_clean_merchant(merchant)[1],
        exclude_public_id=public_id,
    )
    if duplicate is not None:
        raise_recurring_item_conflict(duplicate)


def _raise_update_race(db: Session, *, tenant_id: str, public_id: str) -> None:
    db.expire_all()
    latest = _get_item(db, tenant_id=tenant_id, public_id=public_id)
    if latest.status == "archived" or latest.archived_at is not None:
        raise AppError(
            "recurring_item_archived",
            status_code=409,
            details={"public_id": latest.public_id, "status": latest.status},
        )
    raise AppError("state_conflict", status_code=409)


def _apply_recurring_item_update(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    merchant: str | None,
    merchant_provided: bool,
    baseline_amount_cents: int | None,
    baseline_provided: bool,
    next_expected_date: date | None,
    next_expected_date_provided: bool,
) -> RecurringItem:
    """Apply one already-admitted OCC update without committing it."""
    current = _get_item(db, tenant_id=tenant_id, public_id=public_id)
    _ensure_editable_revision(current, expected_row_version=expected_row_version)
    values = _collect_update_values(
        db,
        current=current,
        tenant_id=tenant_id,
        public_id=public_id,
        merchant=merchant,
        merchant_provided=merchant_provided,
        baseline_amount_cents=baseline_amount_cents,
        baseline_provided=baseline_provided,
        next_expected_date=next_expected_date,
        next_expected_date_provided=next_expected_date_provided,
    )
    resolve_write_capability(db)
    try:
        rowcount = _execute_update(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            expected_row_version=expected_row_version,
            values=values,
        )
    except IntegrityError:
        _raise_duplicate_after_integrity_error(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            merchant=merchant,
            merchant_provided=merchant_provided,
        )
        raise
    if not rowcount:
        _raise_update_race(db, tenant_id=tenant_id, public_id=public_id)
    db.expire_all()
    return _get_item(db, tenant_id=tenant_id, public_id=public_id)


def _recurring_update_body(
    *,
    merchant: str | None,
    merchant_provided: bool,
    baseline_amount_cents: int | None,
    baseline_provided: bool,
    next_expected_date: date | None,
    next_expected_date_provided: bool,
) -> dict[str, object]:
    body: dict[str, object] = {}
    if merchant_provided:
        body["merchant"] = merchant
    if baseline_provided:
        body["baseline_amount_cents"] = baseline_amount_cents
    if next_expected_date_provided:
        body["next_expected_date"] = (
            next_expected_date.isoformat() if next_expected_date else None
        )
    return body


def update_recurring_item(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    idempotency_key: str | None,
    expected_row_version: int,
    merchant: str | None,
    merchant_provided: bool,
    baseline_amount_cents: int | None,
    baseline_provided: bool,
    next_expected_date: date | None,
    next_expected_date_provided: bool,
) -> RecurringItem:
    """Own claim-before-OCC, mutation publication, and commit for one edit."""
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="update_recurring_item",
        target_id=public_id,
        body=_recurring_update_body(
            merchant=merchant,
            merchant_provided=merchant_provided,
            baseline_amount_cents=baseline_amount_cents,
            baseline_provided=baseline_provided,
            next_expected_date=next_expected_date,
            next_expected_date_provided=next_expected_date_provided,
        ),
        expected_row_version=expected_row_version,
        target_type="recurring_item",
    )
    if claim is None:
        return _get_item(db, tenant_id=tenant_id, public_id=public_id)
    item = _apply_recurring_item_update(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=expected_row_version,
        merchant=merchant,
        merchant_provided=merchant_provided,
        baseline_amount_cents=baseline_amount_cents,
        baseline_provided=baseline_provided,
        next_expected_date=next_expected_date,
        next_expected_date_provided=next_expected_date_provided,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="recurring_item",
        resource_id=public_id,
    )
    db.commit()
    return item
