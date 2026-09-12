"""The FX worker survives storage failures and reports real liveness."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, call
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import OperationalError

from app.services import fx_rate_scheduler as scheduler


class _ScheduledTicks(threading.Event):
    def __init__(self, count: int = 3) -> None:
        super().__init__()
        self.count = count
        self.delays: list[float] = []
        self.current = datetime(2026, 9, 13, 9, 9, 30, tzinfo=ZoneInfo("UTC"))

    def now(self, timezone: ZoneInfo) -> datetime:
        return self.current.astimezone(timezone)

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None and 0 < timeout <= 30
        self.delays.append(timeout)
        if len(self.delays) > self.count:
            return True
        self.current += timedelta(seconds=timeout)
        return False


@pytest.fixture
def ticks(monkeypatch: pytest.MonkeyPatch) -> _ScheduledTicks:
    clock = _ScheduledTicks()
    monkeypatch.setattr(scheduler, "datetime", SimpleNamespace(now=clock.now))
    monkeypatch.setattr(scheduler, "refill_pending_expense_fx", Mock(return_value=0))
    return clock


@pytest.mark.parametrize("failure_at", ["lease", "session"])
def test_worker_recovers_after_storage_failure(
    monkeypatch: pytest.MonkeyPatch, failure_at: str, ticks: _ScheduledTicks
) -> None:
    unavailable = OperationalError("lease", {}, RuntimeError("temporarily unavailable"))
    sessions = Mock(side_effect=lambda: nullcontext(object()))
    lease = Mock(return_value=True)
    if failure_at == "lease":
        lease.side_effect = [unavailable, True]
    else:
        sessions.side_effect = [unavailable, nullcontext(object()), nullcontext(object())]
    refresh = Mock(return_value=[])
    monkeypatch.setattr(scheduler._runtime, "counters", scheduler.FxRateSyncStatus())
    monkeypatch.setattr(scheduler, "SessionLocal", sessions)
    monkeypatch.setattr(scheduler, "try_claim_scheduler_lease", lease)
    monkeypatch.setattr(scheduler, "require_runtime_home_currency_code", lambda db: "CNY")
    monkeypatch.setattr(scheduler, "refresh_ecb_fx_rates", refresh)

    scheduler._scheduler_loop(ticks, [time(9, 10), time(9, 11)], ZoneInfo("UTC"))

    status = scheduler.fx_rate_sync_status()
    assert refresh.call_count == 1
    assert status.failed_count == 1
    assert status.success_count == 1
    assert status.last_error is None
    assert status.last_success_at is not None


def test_recovery_respects_an_unexpired_lease_before_a_later_success(
    monkeypatch: pytest.MonkeyPatch, ticks: _ScheduledTicks,
) -> None:
    unavailable = OperationalError("working session", {}, RuntimeError("temporarily unavailable"))
    sessions = Mock(side_effect=[
        nullcontext(object()), unavailable, nullcontext(object()), nullcontext(object()), nullcontext(object()),
    ])
    lease = Mock(side_effect=[True, False, True])
    refresh = Mock(return_value=[])
    monkeypatch.setattr(scheduler._runtime, "counters", scheduler.FxRateSyncStatus())
    monkeypatch.setattr(scheduler, "SessionLocal", sessions)
    monkeypatch.setattr(scheduler, "try_claim_scheduler_lease", lease)
    monkeypatch.setattr(scheduler, "require_runtime_home_currency_code", lambda db: "CNY")
    monkeypatch.setattr(scheduler, "refresh_ecb_fx_rates", refresh)

    ticks.count = 5
    scheduler._scheduler_loop(ticks, [time(9, 10), time(9, 11), time(9, 12)], ZoneInfo("UTC"))

    assert lease.call_count == 3
    assert refresh.call_count == 1
    assert scheduler.fx_rate_sync_status().failed_count == 1
    assert scheduler.fx_rate_sync_status().success_count == 1


def test_startup_and_short_ticks_resume_cursor_without_early_quotes_or_failure_counter_changes(
    monkeypatch: pytest.MonkeyPatch, ticks: _ScheduledTicks, caplog: pytest.LogCaptureFixture,
) -> None:
    ticks.current = ticks.current.replace(hour=9, minute=0, second=0)
    ticks.count = 2
    unavailable = OperationalError("fx-private-sentinel", {}, RuntimeError("private database detail"))
    refill = Mock(side_effect=[32, unavailable, 0])
    sessions = Mock(side_effect=AssertionError("A short tick must not open the daily quote session"))
    monkeypatch.setattr(scheduler, "refill_pending_expense_fx", refill)
    monkeypatch.setattr(scheduler, "SessionLocal", sessions)
    monkeypatch.setattr(scheduler._runtime, "counters", scheduler.FxRateSyncStatus())

    scheduler._scheduler_loop(ticks, [time(9, 10)], ZoneInfo("UTC"))

    assert refill.call_args_list == [call(after_id=0), call(after_id=32), call(after_id=32)]
    assert ticks.current.time() == time(9, 1)
    sessions.assert_not_called()
    status = scheduler.fx_rate_sync_status()
    assert (status.success_count, status.failed_count, status.last_error, status.last_success_at) == (0, 0, None, None)
    assert "FX continuation deferred (storage_unavailable)" in caplog.text
    assert "fx-private-sentinel" not in caplog.text and "private database detail" not in caplog.text


def test_status_tracks_actual_scheduler_thread_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        fx_rate_auto_sync_enabled=True, fx_rate_sync_times="09:10", fx_rate_sync_timezone="UTC"
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    refilled = threading.Event()
    monkeypatch.setattr(scheduler, "refill_pending_expense_fx", lambda **_: refilled.set() or 0)
    worker = scheduler.start_fx_rate_scheduler()
    assert worker is not None
    try:
        assert refilled.wait(timeout=1)
        assert worker.thread.is_alive()
        assert scheduler.fx_rate_sync_status().scheduler_running is True
    finally:
        worker.stop()
    assert scheduler.fx_rate_sync_status().scheduler_running is False


def test_invalid_and_disabled_configuration_never_reports_running(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        fx_rate_auto_sync_enabled=True, fx_rate_sync_times="invalid", fx_rate_sync_timezone="UTC"
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    assert scheduler.start_fx_rate_scheduler() is None
    invalid = scheduler.fx_rate_sync_status()
    assert invalid.scheduler_config_error is True
    assert invalid.scheduler_running is False
    settings.fx_rate_auto_sync_enabled = False
    assert scheduler.start_fx_rate_scheduler() is None
    disabled = scheduler.fx_rate_sync_status()
    assert disabled.scheduler_config_error is False
    assert disabled.scheduler_running is False
