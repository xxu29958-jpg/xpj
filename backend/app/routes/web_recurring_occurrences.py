"""A period's explicit payment selection and undo through the Planning owner."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_return_context import flow_href
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.schemas._recurring_occurrence import RecurringOccurrenceWriteRequest
from app.services.expense_query import resolve_expense
from app.services.recurring_occurrence_command import set_occurrence_payment
from app.services.recurring_occurrence_query import find_recurring_payments, occurrence_period, occurrence_response
from app.services.recurring_service import get_recurring_item
from app.services.spending_contract_service import (
    accounting_datetime_label,
    stat_time,
)

router = APIRouter()


def _payment_view(row, *, ledger_id, origin):
    currency = row.original_currency_code or row.home_currency_code
    amount = row.original_amount_minor if row.original_currency_code else row.amount_cents
    return {
        "public_id": row.public_id, "id": row.id, "row_version": row.row_version, "status": row.status,
        "merchant": row.merchant or "未填写商家",
        "home_currency_code": currency,
        "amount": _amount_yuan(amount, currency) if currency else "币种待确认",
        "date": accounting_datetime_label(stat_time(row), pattern="%Y-%m-%d"),
        "key": uuid4().hex,
        "href": flow_href(f"/web/expenses/{row.id}/edit", ledger_id=ledger_id,
            **origin, return_payment_expense_id=str(row.id)),
    }


def _payments(db, *, ledger_id, month, query, origin):
    rows = find_recurring_payments(db, tenant_id=ledger_id, month=month, query=query)
    return [_payment_view(row, ledger_id=ledger_id, origin=origin) for row in rows[:100]], len(rows) > 100


def _focused_payment(db, *, ledger_id, payment_id, origin):
    if not payment_id or not str(payment_id).isascii() or not str(payment_id).isdigit():
        return None
    if len(str(payment_id)) > 10 or not 0 < int(payment_id) <= 2_147_483_647:
        return None
    expense = resolve_expense(db, ledger_id, int(payment_id))
    if expense is None or expense.status not in {"pending", "confirmed", "rejected"}:
        return None
    return {
        **_payment_view(expense, ledger_id=ledger_id, origin=origin),
        "eligible": bool(find_recurring_payments(db, tenant_id=ledger_id, month=None, query="", expense_id=expense.id)),
        "return_fields": {**origin, "return_payment_expense_id": str(expense.id)},
    }


def _page(
    request: Request, db: Session, *, public_id: str, ledger_id: str | None, month=None, payment_month=None,
    query="", message=None, error=None, retry=None, payment_id=None,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    item = get_recurring_item(db, tenant_id=selected, public_id=public_id)
    period = occurrence_period(month)
    occurrence = occurrence_response(db, item=item, period=period)
    origin = {"return_to": "recurring_occurrence", "return_recurring_public_id": item.public_id,
        "return_month": occurrence.period}
    context = _base_ctx(
        request, db=db, options=options, selected_ledger_id=selected, page_title="本期固定支出",
    )
    selected_payment_month = occurrence.period if payment_month is None else payment_month
    payments, limited = _payments(
        db, ledger_id=selected, month=selected_payment_month, query=query, origin=origin,
    )
    focused = _focused_payment(db, ledger_id=selected, payment_id=payment_id, origin=origin)
    context.update(
        item=item, occurrence=occurrence,
        payments=[payment for payment in payments if not focused or payment["id"] != focused["id"]],
        focused_payment=focused, limited=limited,
        record_payment_href=flow_href("/web/expenses/new", ledger_id=selected, **origin),
        linked_payment_href=flow_href(f"/web/expenses/{occurrence.expense_id}/edit", ledger_id=selected,
            **origin, return_payment_expense_id=str(occurrence.expense_id)) if occurrence.expense_id else None,
        payment_month=selected_payment_month, query=query,
        planned_amount=_amount_yuan(occurrence.planned_amount_cents, occurrence.home_currency_code) if occurrence.home_currency_code else "币种待确认",
        paid_amount=_amount_yuan(occurrence.paid_amount_cents, occurrence.paid_home_currency_code) if occurrence.paid_home_currency_code else "币种待确认",
        can_associate=context["can_write"] and item.status != "archived",
        command_key=uuid4().hex, message=message or request.query_params.get("msg"),
        message_is_error=request.query_params.get("flash_type") == "error", error=error, retry=retry,
    )
    return templates.TemplateResponse(
        request=request, name="recurring_occurrence.html", context=context,
        status_code=error.status_code if error else 200,
    )


@router.get("/{public_id}/occurrence", response_class=HTMLResponse)
def web_recurring_occurrence(
    request: Request, public_id: str, ledger_id: str | None = None,
    month: str | None = None, payment_month: str | None = None,
    q: str = Query(default="", max_length=150), message: str | None = None, payment_id: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
):
    return _page(
        request, db, public_id=public_id, ledger_id=ledger_id, month=month,
        payment_month=payment_month, query=q.strip(), message=message, payment_id=payment_id,
    )


@router.post("/{public_id}/occurrence", response_class=HTMLResponse)
def web_set_recurring_occurrence(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), month: str = Form(default=""),
    action: str = Form(default=""), expense_public_id: str = Form(default=""),
    expected_expense_row_version: str = Form(default=""),
    expected_row_version: str = Form(default=""), expected_series_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    payment_id: str = Form(default=""),
    _local: None = LocalOnly, db: Session = Depends(get_db),
):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    attempt = {
        "action": action, "expense_public_id": expense_public_id,
        "expected_expense_row_version": expected_expense_row_version,
        "expected_row_version": expected_row_version,
        "expected_series_row_version": expected_series_row_version,
        "idempotency_key": idempotency_key,
    }
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={**attempt, "ledger_id": ledger_id, "month": month, "payment_id": payment_id}, task="关联固定支出付款")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    actor_id, _ = resolve_web_actor(db, request, selected)
    try:
        if action not in {"link", "clear"}:
            raise AppError("invalid_request", status_code=422)
        payload = RecurringOccurrenceWriteRequest(
            action=action,
            expense_public_id=expense_public_id if action == "link" else None,
            expected_expense_row_version=expected_expense_row_version if action == "link" else None,
            expected_row_version=expected_row_version,
            expected_series_row_version=expected_series_row_version,
        )
        set_occurrence_payment(
            db, tenant_id=selected, public_id=public_id, month=month,
            actor_account_id=actor_id, idempotency_key=idempotency_key, payload=payload,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        error = exc if isinstance(exc, AppError) else AppError(
            "invalid_request", "付款或页面版本不完整，请刷新并重新核对。", status_code=422,
        )
        return _page(
            request, db, public_id=public_id, ledger_id=selected,
            month=month, error=error, retry=attempt, payment_id=payment_id,
        )
    return _web_redirect(
        f"/web/recurring/{public_id}/occurrence", selected, month=month, payment_id=payment_id,
        message="这次提交已处理，下方显示本期当前状态。",
    )
