"""/web/pending + /web/review/bulk routes.

Split from ``web_app.py`` in v0.4-alpha3 slice 2 to keep per-page routing
modules under the 280-line budget. Business logic lives in
``app.services`` — this module is responsible for HTTP wiring only.
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
from app.schemas import ExpenseUpdateRequest
from app.services.duplicate_service import mark_not_duplicate
from app.services.expense_service import (
    confirm_expense,
    list_pending,
    reject_expense,
    update_expense,
)

router = APIRouter(prefix="/web", tags=["web"])


_PENDING_FILTERS = {"all", "missing_amount", "missing_merchant", "duplicate", "ready"}


def _matches_filter(view: dict, filter_key: str) -> bool:
    if filter_key == "all":
        return True
    if filter_key == "missing_amount":
        return view["needs_amount"]
    if filter_key == "missing_merchant":
        return view["needs_merchant"]
    if filter_key == "duplicate":
        return view["is_duplicate"]
    if filter_key == "ready":
        return (
            not view["needs_amount"]
            and not view["needs_merchant"]
            and not view["is_duplicate"]
        )
    return True


@router.get("/pending", response_class=HTMLResponse)
def web_pending(
    request: Request,
    ledger_id: str | None = None,
    filter: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    raw_items = [_expense_view(e) for e in list_pending(db, selected_id)]

    filter_key = (filter or "all").strip().lower()
    if filter_key not in _PENDING_FILTERS:
        filter_key = "all"

    items = [it for it in raw_items if _matches_filter(it, filter_key)]
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["expenses"] = items
    ctx["pending_count"] = len(raw_items)
    ctx["filtered_count"] = len(items)
    ctx["filter"] = filter_key
    ctx["flash_message"] = msg or ""
    ctx["needs_amount_count"] = sum(1 for it in raw_items if it["needs_amount"])
    ctx["needs_merchant_count"] = sum(1 for it in raw_items if it["needs_merchant"])
    ctx["suspected_duplicate_count"] = sum(1 for it in raw_items if it["is_duplicate"])
    ctx["ready_count"] = sum(
        1
        for it in raw_items
        if not it["needs_amount"] and not it["needs_merchant"] and not it["is_duplicate"]
    )
    return templates.TemplateResponse(request=request, name="pending.html", context=ctx)


_BULK_ACTIONS = {
    "set_category",
    "set_merchant",
    "reject",
    "confirm_ready",
    "keep_duplicate",
}


@router.post("/review/bulk", response_class=HTMLResponse)
def web_review_bulk(
    request: Request,
    action: str = Form(...),
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    category: str = Form(default=""),
    merchant: str = Form(default=""),
    filter: str = Form(default="all"),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)

    action_clean = (action or "").strip()
    if action_clean not in _BULK_ACTIONS:
        raise AppError("invalid_request", status_code=422)

    if not expense_ids:
        return RedirectResponse(
            url=_with_ledger(
                "/web/pending", selected_id, filter=filter or "all", msg="请先勾选账单。"
            ),
            status_code=303,
        )

    rows = list(
        db.scalars(
            select(Expense)
            .where(Expense.tenant_id == selected_id)
            .where(Expense.id.in_(expense_ids))
        )
    )
    found_ids = {row.id for row in rows}
    skipped_cross_ledger = len([eid for eid in expense_ids if eid not in found_ids])

    success_count = 0
    skipped_reasons: dict[str, int] = {}

    def _bump(label: str) -> None:
        skipped_reasons[label] = skipped_reasons.get(label, 0) + 1

    if action_clean == "set_category":
        category_clean = category.strip()
        if not category_clean:
            return RedirectResponse(
                url=_with_ledger("/web/pending", selected_id, filter=filter, msg="请填写分类。"),
                status_code=303,
            )
        for row in rows:
            if row.status != "pending":
                _bump("非待确认")
                continue
            try:
                update_expense(db, row.id, selected_id, ExpenseUpdateRequest(category=category_clean))
                success_count += 1
            except AppError:
                _bump("更新失败")
    elif action_clean == "set_merchant":
        merchant_clean = merchant.strip()
        if not merchant_clean:
            return RedirectResponse(
                url=_with_ledger("/web/pending", selected_id, filter=filter, msg="请填写商家。"),
                status_code=303,
            )
        for row in rows:
            if row.status != "pending":
                _bump("非待确认")
                continue
            try:
                update_expense(db, row.id, selected_id, ExpenseUpdateRequest(merchant=merchant_clean))
                success_count += 1
            except AppError:
                _bump("更新失败")
    elif action_clean == "reject":
        for row in rows:
            if row.status != "pending":
                _bump("非待确认")
                continue
            try:
                reject_expense(db, row.id, selected_id)
                success_count += 1
            except AppError:
                _bump("忽略失败")
    elif action_clean == "confirm_ready":
        for row in rows:
            if row.status != "pending":
                _bump("非待确认")
                continue
            if row.amount_cents is None:
                _bump("缺金额")
                continue
            try:
                confirm_expense(db, row.id, selected_id)
                success_count += 1
            except AppError:
                _bump("确认失败")
    elif action_clean == "keep_duplicate":
        for row in rows:
            if (row.duplicate_status or "") != "suspected":
                _bump("非疑似重复")
                continue
            try:
                mark_not_duplicate(db, row)
                success_count += 1
            except AppError:
                _bump("更新失败")

    parts: list[str] = []
    if success_count:
        if action_clean == "reject":
            parts.append(f"已忽略 {success_count} 条")
        elif action_clean == "confirm_ready":
            parts.append(f"已确认 {success_count} 条")
        elif action_clean == "keep_duplicate":
            parts.append(f"已保留 {success_count} 条")
        else:
            parts.append(f"已更新 {success_count} 条")
    if skipped_cross_ledger:
        parts.append(f"跳过 {skipped_cross_ledger} 条：不属于当前账本")
    for label, count in skipped_reasons.items():
        parts.append(f"跳过 {count} 条：{label}")
    if not parts:
        parts.append("没有可操作的账单。")
    msg = "；".join(parts) + "。"

    return RedirectResponse(
        url=_with_ledger("/web/pending", selected_id, filter=filter or "all", msg=msg),
        status_code=303,
    )
