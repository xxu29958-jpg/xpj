from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseItem
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseItemResponse,
    ExpenseItemsResponse,
)
from app.services.category_service import normalize_category
from app.services.expense_service import EDITABLE_STATUSES, get_expense
from app.services.receipt_parse_service import ParsedReceiptItem
from app.services.time_service import now_utc


def list_expense_items(db: Session, expense_id: int, tenant_id: str) -> ExpenseItemsResponse:
    expense = get_expense(db, expense_id, tenant_id)
    return _build_response(db, expense)


def replace_expense_items(
    db: Session,
    expense_id: int,
    tenant_id: str,
    payload: ExpenseItemReplaceRequest,
) -> ExpenseItemsResponse:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status not in EDITABLE_STATUSES:
        raise AppError("expense_not_found", status_code=404)

    existing = list(
        db.scalars(
            ledger_scoped_select(ExpenseItem, tenant_id).where(
                ExpenseItem.expense_id == expense.id
            )
        )
    )
    for item in existing:
        db.delete(item)
    db.flush()

    now = now_utc()
    for position, request_item in enumerate(payload.items):
        db.add(_new_item(expense, position, request_item, now=now))
    expense.updated_at = now
    db.commit()
    db.refresh(expense)
    return _build_response(db, expense)


def replace_ocr_draft_items(
    db: Session,
    expense: Expense,
    parsed_items: tuple[ParsedReceiptItem, ...],
) -> None:
    if expense.status != "pending":
        return

    existing = list(
        db.scalars(
            ledger_scoped_select(ExpenseItem, expense.tenant_id).where(
                ExpenseItem.expense_id == expense.id
            )
        )
    )
    if any(not item.is_ocr_draft for item in existing):
        return

    for item in existing:
        db.delete(item)
    db.flush()

    now = now_utc()
    for position, parsed_item in enumerate(parsed_items):
        db.add(_new_ocr_draft_item(expense, position, parsed_item, now=now))
    expense.updated_at = now


def _new_item(
    expense: Expense,
    position: int,
    request_item: ExpenseItemRequest,
    *,
    now,
) -> ExpenseItem:
    return ExpenseItem(
        tenant_id=expense.tenant_id,
        expense_id=expense.id,
        position=position,
        name=_clean_required_text(request_item.name),
        quantity_text=_clean_optional_text(request_item.quantity_text),
        unit_price_cents=request_item.unit_price_cents,
        amount_cents=request_item.amount_cents,
        category=normalize_category(request_item.category),
        raw_text=_clean_optional_text(request_item.raw_text),
        confidence=request_item.confidence,
        is_ocr_draft=False,
        created_at=now,
        updated_at=now,
    )


def _new_ocr_draft_item(
    expense: Expense,
    position: int,
    parsed_item: ParsedReceiptItem,
    *,
    now,
) -> ExpenseItem:
    return ExpenseItem(
        tenant_id=expense.tenant_id,
        expense_id=expense.id,
        position=position,
        name=_clean_required_text(parsed_item.name),
        quantity_text=_clean_optional_text(parsed_item.quantity_text),
        unit_price_cents=parsed_item.unit_price_cents,
        amount_cents=parsed_item.amount_cents,
        category=normalize_category(parsed_item.category),
        raw_text=_clean_optional_text(parsed_item.raw_text),
        confidence=parsed_item.confidence,
        is_ocr_draft=True,
        created_at=now,
        updated_at=now,
    )


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_required_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _build_response(db: Session, expense: Expense) -> ExpenseItemsResponse:
    items = list(
        db.scalars(
            ledger_scoped_select(ExpenseItem, expense.tenant_id)
            .where(ExpenseItem.expense_id == expense.id)
            .order_by(ExpenseItem.position.asc(), ExpenseItem.id.asc())
        )
    )
    amounts = [item.amount_cents for item in items if item.amount_cents is not None]
    items_total = sum(amounts) if amounts else None
    mismatch = (
        expense.amount_cents - items_total
        if expense.amount_cents is not None and items_total is not None
        else None
    )
    return ExpenseItemsResponse(
        expense_id=expense.id,
        parent_amount_cents=expense.amount_cents,
        items_total_amount_cents=items_total,
        mismatch_cents=mismatch,
        items=[ExpenseItemResponse.model_validate(item) for item in items],
    )
