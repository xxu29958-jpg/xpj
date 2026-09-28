"""Native income correction delegates publication to the existing revision owner."""

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import draft_ack_response, require_draft_binding
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
from app.routes.web_income_plans import _parse_pay_day, _parse_yuan
from app.schemas import IncomePlanUpdateRequest
from app.services.currency_common import minor_amount_value
from app.services.income_plan_service import get_income_plan
from app.services.income_plan_service._delivery import update_income_plan_idempotently
from app.services.income_plan_service._history import income_plan_history
from app.services.ledger_calendar_service import current_ledger_month
from app.services.manual_expense_draft_presenter import manual_draft_scope

router = APIRouter(prefix="/web/income-plans", tags=["web"])


def _edit_scope(request: Request, db: Session, ledger_id: str, public_id: str):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return options, selected, get_income_plan(db, tenant_id=selected, public_id=public_id)


def _render_editor(
    request: Request, db: Session, options, selected: str, plan,
    *, intent_month: str, values: dict[str, str] | None = None,
    error: str | None = None, conflict: bool = False, status_code: int = 200, draft_result: str = "",
) -> HTMLResponse:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected)
    can_write = True
    try:
        _require_selected_ledger_write(options, selected)
    except AppError as exc:
        if exc.error != "permission_denied":
            raise
        can_write = False
    current = {
        "label": plan.label, "source_type": plan.source_type, "frequency": plan.frequency,
        "income_month": plan.income_month or "", "pay_day": str(plan.pay_day),
        "amount_yuan": minor_amount_value(plan.amount_cents, plan.home_currency_code),
        "expected_row_version": str(plan.row_version),
    }
    ctx.update(
        plan=plan, current=current, currency_input=_currency_input_view(plan.home_currency_code), values=values if values is not None else {
            **current, "intent_month": intent_month, "idempotency_key": str(uuid4()),
        }, error=error, conflict=conflict, permission_refused=status_code == 403 or not can_write,
        can_write=can_write,
        review_month=current_ledger_month(db, ledger_id=selected),
        income_draft_scope=manual_draft_scope(db, request.state.web_session_auth)
            if getattr(request.state, "web_session_auth", None) is not None else None,
        income_draft_result=draft_result,
    )
    return templates.TemplateResponse(
        request=request, name="income_edit.html", context=ctx, status_code=status_code,
    )


@router.get("/{public_id}/history", response_class=HTMLResponse)
def web_income_history(
    request: Request, public_id: str, ledger_id: str = "",
    before_version: int | None = Query(default=None, ge=1), limit: int = Query(default=20, ge=1, le=100),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    history = income_plan_history(db, tenant_id=selected, public_id=public_id, before_version=before_version, limit=limit)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected)
    ctx.update(history=history, before_version=before_version, limit=limit, minor_amount_value=minor_amount_value)
    return templates.TemplateResponse(request=request, name="income_history.html", context=ctx)


@router.get("/{public_id}/edit", response_class=HTMLResponse)
def web_income_edit(
    request: Request, public_id: str,
    intent_month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), ledger_id: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options, selected, plan = _edit_scope(request, db, ledger_id, public_id)
    return _render_editor(request, db, options, selected, plan, intent_month=intent_month)


def _edit_payload(values: dict[str, str], *, currency_code: str) -> IncomePlanUpdateRequest:
    version = parse_form_row_version_token(values["expected_row_version"])
    if version is None:
        raise AppError("state_conflict", status_code=409)
    return IncomePlanUpdateRequest(
        expected_row_version=version, intent_month=values["intent_month"],
        label=values["label"], source_type=values["source_type"], frequency=values["frequency"],
        income_month=(values["income_month"].strip() or None) if values["frequency"] == "one_time" else None,
        amount_cents=_parse_yuan(values["amount_yuan"], currency_code=currency_code, label="预计收入金额"),
        pay_day=_parse_pay_day(values["pay_day"]),
    )


