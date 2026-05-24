"""v1.1 budget advisor API — currently only the discretionary endpoint.

The ``/api/budget/advise`` endpoint that actually calls
``get_budget_advisor`` is intentionally deferred to a follow-up PR
together with the ``BudgetInputs`` adapter (which has to anonymise
real merchant / member / expense data into the ADR-0036 allowed-field
shape before any HTTP body leaves the backend).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import DiscretionaryResponse
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
