"""The spending-goal update transaction shared by API and native Web forms."""

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import GoalResponse, GoalUpdateRequest
from app.services.goal_service import update_goal
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)


def update_goal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: GoalUpdateRequest,
    idempotency_key: str | None,
    timezone_name: str,
) -> GoalResponse:
    # Claim before OCC: replaying a committed but unseen edit must not conflict
    # with its own version increment. Both writes commit in one transaction.
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    claim = claim_idempotency_key(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="update_goal",
        target_id=public_id,
        request_fingerprint=fingerprint_request(
            operation="update_goal", target_id=public_id,
            body=payload.model_dump(mode="json", exclude_unset=True, exclude={"expected_row_version"}),
            expected_row_version=payload.expected_row_version,
        ),
        target_type="goal",
    )
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        body = claim.row.response_body
        if not body or not body.get("home_currency_code"):
            raise AppError("goal_original_requires_review", "原修改已被接受，但缺少原回执。请核对目标，勿重复提交。", status_code=409)
        return GoalResponse.model_validate(body)
    result = update_goal(
        db, tenant_id=tenant_id, public_id=public_id, payload=payload,
        timezone_name=timezone_name, commit=False,
    )
    mark_idempotency_succeeded(db, claim.row, resource_type="goal", resource_id=public_id,
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result
