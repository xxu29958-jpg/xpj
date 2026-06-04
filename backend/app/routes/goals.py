from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.config import get_settings
from app.database import get_db
from app.schemas import GoalCreateRequest, GoalListResponse, GoalResponse, GoalUpdateRequest
from app.services.goal_service import archive_goal, create_goal, get_goal_response, list_goals, update_goal
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)
from app.services.time_service import current_month
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/goals",
    tags=["goals"],
)


@router.get("", response_model=GoalListResponse)
def get_goals(
    month: str | None = None,
    include_archived: bool = False,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> GoalListResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    target_month = month or current_month(timezone_name)
    return GoalListResponse(
        items=list_goals(
            db,
            tenant_id=auth.tenant_id,
            month=target_month,
            timezone_name=timezone_name,
            include_archived=include_archived,
        )
    )


@router.get("/{public_id}", response_model=GoalResponse)
def get_goal_detail(
    public_id: str,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    return get_goal_response(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        timezone_name=timezone_name,
    )


@router.post("", response_model=GoalResponse, status_code=201)
def post_goal(
    payload: GoalCreateRequest,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    return create_goal(
        db,
        tenant_id=auth.tenant_id,
        payload=payload,
        timezone_name=timezone_name,
    )


@router.patch("/{public_id}", response_model=GoalResponse)
def patch_goal(
    public_id: str,
    payload: GoalUpdateRequest,
    timezone: str | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    # ADR-0038 PR-2j: ``expected_row_version`` token gates the PATCH (409 on a
    # stale snapshot). ADR-0042: claim the Idempotency-Key before that OCC claim
    # so an offline-outbox replay of a committed-but-unseen edit re-serialises
    # the goal instead of false-409ing on the bumped row_version.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="update_goal",
        target_id=public_id,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="goal",
    )
    if claim is None:  # §4.6 HIT — re-serialise the current goal
        return get_goal_response(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            timezone_name=timezone_name,
        )

    result = update_goal(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        timezone_name=timezone_name,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="goal", resource_id=public_id
    )
    db.commit()
    return result


@router.post("/{public_id}/archive", response_model=GoalResponse)
def post_goal_archive(
    public_id: str,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    return archive_goal(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        timezone_name=timezone_name,
    )
