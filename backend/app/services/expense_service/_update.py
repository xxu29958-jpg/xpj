"""Update / lifecycle: field edits, batch updates, confirm, reject."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import (
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
    ExpenseUpdateRequest,
)
from app.services.classify_service import classify_expense
from app.services.cleanup_service import cleanup_after_confirm
from app.services.duplicate_service import (
    clear_duplicate_references_to,
    mark_duplicate_status,
    revalidate_duplicate_references_to,
)
from app.services.exchange_rate_service import apply_currency_payload, refresh_currency_snapshot
from app.services.ocr_service import clear_ocr_draft_fields
from app.services.expense_service._helpers import (
    EDITABLE_STATUSES,
    _clean_category,
    _clean_optional_text,
    _clean_text,
    _ensure_expense_can_confirm,
    _expense_has_pending_fx,
)
from app.services.expense_service._query import get_expense
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc


__all__ = [
    "batch_update_confirmed_expenses",
    "confirm_expense",
    "reject_expense",
    "update_expense",
]


def batch_update_confirmed_expenses(
    db: Session,
    *,
    tenant_id: str,
    payload: ConfirmedExpenseBatchUpdateRequest,
) -> ConfirmedExpenseBatchUpdateResponse:
    expense_ids = list(dict.fromkeys(payload.expense_ids))
    category_provided = payload.category is not None
    tags_provided = payload.tags is not None
    if not category_provided and not tags_provided:
        raise AppError("invalid_request", status_code=422)

    category = payload.category.strip() if category_provided else None
    if category_provided and not category:
        raise AppError("invalid_request", status_code=422)

    normalized_tags = normalize_tags(payload.tags) if tags_provided else None
    rows = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.id.in_(expense_ids))
        )
    )
    rows_by_id = {row.id: row for row in rows}

    updated_count = 0
    skipped_not_found = 0
    skipped_not_confirmed = 0
    now = now_utc()
    for expense_id in expense_ids:
        expense = rows_by_id.get(expense_id)
        if expense is None:
            skipped_not_found += 1
            continue
        if expense.status != "confirmed":
            skipped_not_confirmed += 1
            continue
        if category_provided:
            expense.category = _clean_category(category)
        if tags_provided:
            expense.tags = normalized_tags
            sync_expense_tags(db, expense)
        expense.updated_at = now
        updated_count += 1

    if updated_count:
        db.commit()

    return ConfirmedExpenseBatchUpdateResponse(
        requested_count=len(expense_ids),
        updated_count=updated_count,
        skipped_not_found=skipped_not_found,
        skipped_not_confirmed=skipped_not_confirmed,
    )


def update_expense(
    db: Session, expense_id: int, tenant_id: str, payload: ExpenseUpdateRequest
) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status not in EDITABLE_STATUSES:
        raise AppError("expense_not_found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if "merchant" in updates:
        expense.merchant = _clean_optional_text(updates["merchant"])
    if "category" in updates and updates["category"]:
        expense.category = _clean_category(updates["category"])
    if "note" in updates:
        expense.note = _clean_text(updates["note"])
    if "spent_at" in updates:
        expense.expense_time = ensure_utc(updates["spent_at"])
    elif "expense_time" in updates:
        expense.expense_time = ensure_utc(updates["expense_time"])
    if "tags" in updates:
        expense.tags = normalize_tags(updates["tags"])
    if "value_score" in updates:
        expense.value_score = updates["value_score"]
    if "regret_score" in updates:
        expense.regret_score = updates["regret_score"]
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit="amount_cents" in updates,
    )
    if expense.status == "confirmed":
        _ensure_expense_can_confirm(expense)

    clear_ocr_draft_fields(expense, list(updates.keys()))

    should_auto_classify = (
        "category" not in updates
        and expense.category == "其他"
        and any(field in updates for field in {"merchant", "note"})
    )
    if should_auto_classify:
        classify_expense(db, expense)

    if any(
        field in updates
        for field in {
            "amount_cents",
            "original_currency",
            "original_amount",
            "original_currency_code",
            "original_amount_minor",
            "exchange_rate_date",
            "merchant",
            "spent_at",
            "expense_time",
        }
    ):
        mark_duplicate_status(db, expense)
        db.flush()
        revalidate_duplicate_references_to(db, tenant_id=tenant_id, duplicate_of_id=expense.id)
    if "tags" in updates:
        sync_expense_tags(db, expense)

    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense


def confirm_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status == "confirmed":
        return expense
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)
    if _expense_has_pending_fx(expense):
        refresh_currency_snapshot(db, tenant_id=tenant_id, expense=expense)
    _ensure_expense_can_confirm(expense)
    db.flush()

    now = now_utc()
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .where(Expense.status == "pending")
        .where(Expense.amount_cents.is_not(None))
        .values(status="confirmed", confirmed_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        expense = get_expense(db, expense_id, tenant_id)
        if expense.status == "confirmed":
            return expense
        if expense.status == "pending":
            _ensure_expense_can_confirm(expense)
        raise AppError("expense_not_found", status_code=404)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    sync_expense_tags(db, expense)
    db.commit()
    db.refresh(expense)
    if cleanup_after_confirm(expense):
        db.commit()
        db.refresh(expense)
    return expense


def reject_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    now = now_utc()
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .where(Expense.status == "pending")
        .values(status="rejected", rejected_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        existing = get_expense(db, expense_id, tenant_id)
        if existing.status == "rejected":
            return existing
        raise AppError("expense_not_found", status_code=404)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    clear_duplicate_references_to(db, tenant_id=tenant_id, duplicate_of_id=expense.id)
    db.commit()
    db.refresh(expense)
    return expense
