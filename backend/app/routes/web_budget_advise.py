"""v1.1 /web budget advisor page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    templates,
)
from app.services.budget_advisor_service import (
    build_budget_inputs,
    get_budget_advisor,
)
from app.services.budget_baseline_service import (
    compute_monthly_discretionary,
    total_active_recurring_monthly_cents,
)
from app.services.income_plan_service import total_monthly_income_cents
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/web/budget-advise", tags=["web"])


@router.get("", response_class=HTMLResponse)
def page_budget_advise(
    request: Request,
    ledger_id: str | None = Query(default=None),
    month: str | None = Query(default=None),
    savings_target_yuan: float = Query(default=0.0, ge=0),
    reserved_buffer_yuan: float = Query(default=0.0, ge=0),
    run_advise: bool = Query(default=False),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    settings = get_settings()
    provider_name = settings.budget_advisor_provider or "empty"

    month_label = month or current_accounting_month()
    income = total_monthly_income_cents(db, tenant_id=selected)
    fixed = total_active_recurring_monthly_cents(db, tenant_id=selected)
    savings_cents = int(round(savings_target_yuan * 100))
    reserved_cents = int(round(reserved_buffer_yuan * 100))
    breakdown = compute_monthly_discretionary(
        monthly_income_cents=income,
        fixed_expenses_cents=fixed,
        savings_target_cents=savings_cents,
        reserved_buffer_cents=reserved_cents,
    )

    advice = None
    advise_error: str | None = None
    if run_advise and provider_name != "empty":
        try:
            inputs = build_budget_inputs(
                db, tenant_id=selected, month=month_label
            )
            advisor = get_budget_advisor()
            advice = advisor.advise(inputs)
        except AppError as exc:
            advise_error = exc.message

    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected,
        page_title="AI 预算建议",
    )
    ctx.update(
        month=month_label,
        provider_name=provider_name,
        provider_enabled=provider_name != "empty",
        income_yuan=_amount_yuan(breakdown.monthly_income_cents),
        fixed_yuan=_amount_yuan(breakdown.fixed_expenses_cents),
        savings_yuan=_amount_yuan(breakdown.savings_target_cents),
        reserved_yuan=_amount_yuan(breakdown.reserved_buffer_cents),
        discretionary_yuan=_amount_yuan(breakdown.discretionary_cents),
        savings_target_yuan=savings_target_yuan,
        reserved_buffer_yuan=reserved_buffer_yuan,
        advice=advice,
        advise_error=advise_error,
        run_advise=run_advise,
    )
    return templates.TemplateResponse(request=request, name="budget_advise.html", context=ctx)
