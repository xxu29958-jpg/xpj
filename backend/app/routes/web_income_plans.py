"""v1.1 /web monthly income plan management page."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.services.income_plan_service import (
    archive_income_plan,
    create_income_plan,
    list_income_plans,
    restore_income_plan,
    total_monthly_income_cents,
)
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/web/income-plans", tags=["web"])


def _parse_yuan(raw: str, *, label: str) -> int:
    text = (raw or "").strip()
    if not text:
        raise AppError("invalid_request", f"请填写{label}。", status_code=422)
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise AppError("invalid_request", f"{label}不是合法金额。", status_code=422) from exc
    if amount < 0:
        raise AppError("invalid_request", f"{label}不能为负数。", status_code=422)
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_pay_day(raw: str) -> int:
    text = (raw or "").strip()
    if not text:
        raise AppError("invalid_request", "请选择发薪日。", status_code=422)
    try:
        day = int(text)
    except ValueError as exc:
        raise AppError("invalid_request", "发薪日需为 1-31 的整数。", status_code=422) from exc
    if not 1 <= day <= 31:
        raise AppError("invalid_request", "发薪日需为 1-31 的整数。", status_code=422)
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
) -> str | None:
    text = (raw or "").strip()
    if text:
        return text
    clean_year = (year or "").strip()
    clean_month = (month or "").strip()
    if not clean_year and not clean_month:
        return current_accounting_month()
    try:
        return f"{int(clean_year):04d}-{int(clean_month):02d}"
    except ValueError as exc:
        raise AppError("invalid_request", "请选择正确的到账月份。", status_code=422) from exc


def _income_month_options() -> tuple[list[int], str, str]:
    current = current_accounting_month()
    year_text, month_text = current.split("-", maxsplit=1)
    current_year = int(year_text)
    return list(range(current_year - 1, current_year + 3)), year_text, str(int(month_text))


@router.get("", response_class=HTMLResponse)
def page_income_plans(
    request: Request,
    ledger_id: str | None = Query(default=None),
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    plans_active = list_income_plans(db, tenant_id=selected, status="active")
    plans_archived = list_income_plans(db, tenant_id=selected, status="archived")
    total_cents = total_monthly_income_cents(
        db,
        tenant_id=selected,
        month=current_accounting_month(),
    )
    can_write = True
    try:
        _require_selected_ledger_write(options, selected)
    except AppError:
        can_write = False
    income_year_options, income_default_year, income_default_month = _income_month_options()
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected,
        page_title="收入记录",
    )
    ctx.update(
        plans_active=plans_active,
        plans_archived=plans_archived,
        total_yuan=_amount_yuan(total_cents),
        can_write=can_write,
        message=message,
        error=error,
        income_month_label=_format_income_month_label,
        income_year_options=income_year_options,
        income_default_year=income_default_year,
        income_default_month=income_default_month,
    )
    return templates.TemplateResponse(request=request, name="income_plans.html", context=ctx)


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
    pay_day: str = Form(default=""),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    _require_selected_ledger_write(options, selected)
    amount_cents = _parse_yuan(amount_yuan, label="收入金额")
    day = _parse_pay_day(pay_day)
    create_income_plan(
        db,
        tenant_id=selected,
        label=label,
        source_type=source_type,
        frequency=frequency,
        income_month=_income_month_from_form(
            income_month,
            year=income_month_year,
            month=income_month_number,
        ),
        amount_cents=amount_cents,
        pay_day=day,
    )
    return _web_redirect("/web/income-plans", selected, message="已添加收入")


@router.post("/{public_id}/archive")
def post_archive(
    request: Request,
    public_id: str,
    ledger_id: str | None = Form(default=None),
    expected_row_version: str = Form(default=""),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
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
            db, tenant_id=selected, public_id=public_id, expected_row_version=parsed
        )
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect(
                "/web/income-plans", selected, error="页面已过期，请刷新后重新操作。"
            )
        raise
    return _web_redirect("/web/income-plans", selected, message="已归档收入")


@router.post("/{public_id}/restore")
def post_restore(
    request: Request,
    public_id: str,
    ledger_id: str | None = Form(default=None),
    expected_row_version: str = Form(default=""),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    _require_selected_ledger_write(options, selected)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/income-plans", selected, error="页面已过期，请刷新后重新操作。"
        )
    try:
        restore_income_plan(
            db, tenant_id=selected, public_id=public_id, expected_row_version=parsed
        )
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect(
                "/web/income-plans", selected, error="页面已过期，请刷新后重新操作。"
            )
        raise
    return _web_redirect("/web/income-plans", selected, message="已恢复收入")
