from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.config import get_settings
from app.database import get_db
from app.schemas import GoalCreateRequest, GoalListResponse, GoalResponse, GoalUpdateRequest
from app.services.goal_service import archive_goal, create_goal, get_goal_response, list_goals, update_goal
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
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    return update_goal(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        timezone_name=timezone_name,
    )


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
