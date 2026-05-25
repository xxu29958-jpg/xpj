"""v1.2 ops — scheduled learning cleanup contract."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.config import reset_settings_cache
from app.services.learning_cleanup_scheduler import (
    _parse_daily_at,
    _seconds_until_next_run,
    start_learning_cleanup_scheduler,
)


def test_parse_daily_at_accepts_hh_mm() -> None:
    assert _parse_daily_at("03:30") == time(3, 30)
    assert _parse_daily_at("23:59") == time(23, 59)
    assert _parse_daily_at("00:00") == time(0, 0)


def test_seconds_until_next_run_picks_today_when_in_future() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 5, 1, 2, 0, tzinfo=tz)
    delay = _seconds_until_next_run(now, time(3, 30))
    # 03:30 is 90 minutes after 02:00 → 5400 seconds.
    assert delay == pytest.approx(5400, abs=1)


def test_seconds_until_next_run_rolls_to_tomorrow_when_past() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 5, 1, 4, 0, tzinfo=tz)
    delay = _seconds_until_next_run(now, time(3, 30))
    # 03:30 already passed; next is tomorrow → 23h30m = 84600 seconds.
    assert delay == pytest.approx(84600, abs=1)


def test_scheduler_disabled_by_default(*, identity) -> None:
    # Default config: LEARNING_CLEANUP_AUTO_ENABLED=false → returns None.
    reset_settings_cache()
    sched = start_learning_cleanup_scheduler()
    try:
        assert sched is None
    finally:
        if sched is not None:
            sched.stop()


def test_scheduler_starts_when_enabled(
    monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    monkeypatch.setenv("LEARNING_CLEANUP_AUTO_ENABLED", "true")
    reset_settings_cache()
    sched = start_learning_cleanup_scheduler()
    try:
        assert sched is not None
        assert sched.thread.is_alive()
    finally:
        if sched is not None:
            sched.stop()
        reset_settings_cache()


def test_scheduler_returns_none_on_bad_config(
    monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    monkeypatch.setenv("LEARNING_CLEANUP_AUTO_ENABLED", "true")
    monkeypatch.setenv("LEARNING_CLEANUP_DAILY_AT", "not-a-time")
    reset_settings_cache()
    sched = start_learning_cleanup_scheduler()
    try:
        assert sched is None
    finally:
        if sched is not None:
            sched.stop()
        reset_settings_cache()
