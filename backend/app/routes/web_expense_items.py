"""/web expense items routes (ADR-0035 line items + sum mismatch ack)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import (
    _edit_page_or_flash_redirect,
    item_replace_payload,
)
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
)
from app.schemas import ExpenseItemReplaceRequest
from app.services.receipt_item_service import (
    acknowledge_items_sum_mismatch,
    replace_expense_items,
)

router = APIRouter(prefix="/web", tags=["web"])


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
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error: str | None = None
    payload: ExpenseItemReplaceRequest | None = None
    parsed_row_version = parse_form_row_version_token(expected_row_version)
    if parsed_row_version is None:
        error = "页面已过期，请刷新后重新保存明细。"
    try:
        if error is None:
            payload = item_replace_payload(
                expected_row_version=parsed_row_version,
                item_name=item_name,
                item_kind=item_kind,
                item_quantity=item_quantity,
                item_unit_price_yuan=item_unit_price_yuan,
                item_amount_yuan=item_amount_yuan,
                item_category=item_category,
            )
    except AppError as exc:
        error = exc.message
    if error is None and payload is not None:
        try:
            replace_expense_items(db, expense_id, selected_id, payload)
        except AppError as exc:
            error = exc.message
    if error is not None:
        # codex follow-up on audit P2 #6: the re-read shares the main form's
        # vanished-row guard (flash to /web/confirmed, mirroring the GET).
        return _edit_page_or_flash_redirect(
            db, request, options, selected_id, expense_id, error,
            "/web/confirmed", error_key="items_error",
        )
    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected_id, msg="明细已保存。")


@router.post(
    "/expenses/{expense_id}/items/acknowledge-mismatch",
    response_class=HTMLResponse,
)
def web_items_acknowledge_mismatch(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    # ADR-0038 PR-2e: stale-click ("原小票如此" on an outdated page
    # after a peer edited amount/items) surfaces as ``state_conflict``
    # 409 → "账单已在其它端被修改" UX instead of silently flipping a
    # *new* mismatch into ``mismatch_acknowledged``.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _edit_page_or_flash_redirect(
            db, request, options, selected_id, expense_id,
            "页面已过期，请刷新后重新确认。",
            "/web/confirmed", error_key="items_error",
        )
    error: str | None = None
    try:
        acknowledge_items_sum_mismatch(
            db, expense_id, selected_id, expected_row_version=parsed
        )
    except AppError as exc:
        error = (
            "账单已在其它端被修改，请刷新后重新确认。"
            if exc.error == "state_conflict"
            else exc.message
        )
    if error is not None:
        return _edit_page_or_flash_redirect(
            db, request, options, selected_id, expense_id, error,
            "/web/confirmed", error_key="items_error",
        )
    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected_id, msg="已确认原小票如此。")
