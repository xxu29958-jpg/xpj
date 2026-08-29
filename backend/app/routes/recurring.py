from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    RecurringCandidateConfirmRequest,
    RecurringItemCreateRequest,
    RecurringItemListResponse,
    RecurringItemResponse,
    RecurringItemTokenRequest,
    RecurringItemUpdateRequest,
)
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.recurring_item_command_service import (
    create_manual_recurring_item,
    update_recurring_item,
)
from app.services.recurring_service import (
    archive_recurring_item,
    confirm_recurring_candidate,
    get_recurring_item,
    list_recurring_items,
    pause_recurring_item,
    recurring_amount_anomalies,
    recurring_item_response,
    restore_recurring_item,
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


@router.post("/items", response_model=RecurringItemResponse, status_code=201)
def post_recurring_item(
    payload: RecurringItemCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    return recurring_item_response(
        create_manual_recurring_item(
            db,
            tenant_id=auth.tenant_id,
            idempotency_key=idempotency_key,
            merchant=payload.merchant,
            baseline_amount_cents=payload.baseline_amount_cents,
            next_expected_date=payload.next_expected_date,
        )
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


@router.patch("/items/{public_id}", response_model=RecurringItemResponse)
def patch_recurring_item(
    public_id: str,
    payload: RecurringItemUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="update_recurring_item",
        target_id=public_id,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="recurring_item",
    )
    if claim is None:
        return recurring_item_response(
            get_recurring_item(db, tenant_id=auth.tenant_id, public_id=public_id)
        )
    update_recurring_item(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        merchant=payload.merchant,
        merchant_provided="merchant" in payload.model_fields_set,
        baseline_amount_cents=payload.baseline_amount_cents,
        baseline_provided="baseline_amount_cents" in payload.model_fields_set,
        next_expected_date=payload.next_expected_date,
        next_expected_date_provided="next_expected_date" in payload.model_fields_set,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="recurring_item",
        resource_id=public_id,
    )
    db.commit()
    return recurring_item_response(
        get_recurring_item(db, tenant_id=auth.tenant_id, public_id=public_id)
    )


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


@router.post("/items/{public_id}/restore", response_model=RecurringItemResponse)
def post_recurring_restore(
    public_id: str,
    payload: RecurringItemTokenRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RecurringItemResponse:
    # ADR-0051 recycle-bin restore: OCC-gated reactivate (stale token → 409),
    # mirror of the pause/resume toggle. Archive stays keyless (one-way).
    return recurring_item_response(restore_recurring_item(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
    ))
