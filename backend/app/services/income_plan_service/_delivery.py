"""Settle income commands and their original typed results in one transaction."""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.schemas import IncomePlanCreateRequest, IncomePlanResponse, IncomePlanUpdateRequest
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)

from . import create_income_plan, update_income_plan


def _income_create_receipt(claim: IdempotencyOutcome) -> IncomePlanResponse:
    try:
        result = IncomePlanResponse.model_validate(claim.row.response_body)
        if result.public_id != claim.row.resource_id or not result.home_currency_code:
            raise ValueError("Incomplete original receipt")
        return result
    except (ValidationError, ValueError) as exc:
        raise AppError("income_plan_response_unverified",
            "原提交已被接受，但缺少可核对的原回执。请保留提交并核对收入计划。", status_code=409) from exc


def create_income_plan_idempotently(
    db: Session, *, tenant_id: str, payload: IncomePlanCreateRequest,
    actor_account_id: int | None, idempotency_key: str | None,
) -> IncomePlanResponse:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    claim = claim_idempotency_key(
        db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation="create_income_plan", target_type="income_plan", target_id=None,
        request_fingerprint=fingerprint_request(operation="create_income_plan", target_id=None,
            body={"actor_account_id": actor_account_id, "intent": payload.model_dump(mode="json")},
            expected_row_version=None),
    )
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return _income_create_receipt(claim)
    plan = create_income_plan(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
        commit=False, **payload.model_dump())
    result = IncomePlanResponse.model_validate(plan, from_attributes=True)
    mark_idempotency_succeeded(db, claim.row, resource_type="income_plan", resource_id=result.public_id,
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result


def _income_receipt_result(db: Session, *, tenant_id: str, public_id: str, body) -> IncomePlanResponse:
    result = IncomePlanResponse.model_validate(body)
    if result.public_id != public_id:
        raise AppError("income_plan_response_unverified", "原提交结果与计划不一致，请保留原提交并核对。", status_code=409)
    if result.home_currency_code is not None:
        return result
    revision = db.scalar(select(IncomePlanRevision).join(
        MonthlyIncomePlan, (MonthlyIncomePlan.id == IncomePlanRevision.plan_id)
        & (MonthlyIncomePlan.tenant_id == IncomePlanRevision.tenant_id),
    ).where(
        IncomePlanRevision.tenant_id == tenant_id, MonthlyIncomePlan.public_id == public_id,
        IncomePlanRevision.revision_number == result.row_version,
    ))
    fields = ("label", "source_type", "frequency", "income_month", "amount_cents", "pay_day", "status")
    if revision is None or not revision.home_currency_code or any(
        getattr(revision, field) != getattr(result, field) for field in fields
    ):
        raise AppError("income_plan_response_unverified", "原提交的币种还无法确认，请保留记录并核对计划。", status_code=409)
    return result.model_copy(update={"home_currency_code": revision.home_currency_code})


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
        return _income_receipt_result(db, tenant_id=tenant_id, public_id=public_id, body=claim.row.response_body)
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
