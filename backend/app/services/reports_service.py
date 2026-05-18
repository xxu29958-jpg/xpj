from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ledger_scope import add_ledger_scope
from app.models import Expense
from app.services.category_service import category_filter_values, normalize_category
from app.services.csv_security import safe_csv_cell
from app.services.merchant_alias_service import canonical_merchant_for
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.spending_contract_service import (
    enabled_merchant_display_map,
    month_bounds_utc,
    month_labels_ending_at,
    parse_month,
    resolve_accounting_timezone,
    shift_month,
    stat_time_expr,
)

ReportGranularity = Literal["day", "week", "month"]
ReportRankingMetric = Literal["amount", "count"]


@dataclass(frozen=True)
class _TrendBucket:
    bucket: str
    label: str
    start_utc: datetime
    end_utc: datetime


def _stat_time_expr():
    return stat_time_expr()


def _resolve_timezone(timezone_name: str | None) -> tuple[str, ZoneInfo]:
    return resolve_accounting_timezone(timezone_name)


def _parse_month(month: str) -> tuple[int, int]:
    return parse_month(month)


def _shift_month(month: str, offset: int) -> str:
    return shift_month(month, offset)


def _month_labels_ending_at(month: str, count: int) -> list[str]:
    return month_labels_ending_at(month, count)


def _days_in_month(month: str, zone: ZoneInfo) -> list[date]:
    start_utc, end_utc = month_bounds_utc(month, zone.key)
    cursor = start_utc.astimezone(zone).date()
    end_date = end_utc.astimezone(zone).date()
    days: list[date] = []
    while cursor < end_date:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _local_day_bounds_utc(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime(day.year, day.month, day.day, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _local_date_range_bounds_utc(
    start_day: date,
    end_day_exclusive: date,
    zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    start_local = datetime(start_day.year, start_day.month, start_day.day, tzinfo=zone)
    end_local = datetime(
        end_day_exclusive.year,
        end_day_exclusive.month,
        end_day_exclusive.day,
        tzinfo=zone,
    )
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _range_amount_count(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[int, int]:
    stat_time = _stat_time_expr()
    statement = (
        add_ledger_scope(
            select(
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ),
            Expense,
            tenant_id,
        )
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )
    row = db.execute(statement).one()
    return int(row[0] or 0), int(row[1] or 0)


def _month_bounds(month: str, timezone_name: str) -> tuple[datetime, datetime]:
    return month_bounds_utc(month, timezone_name)


def _trend_buckets(
    *,
    month: str,
    granularity: ReportGranularity,
    timezone_name: str,
    zone: ZoneInfo,
) -> list[_TrendBucket]:
    if granularity == "month":
        buckets: list[_TrendBucket] = []
        for label in _month_labels_ending_at(month, 6):
            start_utc, end_utc = _month_bounds(label, timezone_name)
            buckets.append(
                _TrendBucket(
                    bucket=label,
                    label=label,
                    start_utc=start_utc,
                    end_utc=end_utc,
                )
            )
        return buckets

    days = _days_in_month(month, zone)
    if granularity == "week":
        month_start = days[0]
        month_end_exclusive = days[-1] + timedelta(days=1)
        week_starts = sorted({day - timedelta(days=day.weekday()) for day in days})
        buckets = []
        for week_start in week_starts:
            week_end_exclusive = week_start + timedelta(days=7)
            start_day = max(week_start, month_start)
            end_day = min(week_end_exclusive, month_end_exclusive)
            start_utc, end_utc = _local_date_range_bounds_utc(start_day, end_day, zone)
            label_end = end_day - timedelta(days=1)
            buckets.append(
                _TrendBucket(
                    bucket=week_start.isoformat(),
                    label=f"{start_day.strftime('%m-%d')}~{label_end.strftime('%m-%d')}",
                    start_utc=start_utc,
                    end_utc=end_utc,
                )
            )
        return buckets

    buckets = []
    for day in days:
        start_utc, end_utc = _local_day_bounds_utc(day, zone)
        buckets.append(
            _TrendBucket(
                bucket=day.isoformat(),
                label=day.strftime("%m-%d"),
                start_utc=start_utc,
                end_utc=end_utc,
            )
        )
    return buckets


def _bucket_amount_counts(
    db: Session,
    *,
    tenant_id: str,
    buckets: list[_TrendBucket],
) -> dict[str, tuple[int, int]]:
    if not buckets:
        return {}
    stat_time = _stat_time_expr()
    columns = []
    for index, bucket in enumerate(buckets):
        in_bucket = (stat_time >= bucket.start_utc) & (stat_time < bucket.end_utc)
        columns.extend(
            [
                func.coalesce(
                    func.sum(case((in_bucket, Expense.amount_cents), else_=0)),
                    0,
                ).label(f"amount_{index}"),
                func.coalesce(
                    func.sum(case((in_bucket, 1), else_=0)),
                    0,
                ).label(f"count_{index}"),
            ]
        )
    statement = (
        add_ledger_scope(select(*columns), Expense, tenant_id)
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= min(bucket.start_utc for bucket in buckets))
        .where(stat_time < max(bucket.end_utc for bucket in buckets))
    )
    row = db.execute(statement).one()
    return {
        bucket.bucket: (int(row[index * 2] or 0), int(row[index * 2 + 1] or 0))
        for index, bucket in enumerate(buckets)
    }


def _trend_points(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    granularity: ReportGranularity,
    timezone_name: str,
    zone: ZoneInfo,
) -> list[dict]:
    buckets = _trend_buckets(
        month=month,
        granularity=granularity,
        timezone_name=timezone_name,
        zone=zone,
    )
    totals = _bucket_amount_counts(db, tenant_id=tenant_id, buckets=buckets)
    return [
        {
            "bucket": bucket.bucket,
            "label": bucket.label,
            "amount_cents": totals.get(bucket.bucket, (0, 0))[0],
            "count": totals.get(bucket.bucket, (0, 0))[1],
        }
        for bucket in buckets
    ]


def _canonical_display(merchant: str, alias_map: dict[str, str]) -> str:
    display = display_merchant(merchant)
    if not display:
        return "未填写商家"
    canonical = display_merchant(canonical_merchant_for(display, alias_map=alias_map))
    return canonical or display


def _category_filter_values(category: str | None) -> set[str]:
    return category_filter_values(category)


def _merchant_ranking(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
    top_n: int,
    category: str | None,
    ranking_metric: ReportRankingMetric,
) -> list[dict]:
    stat_time = _stat_time_expr()
    statement = (
        add_ledger_scope(
            select(
                func.coalesce(Expense.merchant, ""),
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(func.coalesce(Expense.merchant, "")),
            Expense,
            tenant_id,
        )
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )
    if category:
        statement = statement.where(
            Expense.category.in_(_category_filter_values(category))
        )
    rows = db.execute(statement)
    alias_map = enabled_merchant_display_map(db, tenant_id=tenant_id)
    buckets: dict[str, dict[str, int | str]] = defaultdict(
        lambda: {"merchant": "", "amount_cents": 0, "count": 0}
    )
    for merchant_raw, amount_value, count_value in rows:
        display = _canonical_display(str(merchant_raw or ""), alias_map)
        key = normalize_merchant(display) or "__empty_merchant__"
        bucket = buckets[key]
        bucket["merchant"] = display
        bucket["amount_cents"] = int(bucket["amount_cents"]) + int(amount_value or 0)
        bucket["count"] = int(bucket["count"]) + int(count_value or 0)
    if ranking_metric == "count":
        return sorted(
            buckets.values(),
            key=lambda item: (
                -int(item["count"]),
                -int(item["amount_cents"]),
                str(item["merchant"]),
            ),
        )[:top_n]
    return sorted(
        buckets.values(),
        key=lambda item: (
            -int(item["amount_cents"]),
            -int(item["count"]),
            str(item["merchant"]),
        ),
    )[:top_n]


def _category_totals(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, dict[str, int | str]]:
    stat_time = _stat_time_expr()
    statement = (
        add_ledger_scope(
            select(
                Expense.category,
                func.coalesce(func.sum(Expense.amount_cents), 0),
                func.count(Expense.id),
            ).group_by(Expense.category),
            Expense,
            tenant_id,
        )
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= start_utc)
        .where(stat_time < end_utc)
    )
    rows = db.execute(statement)
    buckets: dict[str, dict[str, int | str]] = defaultdict(
        lambda: {"category": "", "amount_cents": 0, "count": 0}
    )
    for category_raw, amount_value, count_value in rows:
        category = normalize_category(category_raw)
        bucket = buckets[category]
        bucket["category"] = category
        bucket["amount_cents"] = int(bucket["amount_cents"]) + int(amount_value or 0)
        bucket["count"] = int(bucket["count"]) + int(count_value or 0)
    return buckets


def _category_comparison(
    db: Session,
    *,
    tenant_id: str,
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: datetime,
    previous_end_utc: datetime,
) -> list[dict]:
    current = _category_totals(
        db,
        tenant_id=tenant_id,
        start_utc=current_start_utc,
        end_utc=current_end_utc,
    )
    previous = _category_totals(
        db,
        tenant_id=tenant_id,
        start_utc=previous_start_utc,
        end_utc=previous_end_utc,
    )
    items: list[dict] = []
    for category in set(current) | set(previous):
        current_item = current.get(category, {"amount_cents": 0, "count": 0})
        previous_item = previous.get(category, {"amount_cents": 0, "count": 0})
        amount = int(current_item["amount_cents"])
        prev_amount = int(previous_item["amount_cents"])
        count = int(current_item["count"])
        prev_count = int(previous_item["count"])
        items.append(
            {
                "category": category,
                "amount_cents": amount,
                "count": count,
                "previous_amount_cents": prev_amount,
                "previous_count": prev_count,
                "delta_amount_cents": amount - prev_amount,
                "delta_count": count - prev_count,
            }
        )
    return sorted(
        items,
        key=lambda item: (
            -int(item["amount_cents"]),
            -int(item["previous_amount_cents"]),
            str(item["category"]),
        ),
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
    normalized_merchant_category = (
        normalize_category(merchant_category) if merchant_category else None
    )
    current_start_utc, current_end_utc = _month_bounds(month, timezone_key)
    previous_month = _shift_month(month, -1)
    previous_start_utc, previous_end_utc = _month_bounds(previous_month, timezone_key)
    total_amount, count = _range_amount_count(
        db,
        tenant_id=tenant_id,
        start_utc=current_start_utc,
        end_utc=current_end_utc,
    )
    previous_total, previous_count = _range_amount_count(
        db,
        tenant_id=tenant_id,
        start_utc=previous_start_utc,
        end_utc=previous_end_utc,
    )
    return {
        "month": month,
        "timezone": timezone_key,
        "granularity": granularity,
        "total_amount_cents": total_amount,
        "count": count,
        "previous_month": previous_month,
        "previous_total_amount_cents": previous_total,
        "previous_count": previous_count,
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
            ]
        )
    return output.getvalue()
