"""Range and per-bucket amount/count aggregation over confirmed expenses."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ledger_scope import add_ledger_scope
from app.models import Expense
from app.services.reports_service._models import ReportGranularity, _TrendBucket
from app.services.reports_service._time import (
    _days_in_month,
    _local_date_range_bounds_utc,
    _local_day_bounds_utc,
    _month_bounds,
    _month_labels_ending_at,
    _stat_time_expr,
)


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


def _range_amount_counts(
    db: Session,
    *,
    tenant_id: str,
    ranges: dict[str, tuple[datetime, datetime]],
) -> dict[str, tuple[int, int]]:
    if not ranges:
        return {}
    stat_time = _stat_time_expr()
    columns = []
    labels = list(ranges)
    for index, label in enumerate(labels):
        start_utc, end_utc = ranges[label]
        in_range = (stat_time >= start_utc) & (stat_time < end_utc)
        columns.extend(
            [
                func.coalesce(
                    func.sum(case((in_range, Expense.amount_cents), else_=0)),
                    0,
                ).label(f"amount_{index}"),
                func.coalesce(
                    func.sum(case((in_range, 1), else_=0)),
                    0,
                ).label(f"count_{index}"),
            ]
        )
    statement = (
        add_ledger_scope(select(*columns), Expense, tenant_id)
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(stat_time >= min(start for start, _end in ranges.values()))
        .where(stat_time < max(end for _start, end in ranges.values()))
    )
    row = db.execute(statement).one()
    return {
        label: (int(row[index * 2] or 0), int(row[index * 2 + 1] or 0))
        for index, label in enumerate(labels)
    }


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
