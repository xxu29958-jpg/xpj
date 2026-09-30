"""Correction 表单页的 context 与错误重渲（A1 Web 适配层责任之一）。

与事实详情（_web_expense_fact）是两个页面责任：本模块只管
``expense_correct.html`` 的渲染上下文与失败重显 —— 保留可安全重试的提交值、
行级错误、OCC 冲突态。冲突保留原输入和版本，当前事实单独供核对；
显式核对后由既有命令服务验证 predecessor identity。
"""

from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_correction_snapshot import correction_snapshot
from app.routes._web_draft_binding import rendered_draft_scope
from app.routes._web_expense_helpers import web_edit_context
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    flow_href,
    resolve_return_to,
    return_context_params,
)
from app.routes.web_common import _web_redirect, templates
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import currency_input_metadata, supported_currency_codes

# correction 表单一行可改的系统冻结字段（拆账接收票的协定冻结面，与旧编辑页一致）。
_SPLIT_RECEIVED_FROZEN_FIELDS = ("amount_yuan", "merchant", "expense_time")


def web_correction_context(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    form_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    conflict: bool = False,
    error: str | None = None,
    receipt_item_rows: list[dict] | None = None,
    split_form_rows: list[dict] | None = None,
    return_context: ExpenseReturnContext = ExpenseReturnContext(),
) -> dict:
    """Correction form context — reuses the edit view-model so the form posts
    the same field names the pending edit flow already parses."""

    return_values = return_context.as_kwargs()
    ctx = web_edit_context(
        db,
        request,
        options,
        selected_id,
        expense_id,
        form_values=form_values,
        field_errors=field_errors,
        conflict=conflict,
        return_context=return_context,
    )
    ctx["flow_return_fields"] = ctx["edit_return_fields"]
    ctx["fact_href"] = flow_href(
        f"/web/expenses/{expense_id}/edit",
        ledger_id=selected_id,
        **return_values,
    )
    ctx["page_title"] = "更正账单"
    ctx["correction_mode"] = True
    ctx["error"] = error
    ctx["reason_input"] = (form_values or {}).get("reason", "")
    ctx["fact_current_version"] = ctx["current_expense"]["row_version"]
    ctx["fact_draft_client_ref"] = (form_values or {}).get("draft_client_ref") or ctx["confirm_idempotency_key"]
    ctx["fact_current_basis"] = correction_snapshot(ctx)
    ctx["fact_basis"] = (form_values or {}).get("fact_basis", json.dumps(ctx["fact_current_basis"], ensure_ascii=False))
    captured = form_values.get("draft_scope", "") if form_values is not None else None
    ctx["fact_draft_scope"], ctx["fact_binding_required"] = rendered_draft_scope(db, request, captured)
    if captured is not None:
        ctx["captured_fact_scope"] = captured
    if form_values is not None:
        # A submitted correction keeps its identity, including invalid blanks.
        # Only a new GET or an explicit conflict review prepares a fresh intent.
        if "expected_row_version" in form_values:
            ctx["expense"]["row_version"] = form_values["expected_row_version"]
        if "idempotency_key" in form_values:
            ctx["confirm_idempotency_key"] = form_values["idempotency_key"]
    ctx["frozen_scalars"] = (
        (*_SPLIT_RECEIVED_FROZEN_FIELDS, "original_currency") if ctx["expense"]["is_split_received"] else ()
    )
    home_currency = require_runtime_home_currency_code(db)
    ctx["currency_options"] = [
        home_currency,
        *sorted(supported_currency_codes() - {home_currency}),
    ]
    selected_currency = (
        ((form_values or {}).get("original_currency") or ctx["expense"]["original_currency_code"]).strip().upper()
    )
    if selected_currency not in ctx["currency_options"]:
        selected_currency = ctx["expense"]["original_currency_code"]
    ctx["selected_original_currency"] = selected_currency
    ctx["expense_currency_input"] = currency_input_metadata(selected_currency)
    if receipt_item_rows is not None:
        ctx["receipt_items"]["rows"] = receipt_item_rows
    if split_form_rows is not None:
        ctx["split_rows"]["rows"] = split_form_rows
    return ctx


def correction_form_error_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    error: str,
    status_code: int = 422,
    form_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    conflict: bool = False,
    receipt_item_rows: list[dict] | None = None,
    split_form_rows: list[dict] | None = None,
    return_context: ExpenseReturnContext = ExpenseReturnContext(),
    rate_recovery: dict | None = None,
    draft_result: str = "",
) -> Response:
    """更正表单的错误重渲（保留提交值/行级错误/冲突态）；行在提交与重读
    之间消失时退化为列表页 flash 重定向（与编辑页守卫同一语义）。"""

    try:
        ctx = web_correction_context(
            db,
            request,
            options,
            selected_id,
            expense_id,
            form_values=form_values,
            field_errors=field_errors,
            conflict=conflict,
            error=error,
            receipt_item_rows=receipt_item_rows,
            split_form_rows=split_form_rows,
            return_context=return_context,
        )
        ctx["rate_recovery"] = rate_recovery
        ctx["fact_draft_result"] = draft_result
        if conflict:
            ctx.update(fact_review=ctx["fact_current_basis"], fact_review_required={}, fact_review_ready=False)
    except AppError as exc:
        return _web_redirect(
            resolve_return_to(return_context.return_to, "/web/confirmed"),
            selected_id,
            msg=exc.message,
            flash_type="error",
            **return_context_params(**return_context.as_kwargs()),
        )
    return templates.TemplateResponse(
        request=request,
        name="expense_correct.html",
        context=ctx,
        status_code=status_code,
    )
