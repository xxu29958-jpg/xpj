"""Read the confirmed stream once, project recorded money, then group in memory."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.services.money_projection_service import sum_projected_amounts
from app.services.reports_service._models import ReportGranularity, _TrendBucket
from app.services.reports_service._time import (
    _days_in_month,
    _month_labels_ending_at,
)
from app.services.spending_contract_service import calendar_month_bounds


def _entries_in_range(entries, period, zone):
    start, end = period
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
            start, end = calendar_month_bounds(label)
            buckets.append(
                _TrendBucket(
                    bucket=label,
                    label=label,
                    start_date=start,
                    end_date=end,
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
            label_end = end_day - timedelta(days=1)
            buckets.append(
                _TrendBucket(
                    bucket=week_start.isoformat(),
                    label=f"{start_day.strftime('%m-%d')}~{label_end.strftime('%m-%d')}",
                    start_date=start_day,
                    end_date=end_day,
                )
            )
        return buckets

    buckets = []
    for day in days:
        buckets.append(
            _TrendBucket(
                bucket=day.isoformat(),
                label=day.strftime("%m-%d"),
                start_date=day,
                end_date=day + timedelta(days=1),
            )
        )
    return buckets


def _trend_points(entries, buckets, zone, *, undated=0):
    points = []
    for bucket in buckets:
        amount, count = _amount_count(_entries_in_range(entries, (bucket.start_date, bucket.end_date), zone))
        points.append({"bucket": bucket.bucket, "label": bucket.label, "amount_cents": None if undated else amount, "count": count})
    return points
