"""HTTP response assembly for expenses."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import Expense
from app.schemas import ExpenseResponse
from app.services.learning_service import read_ocr_text, read_ocr_texts


def expense_to_response(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    raw_text_by_id: dict[int, str] | None = None,
) -> ExpenseResponse:
    dto = ExpenseResponse.model_validate(expense)
    if raw_text_by_id is None:
        dto.raw_text = read_ocr_text(db, tenant_id=tenant_id, expense=expense)
    else:
        dto.raw_text = raw_text_by_id.get(int(expense.id))
    return dto


def expenses_to_responses(
    db: Session,
    *,
    tenant_id: str,
    expenses: Iterable[Expense],
) -> list[ExpenseResponse]:
    rows = list(expenses)
    raw_text_by_id = read_ocr_texts(db, tenant_id=tenant_id, expenses=rows)
    return [
        expense_to_response(
            db,
            tenant_id=tenant_id,
            expense=expense,
            raw_text_by_id=raw_text_by_id,
        )
        for expense in rows
    ]


def expense_raw_text_by_id(
    db: Session,
    *,
    tenant_id: str,
    expenses: Iterable[Expense],
) -> dict[int, str]:
    return read_ocr_texts(db, tenant_id=tenant_id, expenses=list(expenses))
