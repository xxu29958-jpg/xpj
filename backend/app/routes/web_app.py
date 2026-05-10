"""Web MVP — local-only HTML pages for managing receipts in a browser.

Mirrors the most common Android flows so the owner can review and edit
expenses on a desktop without booting the Android app:

    GET  /web                       — redirects to /web/pending
    GET  /web/pending               — pending list
    GET  /web/confirmed             — confirmed list (paginated)
    GET  /web/stats                 — current month stats
    GET  /web/expenses/{id}/edit    — edit form (pending or confirmed)
    POST /web/expenses/{id}/save    — save edits
    POST /web/expenses/{id}/confirm — confirm a pending expense
    POST /web/expenses/{id}/reject  — reject a pending expense

All endpoints reuse :mod:`app.services.expense_service` and
:mod:`app.services.stats_service`. Authentication is loopback only — the same
boundary as the Owner Console.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.network_boundary import require_owner_console_local
from app.schemas import ExpenseUpdateRequest
from app.services import owner_console_service as owner_svc
from app.services.expense_service import (
    confirm_expense,
    ensure_thumbnail_file,
    get_expense,
    list_confirmed,
    list_pending,
    reject_expense,
    update_expense,
)
from app.services.file_service import resolve_protected_image
from app.services.stats_service import monthly_stats
from app.version import BACKEND_VERSION

from fastapi.templating import Jinja2Templates


_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "web"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/web", tags=["web"])


def _require_local(request: Request) -> None:
    """Loopback gate. Same rule as the Owner Console."""
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


def _resolve_tenant_id(db: Session) -> str:
    ledger_id = owner_svc.get_default_ledger_id(db)
    if not ledger_id:
        raise AppError(
            "invalid_request",
            "服务尚未初始化，请先运行本机的 bootstrap 脚本。",
            status_code=400,
        )
    return ledger_id


def _base_ctx(request: Request) -> dict:
    return {
        "backend_version": BACKEND_VERSION,
        "request": request,
    }


def _amount_yuan(amount_cents: int | None) -> str:
    if amount_cents is None:
        return ""
    return f"{amount_cents / 100:.2f}"


def _expense_view(expense) -> dict:
    return {
        "id": expense.id,
        "amount_yuan": _amount_yuan(expense.amount_cents),
        "amount_cents": expense.amount_cents,
        "merchant": expense.merchant or "",
        "category": expense.category or "",
        "note": expense.note or "",
        "status": expense.status,
        "expense_time": expense.expense_time.strftime("%Y-%m-%d %H:%M") if expense.expense_time else "",
        "created_at": expense.created_at.strftime("%Y-%m-%d %H:%M") if expense.created_at else "",
        "has_image": bool(expense.image_path) and not expense.image_deleted_at,
        "duplicate_status": expense.duplicate_status,
    }


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def web_index(_local: None = LocalOnly) -> RedirectResponse:
    return RedirectResponse(url="/web/pending", status_code=303)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def web_index_slash(_local: None = LocalOnly) -> RedirectResponse:
    return RedirectResponse(url="/web/pending", status_code=303)


@router.get("/pending", response_class=HTMLResponse)
def web_pending(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _resolve_tenant_id(db)
    items = [_expense_view(e) for e in list_pending(db, tenant_id)]
    ctx = _base_ctx(request)
    ctx["expenses"] = items
    return templates.TemplateResponse(request=request, name="pending.html", context=ctx)


@router.get("/confirmed", response_class=HTMLResponse)
def web_confirmed(
    request: Request,
    page: int = 1,
    month: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _resolve_tenant_id(db)
    page_size = 50
    expenses, total = list_confirmed(
        db, tenant_id=tenant_id, page=page, page_size=page_size, month=month
    )
    items = [_expense_view(e) for e in expenses]
    total_pages = max(1, (total + page_size - 1) // page_size)
    ctx = _base_ctx(request)
    ctx["expenses"] = items
    ctx["page"] = page
    ctx["total_pages"] = total_pages
    ctx["total"] = total
    ctx["month"] = month or ""
    return templates.TemplateResponse(request=request, name="confirmed.html", context=ctx)


@router.get("/stats", response_class=HTMLResponse)
def web_stats(
    request: Request,
    month: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _resolve_tenant_id(db)
    if not month:
        month = datetime.now().strftime("%Y-%m")
    stats = monthly_stats(db, month, tenant_id)
    by_category = []
    for row in stats["by_category"]:
        by_category.append(
            {
                "category": row["category"],
                "amount_yuan": _amount_yuan(int(row["amount_cents"])),
                "count": int(row["count"]),
            }
        )
    ctx = _base_ctx(request)
    ctx["month"] = month
    ctx["total_amount_yuan"] = _amount_yuan(int(stats["total_amount_cents"]))
    ctx["count"] = int(stats["count"])
    ctx["by_category"] = by_category
    return templates.TemplateResponse(request=request, name="stats.html", context=ctx)


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _resolve_tenant_id(db)
    expense = get_expense(db, expense_id, tenant_id)
    ctx = _base_ctx(request)
    ctx["expense"] = _expense_view(expense)
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="edit.html", context=ctx)


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    amount_yuan: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    note: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _resolve_tenant_id(db)
    error: str | None = None
    amount_cents: int | None = None
    raw = (amount_yuan or "").strip()
    if raw:
        try:
            d = Decimal(raw)
            if d < 0:
                error = "金额不能为负数。"
            else:
                amount_cents = int(
                    (d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
        except InvalidOperation:
            error = "请填写正确的金额，例如 12.34。"

    if error is None:
        payload = ExpenseUpdateRequest(
            amount_cents=amount_cents,
            merchant=merchant.strip() or None,
            category=category.strip() or None,
            note=note.strip() or None,
        )
        try:
            update_expense(db, expense_id, tenant_id, payload)
        except AppError as exc:
            error = exc.message

    if error is not None:
        expense = get_expense(db, expense_id, tenant_id)
        ctx = _base_ctx(request)
        ctx["expense"] = _expense_view(expense)
        ctx["error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)

    return RedirectResponse(url=f"/web/expenses/{expense_id}/edit", status_code=303)


@router.post("/expenses/{expense_id}/confirm", response_class=HTMLResponse)
def web_confirm(
    expense_id: int,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    tenant_id = _resolve_tenant_id(db)
    try:
        confirm_expense(db, expense_id, tenant_id)
    except AppError as exc:
        # Show the edit page again with the error (e.g. amount_required).
        expense = get_expense(db, expense_id, tenant_id)
        ctx = _base_ctx(request)
        ctx["expense"] = _expense_view(expense)
        ctx["error"] = exc.message
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return RedirectResponse(url="/web/pending", status_code=303)


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    expense_id: int,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    tenant_id = _resolve_tenant_id(db)
    reject_expense(db, expense_id, tenant_id)
    return RedirectResponse(url="/web/pending", status_code=303)


@router.get("/expenses/{expense_id}/image", include_in_schema=False)
def web_image(
    expense_id: int,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    tenant_id = _resolve_tenant_id(db)
    expense = get_expense(db, expense_id, tenant_id)
    path, media_type = resolve_protected_image(expense.image_path, tenant_id)
    return FileResponse(path=path, media_type=media_type)


@router.get("/expenses/{expense_id}/thumbnail", include_in_schema=False)
def web_thumbnail(
    expense_id: int,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    tenant_id = _resolve_tenant_id(db)
    path, media_type = ensure_thumbnail_file(db, expense_id, tenant_id)
    return FileResponse(path=path, media_type=media_type)
