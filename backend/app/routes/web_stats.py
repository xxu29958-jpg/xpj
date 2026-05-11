"""/web/stats page (monthly overview).

Split from ``web_app.py`` to keep each /web route module under 280 lines.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expense
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    templates,
)
from app.services.insights_service import recurring_candidates
from app.services.stats_service import monthly_stats

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/stats", response_class=HTMLResponse)
def web_stats(
    request: Request,
    month: str | None = None,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    if not month:
        month = datetime.now().strftime("%Y-%m")
    stats = monthly_stats(db, month, selected_id)

    by_category = [
        {
            "category": row["category"],
            "amount_yuan": _amount_yuan(int(row["amount_cents"])),
            "count": int(row["count"]),
        }
        for row in stats["by_category"]
    ]

    top_rows: list[dict[str, str]] = []
    top_query = (
        select(Expense)
        .where(Expense.tenant_id == selected_id)
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .order_by(Expense.amount_cents.desc())
        .limit(10)
    )
    for e in db.scalars(top_query).all():
        if e.expense_time and e.expense_time.strftime("%Y-%m") != month:
            continue
        top_rows.append(
            {
                "merchant": e.merchant or "未填写商家",
                "amount_yuan": _amount_yuan(e.amount_cents),
                "category": e.category or "未分类",
                "expense_time": e.expense_time.strftime("%Y-%m-%d") if e.expense_time else "",
            }
        )
        if len(top_rows) >= 5:
            break

    try:
        rc_items = recurring_candidates(
            db, tenant_id=selected_id, timezone_name="Asia/Shanghai"
        )
    except Exception:  # noqa: BLE001 - stats page must never 500 on insight
        rc_items = []
    recurring = [
        {
            "merchant": item["merchant"],
            "amount_yuan": _amount_yuan(int(item["amount_cents"])),
            "occurrence_count": item["occurrence_count"],
            "confidence": item["confidence"],
            "reason": item["reason"],
        }
        for item in rc_items[:5]
    ]

    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["month"] = month
    ctx["total_amount_yuan"] = _amount_yuan(int(stats["total_amount_cents"]))
    ctx["count"] = int(stats["count"])
    ctx["by_category"] = by_category
    ctx["top_expenses"] = top_rows
    ctx["recurring_candidates"] = recurring
    return templates.TemplateResponse(request=request, name="stats.html", context=ctx)
