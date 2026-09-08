"""The spending-goal update transaction shared by API and native Web forms."""

from sqlalchemy.orm import Session

from app.schemas import GoalResponse, GoalUpdateRequest
from app.services.goal_service import get_goal_response, update_goal
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded


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
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="update_goal",
        target_id=public_id,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="goal",
    )
    if claim is None:
        return get_goal_response(
            db, tenant_id=tenant_id, public_id=public_id,
            timezone_name=timezone_name, persist_achievement=True,
        )
    result = update_goal(
        db, tenant_id=tenant_id, public_id=public_id, payload=payload,
        timezone_name=timezone_name, commit=False,
    )
    mark_idempotency_succeeded(db, claim, resource_type="goal", resource_id=public_id)
    db.commit()
    return result
