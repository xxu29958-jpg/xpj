"""v1.1 monthly income plan API.

Thin routes — parse / dispatch / serialise; all validation and
state-machine rules live in :mod:`app.services.income_plan_service`
(ENGINEERING_RULES §1).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.models import MonthlyIncomePlan
from app.schemas import (
    IncomePlanCreateRequest,
    IncomePlanListResponse,
    IncomePlanResponse,
    IncomePlanUpdateRequest,
)
from app.services.income_plan_service import (
    archive_income_plan,
    create_income_plan,
    list_income_plans,
    restore_income_plan,
    total_monthly_income_cents,
    update_income_plan,
)
from app.tenants import AuthContext

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
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    # ADR-0038 PR-2j: token-gated PATCH. Stale snapshot → 409.
    plan = update_income_plan(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_updated_at=payload.expected_updated_at,
        label=payload.label,
        source_type=payload.source_type,
        amount_cents=payload.amount_cents,
        pay_day=payload.pay_day,
    )
    return _to_response(plan)


@router.delete("/{public_id}", response_model=IncomePlanResponse)
def archive_plan(
    public_id: str,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    plan = archive_income_plan(
        db, tenant_id=auth.tenant_id, public_id=public_id
    )
    return _to_response(plan)


@router.post("/{public_id}/restore", response_model=IncomePlanResponse)
def restore_plan(
    public_id: str,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    plan = restore_income_plan(
        db, tenant_id=auth.tenant_id, public_id=public_id
    )
    return _to_response(plan)
