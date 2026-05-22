"""/web/reports page backed by the v0.9 reports service."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.services.reports_service import (
    export_reports_overview_csv,
    reports_overview,
    six_month_summary,
)
from app.services.time_service import current_month

router = APIRouter(prefix="/web/reports", tags=["web"])

_GRANULARITIES = {"day", "week", "month"}
_RANKING_METRICS = {"amount", "count"}


def _clean_granularity(value: str | None) -> str:
    clean = (value or "day").strip().lower()
    return clean if clean in _GRANULARITIES else "day"


def _clean_ranking_metric(value: str | None) -> str:
    clean = (value or "amount").strip().lower()
    return clean if clean in _RANKING_METRICS else "amount"


def _percent(value: int, maximum: int) -> int:
    if maximum <= 0:
        return 0
    return max(2, min(100, round(value * 100 / maximum)))


def _view_model(payload: dict) -> dict:
    max_trend = max([int(point["amount_cents"]) for point in payload["trend"]] or [0])
    max_merchant = max([int(row["amount_cents"]) for row in payload["merchant_ranking"]] or [0])
    max_category = max(
        [max(int(row["amount_cents"]), int(row["previous_amount_cents"])) for row in payload["category_comparison"]]
        or [0]
    )
    return {
        "month": payload["month"],
        "timezone": payload["timezone"],
        "granularity": payload["granularity"],
        "ranking_metric": payload["ranking_metric"],
        "merchant_category": payload["merchant_category"] or "",
        "total_amount_yuan": _amount_yuan(int(payload["total_amount_cents"])),
        "count": int(payload["count"]),
        "previous_month": payload["previous_month"],
        "previous_total_amount_yuan": _amount_yuan(int(payload["previous_total_amount_cents"])),
        "previous_count": int(payload["previous_count"]),
        "trend": [
            {
                "bucket": point["bucket"],
                "label": point["label"],
                "amount_yuan": _amount_yuan(int(point["amount_cents"])),
                "amount_cents": int(point["amount_cents"]),
                "count": int(point["count"]),
                "percent": _percent(int(point["amount_cents"]), max_trend),
            }
            for point in payload["trend"]
        ],
        "merchant_ranking": [
            {
                "merchant": row["merchant"],
                "amount_yuan": _amount_yuan(int(row["amount_cents"])),
                "amount_cents": int(row["amount_cents"]),
                "count": int(row["count"]),
                "percent": _percent(int(row["amount_cents"]), max_merchant),
            }
            for row in payload["merchant_ranking"]
        ],
        "category_comparison": [
            {
                "category": row["category"],
                "amount_yuan": _amount_yuan(int(row["amount_cents"])),
                "previous_amount_yuan": _amount_yuan(int(row["previous_amount_cents"])),
                "delta_amount_yuan": _amount_yuan(int(row["delta_amount_cents"])),
                "amount_cents": int(row["amount_cents"]),
                "previous_amount_cents": int(row["previous_amount_cents"]),
                "delta_amount_cents": int(row["delta_amount_cents"]),
                "count": int(row["count"]),
                "previous_count": int(row["previous_count"]),
                "delta_count": int(row["delta_count"]),
                "current_percent": _percent(int(row["amount_cents"]), max_category),
                "previous_percent": _percent(int(row["previous_amount_cents"]), max_category),
            }
            for row in payload["category_comparison"]
        ],
    }


@router.get("", response_class=HTMLResponse)
def web_reports(
    request: Request,
    month: str | None = None,
    granularity: str | None = None,
    ranking_metric: str | None = None,
    merchant_category: str | None = Query(default=None, max_length=64),
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    selected_granularity = _clean_granularity(granularity)
    selected_metric = _clean_ranking_metric(ranking_metric)
    payload = reports_overview(
        db,
        month=target_month,
        tenant_id=selected_id,
        timezone_name=timezone_name,
        granularity=selected_granularity,
        ranking_metric=selected_metric,
        merchant_category=merchant_category,
    )
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="报表",
        show_month_picker=True,
        selected_month=target_month,
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx.update(
        {
            "report": _view_model(payload),
            "report_export_query": urlencode(
                {
                    "ledger_id": selected_id,
                    "month": target_month,
                    "granularity": selected_granularity,
                    "ranking_metric": selected_metric,
                    "merchant_category": (merchant_category or "").strip(),
                }
            ),
            "month": target_month,
            "granularity_options": [("day", "日"), ("week", "周"), ("month", "月")],
            "ranking_metric_options": [("amount", "金额"), ("count", "笔数")],
            "six_month_trend": six_month_summary(
                db,
                anchor_month=target_month,
                tenant_id=selected_id,
                timezone_name=timezone_name,
            ),
        }
    )
    return templates.TemplateResponse(request=request, name="reports.html", context=ctx)


@router.get("/export.csv")
def web_reports_csv(
    request: Request,
    month: str | None = None,
    granularity: str | None = None,
    ranking_metric: str | None = None,
    merchant_category: str | None = Query(default=None, max_length=64),
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    selected_granularity = _clean_granularity(granularity)
    selected_metric = _clean_ranking_metric(ranking_metric)
    content = "\ufeff" + export_reports_overview_csv(
        db,
        month=target_month,
        tenant_id=selected_id,
        timezone_name=timezone_name,
        granularity=selected_granularity,
        ranking_metric=selected_metric,
        merchant_category=merchant_category,
    )
    filename = f"ticketbox-web-reports-{target_month}-{selected_granularity}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
