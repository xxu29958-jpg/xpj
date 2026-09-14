"""v1.1 /web monthly income plan management page."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _currency_input_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.schemas import IncomePlanCreateRequest
from app.services.currency_common import (
    currency_input_metadata,
    major_amount_to_minor,
    minor_amount_value,
)
from app.services.income_plan_service import (
    archive_income_plan,
    income_forecast,
    list_income_plans,
    restore_income_plan,
)
from app.services.income_plan_service._delivery import create_income_plan_idempotently
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/web/income-plans", tags=["web"])


def _parse_yuan(raw: str, *, currency_code: str, label: str) -> int:
    text = raw or ""
    if not text:
        raise AppError("invalid_request", f"请填写{label}。", status_code=422)
    try:
        result = major_amount_to_minor(text, currency_code)
    except AppError as exc:
        raise AppError(
            "invalid_request",
            f"{label}不是合法金额或超出当前版本可支持范围。",
            status_code=422,
        ) from exc
    assert result is not None
    return result


def _parse_pay_day(raw: str) -> int:
    text = (raw or "").strip()
    if not text:
        raise AppError("invalid_request", "请选择预计收入日。", status_code=422)
    try:
        day = int(text)
    except ValueError as exc:
        raise AppError("invalid_request", "预计收入日需为 1-31 的整数。", status_code=422) from exc
    if not 1 <= day <= 31:
        raise AppError("invalid_request", "预计收入日需为 1-31 的整数。", status_code=422)
    return day


def _format_income_month_label(value: str | None) -> str:
    text = (value or "").strip()
    try:
        year, month = text.split("-", maxsplit=1)
        month_number = int(month)
    except ValueError:
        return "未设置"
    return f"{year}年{month_number}月"


def _income_month_from_form(
    raw: str | None,
    *,
    year: str | None,
    month: str | None,
    fallback_month: str,
) -> str | None:
    text = (raw or "").strip()
    if text:
        return text
    clean_year = (year or "").strip()
    clean_month = (month or "").strip()
    if not clean_year and not clean_month:
        return fallback_month
    try:
        return f"{int(clean_year):04d}-{int(clean_month):02d}"
    except ValueError as exc:
        raise AppError("invalid_request", "请选择正确的预计月份。", status_code=422) from exc


def _income_month_options() -> tuple[list[int], str, str]:
    current = current_accounting_month()
    year_text, month_text = current.split("-", maxsplit=1)
    current_year = int(year_text)
    return list(range(current_year - 1, current_year + 3)), year_text, str(int(month_text))


def _render_income_plans(request, db, *, options, selected, message=None, error=None,
                         draft=None, review=False, status_code=200) -> HTMLResponse:
    plans_active = list_income_plans(db, tenant_id=selected, status="active")
    plans_archived = list_income_plans(db, tenant_id=selected, status="archived")
    intent_month = current_accounting_month()
    forecast = income_forecast(
        db,
        tenant_id=selected,
        month=intent_month,
    )
    can_write = True
    try:
        _require_selected_ledger_write(options, selected)
    except AppError:
        can_write = False
    income_year_options, income_default_year, income_default_month = _income_month_options()
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected,
        page_title="收入计划",
    )
    home = forecast.home_currency_code
    form = draft if draft is not None else {
        "home_currency_code": home or "", "intent_month": intent_month,
        "idempotency_key": str(uuid4()), "label": "", "source_type": "salary",
        "frequency": "one_time", "amount_yuan": "", "pay_day": "10", "income_month": "",
        "income_month_year": income_default_year, "income_month_number": income_default_month,
    }
    try:
        form_currency = currency_input_metadata(form.get("home_currency_code"))
    except AppError:
        form_currency = {}
    ctx.update(
        income_form_draft=form, income_form_currency=form_currency, income_form_error=error if draft is not None else None,
        income_form_review=review,
        plans_active=plans_active,
        plans_archived=plans_archived,
        total_yuan=minor_amount_value(forecast.expected_amount_cents, home) if forecast.expected_amount_cents is not None else None,
        scheduled_yuan=minor_amount_value(forecast.scheduled_amount_cents, home) if forecast.scheduled_amount_cents is not None else None,
        missing_currency_codes=forecast.missing_currency_codes,
        reference_rates=forecast.reference_rates,
        intent_month=intent_month,
        minor_label=lambda plan: minor_amount_value(plan.amount_cents, plan.home_currency_code) if plan.home_currency_code else "待确认币种",
        currency_input=_currency_input_view(home),
        can_write=can_write,
        message=message,
        error=error if draft is None else None,
        income_month_label=_format_income_month_label,
        income_year_options=income_year_options,
        income_default_year=income_default_year,
        income_default_month=income_default_month,
    )
    return templates.TemplateResponse(request=request, name="income_plans.html", context=ctx, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def page_income_plans(
    request: Request, ledger_id: str | None = Query(default=None),
    message: str | None = Query(default=None), error: str | None = Query(default=None),
    db: Session = Depends(get_db), _local: None = LocalOnly,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    return _render_income_plans(request, db, options=options, selected=selected, message=message, error=error)


@router.post("/create")
def post_create(
    request: Request,
    ledger_id: str | None = Form(default=None),
    label: str = Form(default=""),
    source_type: str = Form(default="salary"),
    frequency: str = Form(default="one_time"),
    income_month: str | None = Form(default=None),
    income_month_year: str | None = Form(default=None),
    income_month_number: str | None = Form(default=None),
    amount_yuan: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    pay_day: str = Form(default=""),
    intent_month: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    review_new: bool = Form(default=False),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    draft = {"label": label, "source_type": source_type, "frequency": frequency,
        "income_month": income_month or "", "income_month_year": income_month_year or "",
        "income_month_number": income_month_number or "", "amount_yuan": amount_yuan,
        "home_currency_code": home_currency_code, "pay_day": pay_day,
        "intent_month": intent_month, "idempotency_key": idempotency_key}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={**draft, "ledger_id": ledger_id, "review_new": review_new}, task="添加收入计划")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    if review_new:
        draft["idempotency_key"] = str(uuid4())
        return _render_income_plans(request, db, options=options, selected=selected, draft=draft)
    try:
        payload = IncomePlanCreateRequest(label=label, source_type=source_type, frequency=frequency,
            income_month=_income_month_from_form(income_month, year=income_month_year,
                month=income_month_number, fallback_month=intent_month) if frequency == "one_time" else None,
            amount_cents=_parse_yuan(amount_yuan, currency_code=home_currency_code, label="预计收入金额"),
            home_currency_code=home_currency_code, pay_day=_parse_pay_day(pay_day), intent_month=intent_month)
        create_income_plan_idempotently(db, tenant_id=selected, payload=payload,
            actor_account_id=resolve_web_actor_account_id(db, request, selected), idempotency_key=idempotency_key)
    except (AppError, ValidationError) as exc:
        db.rollback()
        return _render_income_plans(request, db, options=options, selected=selected, draft=draft,
            error=exc.message if isinstance(exc, AppError) else "请检查名称、金额和预计日期。输入已保留。",
            review=isinstance(exc, AppError) and exc.error in {"idempotency_key_reused", "idempotency_key_required"},
            status_code=exc.status_code if isinstance(exc, AppError) else 422)
    return _web_redirect("/web/income-plans", selected, message="已添加收入计划")


@router.post("/{public_id}/archive")
def post_archive(
    request: Request,
    public_id: str,
    ledger_id: str | None = Form(default=None),
    expected_row_version: str = Form(default=""),
    intent_month: str = Form(...),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={"ledger_id": ledger_id, "expected_row_version": expected_row_version, "intent_month": intent_month},
        task="归档收入计划")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    # ADR-0038 PR-B: hidden OCC token. A stale archive against a plan another
    # tab/device just edited redirects with the standard 过期 message rather
    # than flipping status under the user.
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/income-plans", selected, error="页面已过期，请刷新后重新操作。"
        )
    try:
        archive_income_plan(
            db, tenant_id=selected, public_id=public_id, expected_row_version=parsed,
            intent_month=intent_month, actor_account_id=resolve_web_actor_account_id(db, request, selected),
        )
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect(
                "/web/income-plans", selected, error="页面已过期，请刷新后重新操作。"
            )
        raise
    return _web_redirect("/web/income-plans", selected, message="已归档收入计划")


@router.post("/{public_id}/restore")
def post_restore(
    request: Request,
    public_id: str,
    ledger_id: str | None = Form(default=None),
    expected_row_version: str = Form(default=""),
    intent_month: str = Form(...),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={"ledger_id": ledger_id, "expected_row_version": expected_row_version, "intent_month": intent_month},
        task="恢复收入计划")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/income-plans", selected, error="页面已过期，请刷新后重新操作。"
        )
    try:
        restore_income_plan(
            db, tenant_id=selected, public_id=public_id, expected_row_version=parsed,
            intent_month=intent_month, actor_account_id=resolve_web_actor_account_id(db, request, selected),
        )
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect(
                "/web/income-plans", selected, error="页面已过期，请刷新后重新操作。"
            )
        raise
    return _web_redirect("/web/income-plans", selected, message="已恢复收入计划")
