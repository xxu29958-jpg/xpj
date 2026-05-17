"""/web confirmed ledger route."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _confirmed_by_day,
    _confirmed_source_breakdown,
    _expense_view,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.services.expense_service import list_confirmed
from app.services.stats_service import monthly_stats
from app.services.time_service import current_month

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/confirmed", response_class=HTMLResponse)
def web_confirmed(
    request: Request,
    page: int = 1,
    month: str | None = None,
    tag: str | None = None,
    ledger_id: str | None = None,
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
    return templates.TemplateResponse(request=request, name="confirmed.html", context=ctx)
