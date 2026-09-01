"""Range and per-bucket amount/count aggregation over confirmed expenses."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.money_contract import projection_sum_to_int
from app.services.reports_service._models import ReportGranularity, _TrendBucket
from app.services.reports_service._time import (
    _days_in_month,
    _local_date_range_bounds_utc,
    _local_day_bounds_utc,
    _month_bounds,
    _month_labels_ending_at,
)
from app.services.spending_contract_service import (
    accounting_zone,
    confirmed_stream_query,
)


def _stream_for_utc_range(
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
    timezone_name: str,
    category: str | None = None,
):
    zone = accounting_zone(timezone_name)
    start_date = start_utc.astimezone(zone).date()
    end_date = end_utc.astimezone(zone).date()
    stream = confirmed_stream_query(
        tenant_id=tenant_id,
        category=category,
        timezone_name=timezone_name,
        amount_required=True,
    )
    return (
        select(stream)
        .where(stream.c.stream_date >= start_date)
        .where(stream.c.stream_date < end_date)
        .subquery("report_stream")
    )


def _range_amount_count(
    db: Session,
    *,
    tenant_id: str,
    start_utc: datetime,
    end_utc: datetime,
    timezone_name: str,
) -> tuple[int, int]:
    stream = _stream_for_utc_range(
        tenant_id=tenant_id,
        start_utc=start_utc,
        end_utc=end_utc,
        timezone_name=timezone_name,
    )
    statement = select(
        func.coalesce(func.sum(stream.c.stream_amount_cents), 0),
        func.count(stream.c.entry_id),
    ).select_from(stream)
    row = db.execute(statement).one()
    return (
        projection_sum_to_int(
            row[0],
            label="reports.range_amount",
            empty_is_zero=True,
        ),
        int(row[1] or 0),
    )


def _range_amount_counts(
    db: Session,
    *,
    tenant_id: str,
    ranges: dict[str, tuple[datetime, datetime]],
    timezone_name: str,
) -> dict[str, tuple[int, int]]:
    if not ranges:
        return {}
    zone = accounting_zone(timezone_name)
    stream = confirmed_stream_query(
        tenant_id=tenant_id,
        timezone_name=timezone_name,
        amount_required=True,
    )
    columns = []
    labels = list(ranges)
    for index, label in enumerate(labels):
        start_utc, end_utc = ranges[label]
        start_date = start_utc.astimezone(zone).date()
        end_date = end_utc.astimezone(zone).date()
        in_range = (stream.c.stream_date >= start_date) & (
            stream.c.stream_date < end_date
        )
        columns.extend(
            [
                func.coalesce(
                    func.sum(
                        case((in_range, stream.c.stream_amount_cents), else_=0)
                    ),
                    0,
                ).label(f"amount_{index}"),
                func.coalesce(
                    func.sum(case((in_range, 1), else_=0)),
                    0,
                ).label(f"count_{index}"),
            ]
        )
    earliest = min(start for start, _end in ranges.values()).astimezone(zone).date()
    latest = max(end for _start, end in ranges.values()).astimezone(zone).date()
    statement = (
        select(*columns)
        .select_from(stream)
        .where(stream.c.stream_date >= earliest)
        .where(stream.c.stream_date < latest)
    )
    row = db.execute(statement).one()
    return {
        label: (
            projection_sum_to_int(
                row[index * 2],
                label=f"reports.range_amount.{label}",
                empty_is_zero=True,
            ),
            int(row[index * 2 + 1] or 0),
        )
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
    timezone_name: str,
) -> dict[str, tuple[int, int]]:
    if not buckets:
        return {}
    zone = accounting_zone(timezone_name)
    stream = confirmed_stream_query(
        tenant_id=tenant_id,
        timezone_name=timezone_name,
        amount_required=True,
    )
    columns = []
    for index, bucket in enumerate(buckets):
        start_date = bucket.start_utc.astimezone(zone).date()
        end_date = bucket.end_utc.astimezone(zone).date()
        in_bucket = (stream.c.stream_date >= start_date) & (
            stream.c.stream_date < end_date
        )
        columns.extend(
            [
                func.coalesce(
                    func.sum(
                        case((in_bucket, stream.c.stream_amount_cents), else_=0)
                    ),
                    0,
                ).label(f"amount_{index}"),
                func.coalesce(
                    func.sum(case((in_bucket, 1), else_=0)),
                    0,
                ).label(f"count_{index}"),
            ]
        )
    earliest = min(bucket.start_utc for bucket in buckets).astimezone(zone).date()
    latest = max(bucket.end_utc for bucket in buckets).astimezone(zone).date()
    statement = (
        select(*columns)
        .select_from(stream)
        .where(stream.c.stream_date >= earliest)
        .where(stream.c.stream_date < latest)
    )
    row = db.execute(statement).one()
    return {
        bucket.bucket: (
            projection_sum_to_int(
                row[index * 2],
                label=f"reports.bucket_amount.{bucket.bucket}",
                empty_is_zero=True,
            ),
            int(row[index * 2 + 1] or 0),
        )
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
    totals = _bucket_amount_counts(
        db,
        tenant_id=tenant_id,
        buckets=buckets,
        timezone_name=timezone_name,
    )
    return [
        {
            "bucket": bucket.bucket,
            "label": bucket.label,
            "amount_cents": totals.get(bucket.bucket, (0, 0))[0],
            "count": totals.get(bucket.bucket, (0, 0))[1],
        }
        for bucket in buckets
    ]
