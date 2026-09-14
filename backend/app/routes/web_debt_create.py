"""HTML form adapter for creating an external/manual Debt."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_form import parse_expense_time_local
from app.routes._web_rate_recovery import _RATE_FIELDS, rate_recovery_context, rate_recovery_form, submit_recovery_rate
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.routes.web_debt_actions import _actor_account_id, _error_message
from app.routes.web_debts import _debt_create_context
from app.schemas import DebtCreateRequest
from app.services.currency_common import (
    major_amount_to_minor,
    normalize_currency_code,
)
from app.services.debt_command_service import create_debt_idempotently

router = APIRouter(prefix="/web/debts", tags=["web"])


def _positive_int_or_none(raw: str, *, label: str, maximum: int) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise AppError(
            "invalid_request",
            f"{label}必须是整数。",
            status_code=422,
        ) from exc
    if value < 1 or value > maximum:
        raise AppError(
            "invalid_request",
            f"{label}必须在 1 到 {maximum} 之间。",
            status_code=422,
        )
    return value


def _render_create_error(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    values: dict[str, str],
    message: str,
    status_code: int,
    rate_recovery: dict | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="debt_new.html",
        context={**_debt_create_context(
            request,
            db,
            options=options,
            selected_id=selected_id,
            values=values,
            error=message,
        ), "rate_recovery": rate_recovery, "rate_recovery_action": "/web/debts/rate"},
        status_code=status_code,
    )


def _create_payload(
    *,
    direction: str,
    counterparty_label: str,
    note: str,
    amount_major: str,
    currency_code: str,
    event_time: str,
    debt_kind: str,
    installment_count: str,
    installment_period_months: str,
    home_currency: str,
) -> DebtCreateRequest:
    code = normalize_currency_code(currency_code)
    amount_text = amount_major or ""
    amount_minor = major_amount_to_minor(amount_text, code)
    if amount_minor is None or amount_minor <= 0:
        raise AppError(
            "debt_amount_invalid",
            "本金必须大于 0。",
            status_code=422,
        )
    parsed_time, time_error = parse_expense_time_local(event_time)
    if time_error or parsed_time is None:
        raise AppError(
            "invalid_request",
            time_error or "请填写债务发生时间。",
            status_code=422,
        )
    return DebtCreateRequest(
        direction=(direction or "").strip(),
        home_currency_code=home_currency,
        counterparty_type="external",
        counterparty_label=(counterparty_label or "").strip(),
        # Native form encoding expands textarea newlines to CRLF.
        note=note.replace("\r\n", "\n").replace("\r", "\n"),
        principal_amount_cents=amount_minor if code == home_currency else None,
        original_currency=code if code != home_currency else None,
        original_amount=Decimal(amount_text) if code != home_currency else None,
        event_time=parsed_time,
        source_type="manual",
        debt_kind=(debt_kind or "").strip(),
        installment_count=_positive_int_or_none(
            installment_count,
            label="总期数",
            maximum=600,
        ),
        installment_period_months=_positive_int_or_none(
            installment_period_months,
            label="还款周期",
            maximum=120,
        ),
    )


@router.post("")
def web_create_debt(
    request: Request,
    ledger_id: str = Form(default=""),
    direction: str = Form(default=""),
    counterparty_label: str = Form(default=""),
    note: str = Form(default=""),
    amount_major: str = Form(default=""),
    currency_code: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    event_time: str = Form(default=""),
    debt_kind: str = Form(default="unspecified"),
    installment_count: str = Form(default=""),
    installment_period_months: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    values = {
        "direction": direction,
        "counterparty_label": counterparty_label,
        "note": note,
        "amount_major": amount_major,
        "currency_code": currency_code,
        "home_currency_code": home_currency_code,
        "event_time": event_time,
        "debt_kind": debt_kind,
        "installment_count": installment_count,
        "installment_period_months": installment_period_months,
        "idempotency_key": idempotency_key,
    }
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**values, "ledger_id": ledger_id}, task="保存原欠款")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    try:
        if not home_currency_code:
            raise AppError("invalid_request", "页面已更新，请核对金额、原币和记账币种后再次保存。", status_code=422)
        presentation_currency = normalize_currency_code(home_currency_code)
        payload = _create_payload(
            direction=direction,
            counterparty_label=counterparty_label,
            note=note,
            amount_major=amount_major,
            currency_code=currency_code,
            event_time=event_time,
            debt_kind=debt_kind,
            installment_count=installment_count,
            installment_period_months=installment_period_months,
            home_currency=presentation_currency,
        )
        created = create_debt_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            payload=payload,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError, InvalidOperation) as exc:
        db.rollback()
        if isinstance(exc, AppError):
            message = _error_message(exc)
            status_code = exc.status_code
            if exc.error == "idempotency_key_reused":
                values["idempotency_key"] = str(uuid4())
                message = "这个表单编号已使用。请先核对原记录；再次保存将新增一笔往来。"
        else:
            message = "请检查方向、对方、金额、币种、分期设置和往来说明（最多 500 字）。"
            status_code = 422
        return _render_create_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            values=values,
            message=message,
            status_code=status_code,
            rate_recovery=rate_recovery_context(db, selected_id, exc.details)
                if isinstance(exc, AppError) and exc.error == "exchange_rate_pending" else None,
        )
    return _web_redirect(f"/web/debts/{created.public_id}", selected_id)


@router.post("/rate")
def web_debt_rate(
    request: Request, original: dict[str, str] = Depends(rate_recovery_form),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, original.get("ledger_id"), options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=original, task="补汇率并继续原欠款")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    values = {key: original.get(f"fx_{key}", "") for key in _RATE_FIELDS}
    result = submit_recovery_rate(db, request, selected, values,
        review_latest=original.get("fx_review_latest") == "true")
    return _render_create_error(request, db, options=options, selected_id=selected,
        values=original, message="", status_code=result["status_code"], rate_recovery={**values, **result})
