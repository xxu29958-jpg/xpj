from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.errors import AppError

MONTH_LABEL_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def ensure_utc_assuming_local(value: datetime | None, timezone_name: str | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=safe_zone(timezone_name)).astimezone(UTC)
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


def strict_zone(timezone_name: str) -> ZoneInfo:
    """Financial input cannot silently fall back from an unknown zone to UTC."""
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise AppError("accounting_timezone_invalid", "请选择有效的地区时区。", status_code=422) from exc


def _local_time_candidates(value: datetime, zone: ZoneInfo) -> dict[datetime, int]:
    # PEP 495 permits imaginary gap values in replace(); only UTC round-trips prove validity.
    candidates = {}
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        returned = candidate.astimezone(zone)
        if returned.replace(tzinfo=None) == value:
            candidates[candidate] = int(returned.utcoffset().total_seconds())
    return candidates


def resolve_local_datetime(
    value: datetime, timezone_name: str, *, utc_offset_seconds: int | None = None,
) -> datetime:
    """Resolve a local input without guessing through DST gaps or repeated hours."""
    zone = strict_zone(timezone_name)
    if value.utcoffset() is not None:
        actual_offset = int(value.utcoffset().total_seconds())
        if utc_offset_seconds is not None and utc_offset_seconds != actual_offset:
            raise AppError("accounting_time_invalid", "已知时刻与选择的 UTC 偏移不一致。", status_code=422)
        utc_offset_seconds = actual_offset
    candidates = _local_time_candidates(value.replace(tzinfo=None), zone)
    if not candidates:
        raise AppError("local_time_nonexistent", "这个本地时间因夏令时调整不存在，请保留输入并选择有效时间。", status_code=422)
    if utc_offset_seconds is not None:
        for instant, offset in candidates.items():
            if offset == utc_offset_seconds:
                return instant
        raise AppError("accounting_time_invalid", "选择的 UTC 偏移与本地时间不一致。", status_code=422)
    if len(candidates) > 1:
        raise AppError("local_time_ambiguous", "这个本地时间对应两个时刻，请选择 UTC 偏移。", status_code=422,
            details={"utc_offset_seconds_options": list(candidates.values())})
    return next(iter(candidates))


def current_month(timezone_name: str | None) -> str:
    return now_utc().astimezone(safe_zone(timezone_name)).strftime("%Y-%m")


def parse_month_label(month: str | None) -> tuple[int, int] | None:
    cleaned = (month or "").strip()
    if not MONTH_LABEL_PATTERN.fullmatch(cleaned):
        return None
    try:
        year_text, month_text = cleaned.split("-", 1)
        year = int(year_text)
        month_number = int(month_text)
    except ValueError:
        return None
    if year < 1 or not 1 <= month_number <= 12:
        return None
    if year == 9999 and month_number == 12:
        return None
    return year, month_number


def normalize_month_label(month: str | None) -> str | None:
    cleaned = (month or "").strip()
    return cleaned if parse_month_label(cleaned) is not None else None


def local_month_bounds_utc(month: str, timezone_name: str | None) -> tuple[datetime, datetime] | None:
    parsed = parse_month_label(month)
    if parsed is None:
        return None
    year, month_number = parsed

    zone = safe_zone(timezone_name)
    try:
        start_local = datetime(year, month_number, 1, tzinfo=zone)
        if month_number == 12:
            end_local = datetime(year + 1, 1, 1, tzinfo=zone)
        else:
            end_local = datetime(year, month_number + 1, 1, tzinfo=zone)
    except (OverflowError, ValueError):
        return None
    try:
        return start_local.astimezone(UTC), end_local.astimezone(UTC)
    except OverflowError:
        return None


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
