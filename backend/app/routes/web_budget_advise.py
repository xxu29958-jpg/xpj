"""v1.1 /web budget advisor page."""

from __future__ import annotations

from typing import Any, TypedDict

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_budget_fx import router as rates_router
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _selected_option,
    preserve_original_ledger_form,
    templates,
)
from app.services.budget_advisor_service import get_advisor_readiness, read_budget_inputs, run_budget_advisor
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import (
    currency_input_metadata,
    major_amount_to_minor,
    minor_amount_value,
    normalize_currency_code,
    supported_currency_codes,
)
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/web/budget-advise", tags=["web"])
router.include_router(rates_router)


class _AdvisorReadinessContext(TypedDict):
    provider_name: str
    provider_enabled: bool
    advisor_can_request: bool
    advisor_blocked_message: str | None


@router.get("", response_class=HTMLResponse)
def page_budget_advise(
    request: Request,
    ledger_id: str | None = Query(default=None),
    month: str | None = Query(default=None),
    savings_target_yuan: str = Query(default="0"),
    reserved_buffer_yuan: str = Query(default="0"),
    run_advise: bool = Query(default=False),
    home_currency_code: str | None = Query(default=None),
    msg: str | None = Query(default=None),
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
        home_currency_code=home_currency_code,
        message=msg,
    )


@router.post("", response_class=HTMLResponse)
def page_budget_advise_run(
    request: Request,
    ledger_id: str | None = Form(default=None),
    month: str | None = Form(default=None),
    savings_target_yuan: str = Form(default="0"),
    reserved_buffer_yuan: str = Form(default="0"),
    run_advise: bool = Form(default=False),
    home_currency_code: str | None = Form(default=None),
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
        home_currency_code=home_currency_code,
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
    home_currency_code: str | None = None,
    message: str | None = None,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    if request.method == "POST":
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
            fields={"ledger_id": ledger_id, "month": month, "home_currency_code": home_currency_code,
                "savings_target_yuan": savings_target_yuan, "reserved_buffer_yuan": reserved_buffer_yuan,
                "run_advise": run_advise}, task="重新计算预算建议")
        if retained is not None:
            return retained
    readiness_ctx = _advisor_readiness_context(request, selected=selected, options=options)
    month_label = month or current_accounting_month()
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    currency_choice_required = request.method == "POST" and not home_currency_code
    savings_cents, reserved_cents, form_error = _reserve_values(
        savings_target_yuan, reserved_buffer_yuan, home, currency_choice_required=currency_choice_required)
    projection = read_budget_inputs(db, tenant_id=selected, month=month_label, home_currency_code=home,
        timezone_name="Asia/Shanghai", savings_target_cents=savings_cents, reserved_buffer_cents=reserved_cents)
    advice, advise_error, provider_name = None, None, readiness_ctx["provider_name"]
    if not projection.missing_rates and form_error is None:
        advice, advise_error, provider_name = _budget_advice_response(request, db=db, selected=selected,
            options=options, month_label=month_label, provider_name=provider_name,
            run_advise=run_advise, allow_outbound=allow_outbound, home_currency_code=projection.home_currency_code)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="预算建议")
    ctx.update(readiness_ctx)
    ctx.update(_projection_context(projection, form_error=form_error))
    ctx.update(
        month=month_label,
        provider_name=provider_name,
        minor_amount_label=lambda cents: minor_amount_value(cents, home),
        savings_target_yuan=savings_target_yuan,
        reserved_buffer_yuan=reserved_buffer_yuan,
        advice=advice,
        advise_error=advise_error,
        run_advise=run_advise,
        form_error=form_error,
        currency_choice_required=currency_choice_required,
        currency_codes=sorted(supported_currency_codes()),
        message=message,
    )
    status = 409 if currency_choice_required else 422 if form_error else 200
    return templates.TemplateResponse(request=request, name="budget_advise.html", context=ctx, status_code=status)


def _reserve_values(savings, reserved, home, *, currency_choice_required):
    if currency_choice_required:
        return 0, 0, "原表单未记录币种。金额已保留，请选择填写时使用的币种后重新计算。"
    try:
        return _reserve_minor(savings, home), _reserve_minor(reserved, home), None
    except AppError as exc:
        return 0, 0, exc.message


def _reserve_minor(raw: str, currency: str) -> int:
    value = major_amount_to_minor(raw or "0", currency) or 0
    if value < 0:
        raise AppError("invalid_request", "储蓄目标和备用金不能为负数。输入已保留。", status_code=422)
    return value


def _projection_context(projection, *, form_error=None) -> dict:
    fields = {"income_yuan": "monthly_income_cents", "fixed_yuan": "fixed_expenses_cents",
        "spent_yuan": "spent_amount_cents", "savings_yuan": "savings_target_cents",
        "reserved_yuan": "reserved_buffer_cents", "discretionary_yuan": "discretionary_cents"}
    home = projection.home_currency_code
    values = {name: None if (value := getattr(projection.breakdown, field)) is None
        else minor_amount_value(value, home) for name, field in fields.items()}
    if form_error:
        values.update(savings_yuan=None, reserved_yuan=None, discretionary_yuan=None)
    metadata = currency_input_metadata(home)
    return {**values, "home_currency_code": home, "home_currency_symbol": metadata["currency_symbol"], "currency_input": metadata,
        "missing_rates": projection.missing_rates, "reference_rates": projection.reference_rates}


def _advisor_readiness_context(request: Request, *, selected: str, options: list) -> _AdvisorReadinessContext:
    readiness = get_advisor_readiness()
    blocked_reason = readiness.blocked_reason(_actor_role(request, ledger_id=selected, options=options))
    return {
        "provider_name": readiness.provider,
        "provider_enabled": readiness.provider != "empty",
        "advisor_can_request": blocked_reason is None,
        "advisor_blocked_message": (
            AppError(blocked_reason).message
            if blocked_reason not in {None, "ai_advisor_provider_empty"} else None
        ),
    }


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
    home_currency_code: str | None = None,
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
            home_currency_code=home_currency_code,
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
