"""Rule editing uses the same captured-money command as the native client."""

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.routes.web_rule_forms import (
    parse_rule_form,
    rule_amount_label,
    rule_currency_input,
    rule_edit_values,
    rule_form_currency_matches,
)
from app.schemas import CategoryRuleUpdateRequest
from app.services.rule_command_service import update_rule_idempotently
from app.services.rule_service import find_rule_for_tenant

router = APIRouter(prefix="/web/rules", tags=["web"])


def _edit_scope(request: Request, db: Session, ledger_id: str, rule_id: int):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    rule = find_rule_for_tenant(db, tenant_id=selected_id, rule_id=rule_id)
    return options, selected_id, rule


def _render_editor(request, db, options, selected_id, rule, *, rule_id=None, values=None,
                   error=None, conflict=False, status_code=200):
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    current = rule_edit_values(rule, new_currency=ctx["home_currency_code"]) if rule else {}
    draft = values if values is not None else {**current, "idempotency_key": str(uuid4())}
    ctx.update(
        rule=rule, rule_id=rule.id if rule else rule_id, current=current, rule_draft=draft,
        rule_currency_input=rule_currency_input(draft.get("home_currency_code")),
        currency_matches=rule is not None and rule_form_currency_matches(rule, draft), rule_amount_label=rule_amount_label,
        error=error, conflict=conflict, q="?ledger_id=" + selected_id,
    )
    return templates.TemplateResponse(request=request, name="rule_edit.html",
        context=ctx, status_code=status_code)


@router.get("/{rule_id}/edit", response_class=HTMLResponse)
def web_rule_edit(request: Request, rule_id: int, ledger_id: str = "",
                  _local: None = LocalOnly, db: Session = Depends(get_db)):
    options, selected_id, rule = _edit_scope(request, db, ledger_id, rule_id)
    if rule is None:
        raise AppError("rule_not_found", "规则不存在。", status_code=404)
    return _render_editor(request, db, options, selected_id, rule)


@router.post("/{rule_id}/edit", response_class=HTMLResponse)
def web_rule_save(
    request: Request, rule_id: int, ledger_id: str = Form(""),
    keyword: str = Form(""), category: str = Form(""), priority: str = Form("100"),
    amount_min_yuan: str = Form(""), amount_max_yuan: str = Form(""),
    source_contains: str = Form(""), tag_contains: str = Form(""),
    home_currency_code: str = Form(""), expected_row_version: str = Form(""),
    idempotency_key: str = Form(""), review_latest: bool = Form(False),
    _local: None = LocalOnly, db: Session = Depends(get_db),
):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    values = {
        "keyword": keyword, "category": category, "priority": priority,
        "amount_min_yuan": amount_min_yuan, "amount_max_yuan": amount_max_yuan,
        "source_contains": source_contains, "tag_contains": tag_contains,
        "home_currency_code": home_currency_code, "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key,
    }
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**values, "ledger_id": ledger_id, "review_latest": review_latest}, task="修改分类规则")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    rule = find_rule_for_tenant(db, tenant_id=selected_id, rule_id=rule_id)
    if review_latest:
        if rule is not None and rule_form_currency_matches(rule, values):
            values.update(expected_row_version=str(rule.row_version), idempotency_key=str(uuid4()))
        return _render_editor(request, db, options, selected_id, rule, rule_id=rule_id, values=values)
    try:
        version = parse_form_row_version_token(expected_row_version)
        if version is None:
            raise AppError("state_conflict", "页面版本已过期，输入已保留。", status_code=409)
        update_rule_idempotently(db, tenant_id=selected_id, rule_id=rule_id,
            payload=CategoryRuleUpdateRequest(expected_row_version=version, **parse_rule_form(values)),
            idempotency_key=idempotency_key)
    except (AppError, ValidationError) as exc:
        db.rollback()
        conflict = isinstance(exc, AppError) and exc.error in {"state_conflict", "idempotency_key_reused"}
        error = exc.message if isinstance(exc, AppError) else "请检查关键词、分类和金额条件。输入已保留。"
        if conflict:
            error = "这份表单已提交过或规则已更新。输入已保留，请核对当前规则后再保存。"
        return _render_editor(request, db, options, selected_id, rule, rule_id=rule_id, values=values,
            error=error, conflict=conflict, status_code=exc.status_code if isinstance(exc, AppError) else 422)
    return _web_redirect("/web/rules", selected_id, msg="规则修改已保存。已有账单仍需预览并确认后才应用。")
