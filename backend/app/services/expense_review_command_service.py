"""Transactional commands for composite expense-review decisions.

HTTP routes adapt browser input and render outcomes.  This module owns the
cross-service transaction boundaries so API, Web, Desktop, and future workers
cannot invent different save/confirm or duplicate-resolution ordering.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseResponse, ExpenseUpdateRequest
from app.services.cleanup_service import cleanup_after_confirm
from app.services.expense_response_service import expense_to_response
from app.services.expense_service import (
    confirm_expense,
    get_expense,
    mark_expense_not_duplicate,
    reject_expense,
    undo_reject_expense,
    update_expense,
)
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    claim_idempotent_request,
    fingerprint_request,
    mark_idempotency_succeeded,
)

_CONFIRM_OPERATION = "confirm_expense"


def _replayed_rejection_receipt(claim: IdempotencyOutcome) -> ExpenseResponse | None:
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is not IdempotencyOutcomeKind.HIT:
        return None
    try:
        receipt = ExpenseResponse.model_validate(claim.row.response_body)
        statuses = {"rejected"} if claim.row.operation == "reject_expense" else {"pending", "confirmed"}
        if (claim.row.resource_type != "expense" or str(receipt.id) != claim.row.resource_id
                or str(receipt.id) != claim.row.target_id or receipt.row_version < 1 or receipt.status not in statuses):
            raise ValueError("Original rejection receipt does not match its resource")
        return receipt
    except (ValueError, ValidationError) as exc:
        raise AppError("expense_rejection_original_requires_review",
            "原操作已被接受，但原回执无法核对。请查看账单，勿重新提交或撤销其它操作。", status_code=409) from exc


def submit_expense_rejection(
    db: Session,
    *,
    operation: Literal["reject_expense", "undo_expense"],
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
    request_expected_row_version: int,
    idempotency_key: str | None,
    actor_account_id: int | None,
) -> ExpenseResponse:
    """Accept one reviewed rejection/Undo and its original response in one transaction."""
    try:
        if not idempotency_key:
            raise AppError("idempotency_key_required", status_code=422)
        if len(idempotency_key) > 64:
            raise AppError("invalid_request", status_code=422)
        claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
            operation=operation, target_type="expense", target_id=str(expense_id),
            request_fingerprint=fingerprint_request(operation=operation, target_id=str(expense_id),
                body={}, expected_row_version=request_expected_row_version))
        replayed = _replayed_rejection_receipt(claim)
        if replayed is not None:
            return replayed
        if operation == "reject_expense":
            expense = reject_expense(db, expense_id, tenant_id,
                expected_row_version=expected_row_version, commit=False)
        else:
            expense = undo_reject_expense(db, expense_id, tenant_id, expected_row_version,
                actor_account_id=actor_account_id)
        response = expense_to_response(db, tenant_id=tenant_id, expense=expense)
        mark_idempotency_succeeded(db, claim.row, resource_type="expense", resource_id=str(expense_id),
            response_body=response.model_dump(mode="json"))
        db.commit()
        return response
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise


def _commit_confirmation_and_cleanup(db: Session, expense: Expense) -> None:
    """Commit the financial state before the independently retryable file GC."""

    db.commit()
    db.refresh(expense)
    if cleanup_after_confirm(db, expense):
        db.commit()
        db.refresh(expense)


def _save_then_confirm(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
    payload: ExpenseUpdateRequest,
    actor_account_id: int | None,
    actor_device_id: int | None,
) -> Expense:
    if payload.expected_row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)
    updated = update_expense(
        db,
        expense_id,
        tenant_id,
        payload,
        commit=False,
    )
    return confirm_expense(
        db,
        expense_id,
        tenant_id,
        expected_row_version=updated.row_version,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        commit=False,
    )


def confirm_expense_submission(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
    request_expected_row_version: int,
    idempotency_key: str | None,
    intent_body: dict[str, object],
    update_payload: ExpenseUpdateRequest | None,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    require_idempotency: bool = False,
) -> Expense:
    """Confirm one browser snapshot, optionally saving its edits atomically.

    ``update_payload is None`` is the ordinary confirm command.  A payload means
    save-before-confirm: the update and confirmation share one database commit.

    A stable request key is mandatory for save-before-confirm and for API
    callers.  Its fingerprint contains the complete adapter intent, not the
    sparse update diff, so a response-loss replay can skip OCC only when the
    exact submitted form already succeeded.  Different intent under the same
    key is rejected; different keys still compete through OCC.
    """

    try:
        uses_idempotency = bool(idempotency_key) or require_idempotency or update_payload is not None
        claim = None
        if uses_idempotency:
            claim = claim_idempotent_request(
                db,
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
                operation=_CONFIRM_OPERATION,
                target_id=str(expense_id),
                body=intent_body,
                expected_row_version=request_expected_row_version,
            )
            if claim is None:
                return get_expense(db, expense_id, tenant_id)

        if update_payload is not None:
            confirmed = _save_then_confirm(
                db,
                expense_id=expense_id,
                tenant_id=tenant_id,
                expected_row_version=expected_row_version,
                payload=update_payload,
                actor_account_id=actor_account_id,
                actor_device_id=actor_device_id,
            )
        else:
            confirmed = confirm_expense(
                db,
                expense_id,
                tenant_id,
                expected_row_version=expected_row_version,
                actor_account_id=actor_account_id,
                actor_device_id=actor_device_id,
                commit=False,
            )
        if claim is not None:
            mark_idempotency_succeeded(
                db,
                claim,
                resource_type="expense",
                resource_id=str(expense_id),
            )
        _commit_confirmation_and_cleanup(db, confirmed)
        return confirmed
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise


def reject_duplicate_original_keep_current(
    db: Session,
    *,
    current_expense_id: int,
    original_expense_id: int,
    tenant_id: str,
    expected_row_version: int,
    expected_original_row_version: int,
) -> None:
    """Apply a two-snapshot duplicate decision as one transaction."""

    try:
        rows = list(
            db.scalars(
                select(Expense)
                .where(Expense.tenant_id == tenant_id)
                .where(Expense.id.in_((current_expense_id, original_expense_id)))
                .order_by(Expense.id.asc())
                .with_for_update()
            )
        )
        by_id = {row.id: row for row in rows}
        current = by_id.get(current_expense_id)
        original = by_id.get(original_expense_id)
        snapshots_match = (
            current is not None
            and original is not None
            and current.id != original.id
            and current.duplicate_of_id == original.id
            and current.row_version == expected_row_version
            and original.row_version == expected_original_row_version
        )
        if not snapshots_match:
            raise AppError("state_conflict", status_code=409)

        if original.status == "confirmed":
            raise AppError("expense_reversal_required", status_code=409)
        if original.status != "pending":
            raise AppError("state_conflict", status_code=409)

        mark_expense_not_duplicate(
            db,
            current.id,
            tenant_id,
            expected_row_version=expected_row_version,
            commit=False,
        )
        reject_expense(
            db,
            original.id,
            tenant_id,
            expected_row_version=expected_original_row_version,
            commit=False,
        )
        db.commit()
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise
