"""v1.1 /web budget advisor page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
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
    total_active_recurring_monthly_cents,
    total_confirmed_spent_cents,
)
from app.services.currency_common import (
    currency_input_metadata,
    home_currency_code,
    major_amount_to_minor,
    minor_amount_value,
)
from app.services.income_plan_service import total_monthly_income_cents
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/web/budget-advise", tags=["web"])


@router.get("", response_class=HTMLResponse)
def page_budget_advise(
    request: Request,
    ledger_id: str | None = Query(default=None),
    month: str | None = Query(default=None),
    savings_target_yuan: str = Query(default="0"),
    reserved_buffer_yuan: str = Query(default="0"),
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
    savings_target_yuan: str = Form(default="0"),
    reserved_buffer_yuan: str = Form(default="0"),
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
    savings_target_yuan: str,
    reserved_buffer_yuan: str,
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
    # Local inputs and aggregate output share one explicit configured currency.
    home = home_currency_code()
    savings_cents = major_amount_to_minor(savings_target_yuan, home)
    reserved_cents = major_amount_to_minor(reserved_buffer_yuan, home)
    breakdown = compute_monthly_discretionary(
        monthly_income_cents=income,
        fixed_expenses_cents=fixed,
        spent_amount_cents=spent,
        savings_target_cents=savings_cents,
        reserved_buffer_cents=reserved_cents,
    )

    advice, advise_error, provider_name = _budget_advice_response(
        request,
        db=db,
        selected=selected,
        options=options,
        month_label=month_label,
        provider_name=provider_name,
        run_advise=run_advise,
        allow_outbound=allow_outbound,
    )

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
        # Parsing and presentation use one explicit currency authority.
        income_yuan=minor_amount_value(breakdown.monthly_income_cents, home),
        fixed_yuan=minor_amount_value(breakdown.fixed_expenses_cents, home),
        spent_yuan=minor_amount_value(breakdown.spent_amount_cents, home),
        savings_yuan=minor_amount_value(breakdown.savings_target_cents, home),
        reserved_yuan=minor_amount_value(breakdown.reserved_buffer_cents, home),
        discretionary_yuan=minor_amount_value(breakdown.discretionary_cents, home),
        currency_input=currency_input_metadata(home),
        minor_amount_label=lambda cents: minor_amount_value(cents, home),
        savings_target_yuan=savings_target_yuan,
        reserved_buffer_yuan=reserved_buffer_yuan,
        advice=advice,
        advise_error=advise_error,
        run_advise=run_advise,
    )
    return templates.TemplateResponse(request=request, name="budget_advise.html", context=ctx)


def _budget_advice_response(
    request: Request,
    *,
    db: Session,
    selected: str,
    options: list,
    month_label: str,
    provider_name: str,
    run_advise: bool,
    allow_outbound: bool,
) -> tuple[Any, str | None, str]:
    if not run_advise or provider_name == "empty":
        return None, None, provider_name
    if not allow_outbound:
        return None, "AI advisor calls require the form button so request checks can run.", provider_name
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
    except AppError as exc:
        return None, exc.message or exc.error, provider_name

    advice = result.advice
    advise_error = result.reason_code if advice is None and result.reason_code else None
    return advice, advise_error, result.provider_name


def _actor_role(request: Request, *, ledger_id: str, options) -> str:
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.role
    return _selected_option(options, ledger_id).role


def _actor_account_id(request: Request) -> int | None:
    session_auth = getattr(request.state, "web_session_auth", None)
    return session_auth.account_id if session_auth is not None else None
