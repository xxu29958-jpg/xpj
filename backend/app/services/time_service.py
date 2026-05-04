from __future__ import annotations

from datetime import UTC, datetime


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


def matches_month(value: datetime | None, month: str | None) -> bool:
    if not month:
        return True
    value = ensure_utc(value)
    if value is None:
        return False
    return value.strftime("%Y-%m") == month
