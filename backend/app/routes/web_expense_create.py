"""Native Web adapter for the existing manual-expense command owner."""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_accounting_time import (
    accounting_time_form_fields,
    parse_web_accounting_time,
    submitted_time_form_values,
    time_form_projection,
    time_form_values,
)
from app.routes._web_expense_form import (
    parse_amount_yuan,
    parse_expense_time_local,
    web_form_error_status,
)
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    edit_context_params,
    expense_return_form_context,
    expense_return_query_context,
    flow_href,
    return_href,
    return_label,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    templates,
)
from app.schemas import ExpenseManualCreateRequest
from app.services.category_service import list_ledger_category_options
from app.services.currency_common import (
    minor_amount_value,
    normalize_currency_code,
    supported_currency_codes,
)
from app.services.expense_service import create_manual_expense
from app.services.ledger_calendar_service import current_calendar
from app.services.manual_expense_draft_presenter import manual_draft_scope
from app.services.recurring_service import get_recurring_item
from app.services.time_service import now_utc
from app.tenants import AuthContext

router = APIRouter(prefix="/web/expenses", tags=["web"])


def _manual_expense_context(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    form_ledger_id: str,
    form_device_public_id: str,
    values: dict[str, str] | None = None,
    client_ref: str | None = None,
    error: str | None = None,
    draft_result: str = "",
    review_expense_id: int | None = None,
    return_context: ExpenseReturnContext | None = None,
) -> dict:
    context = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="手动记一笔",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    home = context["home_currency_code"]
    current_values = values or {}
    if draft_result:
        time_values = submitted_time_form_values(current_values, wall_time_field="spent_at")
    else:
        time_values = time_form_values(SimpleNamespace(expense_time=now_utc()),
            current_calendar(db, ledger_id=selected_id))
        # A new instant has no user-selected accounting-date override.
        time_values["accounting_date"] = ""
    context["time_form"] = time_form_projection(time_values) if time_values is not None else None
    origin = (return_context or ExpenseReturnContext()).as_kwargs()
    return_fields = edit_context_params(**origin)
    for name in (
        "return_to",
        "return_month",
        "return_recurring_public_id",
        "return_payment_expense_id",
    ):
        return_fields.setdefault(name, origin.get(name, ""))
    context.update(
        {
            "category_options": list_ledger_category_options(
                db,
                tenant_id=selected_id,
            ),
            "client_ref": client_ref or uuid4().hex,
            "form_home_currency_code": current_values.get("home_currency_code", home),
            "currency_options": [
                home,
                *sorted(supported_currency_codes() - {home}),
            ],
            "form_error": error,
            "form_ledger_id": form_ledger_id,
            "form_device_public_id": form_device_public_id,
            "manual_draft_scope": manual_draft_scope(db, _session_writer_auth(request, selected_id)),
            "manual_draft_result": draft_result,
            "manual_review_href": (
                flow_href(
                    f"/web/expenses/{review_expense_id}/edit",
                    ledger_id=selected_id,
                    **replace(return_context or ExpenseReturnContext(), return_payment_expense_id=str(review_expense_id)).as_kwargs(),
                )
                if type(review_expense_id) is int and review_expense_id > 0 else None
            ),
            "spent_at": current_values.get("spent_at", time_values["wall_time"] if time_values else ""),
            "values": current_values,
            "edit_return_fields": return_fields,
            "edit_return_href": (
                return_href(ledger_id=selected_id, default_path="/web/confirmed", **origin)
                if return_fields else f"/web/confirmed?ledger_id={selected_id}"
            ),
            "edit_return_label": return_label(origin.get("return_to", ""), default="返回流水"),
        }
    )
    return context


def _session_writer_auth(request: Request, selected_id: str) -> AuthContext:
    auth = getattr(request.state, "web_session_auth", None)
    if auth is None:
        raise AppError(
            "invalid_token",
            "手动记账需要先建立当前浏览器的设备身份。",
            status_code=401,
        )
    if auth.ledger_id != selected_id:
        raise AppError("permission_denied", status_code=403)
    return auth


def _require_manual_form_binding(
    auth: AuthContext,
    *,
    ledger_id: str,
    expected_device_public_id: str,
) -> None:
    if expected_device_public_id != auth.device_public_id:
        raise AppError(
            "session_binding_changed",
            "浏览器身份已更新，这笔支出尚未保存。输入已保留，请先核对已有流水，再打开新表单记账。",
            status_code=409,
        )
    if ledger_id != auth.ledger_id:
        raise AppError(
            "ledger_target_changed",
            "账本已切换，这笔支出尚未保存。输入已保留，请切回原账本后重试。",
            status_code=409,
        )


def _manual_expense_time_payload(spent_at: str, time_fields: dict[str, str] | None) -> dict:
    """Choose one wire representation, preserving the old draft's timestamp alias."""
    if time_fields is not None:
        return {"time_input": parse_web_accounting_time(spent_at, time_fields)}
    parsed_time, time_error = parse_expense_time_local(spent_at)
    if time_error or parsed_time is None:
        raise AppError(
            "invalid_request",
            time_error or "请填写发生时间。",
            status_code=422,
        )
    return {"spent_at": parsed_time}


