"""Existing maintenance workers wait for the Owner's current saved schedule."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings

logger = logging.getLogger(__name__)
_POLL_SECONDS = 30


def parse_daily_at(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def seconds_until_next_run(now: datetime, daily_at: time) -> float:
    candidate = now.replace(hour=daily_at.hour, minute=daily_at.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return max((candidate - now).total_seconds(), 1)


def _next_daily_run(prefix: str, choices: tuple[bool, str, str]) -> datetime | None:
    if not choices[0]:
        return None
    try:
        daily_at, timezone = parse_daily_at(choices[1]), ZoneInfo(choices[2])
        now = datetime.now(timezone)
        return now + timedelta(seconds=seconds_until_next_run(now, daily_at))
    except (ValueError, ZoneInfoNotFoundError):
        logger.warning("%s schedule is invalid; waiting for corrected settings", prefix)
        return None


def wait_for_daily_run(stop_event: threading.Event, prefix: str) -> datetime | None:
    previous = None
    target = None
    while not stop_event.is_set():
        settings = get_settings()
        choices = (getattr(settings, f"{prefix}_auto_enabled"),
                   getattr(settings, f"{prefix}_daily_at"), getattr(settings, f"{prefix}_timezone"))
        if choices != previous:
            previous, target = choices, _next_daily_run(prefix, choices)
        if target is not None and datetime.now(target.tzinfo) >= target:
            return datetime.now(target.tzinfo)
        delay = _POLL_SECONDS if target is None else min(_POLL_SECONDS, (target - datetime.now(target.tzinfo)).total_seconds())
        if stop_event.wait(max(0, delay)):
            break
    return None


def wait_for_interval_run(stop_event: threading.Event, flag: str, interval_seconds: int) -> bool:
    target = None
    while not stop_event.is_set():
        if not getattr(get_settings(), flag):
            target = None
        elif target is None:
            target = monotonic() + interval_seconds
        elif monotonic() >= target:
            return True
        delay = _POLL_SECONDS if target is None else min(_POLL_SECONDS, target - monotonic())
        if stop_event.wait(max(0, delay)):
            break
    return False
