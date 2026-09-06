"""The FX worker survives storage failures and reports real liveness."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from datetime import time
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import OperationalError

from app.services import fx_rate_scheduler as scheduler


class _ScheduledTicks(threading.Event):
    def __init__(self, count: int = 2) -> None:
        super().__init__()
        self.count = count
        self.waits = 0

    def wait(self, timeout: float | None = None) -> bool:
        self.waits += 1
        return self.waits > self.count


@pytest.mark.parametrize("failure_at", ["lease", "session"])
def test_worker_recovers_after_storage_failure(
    monkeypatch: pytest.MonkeyPatch, failure_at: str
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

    scheduler._scheduler_loop(_ScheduledTicks(), [time(9, 10)], ZoneInfo("UTC"))

    status = scheduler.fx_rate_sync_status()
    assert refresh.call_count == 1
    assert status.failed_count == 1
    assert status.success_count == 1
    assert status.last_error is None
    assert status.last_success_at is not None


def test_recovery_respects_an_unexpired_lease_before_a_later_success(monkeypatch: pytest.MonkeyPatch) -> None:
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

    scheduler._scheduler_loop(_ScheduledTicks(3), [time(9, 10)], ZoneInfo("UTC"))

    assert lease.call_count == 3
    assert refresh.call_count == 1
    assert scheduler.fx_rate_sync_status().failed_count == 1
    assert scheduler.fx_rate_sync_status().success_count == 1


def test_status_tracks_actual_scheduler_thread_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        fx_rate_auto_sync_enabled=True, fx_rate_sync_times="09:10", fx_rate_sync_timezone="UTC"
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    worker = scheduler.start_fx_rate_scheduler()
    assert worker is not None
    try:
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
