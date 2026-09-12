"""v1.1 monthly income plan API.

Thin routes — parse / dispatch / serialise; all validation and
state-machine rules live in :mod:`app.services.income_plan_service`
(ENGINEERING_RULES §1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_protocol_writer_context
from app.database import get_db
from app.schemas import (
    IncomePlanCreateRequest,
    IncomePlanListResponse,
    IncomePlanResponse,
    IncomePlanTokenRequest,
    IncomePlanUpdateRequest,
)
from app.services.income_plan_service import (
    archive_income_plan,
    income_forecast,
    list_income_plans,
    restore_income_plan,
)
from app.services.income_plan_service._delivery import create_income_plan_idempotently, update_income_plan_idempotently
from app.services.spending_contract_service import current_accounting_month
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
        frequency=plan.frequency,
        income_month=plan.income_month,
        amount_cents=plan.amount_cents,
        home_currency_code=plan.home_currency_code,
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
    month: str | None = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Accounting month used for the active total.",
    ),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> IncomePlanListResponse:
    status_filter = None if status == "all" else status
    month_label = month or current_accounting_month()
    plans = list_income_plans(db, tenant_id=auth.tenant_id, status=status_filter)
    forecast = income_forecast(db, tenant_id=auth.tenant_id, month=month_label)
    return IncomePlanListResponse(
        items=[_to_response(p) for p in plans],
        month=month_label,
        home_currency_code=forecast.home_currency_code,
        missing_currency_codes=list(forecast.missing_currency_codes),
        reference_rates=list(forecast.reference_rates),
        # Older APKs render this field as scheduled through today.
        total_active_amount_cents=forecast.scheduled_amount_cents,
        expected_amount_cents=forecast.expected_amount_cents,
        scheduled_amount_cents=forecast.scheduled_amount_cents,
        effective_plan_count=len(forecast.entries),
    )


@router.post("", response_model=IncomePlanResponse, status_code=201)
def create_plan(
    payload: IncomePlanCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    return create_income_plan_idempotently(
        db, tenant_id=auth.tenant_id, payload=payload,
        actor_account_id=auth.account_id, idempotency_key=idempotency_key,
    )


@router.patch("/{public_id}", response_model=IncomePlanResponse)
def update_plan(
    public_id: str,
    payload: IncomePlanUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    return update_income_plan_idempotently(
        db, tenant_id=auth.tenant_id, public_id=public_id, payload=payload,
        actor_account_id=auth.account_id, idempotency_key=idempotency_key,
    )


@router.delete("/{public_id}", response_model=IncomePlanResponse)
def archive_plan(
    public_id: str,
    payload: IncomePlanTokenRequest,
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    # ADR-0038 PR-B: token-gated archive (atomic UPDATE WHERE). Stale → 409.
    plan = archive_income_plan(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        intent_month=payload.intent_month,
        actor_account_id=auth.account_id,
    )
    return _to_response(plan)


@router.post("/{public_id}/restore", response_model=IncomePlanResponse)
def restore_plan(
    public_id: str,
    payload: IncomePlanTokenRequest,
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> IncomePlanResponse:
    plan = restore_income_plan(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        intent_month=payload.intent_month,
        actor_account_id=auth.account_id,
    )
    return _to_response(plan)
