"""/web expense items routes (ADR-0035 line items + sum mismatch ack)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_confirmed_write_guard import confirmed_write_guard_response
from app.routes._web_expense_fact import web_fact_error_response
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_expense_helpers import _edit_page_or_flash_redirect
from app.routes._web_expense_return_context import edit_context_params
from app.routes._web_expense_rows import (
    WebExpenseRowsOutcome,
    attach_form_row_error,
    item_replace_payload,
    submitted_item_form_rows,
)
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.expense_service import get_expense
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.receipt_item_service import (
    acknowledge_items_sum_mismatch,
    replace_expense_items,
)

router = APIRouter(prefix="/web", tags=["web"])


def _save_web_expense_items(
    db: Session,
    *,
    expense_id: int,
    selected_ledger_id: str,
    expected_row_version: str,
    item_name: list[str],
    item_kind: list[str],
    item_quantity: list[str],
    item_unit_price_yuan: list[str],
    item_amount_yuan: list[str],
    item_category: list[str],
) -> WebExpenseRowsOutcome:
    rows = submitted_item_form_rows(
        item_name=item_name,
        item_kind=item_kind,
        item_quantity=item_quantity,
        item_unit_price_yuan=item_unit_price_yuan,
        item_amount_yuan=item_amount_yuan,
        item_category=item_category,
    )
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return WebExpenseRowsOutcome(
            rows=rows,
            error="页面已过期，请刷新后重新保存明细。",
        )
    try:
        expense = get_expense(db, expense_id, selected_ledger_id)
        currency = expense.home_currency_code or require_runtime_home_currency_code(db)
        payload = item_replace_payload(
            currency_code=currency,
            expected_row_version=parsed,
            item_name=item_name,
            item_kind=item_kind,
            item_quantity=item_quantity,
            item_unit_price_yuan=item_unit_price_yuan,
            item_amount_yuan=item_amount_yuan,
            item_category=item_category,
        )
        replace_expense_items(db, expense_id, selected_ledger_id, payload)
    except AppError as exc:
        db.rollback()
        attach_form_row_error(rows, exc)
        return WebExpenseRowsOutcome(
            rows=rows,
            error=exc.message,
            error_status=web_form_error_status(exc),
        )
    return WebExpenseRowsOutcome(rows=rows)


@router.post("/expenses/{expense_id}/items/save", response_class=HTMLResponse)
def web_items_save(
    expense_id: int,
    request: Request,
    item_name: list[str] = Form(default=[]),
    item_kind: list[str] = Form(default=[]),
    item_quantity: list[str] = Form(default=[]),
    item_unit_price_yuan: list[str] = Form(default=[]),
    item_amount_yuan: list[str] = Form(default=[]),
    item_category: list[str] = Form(default=[]),
    expected_row_version: str = Form(default=""),
    ledger_id: str = Form(default=""),
    return_to: str = Form(default=""),
    return_month: str = Form(default=""),
    return_filter: str = Form(default=""),
    return_page: str = Form(default=""),
    return_tag: str = Form(default=""),
    return_query: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    guarded = confirmed_write_guard_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        error_code="expense_correction_required",
    )
    if guarded is not None:
        return guarded
    submitted_return_context = {
        "return_to": return_to,
        "return_month": return_month,
        "return_filter": return_filter,
        "return_page": return_page,
        "return_tag": return_tag,
        "return_query": return_query,
    }
    outcome = _save_web_expense_items(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
        expected_row_version=expected_row_version,
        item_name=item_name,
        item_kind=item_kind,
        item_quantity=item_quantity,
        item_unit_price_yuan=item_unit_price_yuan,
        item_amount_yuan=item_amount_yuan,
        item_category=item_category,
    )
    if outcome.error is not None:
        # codex follow-up on audit P2 #6: the re-read shares the main form's
        # vanished-row guard (flash to /web/confirmed, mirroring the GET).
        return _edit_page_or_flash_redirect(
            db,
            request,
            options,
            selected_id,
            expense_id,
            outcome.error,
            "/web/confirmed",
            error_key="items_error",
            status_code=outcome.error_status,
            receipt_item_rows=outcome.rows if outcome.error_status == 422 else None,
            **submitted_return_context,
        )
    return _web_redirect(
        f"/web/expenses/{expense_id}/edit",
        selected_id,
        msg="明细已保存。",
        **edit_context_params(**submitted_return_context),
    )


def _mismatch_error_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    message: str,
    *,
    status_code: int,
    return_context: dict[str, str],
) -> Response:
    try:
        if get_expense(db, expense_id, selected_id).status == "confirmed":
            return web_fact_error_response(
                db,
                request,
                options,
                selected_id,
                expense_id,
                message,
                status_code=status_code,
            )
    except AppError:
        # The shared edit helper owns the vanished-row flash fallback.
        pass
    return _edit_page_or_flash_redirect(
        db,
        request,
        options,
        selected_id,
        expense_id,
        message,
        "/web/confirmed",
        error_key="items_error",
        status_code=status_code,
        **return_context,
    )


def _acknowledge_web_items_mismatch(
    db: Session,
    request: Request,
    *,
    expense_id: int,
    selected_id: str,
    expected_row_version: int,
    idempotency_key: str,
) -> None:
    """Run the shared ack command and its request claim in one transaction."""

    key = idempotency_key.strip() or str(uuid4())
    claim = claim_idempotent_request(
        db,
        idempotency_key=key,
        tenant_id=selected_id,
        operation="acknowledge_items_mismatch",
        target_id=str(expense_id),
        body={},
        expected_row_version=expected_row_version,
    )
    if claim is None:
        return
    actor_account_id, actor_device_id = resolve_web_actor(db, request, selected_id)
    acknowledge_items_sum_mismatch(
        db,
        expense_id,
        selected_id,
        expected_row_version=expected_row_version,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        idempotency_key=key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="expense",
        resource_id=str(expense_id),
    )
    db.commit()


@router.post(
    "/expenses/{expense_id}/items/acknowledge-mismatch",
    response_class=HTMLResponse,
)
def web_items_acknowledge_mismatch(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    return_to: str = Form(default=""),
    return_month: str = Form(default=""),
    return_filter: str = Form(default=""),
    return_page: str = Form(default=""),
    return_tag: str = Form(default=""),
    return_query: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    return_context = {
        "return_to": return_to,
        "return_month": return_month,
        "return_filter": return_filter,
        "return_page": return_page,
        "return_tag": return_tag,
        "return_query": return_query,
    }
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _mismatch_error_response(
            db,
            request,
            options,
            selected_id,
            expense_id,
            "页面已过期，请刷新后重新确认。",
            status_code=422,
            return_context=return_context,
        )
    try:
        _acknowledge_web_items_mismatch(
            db,
            request,
            expense_id=expense_id,
            selected_id=selected_id,
            expected_row_version=parsed,
            idempotency_key=idempotency_key,
        )
    except AppError as exc:
        db.rollback()
        message = (
            "账单已在其它端被修改，请刷新后重新确认。"
            if exc.error == "state_conflict"
            else exc.message
        )
        return _mismatch_error_response(
            db,
            request,
            options,
            selected_id,
            expense_id,
            message,
            status_code=web_form_error_status(exc),
            return_context=return_context,
        )
    return _web_redirect(
        f"/web/expenses/{expense_id}/edit",
        selected_id,
        msg="已确认原小票如此。",
        **edit_context_params(
            return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        ),
    )
