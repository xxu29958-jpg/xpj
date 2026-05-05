from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_iso(value: datetime | None) -> str | None:
    value = ensure_utc(value)
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def safe_zone(timezone_name: str | None) -> ZoneInfo:
    name = (timezone_name or "").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def current_month(timezone_name: str | None) -> str:
    return now_utc().astimezone(safe_zone(timezone_name)).strftime("%Y-%m")


def local_month_bounds_utc(month: str, timezone_name: str | None) -> tuple[datetime, datetime] | None:
    try:
        year_text, month_text = month.split("-", 1)
        year = int(year_text)
        month_number = int(month_text)
        if not 1 <= month_number <= 12:
            return None
    except (TypeError, ValueError):
        return None

    zone = safe_zone(timezone_name)
    start_local = datetime(year, month_number, 1, tzinfo=zone)
    if month_number == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=zone)
    else:
        end_local = datetime(year, month_number + 1, 1, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def local_month_label(value: datetime | None, timezone_name: str | None) -> str | None:
    value = ensure_utc(value)
    if value is None:
        return None
    return value.astimezone(safe_zone(timezone_name)).strftime("%Y-%m")


def matches_month(value: datetime | None, month: str | None) -> bool:
    if not month:
        return True
    value = ensure_utc(value)
    if value is None:
        return False
    return value.strftime("%Y-%m") == month
