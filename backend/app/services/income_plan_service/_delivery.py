"""Settle an income edit and its original typed result in one transaction."""

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import IncomePlanResponse, IncomePlanUpdateRequest
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)

from . import update_income_plan


def update_income_plan_idempotently(
    db: Session, *, tenant_id: str, public_id: str,
    payload: IncomePlanUpdateRequest, actor_account_id: int | None,
    idempotency_key: str | None,
) -> IncomePlanResponse:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    claim = claim_idempotency_key(
        db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation="update_income_plan", target_type="income_plan", target_id=public_id,
        request_fingerprint=fingerprint_request(
            operation="update_income_plan", target_id=public_id,
            body={"actor_account_id": actor_account_id, "intent": payload.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_row_version"},
            )}, expected_row_version=payload.expected_row_version,
        ),
    )
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return IncomePlanResponse.model_validate(claim.row.response_body)
    plan = update_income_plan(
        db, tenant_id=tenant_id, public_id=public_id,
        expected_row_version=payload.expected_row_version,
        label=payload.label, source_type=payload.source_type,
        frequency=payload.frequency, income_month=payload.income_month,
        income_month_provided="income_month" in payload.model_fields_set,
        amount_cents=payload.amount_cents, pay_day=payload.pay_day,
        intent_month=payload.intent_month, actor_account_id=actor_account_id, commit=False,
    )
    result = IncomePlanResponse.model_validate(plan, from_attributes=True)
    mark_idempotency_succeeded(db, claim.row, resource_type="income_plan", resource_id=public_id,
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result
