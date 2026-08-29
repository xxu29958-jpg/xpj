"""Scalar Expense projection mutation after a command has acquired its CAS."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Expense
from app.schemas import ExpenseUpdateRequest
from app.services.bill_split_service import assert_no_immutable_field_changes
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.classify_service import classify_expense
from app.services.duplicate_service import mark_duplicate_status, revalidate_duplicate_references_to
from app.services.exchange_rate_service import validate_currency_payload_money_command
from app.services.expense_service._helpers import (
    _clean_category,
    _clean_optional_text,
    _clean_text,
    _ensure_expense_can_confirm,
)
from app.services.expense_service._update_currency import _apply_update_currency
from app.services.ocr_service import clear_ocr_draft_fields
from app.services.receipt_item_service import recompute_items_sum_status
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc


def _apply_basic_expense_fields(
    db: Session,
    *,
    expense: Expense,
    tenant_id: str,
    updates: dict[str, object],
) -> None:
    if "merchant" in updates:
        expense.merchant = _clean_optional_text(updates["merchant"])
    if "category" in updates and updates["category"]:
        expense.category = _clean_category(updates["category"])
        ensure_category_preference_for_name(db, tenant_id=tenant_id, name=expense.category)
    if "note" in updates:
        expense.note = _clean_text(updates["note"])
    if "spent_at" in updates:
        expense.expense_time = ensure_utc(updates["spent_at"])
    elif "expense_time" in updates:
        expense.expense_time = ensure_utc(updates["expense_time"])
    if updates.get("tags") is not None:
        expense.tags = normalize_tags(updates["tags"])
    if "value_score" in updates:
        expense.value_score = updates["value_score"]
    if "regret_score" in updates:
        expense.regret_score = updates["regret_score"]


def _apply_classification_and_duplicate_projection(
    db: Session,
    *,
    expense: Expense,
    tenant_id: str,
    updates: dict[str, object],
) -> None:
    if (
        "category" not in updates
        and expense.category == "其他"
        and any(field in updates for field in {"merchant", "note"})
    ):
        classify_expense(db, expense)
        ensure_category_preference_for_name(db, tenant_id=tenant_id, name=expense.category)
    duplicate_fields = {
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
    if any(field in updates for field in duplicate_fields):
        mark_duplicate_status(db, expense)
        db.flush()
        revalidate_duplicate_references_to(db, tenant_id=tenant_id, duplicate_of_id=expense.id)


def apply_expense_fields_to_claimed_row(
    db: Session,
    *,
    expense: Expense,
    tenant_id: str,
    payload: ExpenseUpdateRequest,
) -> None:
    """Apply shared field semantics after the caller's status-specific CAS."""

    validate_currency_payload_money_command(
        payload,
        amount_was_explicit="amount_cents" in payload.model_fields_set,
    )
    updates = payload.model_dump(exclude_unset=True, exclude={"expected_row_version"})
    assert_no_immutable_field_changes(expense, set(updates))
    _apply_basic_expense_fields(db, expense=expense, tenant_id=tenant_id, updates=updates)
    amount_cents_before = expense.amount_cents
    _apply_update_currency(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        updates=updates,
    )
    if expense.status == "confirmed":
        _ensure_expense_can_confirm(expense)
    clear_ocr_draft_fields(expense, list(updates))
    _apply_classification_and_duplicate_projection(
        db, expense=expense, tenant_id=tenant_id, updates=updates
    )
    if updates.get("tags") is not None:
        sync_expense_tags(db, expense)
    if expense.amount_cents != amount_cents_before:
        recompute_items_sum_status(db, expense)
    expense.updated_at = now_utc()
    db.flush()
