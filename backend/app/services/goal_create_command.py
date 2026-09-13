"""Create one spending goal and retain the receipt of its original intent."""

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import GoalCreateRequest, GoalResponse
from app.services.goal_service import create_goal
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)


def _replayed_receipt(claim: IdempotencyOutcome) -> GoalResponse | None:
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is not IdempotencyOutcomeKind.HIT:
        return None
    body = claim.row.response_body
    if not body or not body.get("home_currency_code"):
        raise AppError("goal_original_requires_review", "原创建已被接受，但缺少原回执。请核对目标，勿重复创建。", status_code=409)
    return GoalResponse.model_validate(body)


def create_spending_goal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    payload: GoalCreateRequest,
    idempotency_key: str | None,
    timezone_name: str | None = None,
) -> GoalResponse:
    if payload.goal_type.strip() != "spending_limit":
        raise AppError("invalid_request", status_code=422)
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    claim = claim_idempotency_key(
        db, tenant_id=tenant_id, idempotency_key=idempotency_key, operation="create_goal",
        request_fingerprint=fingerprint_request(
            operation="create_goal", target_id=None, body=payload.model_dump(mode="json"),
            expected_row_version=None,
        ),
        target_type="goal",
    )
    replayed = _replayed_receipt(claim)
    if replayed is not None:
        return replayed
    result = create_goal(db, tenant_id=tenant_id, payload=payload, timezone_name=timezone_name, commit=False)
    mark_idempotency_succeeded(db, claim.row, resource_type="goal", resource_id=result.public_id,
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result
