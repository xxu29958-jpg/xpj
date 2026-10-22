"""HTTP response assembly for expenses."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import Expense, OcrFact
from app.schemas import BackgroundTaskResponse, ExpenseResponse
from app.schemas._recognition_time import RecognitionTimeResponse
from app.services.accounting_time_service import accounting_time_snapshot
from app.services.background_task_response import task_response_dicts
from app.services.learning_service import read_ocr_facts
from app.services.recognition_time_service import recognition_amount_notes, recognition_time


def expense_to_response(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    ocr_facts_by_id: dict[int, OcrFact] | None = None,
    fx_tasks_by_id: dict[int, BackgroundTaskResponse] | None = None,
    notification_times_by_id: dict[str, RecognitionTimeResponse] | None = None,
) -> ExpenseResponse:
    dto = ExpenseResponse.model_validate(expense)
    dto.accounting_time = accounting_time_snapshot(expense)
    if fx_tasks_by_id is None:
        fx_tasks_by_id = expense_fx_tasks_by_id(db, tenant_id=tenant_id, expenses=[expense])
    dto.fx_task = fx_tasks_by_id.get(expense.id)
    if ocr_facts_by_id is None:
        ocr_facts_by_id = read_ocr_facts(db, tenant_id=tenant_id, expenses=[expense])
    fact = ocr_facts_by_id.get(int(expense.id))
    dto.raw_text = fact.raw_text if fact is not None else None
    dto.recognition_time = recognition_time(fact, notification=(notification_times_by_id or {}).get(expense.public_id))
    dto.recognition_notes = recognition_amount_notes(fact)
    return dto


def expenses_to_responses(
    db: Session,
    *,
    tenant_id: str,
    expenses: Iterable[Expense],
) -> list[ExpenseResponse]:
    rows = list(expenses)
    ocr_facts_by_id = read_ocr_facts(db, tenant_id=tenant_id, expenses=rows)
    fx_tasks_by_id = expense_fx_tasks_by_id(db, tenant_id=tenant_id, expenses=rows)
    return [
        expense_to_response(
            db,
            tenant_id=tenant_id,
            expense=expense,
            ocr_facts_by_id=ocr_facts_by_id,
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


def expense_ocr_facts_by_id(
    db: Session,
    *,
    tenant_id: str,
    expenses: Iterable[Expense],
) -> dict[int, OcrFact]:
    return read_ocr_facts(db, tenant_id=tenant_id, expenses=list(expenses))