def _edit_refusal(request, db, *, options, selected, public_id, values, exc):
    db.rollback()
    error = exc.message if isinstance(exc, AppError) else "请检查名称、频率、月份和金额。输入已保留。"
    code = exc.error if isinstance(exc, AppError) else "invalid_request"
    status = exc.status_code if isinstance(exc, AppError) else 422
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"error": code, "message": error, "draft_result": "blocked"},
            status_code=status, headers={"Cache-Control": "no-store"})
    conflict = code in {"state_conflict", "idempotency_key_reused"} or (
        code == "session_binding_changed" and not values["draft_scope"])
    if code == "permission_denied":
        error = "当前角色为只读，尚未保存。原输入已保留，权限恢复后可重试。"
    elif code == "state_conflict":
        error = "计划已有较新变更。你的输入和原生效月份已保留，请核对当前计划后再保存。"
    elif code == "idempotency_key_reused":
        error = "这份表单已经提交过。新的修改尚未保存，请核对当前计划和生效月份后再保存。"
    plan = get_income_plan(db, tenant_id=selected, public_id=public_id)
    return _render_editor(request, db, options, selected, plan, intent_month=values["intent_month"],
        values=values, error=error, conflict=conflict, status_code=status, draft_result="blocked")


@router.post("/{public_id}/edit", response_class=HTMLResponse)
def web_income_save(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), label: str = Form(default=""),
    source_type: str = Form(default=""), frequency: str = Form(default=""),
    income_month: str = Form(default=""), amount_yuan: str = Form(default=""),
    pay_day: str = Form(default=""), intent_month: str = Form(default=""),
    expected_row_version: str = Form(default=""), idempotency_key: str = Form(default=""),
    draft_scope: str = Form(default=""),
    review_latest: bool = Form(default=False),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    values = {
        "label": label, "source_type": source_type, "frequency": frequency,
        "income_month": income_month, "amount_yuan": amount_yuan, "pay_day": pay_day,
        "intent_month": intent_month, "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key,
        "draft_scope": draft_scope,
        "review_latest": "true" if review_latest else "",
    }
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={**values, "ledger_id": ledger_id, "review_latest": review_latest}, task="修改收入计划")
    if retained is not None:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"error": "session_binding_changed", "draft_result": "blocked",
                "message": "账本已切换；原修改仍保留，请切回原账本后继续。"},
                status_code=409, headers={"Cache-Control": "no-store"})
        return retained
    try:
        auth = getattr(request.state, "web_session_auth", None)
        if review_latest and auth is not None and not draft_scope:
            values["draft_scope"] = json.dumps(manual_draft_scope(db, auth))
        require_draft_binding(db, request, ledger_id=selected,
            draft_scope=values["draft_scope"], require_session=False)
        _require_selected_ledger_write(options, selected)
    except AppError as exc:
        if exc.error not in {"permission_denied", "session_binding_changed", "invalid_token"}:
            raise
        return _edit_refusal(request, db, options=options, selected=selected,
            public_id=public_id, values=values, exc=exc)
    plan = get_income_plan(db, tenant_id=selected, public_id=public_id)
    if review_latest:
        # The labelled review action prepares, but never publishes, a new intent.
        values.update(intent_month=current_ledger_month(db, ledger_id=selected), expected_row_version=str(plan.row_version), idempotency_key=str(uuid4()))
        return _render_editor(request, db, options, selected, plan,
            intent_month=values["intent_month"], values=values, draft_result="prepared")
    try:
        payload = _edit_payload(values, currency_code=plan.home_currency_code)
        receipt = update_income_plan_idempotently(
            db, tenant_id=selected, public_id=public_id, payload=payload,
            actor_account_id=resolve_web_actor_account_id(db, request, selected), idempotency_key=idempotency_key,
        )
    except (AppError, ValidationError) as exc:
        return _edit_refusal(request, db, options=options, selected=selected,
            public_id=public_id, values=values, exc=exc)
    redirect = _web_redirect("/web/income-plans", selected, message="收入计划修改已保存")
    return draft_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=receipt.model_dump(mode="json"), next_href=redirect.headers["location"]) or redirect
