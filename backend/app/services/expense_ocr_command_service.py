"""OCR commands shared by API and Web consumers."""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseRecognizeTextRequest
from app.services.expense_service import get_expense, recognize_expense_text, retry_expense_ocr
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.pending_fx_task_service import prepare_pending_expense_fx, submit_pending_expense_fx


def submit_expense_ocr_retry(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    initiator_account_id: int,
    initiator_device_id: int | None,
    expected_row_version: int,
    request_expected_row_version: int,
    idempotency_key: str | None,
) -> Expense:
    try:
        claim = claim_idempotent_request(
            db,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            operation="retry_ocr",
            target_id=str(expense_id),
            body={},
            expected_row_version=request_expected_row_version,
        )
        if claim is None:
            return get_expense(db, expense_id, tenant_id)

        expense = retry_expense_ocr(
            db, expense_id, tenant_id, expected_row_version=expected_row_version, commit=False,
        )
        fx_task = prepare_pending_expense_fx(db, expense=expense,
            initiator_account_id=initiator_account_id, initiator_device_id=initiator_device_id)
        mark_idempotency_succeeded(db, claim, resource_type="expense", resource_id=str(expense_id))
        db.commit()
        if fx_task is not None:
            submit_pending_expense_fx(db, fx_task)
        db.refresh(expense)
        return expense
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise


def submit_expense_text_recognition(
    db: Session, *, expense_id: int, tenant_id: str,
    initiator_account_id: int, initiator_device_id: int | None,
    payload: ExpenseRecognizeTextRequest, expected_row_version: int,
    idempotency_key: str | None,
) -> Expense:
    """Preserve the existing recognize-text fingerprint, claim and single commit."""
    try:
        claim = claim_idempotent_request(db, idempotency_key=idempotency_key, tenant_id=tenant_id,
            operation="recognize_text", target_id=str(expense_id),
            body=payload.model_dump(mode="json", exclude_unset=True, exclude={"expected_row_version"}),
            expected_row_version=payload.expected_row_version)
        if claim is None:
            return get_expense(db, expense_id, tenant_id)
        expense = recognize_expense_text(db, expense_id, tenant_id,
            payload.model_copy(update={"expected_row_version": expected_row_version}), commit=False)
        fx_task = prepare_pending_expense_fx(db, expense=expense,
            initiator_account_id=initiator_account_id, initiator_device_id=initiator_device_id)
        mark_idempotency_succeeded(db, claim, resource_type="expense", resource_id=str(expense_id))
        db.commit()
        if fx_task is not None:
            submit_pending_expense_fx(db, fx_task)
        db.refresh(expense)
        return expense
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise
