"""Correction 表单页的 context 与错误重渲（A1 Web 适配层责任之一）。

与事实详情（_web_expense_fact）是两个页面责任：本模块只管
``expense_correct.html`` 的渲染上下文与失败重显 —— 保留提交值、
行级错误、OCC 冲突态（冲突时把服务器最新 token 写回表单，
否则用户修正后再次提交只会重演 409）。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_helpers import web_edit_context
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
) -> dict:
    """Correction form context — reuses the edit view-model so the form posts
    the same field names the pending edit flow already parses."""

    ctx = web_edit_context(
        db,
        request,
        options,
        selected_id,
        expense_id,
        form_values=form_values,
        field_errors=field_errors,
        conflict=conflict,
    )
    ctx["page_title"] = "更正账单"
    ctx["correction_mode"] = True
    ctx["error"] = error
    ctx["reason_input"] = (form_values or {}).get("reason", "")
    if conflict and ctx["conflict_current"] is not None:
        # 提交值 overlay 会把过期 token 盖进表单（_overlay_submitted_expense_values
        # 的 expected_row_version→row_version 映射）；冲突重渲必须带服务器最新
        # token，否则用户修正后再次提交只会重演 409。
        ctx["expense"]["row_version"] = ctx["conflict_current"]["row_version"]
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
        )
    except AppError as exc:
        return _web_redirect(
            "/web/confirmed",
            selected_id,
            msg=exc.message,
            flash_type="error",
        )
    return templates.TemplateResponse(
        request=request,
        name="expense_correct.html",
        context=ctx,
        status_code=status_code,
    )
