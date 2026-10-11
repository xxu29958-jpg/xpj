"""/web/goals page backed by the v0.9 goals service."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import draft_ack_response, require_draft_binding
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.schemas import GoalCreateRequest
from app.services.currency_common import (
    currency_input_metadata,
    major_amount_to_minor,
    normalize_currency_code,
)
from app.services.goal_create_command import create_spending_goal_idempotently
from app.services.goal_history_service import goal_history
from app.services.goal_service import archive_goal, list_goals
from app.services.ledger_calendar_service import current_ledger_month
from app.services.manual_expense_draft_presenter import manual_draft_scope

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
        "target_yuan": _amount_yuan(goal.target_amount_cents, currency_code) if currency_code else _goal_history_money(goal.target_amount_cents, None),
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
    draft_result: str = "",
) -> HTMLResponse:
    timezone_name = get_settings().ocr_default_timezone
    creating = values is not None or request.query_params.get("new_goal") == "1"
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
        show_month_picker=not creating,
        selected_month=month,
    )
    ctx.update(
        {
            "month": month,
            "include_archived": include_archived,
            "goal_creating": creating,
            "goals": [_goal_view(goal) for goal in goals],
            "message": message,
            "error": error,
        }
    )
    values = values if values is not None else {
        "name": "", "category": "", "target_amount_yuan": "", "month": month,
        "home_currency_code": ctx["home_currency_code"], "idempotency_key": str(uuid4()),
        "return_include_archived": "true" if include_archived else "false",
    }
    try:
        form_currency = currency_input_metadata(values.get("home_currency_code"))
    except AppError:
        form_currency = {}
    auth = getattr(request.state, "web_session_auth", None)
    ctx.update(values=values, form_currency=form_currency, goal_draft_result=draft_result,
        goal_draft_scope=manual_draft_scope(db, auth) if auth is not None else None)
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
    target_month = (month or "").strip() or current_ledger_month(db, ledger_id=selected_id)
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
    draft_scope: str = Form(default=""), review_new: bool = Form(default=False),
    return_include_archived: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_ledger_month(db, ledger_id=selected_id)
    values = {"name": name, "month": month, "target_amount_yuan": target_amount_yuan,
        "category": category, "home_currency_code": home_currency_code, "idempotency_key": idempotency_key,
        "draft_scope": draft_scope, "return_include_archived": return_include_archived}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**values, "ledger_id": ledger_id}, task="添加支出目标")
    if retained is not None:
        return retained
    try:
        auth = getattr(request.state, "web_session_auth", None)
        if review_new and auth is not None and not draft_scope:
            values["draft_scope"] = json.dumps(manual_draft_scope(db, auth))
        require_draft_binding(db, request, ledger_id=selected_id,
            draft_scope=values["draft_scope"], require_session=False)
        _require_selected_ledger_write(options, selected_id)
        if review_new:
            values.update(idempotency_key=str(uuid4()), month=target_month)
            return _render_goals(request=request, db=db, options=options, selected_id=selected_id,
                month=target_month, include_archived=return_include_archived == "true", values=values, draft_result="prepared")
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
        receipt = create_spending_goal_idempotently(db, tenant_id=selected_id, payload=payload,
            idempotency_key=idempotency_key, timezone_name=timezone_name,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id))
    except (AppError, ValidationError) as exc:
        return _create_refusal(request, db, options, selected_id, target_month, values, exc)
    redirect = _web_redirect("/web/goals", selected_id, month=receipt.month,
        include_archived="true" if return_include_archived == "true" else "false", msg="目标已保存。")
    redirect.headers["location"] += f"#goal-{receipt.public_id}"
    return draft_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=receipt.model_dump(mode="json"), next_href=redirect.headers["location"]) or redirect


def _create_refusal(request, db, options, selected_id, month, values, exc):
    db.rollback()
    message = exc.message if isinstance(exc, AppError) else "请检查目标名称、月份、金额和币种。输入已保留。"
    status = exc.status_code if isinstance(exc, AppError) else 422
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"error": exc.error if isinstance(exc, AppError) else "invalid_request",
            "message": message, "draft_result": "blocked"}, status_code=status, headers={"Cache-Control": "no-store"})
    return _render_goals(request=request, db=db, options=options, selected_id=selected_id,
        month=month, include_archived=values.get("return_include_archived") == "true", values=values,
        error=message, status_code=status, draft_result="blocked")


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
    target_month = (month or "").strip() or current_ledger_month(db, ledger_id=selected_id)
    return _web_redirect(
        "/web/goals",
        selected_id,
        month=target_month,
        include_archived="true",
        msg="目标已归档。",
    )


@router.get("/{public_id}/history", response_class=HTMLResponse)
def web_goal_history(
    request: Request, public_id: str, ledger_id: str | None = None, month: str | None = None,
    include_archived: bool = True, limit: int = Query(default=20, ge=1, le=100),
    before_version: int | None = Query(default=None, ge=1),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    history = goal_history(db, tenant_id=selected, public_id=public_id,
        limit=limit, before_version=before_version)
    return_month = month or (history.items[0].snapshot.month if history.items else None)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected,
        show_month_picker=False, selected_month=return_month)
    ctx.update(history=history, return_month=return_month, include_archived=include_archived,
        limit=limit, before_version=before_version, history_money=_goal_history_money)
    return templates.TemplateResponse(request=request, name="goal_history.html", context=ctx)


def _goal_history_money(amount: int, currency: str | None) -> str:
    return f"{currency} {_amount_yuan(amount, currency)}" if currency else f"{amount} 最小单位（原币种未记录）"
