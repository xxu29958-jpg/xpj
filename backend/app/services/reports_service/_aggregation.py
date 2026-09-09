"""Read the confirmed stream once, project recorded money, then group in memory."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.services.money_projection_service import sum_projected_amounts
from app.services.reports_service._models import ReportGranularity, _TrendBucket
from app.services.reports_service._time import (
    _days_in_month,
    _local_date_range_bounds_utc,
    _local_day_bounds_utc,
    _month_bounds,
    _month_labels_ending_at,
)


def _entries_in_range(entries, period, zone):
    start, end = (value.astimezone(zone).date() for value in period)
    return [entry for entry in entries if start <= entry.stream_date < end]


def _amount_count(entries):
    return sum_projected_amounts((entry.amount_cents for entry in entries), label="reports.total"), len(entries)


def _amount_delta(current, previous):
    return sum_projected_amounts((current, None if previous is None else -previous), label="reports.delta")


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


def _trend_points(entries, buckets, zone):
    points = []
    for bucket in buckets:
        amount, count = _amount_count(_entries_in_range(entries, (bucket.start_utc, bucket.end_utc), zone))
        points.append({"bucket": bucket.bucket, "label": bucket.label, "amount_cents": amount, "count": count})
    return points
