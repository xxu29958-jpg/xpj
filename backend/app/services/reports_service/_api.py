"""Public reports API: overview / six-month summary / CSV export."""

from __future__ import annotations

import csv
import logging
from io import StringIO

from sqlalchemy.orm import Session

from app.services.category_service import normalize_category
from app.services.csv_security import safe_csv_cell
from app.services.reports_service._aggregation import (
    _range_amount_count,
    _range_amount_counts,
    _trend_points,
)
from app.services.reports_service._models import (
    ReportGranularity,
    ReportRankingMetric,
)
from app.services.reports_service._ranking import (
    _category_comparison,
    _merchant_ranking,
)
from app.services.reports_service._time import (
    _month_bounds,
    _month_labels_ending_at,
    _parse_month,
    _resolve_timezone,
    _shift_month,
)

logger = logging.getLogger(__name__)


def reports_overview(
    db: Session,
    *,
    month: str,
    tenant_id: str,
    timezone_name: str | None = None,
    granularity: ReportGranularity = "day",
    top_n: int = 8,
    merchant_category: str | None = None,
    ranking_metric: ReportRankingMetric = "amount",
) -> dict:
    _parse_month(month)
    timezone_key, zone = _resolve_timezone(timezone_name)
    normalized_merchant_category = (
        normalize_category(merchant_category) if merchant_category else None
    )
    current_start_utc, current_end_utc = _month_bounds(month, timezone_key)
    previous_month = _shift_month(month, -1)
    previous_start_utc, previous_end_utc = _month_bounds(previous_month, timezone_key)
    year_over_year_month = _shift_month(month, -12)
    yoy_start_utc, yoy_end_utc = _month_bounds(year_over_year_month, timezone_key)
    range_totals = _range_amount_counts(
        db,
        tenant_id=tenant_id,
        ranges={
            "current": (current_start_utc, current_end_utc),
            "previous": (previous_start_utc, previous_end_utc),
            "year_over_year": (yoy_start_utc, yoy_end_utc),
        },
    )
    total_amount, count = range_totals["current"]
    previous_total, previous_count = range_totals["previous"]
    yoy_total, yoy_count = range_totals["year_over_year"]
    return {
        "month": month,
        "timezone": timezone_key,
        "granularity": granularity,
        "total_amount_cents": total_amount,
        "count": count,
        "previous_month": previous_month,
        "previous_total_amount_cents": previous_total,
        "previous_count": previous_count,
        "year_over_year_month": year_over_year_month,
        "year_over_year_total_amount_cents": yoy_total,
        "year_over_year_count": yoy_count,
        "year_over_year_delta_amount_cents": total_amount - yoy_total,
        "year_over_year_delta_count": count - yoy_count,
        "merchant_category": normalized_merchant_category,
        "ranking_metric": ranking_metric,
        "trend": _trend_points(
            db,
            tenant_id=tenant_id,
            month=month,
            granularity=granularity,
            timezone_name=timezone_key,
            zone=zone,
        ),
        "merchant_ranking": _merchant_ranking(
            db,
            tenant_id=tenant_id,
            start_utc=current_start_utc,
            end_utc=current_end_utc,
            top_n=top_n,
            category=merchant_category,
            ranking_metric=ranking_metric,
        ),
        "category_comparison": _category_comparison(
            db,
            tenant_id=tenant_id,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
            year_over_year_start_utc=yoy_start_utc,
            year_over_year_end_utc=yoy_end_utc,
        ),
    }


def six_month_summary(
    db: Session,
    *,
    anchor_month: str,
    tenant_id: str,
    timezone_name: str | None = None,
) -> list[dict]:
    """6 个月（含锚定月）的逐月已确认支出 + 预算汇总。

    供 /web/reports 的「六个月，看清节奏」柱+线图使用。返回顺序：最早 → 锚定月。
    每项 {'month', 'amount_cents', 'amount_yuan', 'count', 'budget_cents', 'budget_yuan'}。
    """
    timezone_key, _zone = _resolve_timezone(timezone_name)
    # 避免循环导入：budget_service 没有反向依赖 reports_service。
    from app.services.budget_service import get_monthly_budget

    results: list[dict] = []
    for month_label in _month_labels_ending_at(anchor_month, 6):
        start_utc, end_utc = _month_bounds(month_label, timezone_key)
        amount, count = _range_amount_count(
            db,
            tenant_id=tenant_id,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        try:
            budget = get_monthly_budget(
                db, tenant_id=tenant_id, month=month_label, timezone_name=timezone_key
            )
            budget_cents = (
                int(budget.total_amount_cents) + int(budget.rollover_amount_cents)
                if budget.configured
                else 0
            )
        except Exception:
            logger.exception(
                "reports trend6: get_monthly_budget failed for ledger=%s month=%s",
                tenant_id,
                month_label,
            )
            budget_cents = 0
        results.append(
            {
                "month": month_label,
                "amount_cents": int(amount),
                "amount_yuan": int(amount) / 100.0,
                "count": int(count),
                "budget_cents": budget_cents,
                "budget_yuan": budget_cents / 100.0,
            }
        )
    return results


def export_reports_overview_csv(
    db: Session,
    *,
    month: str,
    tenant_id: str,
    timezone_name: str | None = None,
    granularity: ReportGranularity = "day",
    top_n: int = 8,
    merchant_category: str | None = None,
    ranking_metric: ReportRankingMetric = "amount",
) -> str:
    overview = reports_overview(
        db,
        month=month,
        tenant_id=tenant_id,
        timezone_name=timezone_name,
        granularity=granularity,
        top_n=top_n,
        merchant_category=merchant_category,
        ranking_metric=ranking_metric,
    )
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["section", "field", "value"])
    for field in [
        "month",
        "timezone",
        "granularity",
        "total_amount_cents",
        "count",
        "previous_month",
        "previous_total_amount_cents",
        "previous_count",
        "year_over_year_month",
        "year_over_year_total_amount_cents",
        "year_over_year_count",
        "year_over_year_delta_amount_cents",
        "year_over_year_delta_count",
        "merchant_category",
        "ranking_metric",
    ]:
        value = overview.get(field)
        writer.writerow(["summary", field, "" if value is None else safe_csv_cell(value)])
    writer.writerow([])
    writer.writerow(["section", "bucket", "label", "amount_cents", "count"])
    for point in overview["trend"]:
        writer.writerow(
            [
                "trend",
                safe_csv_cell(point["bucket"]),
                safe_csv_cell(point["label"]),
                point["amount_cents"],
                point["count"],
            ]
        )
    writer.writerow([])
    writer.writerow(["section", "rank", "merchant", "amount_cents", "count"])
    for index, item in enumerate(overview["merchant_ranking"], start=1):
        writer.writerow(
            [
                "merchant_ranking",
                index,
                safe_csv_cell(item["merchant"]),
                item["amount_cents"],
                item["count"],
            ]
        )
    writer.writerow([])
    writer.writerow(
        [
            "section",
            "category",
            "amount_cents",
            "count",
            "previous_amount_cents",
            "previous_count",
            "delta_amount_cents",
            "delta_count",
            "year_over_year_amount_cents",
            "year_over_year_count",
            "year_over_year_delta_amount_cents",
            "year_over_year_delta_count",
        ]
    )
    for item in overview["category_comparison"]:
        writer.writerow(
            [
                "category_comparison",
                safe_csv_cell(item["category"]),
                item["amount_cents"],
                item["count"],
                item["previous_amount_cents"],
                item["previous_count"],
                item["delta_amount_cents"],
                item["delta_count"],
                item["year_over_year_amount_cents"],
                item["year_over_year_count"],
                item["year_over_year_delta_amount_cents"],
                item["year_over_year_delta_count"],
            ]
        )
    return output.getvalue()
