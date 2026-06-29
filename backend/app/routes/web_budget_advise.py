"""v1.1 /web budget advisor page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
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
    _selected_option,
    templates,
)
from app.services.budget_advisor_service import run_budget_advisor
from app.services.budget_advisor_service._provider_names import canonical_provider_name
from app.services.budget_baseline_service import (
    compute_monthly_discretionary,
    total_confirmed_spent_cents,
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
    # GET renders and computes local numbers only. Live outbound calls go
    # through POST so CSRF and Origin/Referer checks protect the cost boundary.
    return _render_budget_advise(
        request,
        db=db,
        ledger_id=ledger_id,
        month=month,
        savings_target_yuan=savings_target_yuan,
        reserved_buffer_yuan=reserved_buffer_yuan,
        run_advise=run_advise,
        allow_outbound=False,
    )


@router.post("", response_class=HTMLResponse)
def page_budget_advise_run(
    request: Request,
    ledger_id: str | None = Form(default=None),
    month: str | None = Form(default=None),
    savings_target_yuan: float = Form(default=0.0, ge=0),
    reserved_buffer_yuan: float = Form(default=0.0, ge=0),
    run_advise: bool = Form(default=False),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> HTMLResponse:
    return _render_budget_advise(
        request,
        db=db,
        ledger_id=ledger_id,
        month=month,
        savings_target_yuan=savings_target_yuan,
        reserved_buffer_yuan=reserved_buffer_yuan,
        run_advise=run_advise,
        allow_outbound=run_advise,
    )


def _render_budget_advise(
    request: Request,
    *,
    db: Session,
    ledger_id: str | None,
    month: str | None,
    savings_target_yuan: float,
    reserved_buffer_yuan: float,
    run_advise: bool,
    allow_outbound: bool,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    settings = get_settings()
    provider_name = canonical_provider_name(settings.budget_advisor_provider)

    month_label = month or current_accounting_month()
    income = total_monthly_income_cents(
        db,
        tenant_id=selected,
        month=month_label,
    )
    fixed = total_active_recurring_monthly_cents(db, tenant_id=selected)
    spent = total_confirmed_spent_cents(
        db,
        tenant_id=selected,
        month=month_label,
        timezone_name="Asia/Shanghai",
    )
    savings_cents = int(round(savings_target_yuan * 100))
    reserved_cents = int(round(reserved_buffer_yuan * 100))
    breakdown = compute_monthly_discretionary(
        monthly_income_cents=income,
        fixed_expenses_cents=fixed,
        spent_amount_cents=spent,
        savings_target_cents=savings_cents,
        reserved_buffer_cents=reserved_cents,
    )

    advice = None
    advise_error: str | None = None
    if run_advise and provider_name != "empty":
        if not allow_outbound:
            advise_error = "AI advisor calls require the form button so request checks can run."
        else:
            try:
                actor_role = _actor_role(request, ledger_id=selected, options=options)
                actor_account_id = _actor_account_id(request)
                result = run_budget_advisor(
                    db,
                    tenant_id=selected,
                    actor_account_id=actor_account_id,
                    actor_role=actor_role,
                    month=month_label,
                    timezone_name="Asia/Shanghai",
                )
                advice = result.advice
                provider_name = result.provider_name
                if advice is None and result.reason_code:
                    advise_error = result.reason_code
            except AppError as exc:
                advise_error = exc.message or exc.error

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
        spent_yuan=_amount_yuan(breakdown.spent_amount_cents),
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


def _actor_role(request: Request, *, ledger_id: str, options) -> str:
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.role
    return _selected_option(options, ledger_id).role


def _actor_account_id(request: Request) -> int | None:
    session_auth = getattr(request.state, "web_session_auth", None)
    return session_auth.account_id if session_auth is not None else None
