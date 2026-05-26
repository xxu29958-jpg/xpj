"""OCR retry / text re-recognition flows.

Both ``retry_expense_ocr`` and ``recognize_expense_text`` follow the same
optimistic-claim pattern: snapshot ``updated_at``, attempt to atomically
claim the row, then apply the OCR result against the pre-claim snapshot
so legacy draft-field detection stays consistent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.schemas import ExpenseRecognizeTextRequest
from app.services.classify_service import classify_expense
from app.services.duplicate_service import mark_duplicate_status
from app.services.expense_service._helpers import (
    _replace_ocr_draft_items_from_text,
    _updated_at_matches,
)
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.expense_service._query import get_expense
from app.services.learning_service import read_ocr_text
from app.services.ocr_service import OcrResult, extract_ocr_result
from app.services.time_service import now_utc

__all__ = ["recognize_expense_text", "retry_expense_ocr"]


def _claim_pending_expense_for_ocr(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_updated_at,
    claimed_at,
) -> Expense:
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .where(Expense.status == "pending")
        .where(_updated_at_matches(expected_updated_at))
        .values(updated_at=claimed_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        current = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
        )
        if current is None or current.status != "pending":
            raise AppError("expense_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)
    db.expire_all()
    return get_expense(db, expense_id, tenant_id)


def retry_expense_ocr(
    db: Session,
    expense_id: int,
    tenant_id: str,
    *,
    expected_updated_at: datetime,
) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)
    provider_name = _active_provider_name()
    if provider_name == "empty":
        raise AppError(
            "ocr_not_configured",
            "未配置 OCR，请在后端启用 OCR_PROVIDER 后再重试。",
            status_code=503,
        )

    result = extract_ocr_result(expense)
    now = now_utc()
    expense = _claim_pending_expense_for_ocr(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_updated_at=expected_updated_at,
        claimed_at=now,
    )
    # Keep legacy OCR draft-field detection anchored to the pre-claim snapshot.
    expense.updated_at = expected_updated_at
    apply_ocr_result_and_append_fact(
        db,
        expense=expense,
        result=result,
        provider_name=provider_name,
        ocr_model=_active_provider_model(provider_name),
    )
    # v1.2 OCR single-source migration (step 4): pull the canonical
    # OCR text via ``read_ocr_text`` instead of the deprecated
    # ``expense.raw_text`` column. ``append_ocr_fact`` above already
    # wrote the latest fact, so this is a single fact lookup against
    # the row we just inserted (no N+1, no stale-read risk).
    _replace_ocr_draft_items_from_text(
        db,
        expense,
        read_ocr_text(db, tenant_id=expense.tenant_id, expense=expense) or "",
    )
    if expense.category == "其他":
        classify_expense(db, expense)
    if (
        expense.amount_cents is not None
        or expense.merchant
        or expense.expense_time is not None
    ):
        mark_duplicate_status(db, expense)
    expense.updated_at = now
    db.commit()
    db.refresh(expense)
    return expense


def recognize_expense_text(
    db: Session, expense_id: int, tenant_id: str, payload: ExpenseRecognizeTextRequest
) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status != "pending":
        raise AppError("expense_not_found", status_code=404)

    raw_text = payload.raw_text.strip()
    expected_updated_at = expense.updated_at
    now = now_utc()
    expense = _claim_pending_expense_for_ocr(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_updated_at=expected_updated_at,
        claimed_at=now,
    )
    # Keep legacy OCR draft-field detection anchored to the pre-claim snapshot.
    expense.updated_at = expected_updated_at
    result = OcrResult(raw_text=raw_text, confidence=None)
    apply_ocr_result_and_append_fact(
        db,
        expense=expense,
        result=result,
        provider_name="manual_text",
    )
    _replace_ocr_draft_items_from_text(db, expense, raw_text)
    if expense.category == "其他":
        classify_expense(db, expense)
    if (
        expense.amount_cents is not None
        or expense.merchant
        or expense.expense_time is not None
    ):
        mark_duplicate_status(db, expense)
    expense.updated_at = now
    db.commit()
    db.refresh(expense)
    return expense


def _active_provider_name() -> str:
    clean = (get_settings().ocr_provider or "").strip().lower()
    if clean == "rapid_ocr":
        return "rapidocr"
    if clean in {"local_vlm", "vlm"}:
        return "local_llm"
    return clean or "empty"


def _active_provider_model(provider_name: str) -> str | None:
    if provider_name == "local_llm":
        return get_settings().local_llm_model or None
    if provider_name == "rapidocr":
        return "rapidocr"
    return None
