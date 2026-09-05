"""Native Web adapter for the existing manual-expense command owner."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_form import (
    parse_amount_yuan,
    parse_expense_time_local,
    web_form_error_status,
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
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import (
    normalize_currency_code,
    supported_currency_codes,
)
from app.services.expense_service import create_manual_expense
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc
from app.tenants import AuthContext

router = APIRouter(prefix="/web/expenses", tags=["web"])


def _manual_expense_context(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    values: dict[str, str] | None = None,
    client_ref: str | None = None,
    error: str | None = None,
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
    context.update(
        {
            "category_options": list_ledger_category_options(
                db,
                tenant_id=selected_id,
            ),
            "client_ref": client_ref or uuid4().hex,
            "currency_options": [
                home,
                *sorted(supported_currency_codes() - {home}),
            ],
            "form_error": error,
            "spent_at": current_values.get("spent_at")
            or now_utc()
            .astimezone(accounting_zone())
            .strftime("%Y-%m-%dT%H:%M"),
            "values": current_values,
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
) -> ExpenseManualCreateRequest:
    code = normalize_currency_code(currency_code)
    amount_minor, amount_error = parse_amount_yuan(
        amount_major,
        currency_code=code,
    )
    if amount_error:
        raise AppError("amount_invalid", amount_error, status_code=422)
    if amount_minor is None:
        raise AppError("amount_required", status_code=422)
    parsed_time, time_error = parse_expense_time_local(spent_at)
    if time_error or parsed_time is None:
        raise AppError(
            "invalid_request",
            time_error or "请填写发生时间。",
            status_code=422,
        )
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
        "spent_at": parsed_time,
        "client_ref": clean_ref,
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


@router.get("/new", response_class=HTMLResponse)
def web_manual_expense_new(
    request: Request,
    ledger_id: str | None = None,
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
    _session_writer_auth(request, selected_id)
    return templates.TemplateResponse(
        request=request,
        name="expense_new.html",
        context=_manual_expense_context(
            request,
            db,
            options=options,
            selected_id=selected_id,
        ),
    )


@router.post("/new")
def web_manual_expense_create(
    request: Request,
    ledger_id: str = Form(default=""),
    client_ref: str = Form(default=""),
    amount_major: str = Form(default=""),
    currency_code: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    spent_at: str = Form(default=""),
    note: str = Form(default=""),
    csrf_token: str = Form(default=""),
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
    _require_selected_ledger_write(options, selected_id)
    auth = _session_writer_auth(request, selected_id)
    values = {
        "amount_major": amount_major,
        "currency_code": currency_code,
        "merchant": merchant,
        "category": category,
        "spent_at": spent_at,
        "note": note,
    }
    try:
        payload = _manual_expense_payload(
            amount_major=amount_major,
            currency_code=currency_code,
            merchant=merchant,
            category=category,
            note=note,
            spent_at=spent_at,
            client_ref=client_ref,
            home_currency=require_runtime_home_currency_code(db),
        )
        created = create_manual_expense(db, payload, auth)
    except (AppError, ValidationError, InvalidOperation) as exc:
        if isinstance(exc, AppError):
            message = exc.message
            status_code = web_form_error_status(exc)
        else:
            message = "请检查金额、币种和发生时间。"
            status_code = 422
        return templates.TemplateResponse(
            request=request,
            name="expense_new.html",
            context=_manual_expense_context(
                request,
                db,
                options=options,
                selected_id=selected_id,
                values=values,
                client_ref=client_ref,
                error=message,
            ),
            status_code=status_code,
        )
    return_to = "pending" if created.status == "pending" else "confirmed"
    return _web_redirect(
        f"/web/expenses/{created.id}/edit",
        selected_id,
        return_to=return_to,
    )
