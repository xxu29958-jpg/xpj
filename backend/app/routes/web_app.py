"""Web account center — dashboard, confirmed, stats, expense edit.

v0.4-alpha3 slice 2: this module is the slim host for the /web pages that
remain in ``web_app.py``. Pending / bulk live in ``web_pending.py``, rules
live in ``web_rules.py``, helpers and the loopback gate live in
``web_common.py``.

It re-exports ``_require_local`` and ``templates`` because existing tests
import them from this module.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _confirmed_by_day,
    _confirmed_source_breakdown,
    _dashboard_cards,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _trend14_amounts,
    _with_ledger,
    templates,
    _require_local,  # re-exported for tests
)
from app.services.stats_service import monthly_stats
from app.services.time_service import current_month
from app.schemas import DashboardCardUpdateRequest, DashboardCardsUpdateRequest
from app.schemas import ConfirmedExpenseBatchUpdateRequest
from app.services.dashboard_service import list_dashboard_cards, update_dashboard_cards
from app.services.expense_service import (
    batch_update_confirmed_expenses,
    ensure_image_file,
    ensure_thumbnail_file,
    list_confirmed,
)

__all__ = ["router", "_require_local", "templates"]

router = APIRouter(prefix="/web", tags=["web"])


def _dashboard_category_share(db: Session, selected_id: str) -> list[dict]:
    month = current_month("Asia/Shanghai")
    stats = monthly_stats(db, month, selected_id, timezone_name="Asia/Shanghai")
    return [
        {
            "name": item["category"],
            "amount_yuan": int(item["amount_cents"]) / 100.0,
            "amount_cents": int(item["amount_cents"]),
            "count": int(item["count"]),
        }
        for item in stats.get("by_category", [])[:6]
    ]


def _dashboard_data_payload(db: Session, selected_id: str) -> dict:
    cards = _dashboard_cards(db, selected_id)
    return {
        "selected_ledger_id": selected_id,
        "month": cards["month"],
        "cards": cards,
        "visible_layout": [item for item in cards["layout"] if item["visible"]],
        "trend14": _trend14_amounts(db, selected_id),
        "category_share": _dashboard_category_share(db, selected_id),
    }


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def web_root(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="仪表盘",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    dashboard_payload = _dashboard_data_payload(db, selected_id)
    ctx["cards"] = dashboard_payload["cards"]
    ctx["trend14"] = dashboard_payload["trend14"]
    ctx["category_share"] = dashboard_payload["category_share"]
    ctx["dashboard_data_url"] = _with_ledger("/web/dashboard/data", selected_id)
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


def _confirmed_redirect(
    selected_id: str,
    *,
    month: str = "",
    tag: str = "",
    page: int = 1,
    msg: str = "",
) -> RedirectResponse:
    page_value = str(page) if page > 1 else ""
    return RedirectResponse(
        url=_with_ledger("/web/confirmed", selected_id, month=month, tag=tag, page=page_value, msg=msg),
        status_code=303,
    )


@router.get("/confirmed", response_class=HTMLResponse)
def web_confirmed(
    request: Request,
    page: int = 1,
    month: str | None = None,
    tag: str | None = None,
    ledger_id: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    page_size = 50
    expenses, total = list_confirmed(
        db,
        tenant_id=selected_id,
        page=page,
        page_size=page_size,
        month=month,
        tag=tag,
    )
    items = [_expense_view(e) for e in expenses]
    total_pages = max(1, (total + page_size - 1) // page_size)
    pager_params = {"ledger_id": selected_id}
    if month:
        pager_params["month"] = month
    if tag:
        pager_params["tag"] = tag
    effective_month = month or current_month("Asia/Shanghai")
    month_stats = monthly_stats(
        db, effective_month, selected_id, timezone_name="Asia/Shanghai"
    )
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="已确认",
        show_month_picker=True,
        selected_month=effective_month,
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["expenses"] = items
    ctx["page"] = page
    ctx["total_pages"] = total_pages
    ctx["total"] = total
    ctx["month"] = month or ""
    ctx["tag"] = tag or ""
    ctx["pager_query"] = urlencode(pager_params)
    ctx["month_total_amount_yuan"] = int(month_stats.get("total_amount_cents", 0)) / 100.0
    ctx["month_total_count"] = int(month_stats.get("count", 0))
    ctx["by_day"] = _confirmed_by_day(db, selected_id, effective_month)
    ctx["source_breakdown"] = _confirmed_source_breakdown(db, selected_id, effective_month)
    ctx["flash_message"] = msg or ""
    return templates.TemplateResponse(request=request, name="confirmed.html", context=ctx)


@router.post("/confirmed/batch-update", response_class=HTMLResponse)
def web_confirmed_batch_update(
    action: str = Form(...),
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    category: str = Form(default=""),
    tags: str = Form(default=""),
    month: str = Form(default=""),
    tag: str = Form(default=""),
    page: int = Form(default=1),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)

    if not expense_ids:
        return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="请先勾选账单。")

    action_clean = (action or "").strip()
    if action_clean == "set_category":
        category_clean = category.strip()
        if not category_clean:
            return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="请填写分类。")
        payload = ConfirmedExpenseBatchUpdateRequest(
            expense_ids=expense_ids,
            category=category_clean,
        )
    elif action_clean == "set_tags":
        tags_clean = tags.strip()
        if not tags_clean:
            return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="请填写标签。")
        payload = ConfirmedExpenseBatchUpdateRequest(
            expense_ids=expense_ids,
            tags=tags_clean,
        )
    else:
        raise AppError("invalid_request", status_code=422)

    result = batch_update_confirmed_expenses(db, tenant_id=selected_id, payload=payload)
    parts: list[str] = []
    if result.updated_count:
        parts.append(f"已更新 {result.updated_count} 条")
    if result.skipped_not_found:
        parts.append(f"跳过 {result.skipped_not_found} 条：不属于当前账本")
    if result.skipped_not_confirmed:
        parts.append(f"跳过 {result.skipped_not_confirmed} 条：不是已入账")
    if not parts:
        parts.append("没有可更新的账单")
    return _confirmed_redirect(
        selected_id,
        month=month,
        tag=tag,
        page=page,
        msg="；".join(parts) + "。",
    )


@router.get("/expenses/{expense_id}/image", include_in_schema=False)
def web_image(
    expense_id: int,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    selected_id = _resolve_selected_ledger_id(db, ledger_id)
    path, media_type = ensure_image_file(db, expense_id, selected_id)
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
