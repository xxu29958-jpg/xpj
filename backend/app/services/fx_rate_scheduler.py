from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.database import SessionLocal
from app.services.fx_rate_provider import refresh_ecb_fx_rates
from app.services.scheduler_lease_service import try_claim_scheduler_lease

logger = logging.getLogger(__name__)
_SCHEDULER_LEASE_SECONDS = 10 * 60


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


_status = FxRateSyncStatus()


def fx_rate_sync_status() -> FxRateSyncStatus:
    """Snapshot of the background FX sync counters (read-only)."""
    return FxRateSyncStatus(
        success_count=_status.success_count,
        failed_count=_status.failed_count,
        last_error=_status.last_error,
        last_success_at=_status.last_success_at,
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


def _scheduler_loop(stop_event: threading.Event, sync_times: list[time], timezone: ZoneInfo) -> None:
    while not stop_event.is_set():
        delay_seconds = _seconds_until_next_run(datetime.now(timezone), sync_times)
        if stop_event.wait(delay_seconds):
            return
        try:
            with SessionLocal() as db:
                if not try_claim_scheduler_lease(
                    db,
                    name="fx_rate_sync",
                    lease_seconds=_SCHEDULER_LEASE_SECONDS,
                ):
                    logger.info("ECB FX sync skipped: scheduler lease is held")
                    continue
            with SessionLocal() as db:
                rows = refresh_ecb_fx_rates(db)
            _status.success_count += 1
            _status.last_success_at = datetime.now(timezone)
            logger.info("ECB FX sync completed: %s rates", len(rows))
        except Exception as exc:
            # Daemon thread: a propagated exception would kill the scheduler
            # silently. Stay broad on the catch so an upstream library
            # surprise can't take the worker down, but record the failure
            # for the health endpoint to see.
            _status.failed_count += 1
            _status.last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("ECB FX sync failed")


def start_fx_rate_scheduler() -> FxRateScheduler | None:
    settings = get_settings()
    if not settings.fx_rate_auto_sync_enabled:
        return None
    try:
        sync_times = _parse_sync_times(settings.fx_rate_sync_times)
        timezone = ZoneInfo(settings.fx_rate_sync_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        logger.exception("FX rate scheduler config is invalid")
        return None

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(stop_event, sync_times, timezone),
        name="fx-rate-scheduler",
        daemon=True,
    )
    thread.start()
    return FxRateScheduler(thread=thread, stop_event=stop_event)
