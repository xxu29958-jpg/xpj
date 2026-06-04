"""v1.1 monthly income plan API.

Thin routes — parse / dispatch / serialise; all validation and
state-machine rules live in :mod:`app.services.income_plan_service`
(ENGINEERING_RULES §1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    IncomePlanCreateRequest,
    IncomePlanListResponse,
    IncomePlanResponse,
    IncomePlanTokenRequest,
    IncomePlanUpdateRequest,
)
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)
from app.services.income_plan_service import (
    archive_income_plan,
    create_income_plan,
    get_income_plan,
    list_income_plans,
    restore_income_plan,
    total_monthly_income_cents,
    update_income_plan,
)
from app.tenants import AuthContext

if TYPE_CHECKING:
    # Used only for the _to_response type hint; importing at runtime would
    # cross the route→model layer for no behavioural reason.
    from app.models import MonthlyIncomePlan

router = APIRouter(prefix="/api/income-plans", tags=["income-plans"])


def _to_response(plan: MonthlyIncomePlan) -> IncomePlanResponse:
    return IncomePlanResponse(
        public_id=plan.public_id,
        label=plan.label,
        source_type=plan.source_type,
        amount_cents=plan.amount_cents,
        pay_day=plan.pay_day,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        row_version=plan.row_version,
        archived_at=plan.archived_at,
    )


@router.get("", response_model=IncomePlanListResponse)
def list_plans(
    status: str = Query(default="active", pattern="^(active|archived|all)$"),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> IncomePlanListResponse:
    status_filter = None if status == "all" else status
    plans = list_income_plans(db, tenant_id=auth.tenant_id, status=status_filter)
    return IncomePlanListResponse(
        items=[_to_response(p) for p in plans],
        total_active_amount_cents=total_monthly_income_cents(
            db, tenant_id=auth.tenant_id
        ),
    )


@router.post("", response_model=IncomePlanResponse, status_code=201)
def create_plan(
    payload: IncomePlanCreateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    plan = create_income_plan(
        db,
        tenant_id=auth.tenant_id,
        label=payload.label,
        source_type=payload.source_type,
        amount_cents=payload.amount_cents,
        pay_day=payload.pay_day,
    )
    return _to_response(plan)


@router.patch("/{public_id}", response_model=IncomePlanResponse)
def update_plan(
    public_id: str,
    payload: IncomePlanUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    # ADR-0038 PR-2j: token-gated PATCH (stale snapshot → 409). ADR-0042: claim
    # the Idempotency-Key before that OCC claim so an offline-outbox replay of a
    # committed-but-unseen edit re-serialises the plan instead of false-409ing.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="update_income_plan",
        target_id=public_id,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="income_plan",
    )
    if claim is None:  # §4.6 HIT — re-serialise the current plan
        return _to_response(
            get_income_plan(db, tenant_id=auth.tenant_id, public_id=public_id)
        )

    plan = update_income_plan(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        label=payload.label,
        source_type=payload.source_type,
        amount_cents=payload.amount_cents,
        pay_day=payload.pay_day,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="income_plan", resource_id=public_id
    )
    db.commit()
    return _to_response(plan)


@router.delete("/{public_id}", response_model=IncomePlanResponse)
def archive_plan(
    public_id: str,
    payload: IncomePlanTokenRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    # ADR-0038 PR-B: token-gated archive (atomic UPDATE WHERE). Stale → 409.
    plan = archive_income_plan(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
    )
    return _to_response(plan)


@router.post("/{public_id}/restore", response_model=IncomePlanResponse)
def restore_plan(
    public_id: str,
    payload: IncomePlanTokenRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    plan = restore_income_plan(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
    )
    return _to_response(plan)
