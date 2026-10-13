"""Rule editing uses the same captured-money command as the native client."""

import json
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    draft_ack_response,
    draft_error_response,
    rendered_draft_scope,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    category_return_url,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.routes.web_rule_forms import (
    RuleDefinitionForm,
    RuleEditForm,
    parse_rule_form,
    rule_currency_input,
    rule_edit_values,
    rule_form_currency_matches,
    rule_form_failure,
)
from app.schemas import CategoryRuleUpdateRequest
from app.services.rule_command_service import update_rule_idempotently
from app.services.rule_service import find_rule_for_tenant

router = APIRouter(prefix="/web/rules", tags=["web"])


def _edit_scope(request: Request, db: Session, ledger_id: str, rule_id: int):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    rule = find_rule_for_tenant(db, tenant_id=selected_id, rule_id=rule_id)
    return options, selected_id, rule


def render_rule_definition(request, db, options, selected_id, rule=None, *, rule_id=None, values=None,
                           error="", result="", recycle=False, status_code=200, return_category="", return_month=""):
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    scope, binding_required = rendered_draft_scope(db, request, values.get("draft_scope", "") if values is not None else None)
    current = rule_edit_values(rule, new_currency=ctx["home_currency_code"]) if rule else {}
    draft = values if values is not None else {
        **RuleDefinitionForm(home_currency_code=ctx["home_currency_code"] or "").model_dump(), **current,
        "ledger_id": selected_id, "rule_id": str(rule_id or ""), "idempotency_key": str(uuid4()),
        "draft_ref": str(uuid4()), "draft_scope": json.dumps(scope) if scope else "",
        "return_category": return_category, "return_month": return_month}
    available = not rule_id or rule is not None and rule_form_currency_matches(rule, draft)
    ctx.update(rule=rule, rule_id=rule_id, rule_draft=draft, rule_draft_scope=scope,
        binding_required=binding_required, definition_available=available, definition_result=result,
        rule_currency_input=rule_currency_input(draft.get("home_currency_code")),
        error=error, recycle=recycle, q="?ledger_id=" + selected_id,
        category_return_url=category_return_url(selected_id, draft.get("return_category", ""), draft.get("return_month", "")))
    return templates.TemplateResponse(request=request, name="rule_definition.html", context=ctx, status_code=status_code)


@router.get("/{rule_id}/edit", response_class=HTMLResponse)
def web_rule_edit(request: Request, rule_id: int, ledger_id: str = "",
                  return_category: str = "", return_month: str = "",
                  _local: None = LocalOnly, db: Session = Depends(get_db)):
    options, selected_id, rule = _edit_scope(request, db, ledger_id, rule_id)
    return render_rule_definition(request, db, options, selected_id, rule, rule_id=rule_id,
        return_category=return_category, return_month=return_month)


@router.post("/{rule_id}/edit", response_class=HTMLResponse)
def web_rule_save(request: Request, rule_id: int, form: Annotated[RuleEditForm, Form()],
                  _local: None = LocalOnly, db: Session = Depends(get_db)):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    values = form.model_dump()
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=values, task="修改分类规则")
        if retained is not None:
            return retained
    rule = None
    try:
        _require_selected_ledger_write(options, selected_id)
        if form.ledger_id != selected_id or form.rule_id not in {"", str(rule_id)}:
            raise AppError("session_binding_changed", "原账本或规则无法确认，原输入仍保留。", status_code=409)
        values["rule_id"] = str(rule_id)
        values["draft_scope"] = reviewed_draft_scope(db, request, form.draft_scope, review=form.review_latest)
        require_draft_binding(db, request, ledger_id=form.ledger_id, draft_scope=values["draft_scope"], require_session=False)
        rule = find_rule_for_tenant(db, tenant_id=selected_id, rule_id=rule_id)
        if form.review_latest:
            if rule is None or not rule_form_currency_matches(rule, values):
                return render_rule_definition(request, db, options, selected_id, rule, rule_id=rule_id,
                    values=values, result="blocked", error="原规则已不可修改或原金额币种无法确认，原输入仍保留。")
            values.update(expected_row_version=str(rule.row_version), idempotency_key=str(uuid4()))
            return render_rule_definition(request, db, options, selected_id, rule, rule_id=rule_id,
                values=values, result="prepared")
        version = parse_form_row_version_token(form.expected_row_version)
        if version is None:
            raise AppError("state_conflict", "页面版本已过期，输入已保留。", status_code=409)
        receipt = update_rule_idempotently(db, tenant_id=selected_id, rule_id=rule_id,
            payload=CategoryRuleUpdateRequest(expected_row_version=version, **parse_rule_form(values)),
            idempotency_key=form.idempotency_key)
    except (AppError, ValidationError) as exc:
        db.rollback()
        error, result = rule_form_failure(exc)
        return draft_error_response(request, error, refusal_result=result) or render_rule_definition(
            request, db, options, selected_id, rule, rule_id=rule_id, values=values,
            error=error.message, result=result, recycle=error.error == "rule_category_deleted", status_code=error.status_code)
    target = category_return_url(selected_id, form.return_category, form.return_month, message="规则修改已保存，可以继续整理原分类。")
    redirect = RedirectResponse(target, status_code=303) if target else _web_redirect(
        "/web/rules", selected_id, msg="规则修改已保存。已有账单仍需预览并确认后才应用。")
    return draft_ack_response(request, draft_scope=values["draft_scope"], idempotency_key=form.idempotency_key,
        receipt=receipt, next_href=redirect.headers["location"]) or redirect
