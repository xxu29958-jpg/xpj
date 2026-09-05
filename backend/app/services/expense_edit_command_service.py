"""Transactional command shared by API and Web expense edits."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import get_expense, update_expense
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)

_EDIT_OPERATION = "patch_expense"


def edit_expense_submission(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
    request_expected_row_version: int,
    idempotency_key: str | None,
    intent_body: dict[str, object],
    update_payload: ExpenseUpdateRequest,
    require_idempotency: bool = False,
) -> Expense:
    """Apply one exact edit intent with atomic OCC and replay protection.

    ``intent_body`` is supplied by the transport adapter.  API callers use the
    canonical JSON request while Web callers use every raw business-form field;
    neither derives the idempotency fingerprint from a sparse diff against the
    current row.  That keeps a committed-but-unseen replay stable after the row
    has already changed.
    """

    try:
        claim = None
        if idempotency_key or require_idempotency:
            claim = claim_idempotent_request(
                db,
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
                operation=_EDIT_OPERATION,
                target_id=str(expense_id),
                body=intent_body,
                expected_row_version=request_expected_row_version,
            )
            if claim is None:
                return get_expense(db, expense_id, tenant_id)

        expense = update_expense(
            db,
            expense_id,
            tenant_id,
            update_payload.model_copy(update={"expected_row_version": expected_row_version}),
            commit=False,
        )
        if claim is not None:
            mark_idempotency_succeeded(
                db,
                claim,
                resource_type="expense",
                resource_id=str(expense_id),
            )
        db.commit()
        db.refresh(expense)
        return expense
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise
