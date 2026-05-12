"""/web/duplicates side-by-side review (v0.4-alpha3 slice 2 / PR18).

Lists every pending expense currently flagged as a suspected duplicate
together with the row it duplicates, so the user can resolve the pair
in a single click:

* **保留两条** — calls ``mark_expense_not_duplicate`` (records the ignore
  pair so it never re-fires for the same kind).
* **删除当前** — rejects the suspected row.
* **删除被复制的那条** — rejects the original row instead, then clears the
  suspected flag on the kept row so it stops blocking review.

All actions stay loopback-only via ``LocalOnly`` and respect ledger
isolation via ``selected_id``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import Expense
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
)
from app.services.expense_service import (
    list_duplicate_expenses,
    mark_expense_not_duplicate,
    reject_expense,
)


router = APIRouter(prefix="/web", tags=["web"])


def _load_pair(db: Session, *, tenant_id: str, expense_id: int) -> tuple[Expense, Expense | None]:
    expense = db.scalar(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    other = None
    if expense.duplicate_of_id is not None:
        other = db.scalar(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.id == expense.duplicate_of_id)
        )
    return expense, other


@router.get("/duplicates", response_class=HTMLResponse)
def web_duplicates(
    request: Request,
    ledger_id: str = "",
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    rows = list_duplicate_expenses(db, selected_id)
    pairs = []
    for row in rows:
        original = None
        if row.duplicate_of_id is not None:
            original = db.scalar(
                select(Expense)
                .where(Expense.tenant_id == selected_id)
                .where(Expense.id == row.duplicate_of_id)
            )
        pairs.append(
            {
                "current": _expense_view(row),
                "original": _expense_view(original) if original is not None else None,
                "reason": row.duplicate_reason or "",
            }
        )
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["duplicate_pairs"] = pairs
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request, name="duplicates.html", context=ctx
    )


@router.post("/duplicates/{expense_id}/keep")
def web_duplicate_keep(
    expense_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    try:
        mark_expense_not_duplicate(db, expense_id, selected_id)
        msg = "已标记为「不是重复」。"
    except AppError as exc:
        msg = exc.message
    return RedirectResponse(
        url=_with_ledger("/web/duplicates", selected_id, msg=msg),
        status_code=303,
    )


@router.post("/duplicates/{expense_id}/reject-current")
def web_duplicate_reject_current(
    expense_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    try:
        reject_expense(db, expense_id, selected_id)
        msg = "已删除当前账单。"
    except AppError as exc:
        msg = exc.message
    return RedirectResponse(
        url=_with_ledger("/web/duplicates", selected_id, msg=msg),
        status_code=303,
    )


@router.post("/duplicates/{expense_id}/reject-original")
def web_duplicate_reject_original(
    expense_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    msg = "已删除被复制的那条，并保留当前账单。"
    try:
        current, original = _load_pair(db, tenant_id=selected_id, expense_id=expense_id)
        if original is None:
            raise AppError("invalid_request", "找不到被复制的账单。", status_code=404)
        reject_expense(db, original.id, selected_id)
        # Clear the suspected flag on the kept row so it doesn't block review.
        mark_expense_not_duplicate(db, current.id, selected_id)
    except AppError as exc:
        msg = exc.message
    return RedirectResponse(
        url=_with_ledger("/web/duplicates", selected_id, msg=msg),
        status_code=303,
    )
