"""A period's explicit payment selection and undo through the Planning owner."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import Expense
from app.routes._web_expense_return_context import (
    _payment_expense_id,
    edit_context_params,
    flow_href,
)
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
from app.services.recurring_occurrence_query import (
    eligible_payment_query,
    find_recurring_payments,
    occurrence_period,
    occurrence_response,
)
from app.services.expense_service import fetch_expense_row_version_in_status
from app.services.recurring_service import get_recurring_item
from app.services.spending_contract_service import (
    accounting_datetime_label,
    stat_time,
)

router = APIRouter()


def _occurrence_origin(item, occurrence, payment_id=None) -> dict[str, str]:
    origin = edit_context_params(
        return_to="recurring_occurrence",
        return_recurring_public_id=item.public_id,
        return_month=occurrence.period,
        return_payment_expense_id="" if payment_id is None else str(payment_id),
    )
    return origin or {}


def _payment_edit_href(*, ledger_id: str, expense_id: int, item, occurrence) -> str:
    return flow_href(
        f"/web/expenses/{expense_id}/edit",
        ledger_id=ledger_id,
        **_occurrence_origin(item, occurrence, expense_id),
    )


def _payment_view(row, *, ledger_id, item, occurrence) -> dict[str, object]:
    return {
        "public_id": row.public_id, "id": row.id, "row_version": row.row_version,
        "merchant": row.merchant or "未填写商家",
        "home_currency_code": row.home_currency_code,
        "amount": _amount_yuan(row.amount_cents, row.home_currency_code) if row.home_currency_code else "币种待确认",
        "date": accounting_datetime_label(stat_time(row), pattern="%Y-%m-%d"),
        "key": uuid4().hex,
        "href": _payment_edit_href(
            ledger_id=ledger_id, expense_id=row.id, item=item, occurrence=occurrence,
        ),
    }


def _payments(db, *, ledger_id, month, query, item, occurrence):
    rows = find_recurring_payments(db, tenant_id=ledger_id, month=month, query=query)
    return [
        _payment_view(row, ledger_id=ledger_id, item=item, occurrence=occurrence)
        for row in rows[:100]
    ], len(rows) > 100


def _occurrence_reject_undo(db, *, selected_id: str, undo: str | None) -> tuple[int | None, int | None]:
    if not undo or not undo.isdigit():
        return None, None
    candidate = int(undo)
    row_version = fetch_expense_row_version_in_status(
        db, expense_id=candidate, tenant_id=selected_id, status="rejected",
    )
    if row_version is None:
        return None, None
    return candidate, row_version


def _focused_payment(db, *, ledger_id, payment_id, item, occurrence) -> dict[str, object] | None:
    if not _payment_expense_id(payment_id):
        return None
    expense = resolve_expense(db, ledger_id, int(payment_id))
    if expense is None or expense.status not in {"pending", "confirmed", "rejected"}:
        return None
    eligible = db.scalar(
        eligible_payment_query(tenant_id=ledger_id).where(Expense.id == expense.id).limit(1)
    )
    return {
        **_payment_view(expense, ledger_id=ledger_id, item=item, occurrence=occurrence),
        "eligible": eligible is not None,
    }


def _page(
    request: Request, db: Session, *, public_id: str, ledger_id: str | None, month=None, payment_month=None,
    query="", message=None, error=None, retry=None, payment_id=None, undo=None, flash_type=None,
) -> HTMLResponse:
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
        item=item, occurrence=occurrence,
    )
    focused = _focused_payment(
        db, ledger_id=selected, payment_id=payment_id, item=item, occurrence=occurrence,
    )
    can_associate = context["can_write"] and item.status != "archived"
    context.update(
        item=item, occurrence=occurrence,
        payments=[payment for payment in payments if not focused or payment["id"] != focused["id"]],
        focused_payment=focused, limited=limited,
        payment_month=selected_payment_month, query=query,
        planned_amount=_amount_yuan(occurrence.planned_amount_cents, occurrence.home_currency_code) if occurrence.home_currency_code else "币种待确认",
        paid_amount=_amount_yuan(occurrence.paid_amount_cents, occurrence.paid_home_currency_code) if occurrence.paid_home_currency_code else "币种待确认",
        can_associate=can_associate,
        record_payment_href=(
            flow_href(
                "/web/expenses/new",
                ledger_id=selected,
                **_occurrence_origin(item, occurrence),
            )
            if can_associate and occurrence.state == "unfulfilled" else None
        ),
        linked_payment_href=(
            _payment_edit_href(
                ledger_id=selected, expense_id=occurrence.expense_id, item=item, occurrence=occurrence,
            )
            if occurrence.expense_id else None
        ),
        command_key=uuid4().hex, error=error, retry=retry,
        flash_message=message or "",
        flash_type=flash_type if flash_type in {"success", "error"} else ("success" if message else ""),
        undo_expense_id=None, undo_expected_row_version=None, undo_idempotency_key="",
    )
    undo_expense_id, undo_expected_row_version = _occurrence_reject_undo(
        db, selected_id=selected, undo=undo,
    )
    context["undo_expense_id"] = undo_expense_id
    context["undo_expected_row_version"] = undo_expected_row_version
    context["undo_idempotency_key"] = str(uuid4()) if undo_expense_id is not None else ""
    return templates.TemplateResponse(
        request=request, name="recurring_occurrence.html", context=context,
        status_code=error.status_code if error else 200,
    )


@router.get("/{public_id}/occurrence", response_class=HTMLResponse)
def web_recurring_occurrence(
    request: Request, public_id: str, ledger_id: str | None = None,
    month: str | None = None, payment_month: str | None = None,
    q: str = Query(default="", max_length=150), message: str | None = None,
    msg: str | None = None, flash_type: str | None = None, undo: str | None = None,
    payment_id: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
):
    return _page(
        request, db, public_id=public_id, ledger_id=ledger_id, month=month,
        payment_month=payment_month, query=q.strip(), message=message or msg,
        payment_id=payment_id, undo=undo, flash_type=flash_type,
    )


@router.post("/{public_id}/occurrence", response_class=HTMLResponse)
def web_set_recurring_occurrence(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), month: str = Form(default=""),
    action: str = Form(default=""), expense_public_id: str = Form(default=""),
    expected_expense_row_version: str = Form(default=""),
    expected_row_version: str = Form(default=""), expected_series_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""), payment_id: str = Form(default=""),
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
        fields={**attempt, "ledger_id": ledger_id, "month": month}, task="关联固定支出付款")
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
        f"/web/recurring/{public_id}/occurrence", selected, month=month,
        message="这次提交已处理，下方显示本期当前状态。",
    )
