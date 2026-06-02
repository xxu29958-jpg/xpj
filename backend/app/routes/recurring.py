from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    RecurringCandidateConfirmRequest,
    RecurringItemListResponse,
    RecurringItemResponse,
    RecurringItemTokenRequest,
)
from app.services.recurring_service import (
    archive_recurring_item,
    confirm_recurring_candidate,
    get_recurring_item,
    list_recurring_items,
    pause_recurring_item,
    recurring_amount_anomalies,
    recurring_item_response,
    resume_recurring_item,
)
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/recurring",
    tags=["recurring"],
)


@router.get("/items", response_model=RecurringItemListResponse)
def get_recurring_items(
    status: str | None = None,
    include_archived: bool = False,
    month: str | None = None,
    timezone: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RecurringItemListResponse:
    items = list_recurring_items(
        db,
        tenant_id=auth.tenant_id,
        status=status,
        include_archived=include_archived,
    )
    anomalies = recurring_amount_anomalies(
        db,
        tenant_id=auth.tenant_id,
        items=items,
        month=month,
        timezone_name=timezone,
    )
    return RecurringItemListResponse(
        items=[recurring_item_response(item, anomalies.get(item.public_id)) for item in items]
    )


@router.post("/from-candidate", response_model=RecurringItemResponse)
def post_recurring_from_candidate(
    payload: RecurringCandidateConfirmRequest,
    timezone: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    item = confirm_recurring_candidate(
        db,
        tenant_id=auth.tenant_id,
        payload=payload,
        timezone_name=timezone,
    )
    return recurring_item_response(item)


@router.get("/items/{public_id}", response_model=RecurringItemResponse)
def get_recurring_item_detail(
    public_id: str,
    month: str | None = None,
    timezone: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    item = get_recurring_item(db, tenant_id=auth.tenant_id, public_id=public_id)
    anomalies = recurring_amount_anomalies(
        db,
        tenant_id=auth.tenant_id,
        items=[item],
        month=month,
        timezone_name=timezone,
    )
    return recurring_item_response(item, anomalies.get(item.public_id))


@router.post("/items/{public_id}/pause", response_model=RecurringItemResponse)
def post_recurring_pause(
    public_id: str,
    payload: RecurringItemTokenRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    return recurring_item_response(pause_recurring_item(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
    ))


@router.post("/items/{public_id}/resume", response_model=RecurringItemResponse)
def post_recurring_resume(
    public_id: str,
    payload: RecurringItemTokenRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    return recurring_item_response(resume_recurring_item(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
    ))


@router.post("/items/{public_id}/archive", response_model=RecurringItemResponse)
def post_recurring_archive(
    public_id: str,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    return recurring_item_response(archive_recurring_item(db, tenant_id=auth.tenant_id, public_id=public_id))
