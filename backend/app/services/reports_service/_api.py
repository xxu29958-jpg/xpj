"""Public reports API: overview / six-month summary / CSV export."""

from __future__ import annotations

import csv
import logging
from io import StringIO
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.money_contract import projection_sum_to_int
from app.services.category_service import normalize_category
from app.services.csv_security import safe_csv_cell
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import (
    minor_amount_major_number,
    minor_amount_value,
)
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


def _overview_range_totals(
    db: Session,
    *,
    tenant_id: str,
    current: tuple[Any, Any],
    previous: tuple[Any, Any],
    year_over_year: tuple[Any, Any],
    timezone_name: str,
) -> dict[str, tuple[int, int]]:
    return _range_amount_counts(
        db,
        tenant_id=tenant_id,
        ranges={
            "current": current,
            "previous": previous,
            "year_over_year": year_over_year,
        },
        timezone_name=timezone_name,
    )


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
    normalized_merchant_category = normalize_category(merchant_category) if merchant_category else None
    current_start_utc, current_end_utc = _month_bounds(month, timezone_key)
    previous_month = _shift_month(month, -1)
    previous_start_utc, previous_end_utc = _month_bounds(previous_month, timezone_key)
    year_over_year_month = _shift_month(month, -12)
    yoy_start_utc, yoy_end_utc = _month_bounds(year_over_year_month, timezone_key)
    range_totals = _overview_range_totals(
        db,
        tenant_id=tenant_id,
        current=(current_start_utc, current_end_utc),
        previous=(previous_start_utc, previous_end_utc),
        year_over_year=(yoy_start_utc, yoy_end_utc),
        timezone_name=timezone_key,
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
        "year_over_year_delta_amount_cents": (
            projection_sum_to_int(
                total_amount - yoy_total,
                label="reports.overview_yoy_delta",
            )
        ),
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
            timezone_name=timezone_key,
        ),
        "category_comparison": _category_comparison(
            db,
            tenant_id=tenant_id,
            current=(current_start_utc, current_end_utc),
            previous=(previous_start_utc, previous_end_utc),
            year_over_year=(yoy_start_utc, yoy_end_utc),
            timezone_name=timezone_key,
        ),
    }


def six_month_summary(
    db: Session,
    *,
    anchor_month: str,
    tenant_id: str,
    timezone_name: str | None = None,
    currency_code: str | None = None,
) -> list[dict]:
    """6 个月（含锚定月）的逐月已确认支出 + 预算汇总。

    供 /web/reports 的「六个月，看清节奏」柱+线图使用。返回顺序：最早 → 锚定月。
    每项 {'month', 'amount_cents', 'amount_yuan', 'count', 'budget_cents', 'budget_yuan'}。
    """
    timezone_key, _zone = _resolve_timezone(timezone_name)
    # 避免循环导入：budget_service 没有反向依赖 reports_service。
    from app.services.budget_service import get_monthly_budget

    home = currency_code or require_runtime_home_currency_code(db)
    results: list[dict] = []
    for month_label in _month_labels_ending_at(anchor_month, 6):
        start_utc, end_utc = _month_bounds(month_label, timezone_key)
        amount, count = _range_amount_count(
            db,
            tenant_id=tenant_id,
            start_utc=start_utc,
            end_utc=end_utc,
            timezone_name=timezone_key,
        )
        try:
            budget = get_monthly_budget(
                db, tenant_id=tenant_id, month=month_label, timezone_name=timezone_key
            )
            budget_cents = 0
            if budget.configured:
                budget_cents = projection_sum_to_int(
                    projection_sum_to_int(
                        budget.total_amount_cents,
                        label="reports.budget_total",
                    )
                    + projection_sum_to_int(
                        budget.rollover_amount_cents,
                        label="reports.budget_rollover",
                    ),
                    label="reports.budget_available",
                )
        except AppError as exc:
            if exc.error == "money_projection_out_of_range":
                raise
            logger.exception(
                "reports trend6: get_monthly_budget failed for ledger=%s month=%s",
                tenant_id,
                month_label,
            )
            budget_cents = 0
        except SQLAlchemyError:
            logger.exception(
                "reports trend6: get_monthly_budget failed for ledger=%s month=%s",
                tenant_id,
                month_label,
            )
            budget_cents = 0
        results.append(
            {
                "month": month_label,
                "amount_cents": amount,
                "amount_yuan": minor_amount_major_number(amount, home),
                "amount_major_text": minor_amount_value(amount, home),
                "count": int(count),
                "budget_cents": budget_cents,
                "budget_yuan": minor_amount_major_number(budget_cents, home),
                "budget_major_text": minor_amount_value(budget_cents, home),
            }
        )
    return results


def _write_overview_summary(writer: Any, overview: dict) -> None:
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


def _write_overview_trend(writer: Any, overview: dict) -> None:
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


def _write_overview_merchant_ranking(writer: Any, overview: dict) -> None:
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


def _write_overview_category_comparison(writer: Any, overview: dict) -> None:
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
    _write_overview_summary(writer, overview)
    _write_overview_trend(writer, overview)
    _write_overview_merchant_ranking(writer, overview)
    _write_overview_category_comparison(writer, overview)
    return output.getvalue()
