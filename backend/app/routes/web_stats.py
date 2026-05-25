"""/web/stats page (monthly overview).

Split from ``web_app.py`` to keep each /web route module under 280 lines.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    templates,
)
from app.services.insights_service import recurring_candidates
from app.services.recurring_service import list_recurring_items, recurring_amount_anomalies
from app.services.spending_contract_service import (
    current_accounting_month,
    default_accounting_timezone_name,
)
from app.services.stats_service import monthly_stats, top_expenses_for_month

router = APIRouter(prefix="/web", tags=["web"])
logger = logging.getLogger(__name__)


def _build_by_category(stats: dict) -> list[dict]:
    return [
        {
            "category": row["category"],
            "amount_yuan": _amount_yuan(int(row["amount_cents"])),
            "count": int(row["count"]),
        }
        for row in stats["by_category"]
    ]


def _build_top_rows(
    db: Session, *, tenant_id: str, month: str, tag: str | None, timezone_name: str
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for e in top_expenses_for_month(
        db, tenant_id=tenant_id, month=month, tag=tag, timezone_name=timezone_name
    ):
        rows.append(
            {
                "merchant": e.merchant or "未填写商家",
                "amount_yuan": _amount_yuan(e.amount_cents),
                "category": e.category or "未分类",
                "expense_time": e.expense_time.strftime("%Y-%m-%d") if e.expense_time else "",
            }
        )
    return rows


def _build_recurring_candidates_view(
    db: Session, *, tenant_id: str, timezone_name: str
) -> tuple[list[dict], bool]:
    """Return (view rows, error flag). Always succeeds; insight failure
    surfaces as an empty list + error flag rather than HTTP 500."""
    try:
        rc_items = recurring_candidates(
            db, tenant_id=tenant_id, timezone_name=timezone_name
        )
    except Exception:  # noqa: BLE001 - stats page must never 500 on insight
        logger.warning("Recurring candidate insight failed for /web/stats.", exc_info=True)
        return [], True
    return [
        {
            "merchant": item["merchant"],
            "amount_yuan": _amount_yuan(int(item["amount_cents"])),
            "occurrence_count": item["occurrence_count"],
            "confidence": item["confidence"],
            "reason": item["reason"],
        }
        for item in rc_items[:5]
    ], False


def _build_recurring_formal_view(
    db: Session, *, tenant_id: str, month: str, timezone_name: str
) -> list[dict]:
    items = list_recurring_items(db, tenant_id=tenant_id, include_archived=False)
    anomalies = recurring_amount_anomalies(
        db, tenant_id=tenant_id, items=items, month=month, timezone_name=timezone_name
    )
    formal: list[dict] = []
    for item in items[:8]:
        anomaly = anomalies.get(item.public_id)
        formal.append(
            {
                "merchant": item.merchant_name,
                "amount_yuan": _amount_yuan(item.last_amount_cents),
                "status": item.status,
                "next_expected_date": item.next_expected_date.isoformat()
                if item.next_expected_date
                else "",
                "anomaly_status": anomaly.anomaly_status if anomaly else "none",
            }
        )
    return formal


@router.get("/stats", response_class=HTMLResponse)
def web_stats(
    request: Request,
    month: str | None = None,
    tag: str | None = None,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    timezone_name = default_accounting_timezone_name()
    if not month:
        month = current_accounting_month(timezone_name)
    stats = monthly_stats(db, month, selected_id, tag=tag, timezone_name=timezone_name)
    recurring, recurring_error = _build_recurring_candidates_view(
        db, tenant_id=selected_id, timezone_name=timezone_name
    )

    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["month"] = month
    ctx["tag"] = tag or ""
    ctx["total_amount_yuan"] = _amount_yuan(int(stats["total_amount_cents"]))
    ctx["count"] = int(stats["count"])
    ctx["by_category"] = _build_by_category(stats)
    ctx["top_expenses"] = _build_top_rows(
        db, tenant_id=selected_id, month=month, tag=tag, timezone_name=timezone_name
    )
    ctx["recurring_candidates"] = recurring
    ctx["recurring_candidates_error"] = recurring_error
    ctx["recurring_formal"] = _build_recurring_formal_view(
        db, tenant_id=selected_id, month=month, timezone_name=timezone_name
    )
    return templates.TemplateResponse(request=request, name="stats.html", context=ctx)
