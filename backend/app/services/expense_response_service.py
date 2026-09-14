"""HTTP response assembly for expenses."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import Expense
from app.schemas import BackgroundTaskResponse, ExpenseResponse
from app.services.background_task_response import task_response_dicts
from app.services.learning_service import read_ocr_text, read_ocr_texts


def expense_to_response(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    raw_text_by_id: dict[int, str] | None = None,
    fx_tasks_by_id: dict[int, BackgroundTaskResponse] | None = None,
) -> ExpenseResponse:
    dto = ExpenseResponse.model_validate(expense)
    if fx_tasks_by_id is None:
        fx_tasks_by_id = expense_fx_tasks_by_id(db, tenant_id=tenant_id, expenses=[expense])
    dto.fx_task = fx_tasks_by_id.get(expense.id)
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
    fx_tasks_by_id = expense_fx_tasks_by_id(db, tenant_id=tenant_id, expenses=rows)
    return [
        expense_to_response(
            db,
            tenant_id=tenant_id,
            expense=expense,
            raw_text_by_id=raw_text_by_id,
            fx_tasks_by_id=fx_tasks_by_id,
        )
        for expense in rows
    ]


def expense_fx_tasks_by_id(
    db: Session, *, tenant_id: str, expenses: Iterable[Expense],
) -> dict[int, BackgroundTaskResponse]:
    from app.services.pending_fx_task_service import current_pending_expense_fx_tasks

    rows = [expense for expense in expenses if expense.tenant_id == tenant_id and expense.status == "pending"]
    tasks = current_pending_expense_fx_tasks(db, tenant_id=tenant_id, expenses=rows)
    responses = task_response_dicts(db, list(tasks.values()), tenant_id=tenant_id)
    return {item["source_expense_id"]: BackgroundTaskResponse.model_validate(item)
            for item in responses if item["source_expense_id"] is not None}


def expense_raw_text_by_id(
    db: Session,
    *,
    tenant_id: str,
    expenses: Iterable[Expense],
) -> dict[int, str]:
    return read_ocr_texts(db, tenant_id=tenant_id, expenses=list(expenses))
