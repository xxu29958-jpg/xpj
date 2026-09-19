"""Timezone / month / day helpers — thin wrappers over spending_contract_service."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from app.services.spending_contract_service import (
    calendar_month_bounds,
    month_labels_ending_at,
    parse_month,
    resolve_accounting_timezone,
    shift_month,
)


def _resolve_timezone(timezone_name: str | None) -> tuple[str, ZoneInfo]:
    return resolve_accounting_timezone(timezone_name)


def _parse_month(month: str) -> tuple[int, int]:
    return parse_month(month)


def _shift_month(month: str, offset: int) -> str:
    return shift_month(month, offset)


def _month_labels_ending_at(month: str, count: int) -> list[str]:
    return month_labels_ending_at(month, count)


def _days_in_month(month: str, zone: ZoneInfo) -> list[date]:
    cursor, end_date = calendar_month_bounds(month)
    days: list[date] = []
    while cursor < end_date:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days
