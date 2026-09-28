"""Native spending-goal editor; the shared command owns all financial writes."""

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
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
    _with_ledger,
    category_return_url,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.routes.web_goals import _parse_amount_yuan
from app.schemas import GoalUpdateRequest
from app.services.currency_common import currency_input_metadata, normalize_currency_code
from app.services.goal_service import get_goal
from app.services.goal_update_command import update_goal_idempotently
from app.services.manual_expense_draft_presenter import manual_draft_scope

router = APIRouter(prefix="/web/goals", tags=["web"])


def _edit_scope(request: Request, db: Session, ledger_id: str, public_id: str):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return options, selected_id, _editor_goal(db, selected_id, public_id)


def _editor_goal(db, selected_id: str, public_id: str):
    goal = get_goal(db, tenant_id=selected_id, public_id=public_id)
    if goal.goal_type != "spending_limit":
        raise AppError("goal_not_found", status_code=404)
    return goal


def _render_editor(
    request: Request, db: Session, options, selected_id: str, goal,
    *, values: dict[str, str] | None = None, error: str | None = None,
    conflict: bool = False, status_code: int = 200,
    return_category: str = "", return_month: str = "",
    draft_result: str = "",
) -> HTMLResponse:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    current = {
        "name": goal.name, "month": goal.month, "category": goal.category or "",
        "target_amount_yuan": _amount_yuan(goal.target_amount_cents, goal.home_currency_code) if goal.home_currency_code else "",
        "home_currency_code": goal.home_currency_code or "",
        "expected_row_version": str(goal.row_version),
    }
    values = values if values is not None else {**current, "idempotency_key": str(uuid4()),
        "return_category": return_category, "return_month": return_month}
    try:
        form_currency = currency_input_metadata(values.get("home_currency_code"))
    except AppError:
        form_currency = {}
    currency_matches = bool(form_currency) and values["home_currency_code"] == goal.home_currency_code
    ctx.update(
        goal=goal, current=current, values=values, form_currency=form_currency,
        currency_matches=currency_matches, error=error, conflict=conflict,
        goal_draft_result=draft_result,
        goal_draft_scope=manual_draft_scope(db, request.state.web_session_auth)
            if getattr(request.state, "web_session_auth", None) is not None else None,
        category_return_url=category_return_url(selected_id, values.get("return_category", ""), values.get("return_month", "")),
        current_edit_url=_with_ledger(f"/web/goals/{goal.public_id}/edit", selected_id,
            return_category=values.get("return_category", ""), return_month=values.get("return_month", "")),
    )
    return templates.TemplateResponse(
        request=request, name="goal_edit.html", context=ctx, status_code=status_code,
    )


@router.get("/{public_id}/edit", response_class=HTMLResponse)
def web_goal_edit(
    request: Request, public_id: str, ledger_id: str = "",
    return_category: str = "", return_month: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options, selected_id, goal = _edit_scope(request, db, ledger_id, public_id)
    return _render_editor(request, db, options, selected_id, goal,
        return_category=return_category, return_month=return_month)


@router.post("/{public_id}/edit", response_class=HTMLResponse)
def web_goal_save(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), name: str = Form(default=""),
    month: str = Form(default=""), target_amount_yuan: str = Form(default=""),
    category: str = Form(default=""), expected_row_version: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    idempotency_key: str = Form(default=""), review_latest: bool = Form(default=False),
    draft_scope: str = Form(default=""),
    return_category: str = Form(""), return_month: str = Form(""),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    values = {
        "name": name, "month": month, "target_amount_yuan": target_amount_yuan,
        "category": category, "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key,
        "home_currency_code": home_currency_code,
        "draft_scope": draft_scope,
        "review_latest": "true" if review_latest else "",
        "return_category": return_category, "return_month": return_month,
    }
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**values, "ledger_id": ledger_id, "review_latest": review_latest}, task="修改支出目标")
    if retained is not None:
        return retained
    try:
        auth = getattr(request.state, "web_session_auth", None)
        if review_latest and auth is not None and not draft_scope:
            values["draft_scope"] = json.dumps(manual_draft_scope(db, auth))
        require_draft_binding(db, request, ledger_id=selected_id,
            draft_scope=values["draft_scope"], require_session=False)
        _require_selected_ledger_write(options, selected_id)
    except AppError as exc:
        return _edit_refusal(request, db, options, selected_id, public_id, values, exc)
    goal = _editor_goal(db, selected_id, public_id)
    if review_latest:
        # Explicit review only renders a new proposal. It never submits a write.
        if home_currency_code == goal.home_currency_code:
            values.update(expected_row_version=str(goal.row_version), idempotency_key=str(uuid4()))
        return _render_editor(request, db, options, selected_id, goal, values=values, draft_result="prepared")
    try:
        version = parse_form_row_version_token(expected_row_version)
        if version is None:
            raise AppError("state_conflict", status_code=409)
        currency = normalize_currency_code(home_currency_code)
        if currency != goal.home_currency_code:
            raise AppError("goal_currency_conflict", "原输入币种与目标不一致。输入已保留，请核对当前目标。", status_code=409)
        payload = GoalUpdateRequest(
            name=name, month=month, category=category.strip() or None,
            home_currency_code=currency,
            target_amount_cents=_parse_amount_yuan(
                target_amount_yuan, currency_code=currency,
            ), expected_row_version=version,
        )
        result = update_goal_idempotently(
            db, tenant_id=selected_id, public_id=public_id, payload=payload,
            idempotency_key=idempotency_key, timezone_name=get_settings().ocr_default_timezone,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id),
        )
    except (AppError, ValidationError) as exc:
        return _edit_refusal(request, db, options, selected_id, public_id, values, exc)
    target = category_return_url(selected_id, return_category, return_month, message="目标修改已保存，可以继续整理原分类。")
    redirect = RedirectResponse(target, status_code=303) if target else _web_redirect(
        "/web/goals", selected_id, month=result.month, msg="目标修改已保存。")
    return draft_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=result.model_dump(mode="json"), next_href=redirect.headers["location"]) or redirect


def _edit_refusal(request, db, options, selected_id, public_id, values, exc):
    db.rollback()
    code = exc.error if isinstance(exc, AppError) else "invalid_request"
    message = exc.message if isinstance(exc, AppError) else "请检查目标名称、月份和金额。输入已保留。"
    status = exc.status_code if isinstance(exc, AppError) else 422
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"error": code, "message": message, "draft_result": "blocked"},
            status_code=status, headers={"Cache-Control": "no-store"})
    conflict = code in {"state_conflict", "idempotency_key_reused"} or (code == "session_binding_changed" and not values["draft_scope"])
    if code == "state_conflict":
        message = "目标已在其它端更新。你的输入已保留，请对照当前目标核对后再保存。"
    elif code == "idempotency_key_reused":
        message = "这份表单已经提交过。新的修改尚未保存，请核对当前目标后再保存。"
    return _render_editor(request, db, options, selected_id, _editor_goal(db, selected_id, public_id),
        values=values, error=message, conflict=conflict, status_code=status, draft_result="blocked")
