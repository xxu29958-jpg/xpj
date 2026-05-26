"""/web expense edit / save / confirm / reject — expense 主体 routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import parse_original_amount, web_edit_context
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import (
    confirm_expense,
    reject_expense,
    update_expense,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    fragment: int = 0,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    ctx = web_edit_context(db, request, options, selected_id, expense_id)
    # ?fragment=1 returns the drawer fragment fetched by desktop.js.
    template_name = "_edit_drawer.html" if fragment else "edit.html"
    return templates.TemplateResponse(request=request, name=template_name, context=ctx)


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    amount_yuan: str = Form(default=""),
    original_currency: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    note: str = Form(default=""),
    ledger_id: str = Form(default=""),
    expected_updated_at: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    original_amount, error = parse_original_amount(amount_yuan)

    if error is None:
        # ADR-0038: the edit form renders a hidden `expected_updated_at`
        # input pre-filled from ``expense.updated_at``. The handler simply
        # passes it through; if the user submits a stale form (e.g. left
        # the page open while another window mutated the row),
        # ``update_expense``'s atomic claim returns 409 ``state_conflict``.
        payload_args: dict[str, object] = {
            "expected_updated_at": expected_updated_at,
            "merchant": merchant.strip() or None,
            "category": category.strip() or None,
            "note": note.strip() or None,
        }
        if original_amount is not None:
            payload_args["original_currency"] = (
                (original_currency or "").strip().upper() or None
            )
            payload_args["original_amount"] = original_amount
        try:
            payload = ExpenseUpdateRequest(**payload_args)
            update_expense(db, expense_id, selected_id, payload)
        except ValueError as exc:
            error = f"提交参数不正确：{exc}"
        except AppError as exc:
            error = exc.message

    if error is not None:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        ctx["error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)

    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected_id)


def _parse_expected_updated_at(value: str) -> datetime | None:
    """ADR-0038 PR-2b: parse the hidden form field; empty / unparseable
    surfaces a Chinese error on the edit template (callers map to the
    same UX as a stale-write 409)."""
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("/expenses/{expense_id}/confirm", response_class=HTMLResponse)
def web_confirm(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    expected_updated_at: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = _parse_expected_updated_at(expected_updated_at)
    if parsed is None:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        ctx["error"] = "页面已过期，请刷新后重新确认。"
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    try:
        confirm_expense(db, expense_id, selected_id, expected_updated_at=parsed)
    except AppError as exc:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        # ADR-0038 PR-2b: 409 state_conflict surfaces a clearer message
        # than the generic AppError text because user has to refetch.
        if exc.error == "state_conflict":
            ctx["error"] = "账单已在其它端被修改，请刷新后重新确认。"
        else:
            ctx["error"] = exc.message
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return _web_redirect("/web/pending", selected_id)


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    expected_updated_at: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = _parse_expected_updated_at(expected_updated_at)
    if parsed is None:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        ctx["error"] = "页面已过期，请刷新后重新操作。"
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    try:
        reject_expense(db, expense_id, selected_id, expected_updated_at=parsed)
    except AppError as exc:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        if exc.error == "state_conflict":
            ctx["error"] = "账单已在其它端被修改，请刷新后重新操作。"
        else:
            ctx["error"] = exc.message
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return _web_redirect("/web/pending", selected_id)
