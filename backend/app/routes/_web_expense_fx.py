"""Web presentation of the existing pending-bill FX task, with original form preservation."""

from dataclasses import asdict

from fastapi import Request
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_edit_form import WebExpenseEditForm
from app.routes._web_money_views import _expense_view
from app.routes._web_session_common import parse_form_row_version_token, resolve_web_actor
from app.routes.web_common import (
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    preserve_original_ledger_form,
    templates,
)
from app.services.expense_service._fx import PendingFxInput
from app.services.pending_fx_task_service import current_pending_expense_fx_tasks, request_pending_expense_fx


def expense_fx_view(db: Session, *, expense) -> dict | None:
    if not expense.original_currency_code or expense.original_currency_code == expense.home_currency_code:
        return None
    task = current_pending_expense_fx_tasks(db, tenant_id=expense.tenant_id, expenses=[expense]).get(expense.id)
    requested_date = expense.exchange_rate_date
    if task is not None:
        try:
            requested_date = PendingFxInput.model_validate_json(task.input_payload_json or "null").rate_date
        except ValueError:
            requested_date = None
    state = task.status if task is not None else "unrequested"
    return {"state": state, "requested_date": requested_date,
        "message": (task.error_message or task.progress_message or "") if task is not None else "",
        "current": _expense_view(expense),
        "can_request": expense.status == "pending" and expense.fx_status == "pending"
            and expense.original_amount_minor is not None and expense.exchange_rate_date is not None
            and state not in {"queued", "running"}}


def render_web_fx_action(db: Session, request: Request, expense_id: int, form: WebExpenseEditForm, *, start: bool):
    # Import lazily: edit context consumes the read-only FX presentation above.
    from app.routes._web_expense_helpers import web_edit_context

    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    values = {key: value or "" for key, value in asdict(form).items()
        if key not in {"ledger_id", "fragment", "return_context", "save_before_confirm"}}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={**values, **form.return_context.as_kwargs(), "ledger_id": form.ledger_id,
            "fragment": str(form.fragment), "save_before_confirm": "1" if form.save_before_confirm else "0"},
        task="刷新原账单汇率并保留填写")
    if retained is not None:
        return retained
    error, status = None, 200
    if start:
        _require_selected_ledger_write(options, selected)
        account_id, device_id = resolve_web_actor(db, request, selected)
        try:
            version = parse_form_row_version_token(form.expected_row_version)
            if version is None:
                raise AppError("invalid_request", "请载入账单后再获取汇率。", status_code=422)
            request_pending_expense_fx(db, tenant_id=selected, expense_id=expense_id,
                initiator_account_id=account_id, initiator_device_id=device_id, expected_row_version=version)
        except AppError as exc:
            db.rollback()
            error, status = exc.message, exc.status_code
    ctx = web_edit_context(db, request, options, selected, expense_id, form_values=values,
        return_context=form.return_context)
    ctx["error"] = error
    if ctx["expense"]["status"] != "pending":
        ctx["can_write"] = False
    return templates.TemplateResponse(request=request,
        name="_edit_drawer.html" if form.fragment else "edit.html", context=ctx, status_code=status)
