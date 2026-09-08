"""Native spending-goal editor; the shared command owns all financial writes."""

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
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
    parse_form_row_version_token,
    templates,
)
from app.routes.web_goals import _parse_amount_yuan
from app.schemas import GoalUpdateRequest
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.goal_service import get_goal
from app.services.goal_update_command import update_goal_idempotently

router = APIRouter(prefix="/web/goals", tags=["web"])


def _edit_scope(request: Request, db: Session, ledger_id: str, public_id: str):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    goal = get_goal(db, tenant_id=selected_id, public_id=public_id)
    if goal.goal_type != "spending_limit":
        raise AppError("goal_not_found", status_code=404)
    return options, selected_id, goal


def _render_editor(
    request: Request, db: Session, options, selected_id: str, goal,
    *, values: dict[str, str] | None = None, error: str | None = None,
    conflict: bool = False, status_code: int = 200,
) -> HTMLResponse:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    current = {
        "name": goal.name, "month": goal.month, "category": goal.category or "",
        "target_amount_yuan": _amount_yuan(goal.target_amount_cents, ctx["home_currency_code"]),
        "expected_row_version": str(goal.row_version),
    }
    ctx.update(
        goal=goal, current=current, values=values if values is not None else {
            **current, "idempotency_key": str(uuid4()),
        }, error=error, conflict=conflict,
    )
    return templates.TemplateResponse(
        request=request, name="goal_edit.html", context=ctx, status_code=status_code,
    )


@router.get("/{public_id}/edit", response_class=HTMLResponse)
def web_goal_edit(
    request: Request, public_id: str, ledger_id: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options, selected_id, goal = _edit_scope(request, db, ledger_id, public_id)
    return _render_editor(request, db, options, selected_id, goal)


@router.post("/{public_id}/edit", response_class=HTMLResponse)
def web_goal_save(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), name: str = Form(default=""),
    month: str = Form(default=""), target_amount_yuan: str = Form(default=""),
    category: str = Form(default=""), expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""), review_latest: bool = Form(default=False),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options, selected_id, goal = _edit_scope(request, db, ledger_id, public_id)
    values = {
        "name": name, "month": month, "target_amount_yuan": target_amount_yuan,
        "category": category, "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key,
    }
    if review_latest:
        # Explicit review only renders a new proposal. It never submits a write.
        values.update(expected_row_version=str(goal.row_version), idempotency_key=str(uuid4()))
        return _render_editor(request, db, options, selected_id, goal, values=values)
    try:
        version = parse_form_row_version_token(expected_row_version)
        if version is None:
            raise AppError("state_conflict", status_code=409)
        payload = GoalUpdateRequest(
            name=name, month=month, category=category.strip() or None,
            target_amount_cents=_parse_amount_yuan(
                target_amount_yuan, currency_code=require_runtime_home_currency_code(db),
            ), expected_row_version=version,
        )
        result = update_goal_idempotently(
            db, tenant_id=selected_id, public_id=public_id, payload=payload,
            idempotency_key=idempotency_key, timezone_name=get_settings().ocr_default_timezone,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        conflict = isinstance(exc, AppError) and exc.error == "state_conflict"
        error = exc.message if isinstance(exc, AppError) else "请检查目标名称、月份和金额。输入已保留。"
        if conflict:
            error = "目标已在其它端更新。你的输入已保留，请对照当前目标核对后再保存。"
        return _render_editor(
            request, db, options, selected_id, goal, values=values, error=error,
            conflict=conflict, status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _web_redirect("/web/goals", selected_id, month=result.month, msg="目标修改已保存。")
