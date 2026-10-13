"""Accept expense-detail subtasks and their first receipts in one transaction."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import (
    ExpenseAcknowledgeItemsMismatchRequest,
    ExpenseItemReplaceRequest,
    ExpenseItemsResponse,
    ExpenseSplitReplaceRequest,
    ExpenseSplitsResponse,
)
from app.services.expense_split_service import replace_expense_splits
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.receipt_item_service import acknowledge_items_sum_mismatch, replace_expense_items

SubtaskRequest = ExpenseItemReplaceRequest | ExpenseSplitReplaceRequest | ExpenseAcknowledgeItemsMismatchRequest
SubtaskReceipt = ExpenseItemsResponse | ExpenseSplitsResponse


def submit_expense_subtask(
    db: Session, *, expense_id: int, tenant_id: str, payload: SubtaskRequest,
    expected_row_version: int, idempotency_key: str | None,
    actor_account_id: int | None, actor_device_id: int | None,
) -> SubtaskReceipt:
    """Replay the original acceptance before consulting today's editable state."""
    operation = {ExpenseItemReplaceRequest: "replace_items", ExpenseSplitReplaceRequest: "replace_splits",
        ExpenseAcknowledgeItemsMismatchRequest: "acknowledge_items_mismatch"}[type(payload)]
    try:
        if not idempotency_key:
            raise AppError("idempotency_key_required", status_code=422)
        if len(idempotency_key) > 64:
            raise AppError("invalid_request", status_code=422)
        claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
            operation=operation, target_type="expense", target_id=str(expense_id),
            request_fingerprint=fingerprint_request(operation=operation, target_id=str(expense_id),
                body=payload.model_dump(mode="json", exclude_unset=True, exclude={"expected_row_version"}),
                expected_row_version=payload.expected_row_version))
        replay = _replayed_receipt(claim, payload)
        if replay is not None:
            return replay
        response = _apply_subtask(db, expense_id, tenant_id,
            payload.model_copy(update={"expected_row_version": expected_row_version}),
            actor_account_id=actor_account_id, actor_device_id=actor_device_id, idempotency_key=idempotency_key)
        mark_idempotency_succeeded(db, claim.row, resource_type="expense", resource_id=str(expense_id),
            response_body=response.model_dump(mode="json"))
        db.commit()
        return response
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise


def _apply_subtask(
    db: Session, expense_id: int, tenant_id: str, payload: SubtaskRequest, *,
    actor_account_id: int | None, actor_device_id: int | None, idempotency_key: str,
) -> SubtaskReceipt:
    if isinstance(payload, ExpenseItemReplaceRequest):
        return replace_expense_items(db, expense_id, tenant_id, payload, commit=False)
    if isinstance(payload, ExpenseSplitReplaceRequest):
        return replace_expense_splits(db, expense_id, tenant_id, payload,
            actor_account_id=actor_account_id, commit=False)
    return acknowledge_items_sum_mismatch(db, expense_id, tenant_id,
        expected_row_version=payload.expected_row_version, actor_account_id=actor_account_id,
        actor_device_id=actor_device_id, idempotency_key=idempotency_key, commit=False)


def _replayed_receipt(claim: IdempotencyOutcome, payload: SubtaskRequest) -> SubtaskReceipt | None:
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is not IdempotencyOutcomeKind.HIT:
        return None
    try:
        response_type = ExpenseSplitsResponse if isinstance(payload, ExpenseSplitReplaceRequest) else ExpenseItemsResponse
        receipt = response_type.model_validate(claim.row.response_body)
        if (claim.row.resource_type != "expense" or str(receipt.expense_id) != claim.row.resource_id
                or str(receipt.expense_id) != claim.row.target_id or receipt.row_version < 1):
            raise ValueError("Original subtask receipt does not match its expense")
        if payload.expected_row_version > 0 and receipt.row_version != payload.expected_row_version + 1:
            raise ValueError("Original subtask receipt does not match its accepted version")
        return receipt
    except (ValueError, ValidationError) as exc:
        raise AppError("expense_subtask_original_requires_review",
            "原分项操作已被接受，但原回执无法核对。请查看账单后继续，勿重复提交原操作。", status_code=409) from exc
