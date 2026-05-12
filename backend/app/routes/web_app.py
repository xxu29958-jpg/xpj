"""Web account center — dashboard, confirmed, stats, expense edit.

v0.4-alpha3 slice 2: this module is the slim host for the /web pages that
remain in ``web_app.py``. Pending / bulk live in ``web_pending.py``, rules
live in ``web_rules.py``, helpers and the loopback gate live in
``web_common.py``.

It re-exports ``_require_local`` and ``templates`` because existing tests
import them from this module.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _dashboard_cards,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
    _require_local,  # re-exported for tests
)
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import (
    confirm_expense,
    ensure_thumbnail_file,
    get_expense,
    list_confirmed,
    reject_expense,
    update_expense,
)
from app.services.file_service import resolve_protected_image

__all__ = ["router", "_require_local", "templates"]

router = APIRouter(prefix="/web", tags=["web"])


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def web_root(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["cards"] = _dashboard_cards(db, selected_id)
    return templates.TemplateResponse(request=request, name="dashboard.html", context=ctx)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def web_root_slash(
    ledger_id: str | None = None,
    _local: None = LocalOnly,
) -> RedirectResponse:
    target = "/web"
    if ledger_id:
        target = _with_ledger(target, ledger_id)
    return RedirectResponse(url=target, status_code=303)


@router.get("/confirmed", response_class=HTMLResponse)
def web_confirmed(
    request: Request,
    page: int = 1,
    month: str | None = None,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    page_size = 50
    expenses, total = list_confirmed(
        db, tenant_id=selected_id, page=page, page_size=page_size, month=month
    )
    items = [_expense_view(e) for e in expenses]
    total_pages = max(1, (total + page_size - 1) // page_size)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["expenses"] = items
    ctx["page"] = page
    ctx["total_pages"] = total_pages
    ctx["total"] = total
    ctx["month"] = month or ""
    return templates.TemplateResponse(request=request, name="confirmed.html", context=ctx)


# ── Expense edit / save / confirm / reject / image ──────────────────────────


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    expense = get_expense(db, expense_id, selected_id)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["expense"] = _expense_view(expense)
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="edit.html", context=ctx)


def _parse_amount_yuan(raw: str) -> tuple[int | None, str | None]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None, None
    try:
        d = Decimal(cleaned)
    except InvalidOperation:
        return None, "请填写正确的金额，例如 12.34。"
    if d < 0:
        return None, "金额不能为负数。"
    cents = int((d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents, None


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    amount_yuan: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    note: str = Form(default=""),
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    amount_cents, error = _parse_amount_yuan(amount_yuan)

    if error is None:
        payload = ExpenseUpdateRequest(
            amount_cents=amount_cents,
            merchant=merchant.strip() or None,
            category=category.strip() or None,
            note=note.strip() or None,
        )
        try:
            update_expense(db, expense_id, selected_id, payload)
        except AppError as exc:
            error = exc.message

    if error is not None:
        expense = get_expense(db, expense_id, selected_id)
        ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
        ctx["expense"] = _expense_view(expense)
        ctx["error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)

    return RedirectResponse(
        url=_with_ledger(f"/web/expenses/{expense_id}/edit", selected_id),
        status_code=303,
    )


@router.post("/expenses/{expense_id}/confirm", response_class=HTMLResponse)
def web_confirm(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    try:
        confirm_expense(db, expense_id, selected_id)
    except AppError as exc:
        expense = get_expense(db, expense_id, selected_id)
        ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
        ctx["expense"] = _expense_view(expense)
        ctx["error"] = exc.message
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return RedirectResponse(url=_with_ledger("/web/pending", selected_id), status_code=303)


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    expense_id: int,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    reject_expense(db, expense_id, selected_id)
    return RedirectResponse(url=_with_ledger("/web/pending", selected_id), status_code=303)


@router.get("/expenses/{expense_id}/image", include_in_schema=False)
def web_image(
    expense_id: int,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    selected_id = _resolve_selected_ledger_id(db, ledger_id)
    expense = get_expense(db, expense_id, selected_id)
    path, media_type = resolve_protected_image(expense.image_path, selected_id)
    return FileResponse(path=path, media_type=media_type)


@router.get("/expenses/{expense_id}/thumbnail", include_in_schema=False)
def web_thumbnail(
    expense_id: int,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    selected_id = _resolve_selected_ledger_id(db, ledger_id)
    path, media_type = ensure_thumbnail_file(db, expense_id, selected_id)
    return FileResponse(path=path, media_type=media_type)