def _manual_expense_payload(
    *,
    amount_major: str,
    currency_code: str,
    merchant: str,
    category: str,
    note: str,
    spent_at: str,
    client_ref: str,
    home_currency: str,
    time_fields: dict[str, str] | None = None,
) -> ExpenseManualCreateRequest:
    if not home_currency:
        raise AppError("manual_currency_context_required", "这份旧草稿缺少记账币种，输入仍保留。请先核对已有流水，再用新表单确认这笔支出。", status_code=409)
    home_currency = normalize_currency_code(home_currency)
    code = normalize_currency_code(currency_code)
    amount_minor, amount_error = parse_amount_yuan(
        amount_major,
        currency_code=code,
    )
    if amount_error:
        raise AppError("amount_invalid", amount_error, status_code=422)
    if amount_minor is None:
        raise AppError("amount_required", status_code=422)
    time_payload = _manual_expense_time_payload(spent_at, time_fields)
    clean_ref = (client_ref or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", clean_ref):
        raise AppError(
            "invalid_request",
            "这张表单已失效，请刷新页面后重试。",
            status_code=422,
        )
    common = {
        "merchant": (merchant or "").strip() or None,
        "category": (category or "").strip() or None,
        "note": (note or "").strip() or None,
        **time_payload,
        "client_ref": clean_ref,
        "home_currency_code": home_currency,
    }
    if code == home_currency:
        return ExpenseManualCreateRequest(
            amount_cents=amount_minor,
            **common,
        )
    return ExpenseManualCreateRequest(
        original_currency=code,
        original_amount=Decimal((amount_major or "").strip()),
        **common,
    )


@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def web_manual_expense_new(
    request: Request,
    ledger_id: str | None = None,
    return_context: ExpenseReturnContext = Depends(expense_return_query_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    auth = _session_writer_auth(request, selected_id)
    return templates.TemplateResponse(
        request=request,
        name="expense_new.html",
        context=_manual_expense_context(
            request,
            db,
            options=options,
            selected_id=selected_id,
            form_ledger_id=selected_id,
            form_device_public_id=auth.device_public_id,
            values=_recurring_commitment_values(db, selected_id, return_context),
            return_context=return_context,
        ),
    )


def _recurring_commitment_values(
    db: Session,
    selected_id: str,
    return_context: ExpenseReturnContext,
) -> dict[str, str]:
    series_id = (return_context.return_recurring_public_id or "").strip()
    if not series_id:
        return {}
    try:
        item = get_recurring_item(db, tenant_id=selected_id, public_id=series_id)
    except AppError:
        return {}
    values: dict[str, str] = {}
    if item.merchant_name:
        values["merchant"] = item.merchant_name
    raw_currency = (item.home_currency_code or "").strip()
    if not raw_currency:
        values["currency_unspecified"] = "1"
        return values
    try:
        currency = normalize_currency_code(raw_currency)
    except AppError:
        values["currency_unspecified"] = "1"
        return values
    values["currency_code"] = currency
    if item.baseline_amount_cents is not None:
        values["amount_major"] = minor_amount_value(item.baseline_amount_cents, currency)
    return values


def _manual_expense_failure(exc: AppError | ValidationError | InvalidOperation) -> tuple[str, int, str]:
    """Only a definite validation refusal reopens an immutable submitted draft."""
    if not isinstance(exc, AppError):
        return "请检查金额、币种和发生时间。", 422, "rejected"
    status = web_form_error_status(exc)
    result = "rejected" if status == 422 and exc.error != "idempotency_key_reused" else "blocked"
    return exc.message, status, result


@router.post("/new", include_in_schema=False)
def web_manual_expense_create(
    request: Request,
    ledger_id: str = Form(default=""),
    expected_device_public_id: str = Form(default=""),
    client_ref: str = Form(default=""),
    amount_major: str = Form(default=""),
    currency_code: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    spent_at: str = Form(default=""),
    note: str = Form(default=""),
    csrf_token: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    time_fields: dict[str, str] | None = Depends(accounting_time_form_fields),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    auth = _session_writer_auth(request, selected_id)
    values = {
        "amount_major": amount_major,
        "currency_code": currency_code,
        "home_currency_code": home_currency_code,
        "merchant": merchant,
        "category": category,
        "spent_at": spent_at,
        "note": note,
    }
    if time_fields is not None:
        values.update(time_fields)
    if not currency_code.strip():
        values["currency_unspecified"] = "1"
    try:
        _require_manual_form_binding(
            auth,
            ledger_id=ledger_id,
            expected_device_public_id=expected_device_public_id,
        )
        _require_selected_ledger_write(options, selected_id)
        payload = _manual_expense_payload(
            amount_major=amount_major,
            currency_code=currency_code,
            merchant=merchant,
            category=category,
            note=note,
            spent_at=spent_at,
            client_ref=client_ref,
            home_currency=home_currency_code,
            time_fields=time_fields,
        )
        created = create_manual_expense(db, payload, auth)
    except (AppError, ValidationError, InvalidOperation) as exc:
        db.rollback()
        message, status_code, draft_result = _manual_expense_failure(exc)
        review_id = (
            (exc.details or {}).get("expense_id")
            if isinstance(exc, AppError) and exc.error == "manual_create_original_requires_review" else None
        )
        return templates.TemplateResponse(
            request=request,
            name="expense_new.html",
            context=_manual_expense_context(
                request,
                db,
                options=_list_ledger_options(db),
                selected_id=selected_id,
                values=values,
                client_ref=client_ref,
                error=message,
                form_ledger_id=ledger_id,
                form_device_public_id=expected_device_public_id,
                draft_result=draft_result,
                review_expense_id=review_id,
                return_context=return_context,
            ),
            status_code=status_code,
        )
    return_fields = edit_context_params(**return_context.as_kwargs())
    if return_fields.get("return_to") == "recurring_occurrence":
        return_fields = edit_context_params(
            **replace(return_context, return_payment_expense_id=str(created.id)).as_kwargs()
        )
        return _web_redirect(
            f"/web/expenses/{created.id}/edit",
            selected_id,
            **return_fields,
        )
    return_to = "pending" if created.status == "pending" else "confirmed"
    return _web_redirect(
        f"/web/expenses/{created.id}/edit",
        selected_id,
        return_to=return_to,
    )
