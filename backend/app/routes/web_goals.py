"""/web/goals page backed by the v0.9 goals service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.schemas import GoalCreateRequest, GoalUpdateRequest
from app.services.goal_service import archive_goal, create_goal, list_goals, update_goal
from app.services.time_service import current_month

router = APIRouter(prefix="/web/goals", tags=["web"])

_GOAL_PROGRESS_UI = {
    "not_started": ("未开始", ""),
    "on_track": ("进行中", "success"),
    "near_limit": ("接近目标", "warning"),
    "over_limit": ("已超出", "danger"),
    "archived": ("已归档", ""),
}


def _goal_progress_ui(progress_state: str) -> tuple[str, str]:
    return _GOAL_PROGRESS_UI.get(progress_state, ("状态待确认", ""))


def _goal_view(goal) -> dict:
    percent = min(120, max(0, int(goal.progress_percent)))
    progress_label, progress_tone = _goal_progress_ui(goal.progress_state)
    return {
        "public_id": goal.public_id,
        "name": goal.name,
        "month": goal.month,
        "category": goal.category or "总支出",
        "target_yuan": _amount_yuan(goal.target_amount_cents),
        "spent_yuan": _amount_yuan(goal.spent_amount_cents),
        "remaining_yuan": _amount_yuan(goal.remaining_amount_cents),
        "progress_percent": int(goal.progress_percent),
        "bar_percent": percent,
        "progress_label": progress_label,
        "progress_tone": progress_tone,
        "is_archived": goal.status == "archived",
        "is_over_limit": goal.progress_state == "over_limit",
        "row_version": goal.row_version,
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
        options=options,
        selected_ledger_id=selected_id,
        show_month_picker=True,
        selected_month=month,
    )
    ctx.update(
        {
            "month": month,
            "month_label": _month_display_label(month),
            "include_archived": include_archived,
            "goals": [_goal_view(goal) for goal in goals],
            "message": message,
            "error": error,
        }
    )
    return templates.TemplateResponse(request=request, name="goals.html", context=ctx)


@router.get("", response_class=HTMLResponse)
def web_goals(
    request: Request,
    ledger_id: str | None = None,
    month: str | None = None,
    include_archived: bool = False,
    msg: str | None = None,
    error: str | None = None,
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
        error=error,
    )


@router.post("/create", response_class=HTMLResponse)
def web_goals_create(
    request: Request,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    name: str = Form(default=""),
    target_amount_yuan: str = Form(default=""),
    category: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    try:
        target_amount_cents = _parse_major_amount(
            target_amount_yuan,
            label="目标金额",
            required=True,
        )
        if target_amount_cents is None or target_amount_cents <= 0:
            raise AppError("invalid_request", "目标金额必须大于 0。", status_code=422)
        payload = GoalCreateRequest(
            name=name,
            month=target_month,
            target_amount_cents=target_amount_cents,
            category=category.strip() or None,
        )
        create_goal(db, tenant_id=selected_id, payload=payload, timezone_name=timezone_name)
    except AppError as exc:
        return _render_goals(
            request=request,
            db=db,
            options=options,
            selected_id=selected_id,
            month=target_month,
            include_archived=False,
            error=exc.message,
        )
    return _web_redirect("/web/goals", selected_id, month=target_month, msg="目标已保存。")


@router.post("/{public_id}/edit")
def web_goals_edit(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    name: str = Form(default=""),
    target_amount_yuan: str = Form(default=""),
    category: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/goals",
            selected_id,
            month=target_month,
            error="页面已过期，请刷新后重新操作。",
        )
    try:
        target_amount_cents = _parse_major_amount(
            target_amount_yuan,
            label="目标金额",
            required=True,
        )
        if target_amount_cents is None or target_amount_cents <= 0:
            raise AppError("invalid_request", "目标金额必须大于 0。", status_code=422)
        result = update_goal(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            payload=GoalUpdateRequest(
                expected_row_version=parsed,
                name=name,
                month=target_month,
                category=category.strip() or None,
                target_amount_cents=target_amount_cents,
            ),
            timezone_name=timezone_name,
        )
    except AppError as exc:
        message = "页面已过期，请刷新后重新操作。" if exc.error == "state_conflict" else exc.message
        return _web_redirect(
            "/web/goals",
            selected_id,
            month=target_month,
            error=message,
        )
    return _web_redirect(
        "/web/goals",
        selected_id,
        month=result.month or target_month,
        msg="目标已更新。",
    )


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
