"""Web pending-expense lifecycle commands: confirm, reject, and reject undo."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_confirmed_write_guard import confirmed_write_guard_response
from app.routes._web_expense_confirm_command import confirm_web_expense
from app.routes._web_expense_edit_form import WebExpenseEditForm, web_expense_edit_form
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_expense_helpers import confirm_reject_error, drawer_fragment_ok
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    expense_return_form_context,
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
)
from app.services.expense_service import reject_expense, undo_reject_expense

router = APIRouter(prefix="/web", tags=["web"])


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
    _require_selected_ledger_write(options, selected_id)
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
    if form.fragment:
        return drawer_fragment_ok("confirm")
    return_context = form.return_context
    return _web_redirect(
        return_context.resolve_path("/web/pending"),
        selected_id,
        **return_context_params(**{**return_context.as_kwargs(), "return_to": return_context.return_to or "pending"}),
    )


def _reject_error(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    message: str,
    fragment: int,
    status_code: int,
    return_context: ExpenseReturnContext,
) -> Response:
    return confirm_reject_error(
        db,
        request,
        options,
        selected_id,
        expense_id,
        message,
        fragment,
        status_code=status_code,
        return_context=return_context,
    )


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    guarded = confirmed_write_guard_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        error_code="expense_reversal_required",
        fragment=bool(fragment),
        return_context=return_context,
    )
    if guarded is not None:
        return guarded
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _reject_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            "页面已过期，请刷新后重新操作。",
            fragment,
            422,
            return_context,
        )
    try:
        reject_expense(db, expense_id, selected_id, expected_row_version=parsed)
    except AppError as exc:
        db.rollback()
        message = "账单已在其它端被修改，请刷新后重新操作。" if exc.error == "state_conflict" else exc.message
        return _reject_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            message,
            fragment,
            web_form_error_status(exc),
            return_context,
        )
    if fragment:
        return drawer_fragment_ok("reject")
    origin = return_context if return_context.return_to == "recurring_occurrence" else ExpenseReturnContext(
        return_to="pending", return_filter=return_context.return_filter)
    return _web_redirect(
        origin.resolve_path("/web/pending"),
        selected_id,
        msg="已忽略这笔账单。",
        undo=str(expense_id),
        flash_type="success",
        **return_context_params(**origin.as_kwargs()),
    )


@router.post("/expenses/{expense_id}/undo", response_class=HTMLResponse)
def web_expense_undo(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            return_context.resolve_path("/web/pending"),
            selected_id,
            msg="页面已过期，请刷新后重新操作。",
            flash_type="error",
            **return_context_params(**return_context.as_kwargs()),
        )
    try:
        undo_reject_expense(db, expense_id, selected_id, parsed)
        message, flash_type = "已撤销，账单已恢复待确认。", "success"
    except AppError:
        message = "无法撤销：账单已超过 5 分钟保留窗口，或已被清理。"
        flash_type = "error"
    return _web_redirect(return_context.resolve_path("/web/pending"), selected_id,
        msg=message, flash_type=flash_type, **return_context_params(**return_context.as_kwargs()))
