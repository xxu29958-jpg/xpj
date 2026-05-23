"""ADR-0030 background_tasks read API.

PR-1 exposes only query + cancel. Enqueue is internal — csv-import /
v1-migration each add their own ``POST /api/tasks/csv-import`` etc.
routes in their own PR.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import BackgroundTaskListResponse, BackgroundTaskResponse
from app.services import background_task_service as bgtasks
from app.tenants import AuthContext

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=BackgroundTaskListResponse)
def list_my_tasks(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BackgroundTaskListResponse:
    rows = bgtasks.list_recent_tasks(db, account_id=auth.account_id)
    return BackgroundTaskListResponse(
        items=[BackgroundTaskResponse.model_validate(bgtasks.to_response_dict(t)) for t in rows]
    )


@router.get("/{public_id}", response_model=BackgroundTaskResponse)
def get_task(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BackgroundTaskResponse:
    task = bgtasks.get_task(db, public_id, account_id=auth.account_id)
    return BackgroundTaskResponse.model_validate(bgtasks.to_response_dict(task))


@router.post("/{public_id}/cancel", response_model=BackgroundTaskResponse)
def cancel_task(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BackgroundTaskResponse:
    task = bgtasks.request_cancellation(db, public_id, account_id=auth.account_id)
    return BackgroundTaskResponse.model_validate(bgtasks.to_response_dict(task))
