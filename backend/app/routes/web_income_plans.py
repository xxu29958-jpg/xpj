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
    total_cents = total_monthly_income_cents(db, tenant_id=selected)
    can_write = True
    try:
        _require_selected_ledger_write(options, selected)
    except AppError:
        can_write = False
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected,
        page_title="收入计划",
    )
    ctx.update(
        plans_active=plans_active,
        plans_archived=plans_archived,
        total_yuan=_amount_yuan(total_cents),
        can_write=can_write,
        message=message,
        error=error,
    )
    return templates.TemplateResponse(request=request, name="income_plans.html", context=ctx)


@router.post("/create")
def post_create(
    request: Request,
    ledger_id: str | None = Form(default=None),
    label: str = Form(default=""),
    source_type: str = Form(default="salary"),
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
        amount_cents=amount_cents,
        pay_day=day,
    )
    return _web_redirect("/web/income-plans", selected, message="已添加收入计划")


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
    return _web_redirect("/web/income-plans", selected, message="已归档收入计划")


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
    return _web_redirect("/web/income-plans", selected, message="已恢复收入计划")
