"""v1.1 budget advisor API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import (
    BudgetAdviceDto,
    BudgetAdviseRequest,
    BudgetAdviseResponse,
    BudgetAdvisorStatusResponse,
    BudgetSuggestionDto,
    DiscretionaryResponse,
)
from app.services.budget_advisor_service import (
    BudgetAdvice,
    advisor_status_for_tenant,
    run_budget_advisor,
)
from app.services.budget_baseline_service import (
    compute_monthly_discretionary,
    total_active_recurring_monthly_cents,
    total_confirmed_spent_cents,
)
from app.services.income_plan_service import total_monthly_income_cents
from app.services.spending_contract_service import current_accounting_month
from app.tenants import AuthContext

router = APIRouter(prefix="/api/budget", tags=["budget-advisor"])


@router.get("/discretionary", response_model=DiscretionaryResponse)
def get_discretionary(
    month: str | None = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Accounting month used for one-time income.",
    ),
    savings_target_cents: int = Query(default=0, ge=0),
    reserved_buffer_cents: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DiscretionaryResponse:
    month_label = month or current_accounting_month()
    income = total_monthly_income_cents(
        db,
        tenant_id=auth.tenant_id,
        month=month_label,
    )
    fixed = total_active_recurring_monthly_cents(db, tenant_id=auth.tenant_id)
    spent = total_confirmed_spent_cents(
        db,
        tenant_id=auth.tenant_id,
        month=month_label,
        timezone_name="Asia/Shanghai",
    )
    breakdown = compute_monthly_discretionary(
        monthly_income_cents=income,
        fixed_expenses_cents=fixed,
        spent_amount_cents=spent,
        savings_target_cents=savings_target_cents,
        reserved_buffer_cents=reserved_buffer_cents,
    )
    return DiscretionaryResponse(
        monthly_income_cents=breakdown.monthly_income_cents,
        fixed_expenses_cents=breakdown.fixed_expenses_cents,
        spent_amount_cents=breakdown.spent_amount_cents,
        savings_target_cents=breakdown.savings_target_cents,
        reserved_buffer_cents=breakdown.reserved_buffer_cents,
        discretionary_cents=breakdown.discretionary_cents,
    )


@router.post("/advise", response_model=BudgetAdviseResponse)
def post_advise(
    payload: BudgetAdviseRequest,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetAdviseResponse:
    result = run_budget_advisor(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        actor_role=auth.role,
        month=payload.month,
        timezone_name=payload.timezone or "Asia/Shanghai",
    )
    return BudgetAdviseResponse(
        advice=_advice_to_dto(result.advice),
        provider_name=result.provider_name,
        reason_code=result.reason_code,
    )


@router.get("/advisor/status", response_model=BudgetAdvisorStatusResponse)
def get_advisor_status(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetAdvisorStatusResponse:
    status = advisor_status_for_tenant(db, tenant_id=auth.tenant_id)
    return BudgetAdvisorStatusResponse(
        provider=status.provider,
        model=status.model,
        base_url=status.base_url,
        owner_confirmed=status.owner_confirmed,
        is_live=status.is_live,
        needs_confirmation=status.needs_confirmation,
        last_called_at=status.last_called_at,
        last_success=status.last_success,
        last_error_code=status.last_error_code,
        last_suggestion_count=status.last_suggestion_count,
        last_duration_ms=status.last_duration_ms,
    )


def _advice_to_dto(advice: BudgetAdvice | None) -> BudgetAdviceDto | None:
    if advice is None:
        return None
    return BudgetAdviceDto(
        summary=advice.summary,
        suggestions=[
            BudgetSuggestionDto(
                category=s.category,
                suggested_amount_cents=s.suggested_amount_cents,
                rationale=s.rationale,
            )
            for s in advice.suggestions
        ],
        confidence=advice.confidence,
    )
