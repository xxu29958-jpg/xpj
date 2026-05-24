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
    _sidebar_counts,
    _web_redirect,
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
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
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
        reason = row.duplicate_reason or ""
        # 把判定 reason 字符串映射成相似度 score（高/中置信度 pill 用）。
        # 后端目前没有持久化 score；规则简单透明，由 reason 关键词派生。
        if "hash" in reason or "完全一致" in reason:
            score = 0.98
        elif "金额" in reason and "时间" in reason:
            score = 0.85
        elif reason:
            score = 0.72
        else:
            score = 0.7
        current_view = _expense_view(row)
        original_view = _expense_view(original) if original is not None else None
        diff_fields: list[str] = []
        if original_view:
            if current_view.get("merchant") != original_view.get("merchant"):
                diff_fields.append("merchant")
            if current_view.get("amount_cents") != original_view.get("amount_cents"):
                diff_fields.append("amount")
            if current_view.get("expense_time") != original_view.get("expense_time"):
                diff_fields.append("time")
        pairs.append(
            {
                "current": current_view,
                "original": original_view,
                "reason": reason,
                "score": score,
                "score_pct": int(round(score * 100)),
                "confidence_tier": "high" if score >= 0.9 else "mid",
                "diff_fields": diff_fields,
            }
        )
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="疑似重复",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["duplicate_pairs"] = pairs
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request, name="duplicates.html", context=ctx
    )


@router.post("/duplicates/{expense_id}/keep")
def web_duplicate_keep(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        mark_expense_not_duplicate(db, expense_id, selected_id)
        msg = "已标记为「不是重复」。"
    except AppError as exc:
        msg = exc.message
    return _web_redirect("/web/duplicates", selected_id, msg=msg)


@router.post("/duplicates/{expense_id}/reject-current")
def web_duplicate_reject_current(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        reject_expense(db, expense_id, selected_id)
        msg = "已删除当前账单。"
    except AppError as exc:
        msg = exc.message
    return _web_redirect("/web/duplicates", selected_id, msg=msg)


@router.post("/duplicates/{expense_id}/reject-original")
def web_duplicate_reject_original(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
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
    return _web_redirect("/web/duplicates", selected_id, msg=msg)
