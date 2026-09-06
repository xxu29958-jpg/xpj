"""Transactional owner of explicit monthly fulfillment and its reversal."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, RecurringItem, RecurringOccurrence, RecurringOccurrenceRevision
from app.schemas._recurring_occurrence import RecurringOccurrenceResponse, RecurringOccurrenceWriteRequest
from app.services.currency_binding_service import resolve_write_capability
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.recurring_occurrence_query import eligible_payment_query, occurrence_period, occurrence_response
from app.services.spending_contract_service import clean_month
from app.services.time_service import now_utc

_OPERATION = "set_recurring_occurrence_payment"


def _claim(db, *, tenant_id, public_id, month, payload, key):
    if not key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(key) > 128:
        raise AppError("invalid_request", status_code=422)
    target = f"{public_id}:{month}"
    outcome = claim_idempotency_key(
        db, tenant_id=tenant_id, idempotency_key=key, operation=_OPERATION,
        request_fingerprint=fingerprint_request(
            operation=_OPERATION, target_id=target,
            body=payload.model_dump(mode="json"), expected_row_version=payload.expected_row_version,
        ),
        target_type="recurring_occurrence", target_id=target,
    )
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    return outcome


def _lock_series(db, *, tenant_id, public_id, expected_row_version):
    item = db.scalar(select(RecurringItem).where(
        RecurringItem.tenant_id == tenant_id,
        RecurringItem.public_id == public_id,
    ).with_for_update().execution_options(populate_existing=True))
    if item is None:
        raise AppError("recurring_item_not_found", status_code=404)
    if item.status == "archived":
        raise AppError("recurring_item_archived", status_code=409)
    if item.row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)
    return item


def _lock_payment(db, *, tenant_id, payload, item, period):
    if payload.expense_public_id is None:
        return None
    # Lock the root before checking offsets; offset/correction commands lock this
    # same root. A reversal cannot race between eligibility and publication.
    expense = db.scalar(select(Expense).where(
        Expense.tenant_id == tenant_id,
        Expense.public_id == payload.expense_public_id,
    ).with_for_update().execution_options(populate_existing=True))
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    eligible = db.scalar(eligible_payment_query(tenant_id=tenant_id).where(Expense.id == expense.id))
    if eligible is None:
        raise AppError("state_conflict", "这笔付款已撤回或冲销，请重新核对账单。", status_code=409)
    if expense.row_version != payload.expected_expense_row_version:
        raise AppError("state_conflict", "所选账单已变化，请核对最新账单后重新关联。", status_code=409)
    occupied = db.scalar(select(RecurringOccurrence).where(
        RecurringOccurrence.tenant_id == tenant_id,
        RecurringOccurrence.expense_id == expense.id,
    ))
    if occupied and (occupied.series_id != item.id or occupied.period_start != period):
        raise AppError("state_conflict", "这笔付款已关联另一项固定支出或另一月份。", status_code=409)
    return expense


def set_occurrence_payment(
    db: Session, *, tenant_id: str, public_id: str, month: str,
    actor_account_id: int, idempotency_key: str | None,
    payload: RecurringOccurrenceWriteRequest,
) -> RecurringOccurrenceResponse:
    period = occurrence_period(clean_month(month))
    claim = _claim(
        db, tenant_id=tenant_id, public_id=public_id, month=month,
        payload=payload, key=idempotency_key,
    )
    if claim.kind is IdempotencyOutcomeKind.HIT:
        # This typed aggregate includes period state, source payment and schedule.
        # A later unlink must not rewrite the first command's successful result.
        return RecurringOccurrenceResponse.model_validate(claim.row.response_body)
    resolve_write_capability(db)
    item = _lock_series(
        db, tenant_id=tenant_id, public_id=public_id,
        expected_row_version=payload.expected_series_row_version,
    )
    row = db.get(RecurringOccurrence, (tenant_id, item.id, period), populate_existing=True)
    if (row.row_version if row else 0) != payload.expected_row_version:
        raise AppError("state_conflict", status_code=409)
    payment = _lock_payment(db, tenant_id=tenant_id, payload=payload, item=item, period=period)
    previous_id = row.expense_id if row else None
    payment_id = payment.id if payment else None
    if previous_id == payment_id:
        raise AppError("invalid_request", "本期付款关联没有变化。", status_code=422)
    if row is None:
        row = RecurringOccurrence(tenant_id=tenant_id, series_id=item.id, period_start=period, row_version=1)
        db.add(row)
    else:
        row.row_version += 1
    row.expense_id = payment_id
    row.updated_at = now_utc()
    db.flush()
    db.add(RecurringOccurrenceRevision(
        tenant_id=tenant_id, series_id=item.id, period_start=period,
        revision_number=row.row_version, previous_expense_id=previous_id, expense_id=payment_id,
        actor_account_id=actor_account_id, idempotency_key=idempotency_key,
    ))
    result = occurrence_response(db, item=item, period=period)
    mark_idempotency_succeeded(
        db, claim.row, resource_type="recurring_occurrence",
        resource_id=f"{public_id}:{month}", response_body=result.model_dump(mode="json"),
    )
    db.commit()
    return result
