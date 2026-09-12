from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.fx_rate_provider import FxFetchError, refresh_ecb_fx_rates
from app.services.pending_fx_task_service import refill_pending_expense_fx
from app.services.scheduler_lease_service import try_claim_scheduler_lease
from app.services.time_service import now_utc

logger = logging.getLogger(__name__)
_SCHEDULER_LEASE_SECONDS = 10 * 60
_PENDING_FX_TICK_SECONDS = 30


@dataclass
class FxRateSyncStatus:
    """In-process counter for FX sync outcomes.

    The scheduler is a daemon thread with no external metrics pipeline;
    without this counter, a silent failure (network outage, ECB schema
    change, DB lock) is only visible by tailing logs. Health endpoints
    or future Prometheus exporters can call ``fx_rate_sync_status()``
    to surface ``failed_count`` / ``last_error``.
    """

    success_count: int = 0
    failed_count: int = 0
    last_error: str | None = None
    last_success_at: datetime | None = None
    scheduler_running: bool = False
    scheduler_config_error: bool = False


@dataclass
class _FxRateRuntime:
    counters: FxRateSyncStatus = field(default_factory=FxRateSyncStatus)
    scheduler: FxRateScheduler | None = None
    config_error: bool = False


_runtime = _FxRateRuntime()


def fx_rate_sync_status() -> FxRateSyncStatus:
    """Snapshot of the background FX sync counters (read-only)."""
    return FxRateSyncStatus(
        success_count=_runtime.counters.success_count,
        failed_count=_runtime.counters.failed_count,
        last_error=_runtime.counters.last_error,
        last_success_at=_runtime.counters.last_success_at,
        scheduler_running=_runtime.scheduler is not None and _runtime.scheduler.thread.is_alive(),
        scheduler_config_error=_runtime.config_error,
    )


@dataclass
class FxRateScheduler:
    thread: threading.Thread
    stop_event: threading.Event

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=5)


def _parse_sync_times(value: str) -> list[time]:
    result: list[time] = []
    for part in value.split(","):
        raw = part.strip()
        if not raw:
            continue
        hour_text, minute_text = raw.split(":", 1)
        result.append(time(hour=int(hour_text), minute=int(minute_text)))
    if not result:
        raise ValueError("empty sync time list")
    return sorted(result)


def _seconds_until_next_run(now: datetime, sync_times: list[time]) -> float:
    for sync_time in sync_times:
        candidate = now.replace(
            hour=sync_time.hour,
            minute=sync_time.minute,
            second=0,
            microsecond=0,
        )
        if candidate > now:
            return max((candidate - now).total_seconds(), 1)
    first = sync_times[0]
    tomorrow = now + timedelta(days=1)
    candidate = tomorrow.replace(hour=first.hour, minute=first.minute, second=0, microsecond=0)
    return max((candidate - now).total_seconds(), 1)


def run_fx_sync_once(db: Session) -> bool:
    """Run one FX sync, updating the shared status counters; returns success.

    Shared by the scheduler loop and the owner-console manual "立即拉取" trigger
    so both paths feed the same ``fx_rate_sync_status()`` snapshot. A transient
    network / TLS drop (this machine intermittently kills outbound handshakes —
    same flakiness that hits Maven; the fetch already retried) degrades
    gracefully to last-known rates and logs at WARNING with no traceback.
    Failures expose bounded reason codes, not exception messages or configured
    URLs. The loop also owns failures when opening its sessions or claiming its
    lease, before this function is reached.
    """
    try:
        rows = refresh_ecb_fx_rates(
            db,
            home_currency_code=require_runtime_home_currency_code(db),
        )
    except FxFetchError:
        _record_sync_failure("provider_unavailable")
        return False
    except Exception:  # noqa: BLE001 — daemon thread + UI trigger must not crash
        _record_sync_failure("sync_failed")
        return False
    _runtime.counters.success_count += 1
    _runtime.counters.last_success_at = now_utc()
    _runtime.counters.last_error = None
    logger.info("FX sync completed: %s rates", len(rows))
    return True


def _record_sync_failure(code: str) -> None:
    _runtime.counters.failed_count += 1
    _runtime.counters.last_error = code
    logger.warning("FX sync failed (%s); keeping last-known rates", code)


def _run_scheduled_fx_sync() -> None:
    try:
        with SessionLocal() as db:
            if not try_claim_scheduler_lease(
                db,
                name="fx_rate_sync",
                lease_seconds=_SCHEDULER_LEASE_SECONDS,
            ):
                logger.info("FX sync skipped: scheduler lease is held")
                return
        with SessionLocal() as db:
            run_fx_sync_once(db)
    except SQLAlchemyError:
        _record_sync_failure("storage_unavailable")


def _scheduler_loop(stop_event: threading.Event, sync_times: list[time], timezone: ZoneInfo) -> None:
    after_id = 0
    now = datetime.now(timezone)
    next_sync_at = now + timedelta(seconds=_seconds_until_next_run(now, sync_times))
    while not stop_event.is_set():
        try:
            after_id = refill_pending_expense_fx(after_id=after_id)
        except SQLAlchemyError:
            logger.warning("FX continuation deferred (storage_unavailable)")
        if stop_event.is_set():
            return
        now = datetime.now(timezone)
        if now >= next_sync_at:
            _run_scheduled_fx_sync()
            now = datetime.now(timezone)
            next_sync_at = now + timedelta(seconds=_seconds_until_next_run(now, sync_times))
        delay_seconds = min(_PENDING_FX_TICK_SECONDS, max((next_sync_at - now).total_seconds(), 1))
        if stop_event.wait(delay_seconds):
            return


def start_fx_rate_scheduler() -> FxRateScheduler | None:
    _runtime.scheduler = None
    _runtime.config_error = False
    settings = get_settings()
    if not settings.fx_rate_auto_sync_enabled:
        return None
    try:
        sync_times = _parse_sync_times(settings.fx_rate_sync_times)
        timezone = ZoneInfo(settings.fx_rate_sync_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        _runtime.config_error = True
        logger.warning("FX rate scheduler config is invalid")
        return None

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(stop_event, sync_times, timezone),
        name="fx-rate-scheduler",
        daemon=True,
    )
    scheduler = FxRateScheduler(thread=thread, stop_event=stop_event)
    _runtime.scheduler = scheduler
    thread.start()
    return scheduler
