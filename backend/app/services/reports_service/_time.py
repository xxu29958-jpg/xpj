"""Timezone / month / day helpers — thin wrappers over spending_contract_service."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.spending_contract_service import (
    month_bounds_utc,
    month_labels_ending_at,
    parse_month,
    resolve_accounting_timezone,
    shift_month,
    stat_time_expr,
)


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


def _month_bounds(month: str, timezone_name: str) -> tuple[datetime, datetime]:
    return month_bounds_utc(month, timezone_name)


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
