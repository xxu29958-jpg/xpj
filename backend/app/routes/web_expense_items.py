"""/web expense items routes (ADR-0035 line items + sum mismatch ack)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import item_replace_payload, web_edit_context
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
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
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error: str | None = None
    payload: ExpenseItemReplaceRequest | None = None
    try:
        payload = item_replace_payload(
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
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        ctx["items_error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected_id, msg="明细已保存。")


@router.post(
    "/expenses/{expense_id}/items/acknowledge-mismatch",
    response_class=HTMLResponse,
)
def web_items_acknowledge_mismatch(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error: str | None = None
    try:
        acknowledge_items_sum_mismatch(db, expense_id, selected_id)
    except AppError as exc:
        error = exc.message
    if error is not None:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        ctx["items_error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected_id, msg="已确认原小票如此。")
