"""/web expense splits routes (v1.0 家庭拆账)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_fact import web_fact_error_response
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_expense_helpers import _edit_page_or_flash_redirect
from app.routes._web_expense_return_context import edit_context_params
from app.routes._web_expense_rows import (
    WebExpenseRowsOutcome,
    attach_form_row_error,
    split_replace_payload,
    submitted_split_form_rows,
)
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.expense_service import get_expense, resolve_expense
from app.services.expense_split_service import replace_expense_splits

router = APIRouter(prefix="/web", tags=["web"])


def _save_web_expense_splits(
    db: Session,
    request: Request,
    *,
    expense_id: int,
    selected_ledger_id: str,
    expected_row_version: str,
    split_member_id: list[str],
    split_amount_yuan: list[str],
    split_note: list[str],
) -> WebExpenseRowsOutcome:
    rows = submitted_split_form_rows(
        split_member_id=split_member_id,
        split_amount_yuan=split_amount_yuan,
        split_note=split_note,
    )
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return WebExpenseRowsOutcome(
            rows=rows,
            error="页面已过期，请刷新后重新保存拆账。",
        )
    try:
        expense = get_expense(db, expense_id, selected_ledger_id)
        currency = expense.home_currency_code or require_runtime_home_currency_code(db)
        payload = split_replace_payload(
            currency_code=currency,
            expected_row_version=parsed,
            split_member_id=split_member_id,
            split_amount_yuan=split_amount_yuan,
            split_note=split_note,
        )
        replace_expense_splits(
            db,
            expense_id,
            selected_ledger_id,
            payload,
            actor_account_id=resolve_web_actor_account_id(
                db,
                request,
                selected_ledger_id,
            ),
        )
    except AppError as exc:
        db.rollback()
        attach_form_row_error(rows, exc)
        return WebExpenseRowsOutcome(
            rows=rows,
            error=exc.message,
            error_status=web_form_error_status(exc),
        )
    return WebExpenseRowsOutcome(rows=rows)


@router.post("/expenses/{expense_id}/splits/save", response_class=HTMLResponse)
def web_splits_save(
    expense_id: int,
    request: Request,
    split_member_id: list[str] = Form(default=[]),
    split_amount_yuan: list[str] = Form(default=[]),
    split_note: list[str] = Form(default=[]),
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
    # A1: confirmed 的旧 splits 直写已失权（拆账改动必须进入更正意图）——
    # 明确 409 + 事实页错误呈现。
    guarded_expense = resolve_expense(db, selected_id, expense_id)
    if guarded_expense is not None and guarded_expense.status == "confirmed":
        return web_fact_error_response(
            db,
            request,
            options,
            selected_id,
            expense_id,
            AppError("expense_correction_required").message,
        )
    submitted_return_context = {
        "return_to": return_to,
        "return_month": return_month,
        "return_filter": return_filter,
        "return_page": return_page,
        "return_tag": return_tag,
        "return_query": return_query,
    }
    outcome = _save_web_expense_splits(
        db,
        request,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
        expected_row_version=expected_row_version,
        split_member_id=split_member_id,
        split_amount_yuan=split_amount_yuan,
        split_note=split_note,
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
            error_key="splits_error",
            status_code=outcome.error_status,
            split_form_rows=outcome.rows if outcome.error_status == 422 else None,
            **submitted_return_context,
        )
    return _web_redirect(
        f"/web/expenses/{expense_id}/edit",
        selected_id,
        msg="拆账已保存。",
        **edit_context_params(**submitted_return_context),
    )
