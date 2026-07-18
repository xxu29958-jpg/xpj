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
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _month_display_label,
    _parse_major_amount,
    _resolve_selected_ledger_id,
    _selected_option,
    templates,
)
from app.services.budget_advisor_service import run_budget_advisor
from app.services.budget_advisor_service._provider_names import canonical_provider_name
from app.services.budget_baseline_service import (
    DiscretionaryBreakdown,
    compute_monthly_discretionary,
    total_active_recurring_monthly_cents,
    total_confirmed_spent_cents,
)
from app.services.income_plan_service import total_monthly_income_cents
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/web/budget-advise", tags=["web"])

_ADVISE_ERROR_LABELS = {
    "ai_advisor_not_confirmed": "智能建议尚未由账本拥有者启用。",
    "ai_advisor_owner_required": "只有账本拥有者可以生成智能建议。",
    "ai_advisor_rate_limited": "请求过于频繁，请稍后再试。",
    "ai_advisor_daily_limit_exceeded": "今天的智能建议次数已用完，请明天再试。",
    "ai_advisor_payload_invalid": "本月数据暂时无法用于生成建议。",
    "ai_advisor_no_advice": "当前数据不足以生成建议。",
    "ai_advisor_provider_empty": "智能建议暂未启用。",
    "ai_advisor_provider_call_failed": "智能建议暂时无法连接，请稍后再试。",
    "ai_advisor_provider_unexpected_error": "智能建议暂时不可用，请稍后再试。",
    "ai_advisor_response_parse_failed": "本次建议未能正确生成，请再试一次。",
    "ai_advisor_response_unexpected_error": "本次建议未能正确生成，请再试一次。",
}


def _advise_error_label(code: str | None) -> str:
    return _ADVISE_ERROR_LABELS.get(
        code or "",
        "暂时无法生成智能建议，请稍后再试。",
    )


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


def _monthly_discretionary_breakdown(
    db: Session,
    *,
    selected_ledger_id: str,
    month: str,
    savings_target_yuan: float,
    reserved_buffer_yuan: float,
) -> DiscretionaryBreakdown:
    income = total_monthly_income_cents(
        db,
        tenant_id=selected_ledger_id,
        month=month,
    )
    fixed = total_active_recurring_monthly_cents(
        db,
        tenant_id=selected_ledger_id,
    )
    spent = total_confirmed_spent_cents(
        db,
        tenant_id=selected_ledger_id,
        month=month,
        timezone_name="Asia/Shanghai",
    )
    savings_cents = _parse_major_amount(
        str(savings_target_yuan),
        label="储蓄目标",
        empty_value=0,
    )
    reserved_cents = _parse_major_amount(
        str(reserved_buffer_yuan),
        label="备用金",
        empty_value=0,
    )
    assert savings_cents is not None
    assert reserved_cents is not None
    return compute_monthly_discretionary(
        monthly_income_cents=income,
        fixed_expenses_cents=fixed,
        spent_amount_cents=spent,
        savings_target_cents=savings_cents,
        reserved_buffer_cents=reserved_cents,
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
    breakdown = _monthly_discretionary_breakdown(
        db,
        selected_ledger_id=selected,
        month=month_label,
        savings_target_yuan=savings_target_yuan,
        reserved_buffer_yuan=reserved_buffer_yuan,
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
        page_title="预算建议",
    )
    ctx.update(
        month=month_label,
        month_display=_month_display_label(month_label),
        provider_name=provider_name,
        provider_enabled=provider_name != "empty",
        can_generate_ai_advice=ctx["selected_ledger_role"] == "owner",
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
        return None, "请使用页面中的生成按钮获取智能建议。", provider_name
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
        return None, _advise_error_label(exc.error), provider_name

    advice = result.advice
    advise_error = _advise_error_label(result.reason_code) if advice is None and result.reason_code else None
    return advice, advise_error, result.provider_name


def _actor_role(request: Request, *, ledger_id: str, options) -> str:
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.role
    return _selected_option(options, ledger_id).role


def _actor_account_id(request: Request) -> int | None:
    session_auth = getattr(request.state, "web_session_auth", None)
    return session_auth.account_id if session_auth is not None else None
