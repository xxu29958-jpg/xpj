"""The original ignore/undo task's address and read-only presentation."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_draft_binding import browser_draft_scope, draft_ack_response
from app.routes._web_expense_helpers import drawer_fragment_ok
from app.routes._web_expense_return_context import ExpenseReturnContext, confirm_return_redirect, flow_href, return_href
from app.routes.web_common import _base_ctx, _expense_view, _web_redirect, parse_form_row_version_token, templates
from app.services.expense_service import get_expense


def undo_command_key(value: str | None) -> str:
    try:
        return str(UUID(value or ""))
    except ValueError:
        return str(uuid4())


def rejection_undo_key(ledger_id: str, expense_id: int, reject_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ticketbox:undo:{ledger_id}:{expense_id}:{reject_key}"))


def rejection_queue_response(ledger_id: str, origin: ExpenseReturnContext, *, message: str, flash_type: str, **result) -> RedirectResponse:
    queue = origin if origin.return_to == "recurring_occurrence" else ExpenseReturnContext(return_to="pending", return_filter=origin.return_filter)
    path, params = confirm_return_redirect(queue)
    return _web_redirect(path, ledger_id, msg=message, flash_type=flash_type, **params, **result)


def rejection_result_response(request: Request, *, ledger_id: str, expense_id: int, form, receipt) -> Response:
    undo_key = rejection_undo_key(ledger_id, expense_id, form.reject_idempotency_key)
    destination = rejection_queue_response(ledger_id, form.return_context,
        message="已接受这次忽略，请以账单当前状态为准。", flash_type="success",
        undo=str(expense_id), undo_version=str(receipt.row_version), undo_key=undo_key)
    response = draft_ack_response(request, draft_scope=form.draft_scope, idempotency_key=form.reject_idempotency_key,
        receipt={**receipt.model_dump(mode="json"), "undo_idempotency_key": undo_key},
        next_href=destination.headers["location"])
    return response or (drawer_fragment_ok("reject") if form.fragment else destination)


def undo_result_href(ledger_id: str, origin: ExpenseReturnContext) -> str:
    target = urlsplit(return_href(ledger_id=ledger_id, default_path="/web/pending", **origin.as_kwargs()))
    query = dict(parse_qsl(target.query))
    query.update(msg="已撤销原来的忽略操作，请以账单当前状态为准。", flash_type="success")
    return urlunsplit(target._replace(query=urlencode(query)))


def render_undo_task(request: Request, db: Session, *, options, ledger_id: str, expense_id: int,
                     version: str, key: str, origin: ExpenseReturnContext) -> Response:
    if parse_form_row_version_token(version) is None or undo_command_key(key) != key:
        raise AppError("invalid_request", "这次忽略的原操作信息不完整，请从原结果继续。", status_code=422)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=ledger_id, page_title="撤销这次忽略")
    current, error = None, ""
    try:
        current = _expense_view(get_expense(db, expense_id, ledger_id),
            presentation_currency_code=ctx["home_currency_code"])
    except AppError as exc:
        if exc.error != "expense_not_found":
            raise
        error = "当前无法读取这笔账单。原撤销请求仍保留，可恢复访问后核实。"
    ctx.update(undo_expense_id=expense_id, undo_expected_row_version=version, undo_idempotency_key=key,
        undo_scope=browser_draft_scope(db, request), undo_origin=origin.as_kwargs(), undo_current=current,
        error=error, undo_return_href=return_href(ledger_id=ledger_id, default_path="/web/pending", **origin.as_kwargs()),
        undo_current_href=flow_href(f"/web/expenses/{expense_id}/edit", ledger_id=ledger_id, **origin.as_kwargs()))
    ctx.update(task_return_href=ctx["undo_return_href"], task_return_label="返回原任务")
    return templates.TemplateResponse(request=request, name="expense_undo.html", context=ctx,
        headers={"Cache-Control": "no-store"})
