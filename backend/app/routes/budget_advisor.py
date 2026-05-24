"""v1.1 budget advisor API.

Two endpoints:

- ``GET /api/budget/discretionary`` — pure arithmetic over the user's
  income plan + recurring outflows + caller-supplied savings buffer.
- ``POST /api/budget/advise`` — assemble an anonymised :class:`BudgetInputs`
  (privacy boundary lives in :mod:`app.services.budget_advisor_service`)
  and hand it to the configured provider. With the default ``empty``
  provider this returns ``advice=null`` cleanly so the UI can render
  "no AI suggestion configured" without ambiguity.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.config import get_settings
from app.database import get_db
from app.schemas import (
    BudgetAdviceDto,
    BudgetAdviseRequest,
    BudgetAdviseResponse,
    BudgetSuggestionDto,
    DiscretionaryResponse,
)
from app.services.budget_advisor_service import (
    BudgetAdvice,
    build_budget_inputs,
    get_budget_advisor,
)
from app.services.budget_baseline_service import (
    compute_monthly_discretionary,
    total_active_recurring_monthly_cents,
)
from app.services.income_plan_service import total_monthly_income_cents
from app.tenants import AuthContext

router = APIRouter(prefix="/api/budget", tags=["budget-advisor"])


@router.get("/discretionary", response_model=DiscretionaryResponse)
def get_discretionary(
    savings_target_cents: int = Query(default=0, ge=0),
    reserved_buffer_cents: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DiscretionaryResponse:
    """本月可自由支配 = income - fixed - savings - reserved (floored at 0)."""
    income = total_monthly_income_cents(db, tenant_id=auth.tenant_id)
    fixed = total_active_recurring_monthly_cents(db, tenant_id=auth.tenant_id)
    breakdown = compute_monthly_discretionary(
        monthly_income_cents=income,
        fixed_expenses_cents=fixed,
        savings_target_cents=savings_target_cents,
        reserved_buffer_cents=reserved_buffer_cents,
    )
    return DiscretionaryResponse(
        monthly_income_cents=breakdown.monthly_income_cents,
        fixed_expenses_cents=breakdown.fixed_expenses_cents,
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
    """Build anonymised BudgetInputs → advisor → BudgetAdvice.

    ADR-0036: payload going out only includes the allowed-field surface
    (enforced inside the provider by ``to_outbound_dict`` /
    ``validate_outbound_payload``). The de-anonymisation is the UI's
    job, using the alias resolver on the way back.
    """

    inputs = build_budget_inputs(
        db,
        tenant_id=auth.tenant_id,
        month=payload.month,
        timezone_name=payload.timezone or "Asia/Shanghai",
    )
    advisor = get_budget_advisor()
    advice = advisor.advise(inputs)
    provider_name = get_settings().budget_advisor_provider or "empty"
    return BudgetAdviseResponse(
        advice=_advice_to_dto(advice),
        provider_name=provider_name,
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
