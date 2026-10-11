"""Web form adaptation for the existing expense subtask command owner."""
from dataclasses import dataclass, replace
from uuid import uuid4

from fastapi import Form, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_draft_binding import (
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes._web_expense_fact import web_fact_error_response
from app.routes._web_expense_helpers import _edit_page_or_flash_redirect
from app.routes._web_expense_return_context import ExpenseReturnContext, edit_context_params
from app.routes._web_expense_rows import (
    EXPENSE_ROW_ERROR_MESSAGES,
    attach_form_row_error,
    item_replace_payload,
    split_replace_payload,
    submitted_item_form_rows,
    submitted_split_form_rows,
)
from app.routes._web_session_common import parse_form_row_version_token, resolve_web_actor
from app.routes.web_common import _require_selected_ledger_write, _web_redirect
from app.schemas import ExpenseAcknowledgeItemsMismatchRequest
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.expense_service import get_expense
from app.services.expense_subtask_command_service import submit_expense_subtask


@dataclass(frozen=True)
class WebExpenseSubtaskForm:
    ledger_id: str
    expected_row_version: str
    idempotency_key: str
    draft_ref: str
    draft_scope: str
    review_latest: bool


def web_expense_subtask_form(
    ledger_id: str = Form(default=""), expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""), draft_ref: str = Form(default=""),
    draft_scope: str = Form(default=""), review_latest: bool = Form(default=False),
) -> WebExpenseSubtaskForm:
    return WebExpenseSubtaskForm(ledger_id, expected_row_version, idempotency_key or str(uuid4()),
        draft_ref or str(uuid4()), draft_scope, review_latest)


def _render_subtask(db, request, options, selected_id, expense_id, kind, form, rows, return_context, error=None):
    result = "prepared" if form.review_latest and error is None else draft_refusal_result(error) if error else ""
    response = draft_error_response(request, error) if error else None
    if response is not None:
        return response
    values = {"kind": kind, "idempotency_key": str(uuid4()) if result == "prepared" else form.idempotency_key,
        "draft_ref": form.draft_ref, "draft_scope": form.draft_scope, "result": result,
        "expected_row_version": "" if result == "prepared" else form.expected_row_version}
    message = EXPENSE_ROW_ERROR_MESSAGES.get(error.error, error.message) if error else ""
    status_code = error.status_code if error else 200
    if kind == "ack":
        return _render_acknowledgement(db, request, options, selected_id, expense_id, message,
            status_code=status_code, subtask_values=values, return_context=return_context)
    return _edit_page_or_flash_redirect(db, request, options, selected_id, expense_id,
        message, "/web/confirmed",
        error_key="splits_error" if kind == "splits" else "items_error",
        status_code=status_code,
        receipt_item_rows=rows if kind == "items" else None, split_form_rows=rows if kind == "splits" else None,
        subtask_expected_version=form.expected_row_version,
        subtask_reviewed=result == "prepared", subtask_values=values,
        return_context=return_context)


def _render_acknowledgement(db, request, options, selected_id, expense_id, message, **context):
    try:
        if get_expense(db, expense_id, selected_id).status == "confirmed":
            return web_fact_error_response(db, request, options, selected_id, expense_id, message, **context)
    except AppError:
        pass  # The edit presenter retains its existing vanished-row return.
    return _edit_page_or_flash_redirect(db, request, options, selected_id, expense_id, message,
        "/web/confirmed", error_key="items_error", **context)


def _subtask_payload(db, selected_id, expense_id, kind, form, lines):
    version = parse_form_row_version_token(form.expected_row_version)
    if version is None:
        raise AppError("invalid_request", "提交依据无法核对。原填写仍保留，请核对当前记录后继续。", status_code=422)
    if kind == "ack":
        return ExpenseAcknowledgeItemsMismatchRequest(expected_row_version=version)
    # Preserve the existing legacy-row currency fallback; display currency never reinterprets rows.
    currency = get_expense(db, expense_id, selected_id).home_currency_code or require_runtime_home_currency_code(db)
    parser = item_replace_payload if kind == "items" else split_replace_payload
    return parser(currency_code=currency, expected_row_version=version, **lines)


def submit_web_expense_subtask(
    db: Session, request: Request, options, selected_id: str, expense_id: int, *,
    kind: str, form: WebExpenseSubtaskForm, lines: dict, return_context: ExpenseReturnContext,
) -> Response:
    rows = (submitted_item_form_rows(**lines) if kind == "items" else
        submitted_split_form_rows(**lines) if kind == "splits" else [])
    try:
        _require_selected_ledger_write(options, selected_id)
        form = replace(form, draft_scope=reviewed_draft_scope(db, request, form.draft_scope, review=form.review_latest))
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=form.draft_scope,
            require_session=False, original_ledger_id=form.ledger_id)
        if form.review_latest:
            return _render_subtask(db, request, options, selected_id, expense_id, kind, form, rows, return_context)
        payload = _subtask_payload(db, selected_id, expense_id, kind, form, lines)
        account_id, device_id = resolve_web_actor(db, request, selected_id)
        receipt = submit_expense_subtask(db, expense_id=expense_id, tenant_id=selected_id, payload=payload,
            expected_row_version=payload.expected_row_version, idempotency_key=form.idempotency_key,
            actor_account_id=account_id, actor_device_id=device_id)
    except AppError as exc:
        db.rollback()
        attach_form_row_error(rows, exc)
        return _render_subtask(db, request, options, selected_id, expense_id, kind, form, rows, return_context, exc)
    next_response = _web_redirect(f"/web/expenses/{expense_id}/edit", selected_id,
        msg={"items": "这次明细已保存。", "splits": "这次家庭拆账已保存。", "ack": "已确认原小票如此。"}[kind],
        **edit_context_params(**return_context.as_kwargs()))
    return draft_ack_response(request, draft_scope=form.draft_scope, idempotency_key=form.idempotency_key,
        receipt=receipt, next_href=next_response.headers["location"]) or next_response
