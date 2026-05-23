"""/web/pending + /web/review/bulk routes.

Split from ``web_app.py`` in v0.4-alpha3 slice 2 to keep per-page routing
modules under the 280-line budget. Business logic lives in
``app.services`` — this module is responsible for HTTP wiring only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
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
    list_pending,
)
from app.services.pending_review_bulk_service import (
    ALLOWED_ACTIONS,
    BulkResult,
    apply_review_bulk,
)

router = APIRouter(prefix="/web", tags=["web"])


_PENDING_FILTERS = {
    "all",
    "missing_amount",
    "missing_merchant",
    "missing_category",
    "duplicate",
    "ready",
}


def _needs_category(view: dict) -> bool:
    # 分类为空，或仍是默认占位「未分类」时视为待分类。
    # 「其他」是用户可主动选择的合法分类，不能把它算进缺分类，
    # 否则旧账单会被错误排除在 ready 筛选外。
    cat = (view.get("category") or "").strip()
    return cat == "" or cat == "未分类"


def _matches_filter(view: dict, filter_key: str) -> bool:
    if filter_key == "all":
        return True
    if filter_key == "missing_amount":
        return view["needs_amount"]
    if filter_key == "missing_merchant":
        return view["needs_merchant"]
    if filter_key == "missing_category":
        return _needs_category(view)
    if filter_key == "duplicate":
        return view["is_duplicate"]
    if filter_key == "ready":
        return (
            not view["needs_amount"]
            and not view["needs_merchant"]
            and not _needs_category(view)
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
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    raw_items = [_expense_view(e) for e in list_pending(db, selected_id)]

    filter_key = (filter or "all").strip().lower()
    if filter_key not in _PENDING_FILTERS:
        filter_key = "all"

    items = [it for it in raw_items if _matches_filter(it, filter_key)]
    pending_total = len(raw_items)
    suspected_total = sum(1 for it in raw_items if it["is_duplicate"])
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="待确认",
        sidebar_counts=(pending_total, suspected_total),
    )
    ctx["expenses"] = items
    ctx["pending_count"] = pending_total
    ctx["filtered_count"] = len(items)
    ctx["filter"] = filter_key
    ctx["flash_message"] = msg or ""
    ctx["needs_amount_count"] = sum(1 for it in raw_items if it["needs_amount"])
    ctx["needs_merchant_count"] = sum(1 for it in raw_items if it["needs_merchant"])
    ctx["needs_category_count"] = sum(1 for it in raw_items if _needs_category(it))
    ctx["suspected_duplicate_count"] = suspected_total
    ctx["ready_count"] = sum(
        1
        for it in raw_items
        if not it["needs_amount"]
        and not it["needs_merchant"]
        and not _needs_category(it)
        and not it["is_duplicate"]
    )
    return templates.TemplateResponse(request=request, name="pending.html", context=ctx)


def _pending_redirect(selected_id: str, *, filter: str, msg: str) -> RedirectResponse:
    return RedirectResponse(
        url=_with_ledger("/web/pending", selected_id, filter=filter or "all", msg=msg),
        status_code=303,
    )


_SUCCESS_VERBS = {
    "reject": "已忽略",
    "confirm_ready": "已确认",
    "keep_duplicate": "已保留",
}


def _format_bulk_message(action: str, result: BulkResult) -> str:
    parts: list[str] = []
    if result.success_count:
        verb = _SUCCESS_VERBS.get(action, "已更新")
        parts.append(f"{verb} {result.success_count} 条")
    for label, count in result.skipped_reasons.items():
        parts.append(f"跳过 {count} 条：{label}")
    if not parts:
        parts.append("没有可操作的账单。")
    return "；".join(parts) + "。"


def _reject_pending_rows(
    db: Session,
    *,
    selected_id: str,
    expense_ids: list[int],
) -> str:
    result = apply_review_bulk(
        db, tenant_id=selected_id, action="reject", expense_ids=expense_ids
    )
    return _format_bulk_message("reject", result)


@router.post("/pending/batch-reject", response_class=HTMLResponse)
def web_pending_batch_reject(
    request: Request,
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    filter: str = Form(default="all"),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)

    if not expense_ids:
        return _pending_redirect(selected_id, filter=filter, msg="请先勾选账单。")

    return _pending_redirect(
        selected_id,
        filter=filter,
        msg=_reject_pending_rows(db, selected_id=selected_id, expense_ids=expense_ids),
    )


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
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)

    action_clean = (action or "").strip()
    if action_clean not in ALLOWED_ACTIONS:
        raise AppError("invalid_request", status_code=422)

    if not expense_ids:
        return _pending_redirect(selected_id, filter=filter, msg="请先勾选账单。")

    try:
        result = apply_review_bulk(
            db,
            tenant_id=selected_id,
            action=action_clean,
            expense_ids=expense_ids,
            category=category,
            merchant=merchant,
        )
    except AppError as exc:
        if exc.status_code == 422 and exc.error == "invalid_request":
            return _pending_redirect(selected_id, filter=filter, msg=exc.message)
        raise

    return _pending_redirect(
        selected_id,
        filter=filter,
        msg=_format_bulk_message(action_clean, result),
    )
