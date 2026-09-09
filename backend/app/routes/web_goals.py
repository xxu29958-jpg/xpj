"""/web/goals page backed by the v0.9 goals service."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
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
    templates,
)
from app.schemas import GoalCreateRequest
from app.services.currency_common import currency_input_metadata, major_amount_to_minor, normalize_currency_code
from app.services.goal_create_command import create_spending_goal_idempotently
from app.services.goal_service import archive_goal, list_goals
from app.services.time_service import current_month

router = APIRouter(prefix="/web/goals", tags=["web"])


def _parse_amount_yuan(raw: str, *, currency_code: str) -> int:
    text = raw or ""
    if not text:
        raise AppError("invalid_request", "请填写目标金额。", status_code=422)
    try:
        result = major_amount_to_minor(text, currency_code)
    except AppError as exc:
        raise AppError(
            "invalid_request",
            "目标金额不是合法正数或超出当前版本可支持范围。",
            status_code=422,
        ) from exc
    if result is None or result <= 0:
        raise AppError(
            "invalid_request",
            "目标金额必须大于 0。",
            status_code=422,
        )
    assert result is not None
    return result


def _goal_view(goal) -> dict:
    currency_code = goal.home_currency_code
    percent = min(100, max(0, goal.progress_percent)) if goal.progress_percent is not None else None
    return {
        "public_id": goal.public_id,
        "name": goal.name,
        "month": goal.month,
        "category": goal.category or "总支出",
        "home_currency_code": currency_code,
        "target_yuan": _amount_yuan(goal.target_amount_cents, currency_code) if currency_code else "币种待确认",
        "spent_yuan": _amount_yuan(goal.spent_amount_cents, currency_code) if currency_code else "",
        "remaining_yuan": _amount_yuan(goal.remaining_amount_cents, currency_code) if currency_code else "",
        "progress_percent": goal.progress_percent,
        "bar_percent": percent,
        "progress_state": goal.progress_state,
        "status": goal.status,
        "is_archived": goal.status == "archived",
        "is_over_limit": goal.progress_state == "over_limit",
    }


def _render_goals(
    *,
    request: Request,
    db: Session,
    options,
    selected_id: str,
    month: str,
    include_archived: bool,
    message: str | None = None,
    error: str | None = None,
    values: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    timezone_name = get_settings().ocr_default_timezone
    goals = list_goals(
        db,
        tenant_id=selected_id,
        month=month,
        timezone_name=timezone_name,
        include_archived=include_archived,
    )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        show_month_picker=True,
        selected_month=month,
    )
    ctx.update(
        {
            "month": month,
            "include_archived": include_archived,
            "goals": [_goal_view(goal) for goal in goals],
            "message": message,
            "error": error,
        }
    )
    values = values if values is not None else {
        "name": "", "category": "", "target_amount_yuan": "", "month": month,
        "home_currency_code": ctx["home_currency_code"], "idempotency_key": str(uuid4()),
    }
    try:
        form_currency = currency_input_metadata(values.get("home_currency_code"))
    except AppError:
        form_currency = {}
    ctx.update(values=values, form_currency=form_currency)
    return templates.TemplateResponse(request=request, name="goals.html", context=ctx, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def web_goals(
    request: Request,
    ledger_id: str | None = None,
    month: str | None = None,
    include_archived: bool = False,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    return _render_goals(
        request=request,
        db=db,
        options=options,
        selected_id=selected_id,
        month=target_month,
        include_archived=include_archived,
        message=msg,
    )


@router.post("/create", response_class=HTMLResponse)
def web_goals_create(
    request: Request,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    name: str = Form(default=""),
    target_amount_yuan: str = Form(default=""),
    category: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    values = {"name": name, "month": month, "target_amount_yuan": target_amount_yuan,
        "category": category, "home_currency_code": home_currency_code, "idempotency_key": idempotency_key}
    try:
        presentation_currency = normalize_currency_code(home_currency_code)
        payload = GoalCreateRequest(
            name=name,
            month=target_month,
            home_currency_code=presentation_currency,
            target_amount_cents=_parse_amount_yuan(
                target_amount_yuan,
                currency_code=presentation_currency,
            ),
            category=category.strip() or None,
        )
        create_spending_goal_idempotently(db, tenant_id=selected_id, payload=payload,
            idempotency_key=idempotency_key, timezone_name=timezone_name)
    except (AppError, ValidationError) as exc:
        db.rollback()
        return _render_goals(
            request=request,
            db=db,
            options=options,
            selected_id=selected_id,
            month=target_month,
            include_archived=False,
            error=exc.message if isinstance(exc, AppError) else "请检查目标名称、月份、金额和币种。输入已保留。",
            values=values,
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _web_redirect("/web/goals", selected_id, month=target_month, msg="目标已保存。")


@router.post("/{public_id}/archive")
def web_goals_archive(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    timezone_name = get_settings().ocr_default_timezone
    archive_goal(db, tenant_id=selected_id, public_id=public_id, timezone_name=timezone_name)
    target_month = (month or "").strip() or current_month(timezone_name)
    return _web_redirect(
        "/web/goals",
        selected_id,
        month=target_month,
        include_archived="true",
        msg="目标已归档。",
    )
