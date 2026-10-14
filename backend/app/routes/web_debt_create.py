"""HTML form adapter for creating an external/manual Debt."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_accounting_time import accounting_time_form_fields, parse_web_accounting_time
from app.routes._web_draft_binding import (
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    require_draft_binding,
)
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
from app.schemas import DebtCreateRequest, DebtResponse
from app.services.currency_common import (
    major_amount_to_minor,
    normalize_currency_code,
)
from app.services.debt_command_service import create_debt_idempotently

router = APIRouter(prefix="/web/debts", tags=["web"])


class DebtCreationForm(BaseModel):
    ledger_id: str = ""
    direction: str = ""
    counterparty_label: str = ""
    note: str = ""
    amount_major: str = ""
    currency_code: str = ""
    home_currency_code: str = ""
    event_time: str = ""
    debt_kind: str = "unspecified"
    installment_count: str = ""
    installment_period_months: str = ""
    idempotency_key: str = ""
    draft_scope: str = ""
    csrf_token: str = ""
    review_new: bool = False


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
    draft_result: str = "",
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
        ), "rate_recovery": rate_recovery, "rate_recovery_action": "/web/debts/rate",
            "debtcreation_native_result": draft_result},
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
    calendar_revision: str | None = None,
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
    if calendar_revision is not None:
        occurrence = {"time_input": parse_web_accounting_time(None, {
            "time_precision": "date_only", "calendar_revision": calendar_revision, "user_local_date": event_time,
        })}
    else:
        parsed_time, time_error = parse_expense_time_local(event_time)
        if time_error or parsed_time is None:
            raise AppError("invalid_request", time_error or "请填写债务发生时间。", status_code=422)
        occurrence = {"event_time": parsed_time}
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
        **occurrence,
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
    form: Annotated[DebtCreationForm, Form()],
    time_fields: dict[str, str] | None = Depends(accounting_time_form_fields),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    calendar_revision = time_fields.get("calendar_revision", "") if time_fields is not None else None
    values = form.model_dump(exclude={"csrf_token", "review_new"})
    if calendar_revision is not None:
        values["calendar_revision"] = calendar_revision
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields=values, task="保存原欠款")
    if retained is not None:
        return retained
    try:
        if form.draft_scope or "application/json" in request.headers.get("accept", ""):
            require_draft_binding(db, request, ledger_id=selected_id, draft_scope=form.draft_scope, require_session=False)
        _require_selected_ledger_write(options, selected_id)
        if form.review_new:
            return _render_create_error(request, db, options=options, selected_id=selected_id, values=values,
                message="原输入与提交编号已保留。核对后可修改；本次没有创建往来。", status_code=200, draft_result="prepared")
        if not form.home_currency_code:
            raise AppError("invalid_request", "页面已更新，请核对金额、原币和记账币种后再次保存。", status_code=422)
        payload = _create_payload(
            **form.model_dump(exclude={"ledger_id", "csrf_token", "review_new", "draft_scope", "idempotency_key", "home_currency_code"}),
            home_currency=normalize_currency_code(form.home_currency_code),
            calendar_revision=calendar_revision,
        )
        created = create_debt_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            payload=payload,
            idempotency_key=form.idempotency_key.strip(),
        )
    except (AppError, ValidationError, InvalidOperation) as exc:
        db.rollback()
        if isinstance(exc, AppError):
            message = _error_message(exc)
            status_code = exc.status_code
            if exc.error == "idempotency_key_reused":
                message = "这次输入与原提交不同。原编号已保留，请先打开原稿核实已有结果。"
        else:
            message = "请检查方向、对方、金额、币种、分期设置和往来说明（最多 500 字）。"
            status_code = 422
        refusal = exc if isinstance(exc, AppError) else AppError("invalid_request", message, status_code=status_code)
        if response := draft_error_response(request, AppError(refusal.error, message, status_code=status_code)):
            return response
        return _render_create_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            values=values,
            message=message,
            status_code=status_code,
            draft_result=draft_refusal_result(refusal),
            rate_recovery=rate_recovery_context(db, selected_id, refusal.details)
                if refusal.error == "exchange_rate_pending" else None,
        )
    return _creation_receipt_response(request, db, options=options, selected_id=selected_id,
        form=form, values=values, created=created)


def _creation_receipt_response(
    request: Request, db: Session, *, options, selected_id: str,
    form: DebtCreationForm, values: dict[str, str], created: DebtResponse,
) -> Response:
    """Both enhanced and native consumers receive the first accepted creation result."""
    destination = _web_redirect(f"/web/debts/{created.public_id}", selected_id).headers["location"]
    if response := draft_ack_response(request, draft_scope=form.draft_scope, idempotency_key=form.idempotency_key,
            receipt=created, next_href=destination):
        return response
    if form.draft_scope:
        return templates.TemplateResponse(request=request, name="debt_new.html", context={
            **_debt_create_context(request, db, options=options, selected_id=selected_id, values=values),
            "accepted_creation": created.model_dump(mode="json"), "creation_destination": destination,
        })
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
    try:
        if original.get("draft_scope"):
            require_draft_binding(db, request, ledger_id=selected, draft_scope=original["draft_scope"])
        _require_selected_ledger_write(options, selected)
    except AppError as exc:
        return preserve_original_ledger_form(request, db, options=options, selected=selected,
            fields=original, task="补汇率并继续原欠款", error=exc)
    values = {key: original.get(f"fx_{key}", "") for key in _RATE_FIELDS}
    result = submit_recovery_rate(db, request, selected, values,
        review_latest=original.get("fx_review_latest") == "true", fetch_reference=original.get("fx_fetch_reference") == "true")
    return _render_create_error(request, db, options=options, selected_id=selected,
        values=original, message="", status_code=result["status_code"], rate_recovery={**values, **result})
