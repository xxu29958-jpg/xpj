"""Browser commands for refund, chargeback, reversal, and void facts."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_fact import web_fact_context
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    edit_context_params,
    expense_return_form_context,
)
from app.routes._web_rate_recovery import _RATE_FIELDS, rate_recovery_context, rate_recovery_form, submit_recovery_rate
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.schemas import ExpenseOffsetCreateRequest, ExpenseOffsetVoidRequest
from app.services.currency_common import major_amount_to_minor
from app.services.expense_offset_lifecycle_service import void_expense_offset
from app.services.expense_offset_service import create_expense_offset
from app.services.expense_service import get_expense

router = APIRouter(prefix="/web", tags=["web"])

_CREATE_MESSAGES = {
    "refund": "退款已登记。",
    "chargeback": "拒付已登记。",
    "reversal": "账单已冲销。",
}
_CONFLICT_MESSAGE = "退款或冲销事实刚在其它端发生变化；已载入最新事实，请核对草稿后重试。"
_VOID_TARGET_GONE_MESSAGE = "这条退回或冲销记录已不再生效；已载入最新事实，无需再次撤销。"


def _form_error(message: str) -> AppError:
    return AppError("invalid_request", message, status_code=422)


def _required_row_version(raw: str) -> int:
    parsed = parse_form_row_version_token(raw)
    if parsed is None:
        raise _form_error("页面状态已过期，请刷新后重试。")
    return parsed


def _required_date(raw: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError as exc:
        raise _form_error("请选择有效的生效日期。") from exc


def _create_payload(
    *,
    kind: str,
    original_amount: str,
    accounting_date: str,
    reason: str,
    expected_row_version: str,
    original_currency_code: str,
) -> ExpenseOffsetCreateRequest:
    clean_kind = (kind or "").strip()
    if clean_kind not in _CREATE_MESSAGES:
        raise _form_error("请选择退款、拒付或冲销。")
    amount_minor = None
    if clean_kind != "reversal":
        clean_amount = (original_amount or "").strip()
        if not clean_amount:
            raise _form_error("请输入退回金额。")
        try:
            amount_minor = major_amount_to_minor(clean_amount, original_currency_code)
        except AppError as exc:
            raise _form_error("请输入大于 0 的有效金额。") from exc
        if amount_minor is None or amount_minor <= 0:
            raise _form_error("请输入大于 0 的有效金额。")
    try:
        return ExpenseOffsetCreateRequest(
            kind=clean_kind,
            original_amount_minor=amount_minor,
            accounting_date=_required_date(accounting_date),
            reason=reason,
            expected_row_version=_required_row_version(expected_row_version),
        )
    except ValidationError as exc:
        raise _form_error("请完整填写日期、金额和原因。") from exc


def _actor_snapshot(
    db: Session,
    request: Request,
    selected_id: str,
) -> tuple[int, str | None, str | None]:
    account_id, device_id = resolve_web_actor(db, request, selected_id)
    if device_id is None:
        return account_id, None, None
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is None or session_auth.device_id != device_id:
        raise AppError("state_conflict", status_code=409)
    return account_id, session_auth.device_public_id, session_auth.device_name


def _fact_redirect(
    expense_id: int,
    selected_id: str,
    return_context: ExpenseReturnContext,
    *,
    message: str,
) -> Response:
    response = _web_redirect(
        f"/web/expenses/{expense_id}/edit",
        selected_id,
        msg=message,
        flash_type="success",
        **edit_context_params(**return_context.as_kwargs()),
    )
    response.headers["location"] = f'{response.headers["location"]}#fact-offsets'
    return response


def _render_error(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    return_context: ExpenseReturnContext,
    exc: AppError | None,
    *,
    create_draft: dict[str, str] | None = None,
    void_draft: dict[str, str] | None = None,
    rate_recovery: dict | None = None,
) -> Response:
    db.rollback()
    ctx = web_fact_context(
        db,
        request,
        options,
        selected_id,
        expense_id,
        return_context=return_context,
    )
    error = exc.error if exc else ""
    message = _CONFLICT_MESSAGE if error == "state_conflict" else exc.message if exc else ""
    if error == "exchange_rate_pending":
        rate_recovery = rate_recovery_context(db, selected_id, exc.details)
    ctx.update(rate_recovery=rate_recovery, rate_recovery_action=f"/web/expenses/{expense_id}/offset-rate")
    if create_draft is not None:
        ctx["offset_form"].update(
            create_draft,
            open=True,
            error=message,
            conflict=error == "state_conflict",
        )
        if rate_recovery is None:
            ctx["offset_form"].update(expected_row_version=ctx["expense"]["row_version"], idempotency_key=str(uuid4()))
    if void_draft is not None:
        current = next(
            (
                row
                for row in ctx["active_offsets"]
                if row["public_id"] == void_draft["target_public_id"]
            ),
            None,
        )
        if current is None:
            ctx["error"] = _VOID_TARGET_GONE_MESSAGE
        else:
            ctx["offset_void_form"].update(
                void_draft,
                open=True,
                expected_row_version=current["row_version"],
                idempotency_key=str(uuid4()),
                error=message,
                conflict=error == "state_conflict",
            )
    return templates.TemplateResponse(
        request=request,
        name="expense_fact.html",
        context=ctx,
        status_code=web_form_error_status(exc) if exc else rate_recovery["status_code"],
    )


@router.post("/expenses/{expense_id}/offsets", response_class=HTMLResponse)
def web_create_expense_offset(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    kind: str = Form(default=""),
    original_amount: str = Form(default=""),
    accounting_date: str = Form(default=""),
    reason: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    draft = {
        "kind": kind,
        "original_amount": original_amount,
        "accounting_date": accounting_date,
        "reason": reason,
    }
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**draft, **return_context.as_kwargs(), "ledger_id": ledger_id,
            "expected_row_version": expected_row_version, "idempotency_key": idempotency_key},
        task="保存原退款或冲销")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    try:
        root = get_expense(db, expense_id, selected_id)
        payload = _create_payload(
            **draft,
            expected_row_version=expected_row_version,
            original_currency_code=root.original_currency_code,
        )
        account_id, device_public_id, device_name = _actor_snapshot(
            db,
            request,
            selected_id,
        )
        result = create_expense_offset(
            db,
            tenant_id=selected_id,
            expense_id=expense_id,
            payload=payload,
            effective_expected_row_version=payload.expected_row_version,
            actor_account_id=account_id,
            actor_device_public_id=device_public_id,
            actor_device_name=device_name,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except AppError as exc:
        return _render_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            return_context,
            exc,
            create_draft={**draft, "expected_row_version": expected_row_version, "idempotency_key": idempotency_key},
        )
    message = _CREATE_MESSAGES[payload.kind]
    cancelled_count = len(result.relationship_impacts.pending_invites_cancelled)
    if cancelled_count:
        message = f"{message.rstrip('。')}；同时撤回 {cancelled_count} 个待处理拆账邀请。"
    return _fact_redirect(
        expense_id,
        selected_id,
        return_context,
        message=message,
    )


@router.post("/expenses/{expense_id}/offset-rate")
def web_offset_rate(
    expense_id: int, request: Request, original: dict[str, str] = Depends(rate_recovery_form),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, original.get("ledger_id"), options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=original, task="补汇率并继续原退款")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    get_expense(db, expense_id, selected)
    values = {key: original.get(f"fx_{key}", "") for key in _RATE_FIELDS}
    result = submit_recovery_rate(db, request, selected, values,
        review_latest=original.get("fx_review_latest") == "true")
    draft = {key: original.get(key, "") for key in ("kind", "original_amount", "accounting_date", "reason",
        "expected_row_version", "idempotency_key")}
    return _render_error(db, request, options, selected, expense_id, return_context, None,
        create_draft=draft, rate_recovery={**values, **result})


@router.post(
    "/expenses/{expense_id}/offsets/{offset_public_id}/voids",
    response_class=HTMLResponse,
)
def web_void_expense_offset(
    expense_id: int,
    offset_public_id: str,
    request: Request,
    ledger_id: str = Form(default=""),
    void_reason: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    draft = {
        "target_public_id": offset_public_id,
        "void_reason": void_reason,
    }
    try:
        payload = ExpenseOffsetVoidRequest(
            void_reason=void_reason,
            expected_row_version=_required_row_version(expected_row_version),
        )
        account_id, device_public_id, device_name = _actor_snapshot(
            db,
            request,
            selected_id,
        )
        void_expense_offset(
            db,
            tenant_id=selected_id,
            expense_id=expense_id,
            offset_public_id=offset_public_id,
            payload=payload,
            actor_account_id=account_id,
            actor_device_public_id=device_public_id,
            actor_device_name=device_name,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except ValidationError:
        return _render_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            return_context,
            _form_error("请填写撤销原因。"),
            void_draft=draft,
        )
    except AppError as exc:
        return _render_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            return_context,
            exc,
            void_draft=draft,
        )
    return _fact_redirect(
        expense_id,
        selected_id,
        return_context,
        message="这条退回或冲销已撤销。",
    )
