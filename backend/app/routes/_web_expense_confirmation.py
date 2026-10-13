"""Web presentation of the accepted confirmation, separate from today's bill."""
from dataclasses import replace
from uuid import uuid4

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_edit_command import expense_edit_form_values
from app.routes._web_expense_edit_form import WebExpenseEditForm
from app.routes._web_expense_helpers import web_edit_context
from app.routes._web_expense_return_context import ExpenseReturnContext, flow_href, return_href
from app.routes._web_money_views import _minor_amount_label
from app.routes.web_common import _base_ctx, templates
from app.services.expense_review_command_service import read_expense_confirmation_receipt
from app.services.expense_service import get_expense


def confirmation_draft_fields(form: WebExpenseEditForm) -> dict:
    return {**expense_edit_form_values(form), **form.return_context.as_kwargs(),
        "ledger_id": form.ledger_id, "expected_row_version": form.expected_row_version,
        "idempotency_key": form.idempotency_key, "draft_scope": form.draft_scope, "draft_ref": form.draft_ref,
        "command_action": form.command_action,
        "keep_idempotency_key": form.keep_idempotency_key, "reject_idempotency_key": form.reject_idempotency_key,
        "save_before_confirm": "1" if form.save_before_confirm else "0"}


def render_confirmation_task(request: Request, db: Session, *, options, ledger_id: str, expense_id: int,
                             form: WebExpenseEditForm, error: str = "", result: str = "", status: int = 200) -> Response:
    fields = {**confirmation_draft_fields(form), "review_result": result}
    if result == "prepared":
        current = get_expense(db, expense_id, ledger_id)
        if current.status != "pending":
            original = read_expense_confirmation_receipt(db, tenant_id=ledger_id, expense_id=expense_id,
                idempotency_key=form.idempotency_key) if form.idempotency_key and form.command_action not in {"save", "keep", "reject"} else None
            if original is not None:
                return RedirectResponse(confirmation_href(expense_id, form.idempotency_key, ledger_id, form.return_context), status_code=303)
            raise AppError("expense_correction_required", "这笔账单已离开待确认状态，请查看当前账单。", status_code=409)
        fields.update(expected_row_version=str(current.row_version), idempotency_key=str(uuid4()),
            keep_idempotency_key=str(uuid4()), reject_idempotency_key=str(uuid4()),
            command_action="confirm" if form.command_action in {"keep", "reject"} else form.command_action)
    ctx = web_edit_context(db, request, options, ledger_id, expense_id,
        form_values=fields, return_context=form.return_context)
    ctx.update(error=error, expense_review_task=True,
        expense_review_current=ctx["current_expense"] if result == "prepared" else None)
    return templates.TemplateResponse(request=request, name="_edit_drawer.html" if form.fragment else "edit.html", context=ctx, status_code=status,
                                      headers={"Cache-Control": "no-store"})


def confirmation_href(expense_id: int, key: str, ledger_id: str, origin: ExpenseReturnContext) -> str:
    return flow_href(f"/web/expenses/{expense_id}/confirmation/{key}", ledger_id=ledger_id,
        **replace(origin, return_to=origin.return_to or "pending", return_receipt_key="", return_receipt_expense_id="").as_kwargs())


def render_expense_confirmation(request: Request, db: Session, *, options, ledger_id: str, expense_id: int,
    key: str, origin: ExpenseReturnContext, fragment: bool) -> Response:
    origin = replace(origin, return_to=origin.return_to or "pending", return_receipt_key="", return_receipt_expense_id="")
    receipt, error, status = None, "", 200
    try:
        receipt = read_expense_confirmation_receipt(db, tenant_id=ledger_id, expense_id=expense_id, idempotency_key=key)
        if receipt is None:
            error, status = "暂时无法核对这次确认的原回执。请返回原任务核实，原账单和提交保持不变。", 404
    except AppError as exc:
        error, status = exc.message, exc.status_code
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=ledger_id, page_title="确认回执")
    ctx.update(receipt=receipt, error=error,
        task_return_href=return_href(ledger_id=ledger_id, default_path="/web/pending", **origin.as_kwargs()),
        task_return_label="返回原列表", confirmation_fragment=fragment,
        confirmation_detail_href=flow_href(f"/web/expenses/{expense_id}/edit", ledger_id=ledger_id,
            **replace(origin, return_receipt_key=key, return_receipt_expense_id=str(expense_id)).as_kwargs()),
        confirmation_original_href=flow_href(f"/web/expenses/{expense_id}/edit", ledger_id=ledger_id, **origin.as_kwargs()))
    if receipt is not None:
        ctx.update(receipt_amount=_minor_amount_label(receipt.amount_cents, receipt.home_currency),
            receipt_original=_minor_amount_label(receipt.original_amount_minor, receipt.original_currency_code),
            receipt_date=receipt.accounting_time.accounting_date if receipt.accounting_time else None)
    return templates.TemplateResponse(request=request,
        name="_expense_confirmation.html" if fragment else "expense_confirmation.html", context=ctx,
        status_code=status, headers={"Cache-Control": "no-store"})
