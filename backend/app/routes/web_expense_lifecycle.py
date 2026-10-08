"""Web pending-expense lifecycle commands: confirm, reject, and reject undo."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.errors import AppError
from app.routes._web_confirmed_write_guard import confirmed_write_guard_response
from app.routes._web_draft_binding import (
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes._web_expense_confirm_command import confirm_web_expense
from app.routes._web_expense_confirmation import (
    confirmation_draft_fields,
    confirmation_href,
    render_confirmation_task,
    render_expense_confirmation,
)
from app.routes._web_expense_edit_form import WebExpenseEditForm, web_expense_edit_form
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_expense_helpers import confirm_reject_error, drawer_fragment_ok
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    confirm_return_redirect,
    expense_return_form_context,
    expense_return_query_context,
    resolve_return_to,
    return_context_params,
)
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
)
from app.services.expense_review_command_service import submit_expense_rejection

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/confirmation/{command_key}", response_class=HTMLResponse)
def web_confirmation_receipt(
    expense_id: int, command_key: str, request: Request, ledger_id: str = "", fragment: int = 0,
    return_context: ExpenseReturnContext = Depends(expense_return_query_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return render_expense_confirmation(request, db, options=options, ledger_id=selected, expense_id=expense_id,
        key=command_key, origin=return_context, fragment=bool(fragment))


@router.post("/expenses/{expense_id}/confirm", response_class=HTMLResponse)
def web_confirm(
    expense_id: int,
    request: Request,
    form: WebExpenseEditForm = Depends(web_expense_edit_form),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db, form.ledger_id or None, options, request=request
    )
    form = replace(form, command_action="confirm")
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=confirmation_draft_fields(form), task="核对并确认原账单")
        if retained is not None:
            return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        form = replace(form, draft_scope=reviewed_draft_scope(db, request, form.draft_scope, review=form.review_latest))
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=form.draft_scope, require_session=False)
        if form.draft_scope and form.ledger_id != selected_id:
            raise AppError("session_binding_changed", "原账本已切换，请保留输入并切回原账本。", status_code=409)
        if form.review_latest:
            return render_confirmation_task(request, db, options=options, ledger_id=selected_id,
                expense_id=expense_id, form=form, result="prepared")
    except AppError as exc:
        response = draft_error_response(request, exc)
        if response is not None:
            return response
        return render_confirmation_task(request, db, options=options, ledger_id=selected_id,
            expense_id=expense_id, form=form, error=exc.message, result="blocked", status=exc.status_code)
    actor_account_id, actor_device_id = resolve_web_actor(db, request, selected_id)
    outcome = confirm_web_expense(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
        form=form,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
    )
    if outcome.error is not None:
        error = AppError(outcome.error_code or "invalid_request", outcome.error, status_code=outcome.error_status)
        response = draft_error_response(request, error)
        if response is not None:
            return response
        if form.draft_scope:
            return render_confirmation_task(request, db, options=options, ledger_id=selected_id,
                expense_id=expense_id, form=form, error=error.message, result=draft_refusal_result(error), status=error.status_code)
        return confirm_reject_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            outcome.error,
            form.fragment,
            status_code=outcome.error_status,
            return_context=form.return_context,
            form_values=outcome.form_values,
            field_errors=outcome.field_errors,
            conflict=outcome.conflict,
        )
    if form.idempotency_key:
        href = confirmation_href(expense_id, form.idempotency_key, selected_id, form.return_context)
        response = draft_ack_response(request, draft_scope=form.draft_scope, idempotency_key=form.idempotency_key,
            receipt=outcome.receipt, next_href=href)
        if response is not None:
            return response
        if not form.fragment:
            return RedirectResponse(href, status_code=303)
    if form.fragment:
        return drawer_fragment_ok("confirm")
    path, params = confirm_return_redirect(form.return_context)
    return _web_redirect(path, selected_id, **params)


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    request: Request,
    expense_id: int,
    form: WebExpenseEditForm = Depends(web_expense_edit_form),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    values = {**confirmation_draft_fields(form), "fragment": str(form.fragment), "expense_id": str(expense_id)}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields=values, task="继续原忽略操作并保留核对填写")
    if retained is not None:
        return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=form.draft_scope, require_session=False)
        parsed = parse_form_row_version_token(form.expected_row_version)
        if parsed is None:
            raise AppError("state_conflict", "页面已过期，请核对当前账单后继续。", status_code=422)
        receipt = submit_expense_rejection(
            db,
            operation="reject_expense",
            expense_id=expense_id,
            tenant_id=selected_id,
            expected_row_version=parsed,
            request_expected_row_version=parsed,
            idempotency_key=form.reject_idempotency_key,
            actor_account_id=None,
        )
    except AppError as exc:
        db.rollback()
        if exc.error in {"invalid_token", "session_binding_changed", "permission_denied"}:
            return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
                fields=values, task="原忽略操作与核对填写仍保留", error=exc)
        if exc.error == "expense_reversal_required":
            guarded = confirmed_write_guard_response(db, request, options, selected_id, expense_id,
                error_code=exc.error, fragment=bool(form.fragment), return_context=form.return_context)
            if guarded is not None:
                return guarded
        message = "账单已在其它端被修改，请刷新后重新操作。" if exc.error == "state_conflict" else exc.message
        return confirm_reject_error(db, request, options, selected_id, expense_id, message, form.fragment,
            status_code=web_form_error_status(exc), form_values=values, return_context=form.return_context)
    if form.fragment:
        return drawer_fragment_ok("reject")
    origin = form.return_context.as_kwargs()
    if origin.get("return_to") == "recurring_occurrence":
        path = resolve_return_to("recurring_occurrence", "/web/pending", **origin)
        params = return_context_params(**origin)
    else:
        path = "/web/pending"
        params = return_context_params("pending", return_filter=form.return_context.return_filter)
    return _web_redirect(
        path,
        selected_id,
        msg="已接受这次忽略，请以账单当前状态为准。",
        undo=str(expense_id),
        undo_version=str(receipt.row_version),
        flash_type="success",
        **params,
    )


@router.post("/expenses/{expense_id}/undo", response_class=HTMLResponse)
def web_expense_undo(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    draft_scope: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    fields = {"ledger_id": ledger_id, "expense_id": str(expense_id), "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key, "draft_scope": draft_scope, **return_context.as_kwargs()}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields=fields, task="核实原撤销操作")
    if retained is not None:
        return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=draft_scope, require_session=False)
    except AppError as exc:
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=fields, task="原撤销操作仍保留", error=exc)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        origin = return_context.as_kwargs()
        if origin.get("return_to") == "recurring_occurrence":
            path = resolve_return_to("recurring_occurrence", "/web/pending", **origin)
            params = return_context_params(**origin)
            return _web_redirect(
                path,
                selected_id,
                msg="页面已过期，请刷新后重新操作。",
                flash_type="error",
                **params,
            )
        return _web_redirect(
            "/web/pending",
            selected_id,
            msg="页面已过期，请刷新后重新操作。",
            flash_type="error",
            **return_context_params("pending", return_filter=return_context.return_filter),
        )
    actor_account_id, _ = resolve_web_actor(db, request, selected_id)
    try:
        submit_expense_rejection(
            db,
            operation="undo_expense",
            expense_id=expense_id,
            tenant_id=selected_id,
            expected_row_version=parsed,
            request_expected_row_version=parsed,
            idempotency_key=idempotency_key,
            actor_account_id=actor_account_id,
        )
        message, flash_type = "已撤销原来的忽略操作，请以账单当前状态为准。", "success"
    except AppError as exc:
        db.rollback()
        if exc.error == "expense_not_found":
            exc = AppError(exc.error, "这次忽略当前无法撤销，请查看账单状态；原提交仍保留。", status_code=exc.status_code)
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=fields, task="原撤销操作仍保留", error=exc)
    except SQLAlchemyError as exc:
        retain_handled_error(request, exc)
        db.rollback()
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=fields, task="核实原撤销操作", error=AppError("internal_error",
                "暂时无法确认撤销结果。原提交仍保留，恢复连接后请核实这次操作。", status_code=503))
    origin = return_context.as_kwargs()
    if origin.get("return_to") == "recurring_occurrence":
        path = resolve_return_to("recurring_occurrence", "/web/pending", **origin)
        params = return_context_params(**origin)
        return _web_redirect(path, selected_id, msg=message, flash_type=flash_type, **params)
    return _web_redirect("/web/pending", selected_id, msg=message, flash_type=flash_type,
        **return_context_params("pending", return_filter=return_context.return_filter))
