"""Server-rendered manual expense creation for the independent Web product."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import parse_expense_time_local
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _parse_major_amount,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas import ExpenseManualCreateRequest
from app.services.expense_service import create_manual_expense
from app.services.ledger_service import build_loopback_owner_auth_context
from app.services.merchant_catalog_service import list_merchant_catalog
from app.services.spending_contract_service import accounting_zone
from app.services.stats_service import list_categories
from app.services.tag_service import list_tags
from app.services.time_service import now_utc
from app.tenants import AuthContext

router = APIRouter(prefix="/web/expenses", tags=["web"])


def _manual_auth(request: Request, db: Session, *, ledger_id: str, role: str) -> AuthContext:
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth
    return build_loopback_owner_auth_context(
        db,
        ledger_id=ledger_id,
        role=role,
    )


def _default_values() -> dict[str, str]:
    local_now = now_utc().astimezone(accounting_zone())
    return {
        "amount_yuan": "",
        "currency_code": "",
        "expense_time": local_now.strftime("%Y-%m-%dT%H:%M"),
        "merchant": "",
        "category": "",
        "tags": "",
        "note": "",
        "client_ref": str(uuid4()),
    }


def _render_manual_form(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    values: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="记一笔",
    )
    form_values = _default_values()
    if values:
        form_values.update(values)
    form_values["currency_code"] = ctx["home_currency_code"]
    ctx.update(
        form_values=form_values,
        form_error=error,
        category_options=list_categories(db, selected_id),
        tag_options=list_tags(db, selected_id),
        merchant_options=[
            row.display_name for row in list_merchant_catalog(db, tenant_id=selected_id, include_hidden=False)
        ],
    )
    return templates.TemplateResponse(
        request=request,
        name="manual_expense.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/new", response_class=HTMLResponse)
def web_manual_expense_new(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    return _render_manual_form(
        request,
        db,
        options=options,
        selected_id=selected_id,
    )


@router.post("/new", response_class=HTMLResponse)
def web_manual_expense_create(
    request: Request,
    ledger_id: str = Form(default=""),
    amount_yuan: str = Form(default=""),
    currency_code: str = Form(default=""),
    expense_time: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    tags: str = Form(default=""),
    note: str = Form(default=""),
    client_ref: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    role = next(item.role for item in options if item.ledger_id == selected_id)
    values = {
        "amount_yuan": amount_yuan,
        "currency_code": currency_code,
        "expense_time": expense_time,
        "merchant": merchant,
        "category": category,
        "tags": tags,
        "note": note,
        "client_ref": client_ref,
    }
    try:
        ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
        home_code = ctx["home_currency_code"]
        if currency_code.strip().upper() != home_code:
            raise AppError(
                "invalid_request",
                f"当前 Web 手工记账使用账本本位币 {home_code}。",
                status_code=422,
            )
        amount_cents = _parse_major_amount(amount_yuan, label="金额", required=True, currency_code=home_code)
        if amount_cents is None or amount_cents <= 0:
            raise AppError("invalid_request", "金额必须大于 0。", status_code=422)
        parsed_time, time_error = parse_expense_time_local(expense_time)
        if time_error:
            raise AppError("invalid_request", time_error, status_code=422)
        clean_ref = client_ref.strip()
        if not clean_ref or len(clean_ref) > 64:
            raise AppError(
                "invalid_request",
                "本次提交标识已失效，请刷新页面后重试。",
                status_code=422,
            )
        expense = create_manual_expense(
            db,
            ExpenseManualCreateRequest(
                amount_cents=amount_cents,
                expense_time=parsed_time,
                merchant=merchant.strip() or None,
                category=category.strip() or None,
                tags=tags.strip() or None,
                note=note.strip() or None,
                client_ref=clean_ref,
            ),
            _manual_auth(request, db, ledger_id=selected_id, role=role),
        )
    except AppError as exc:
        return _render_manual_form(
            request,
            db,
            options=options,
            selected_id=selected_id,
            values=values,
            error=exc.message,
            status_code=exc.status_code,
        )
    return _web_redirect(f"/web/expenses/{expense.id}/edit", selected_id)
