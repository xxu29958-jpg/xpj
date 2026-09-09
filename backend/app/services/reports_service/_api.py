"""Period report and CSV publication from one projected set of confirmed entries."""

import csv
from io import StringIO
from typing import Any

from sqlalchemy.orm import Session

from app.services.category_service import normalize_category
from app.services.csv_security import safe_csv_cell
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code
from app.services.reports_service._aggregation import (
    _amount_count,
    _amount_delta,
    _entries_in_range,
    _trend_buckets,
    _trend_points,
)
from app.services.reports_service._models import ReportGranularity, ReportRankingMetric
from app.services.reports_service._ranking import _category_comparison, _merchant_ranking
from app.services.reports_service._time import _month_bounds, _parse_month, _resolve_timezone, _shift_month
from app.services.spending_projection_service import entry_gaps, read_projected_entries


def reports_overview(db: Session, *, month: str, tenant_id: str,
    timezone_name: str | None = None, granularity: ReportGranularity = "day", top_n: int = 8,
    merchant_category: str | None = None, ranking_metric: ReportRankingMetric = "amount",
    home_currency_code: str | None = None,
) -> dict:
    _parse_month(month)
    timezone_key, zone = _resolve_timezone(timezone_name)
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    previous_month, yoy_month = _shift_month(month, -1), _shift_month(month, -12)
    periods = [_month_bounds(label, timezone_key) for label in (month, previous_month, yoy_month)]
    buckets = _trend_buckets(month=month, granularity=granularity, timezone_name=timezone_key, zone=zone)
    entries = read_projected_entries(db, tenant_id=tenant_id, home=home, timezone_name=timezone_key,
        ranges=periods + [(bucket.start_utc, bucket.end_utc) for bucket in buckets])
    current, previous, yoy = [_entries_in_range(entries, period, zone) for period in periods]
    total_amount, count = _amount_count(current)
    previous_total, previous_count = _amount_count(previous)
    yoy_total, yoy_count = _amount_count(yoy)
    return {
        "month": month, "timezone": timezone_key, "home_currency_code": home,
        "missing_rates": entry_gaps(entries), "granularity": granularity,
        "total_amount_cents": total_amount, "count": count,
        "previous_month": previous_month, "previous_total_amount_cents": previous_total, "previous_count": previous_count,
        "year_over_year_month": yoy_month, "year_over_year_total_amount_cents": yoy_total, "year_over_year_count": yoy_count,
        "year_over_year_delta_amount_cents": _amount_delta(total_amount, yoy_total),
        "year_over_year_delta_count": count - yoy_count,
        "merchant_category": normalize_category(merchant_category) if merchant_category else None,
        "ranking_metric": ranking_metric, "trend": _trend_points(entries, buckets, zone),
        "merchant_ranking": _merchant_ranking(db, current, tenant_id=tenant_id, top_n=top_n,
            category=merchant_category, ranking_metric=ranking_metric),
        "category_comparison": _category_comparison(current, previous, yoy),
    }


def _write_overview_summary(writer: Any, overview: dict) -> None:
    writer.writerow(["section", "field", "value"])
    for field in [
        "month",
        "timezone",
        "home_currency_code",
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
    home_currency_code: str | None = None,
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
        home_currency_code=home_currency_code,
    )
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    _write_overview_summary(writer, overview)
    _write_overview_trend(writer, overview)
    _write_overview_merchant_ranking(writer, overview)
    _write_overview_category_comparison(writer, overview)
    writer.writerow([])
    writer.writerow(["section", "source_currency_code", "home_currency_code", "rate_date"])
    for gap in overview["missing_rates"]:
        writer.writerow(["missing_rates", gap.source_currency_code or "", gap.home_currency_code,
            gap.rate_date.isoformat() if gap.rate_date is not None else ""])
    return output.getvalue()
