"""A period's explicit payment selection and undo through the Planning owner."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import Expense
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas._recurring_occurrence import RecurringOccurrenceWriteRequest
from app.services.recurring_occurrence_command import set_occurrence_payment
from app.services.recurring_occurrence_query import eligible_payment_query, occurrence_period, occurrence_response
from app.services.recurring_service import get_recurring_item
from app.services.spending_contract_service import (
    accounting_datetime_label,
    month_bounds_utc,
    stat_time,
    stat_time_expr,
)

router = APIRouter()


def _payments(db, *, ledger_id, month, query, currency):
    statement = eligible_payment_query(tenant_id=ledger_id)
    if month:
        start, end = month_bounds_utc(month)
        statement = statement.where(stat_time_expr() >= start, stat_time_expr() < end)
    if query:
        statement = statement.where(or_(
            Expense.merchant.contains(query, autoescape=True),
            Expense.note.contains(query, autoescape=True),
        ))
    rows = db.scalars(statement.order_by(stat_time_expr().desc(), Expense.id.desc()).limit(101)).all()
    return [{
        "public_id": row.public_id, "id": row.id, "row_version": row.row_version,
        "merchant": row.merchant or "未填写商家",
        "amount": _amount_yuan(row.amount_cents, currency),
        "date": accounting_datetime_label(stat_time(row), pattern="%Y-%m-%d"),
        "key": uuid4().hex,
    } for row in rows[:100]], len(rows) > 100


def _page(
    request, db, *, public_id, ledger_id, month=None, payment_month=None,
    query="", message=None, error=None, retry=None,
):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    item = get_recurring_item(db, tenant_id=selected, public_id=public_id)
    period = occurrence_period(month)
    occurrence = occurrence_response(db, item=item, period=period)
    context = _base_ctx(
        request, db=db, options=options, selected_ledger_id=selected, page_title="本期固定支出",
    )
    selected_payment_month = occurrence.period if payment_month is None else payment_month
    payments, limited = _payments(
        db, ledger_id=selected, month=selected_payment_month, query=query,
        currency=context["home_currency_code"],
    )
    context.update(
        item=item, occurrence=occurrence, payments=payments, limited=limited,
        payment_month=selected_payment_month, query=query,
        planned_amount=_amount_yuan(occurrence.planned_amount_cents, context["home_currency_code"]),
        paid_amount=_amount_yuan(occurrence.paid_amount_cents, context["home_currency_code"]),
        can_associate=context["can_write"] and item.status != "archived",
        command_key=uuid4().hex, message=message, error=error, retry=retry,
    )
    return templates.TemplateResponse(
        request=request, name="recurring_occurrence.html", context=context,
        status_code=error.status_code if error else 200,
    )


@router.get("/{public_id}/occurrence", response_class=HTMLResponse)
def web_recurring_occurrence(
    request: Request, public_id: str, ledger_id: str | None = None,
    month: str | None = None, payment_month: str | None = None,
    q: str = Query(default="", max_length=150), message: str | None = None,
    _local: None = LocalOnly, db: Session = Depends(get_db),
):
    return _page(
        request, db, public_id=public_id, ledger_id=ledger_id, month=month,
        payment_month=payment_month, query=q.strip(), message=message,
    )


@router.post("/{public_id}/occurrence", response_class=HTMLResponse)
def web_set_recurring_occurrence(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), month: str = Form(default=""),
    action: str = Form(default=""), expense_public_id: str = Form(default=""),
    expected_expense_row_version: str = Form(default=""),
    expected_row_version: str = Form(default=""), expected_series_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    _local: None = LocalOnly, db: Session = Depends(get_db),
):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected)
    actor_id, _ = resolve_web_actor(db, request, selected)
    attempt = {
        "action": action, "expense_public_id": expense_public_id,
        "expected_expense_row_version": expected_expense_row_version,
        "expected_row_version": expected_row_version,
        "expected_series_row_version": expected_series_row_version,
        "idempotency_key": idempotency_key,
    }
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
            month=month, error=error, retry=attempt,
        )
    return _web_redirect(
        f"/web/recurring/{public_id}/occurrence", selected, month=month,
        message="这次提交已处理，下方显示本期当前状态。",
    )
