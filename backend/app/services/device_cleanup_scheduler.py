"""Optional daily cleanup for revoked device rows."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Ledger
from app.services.admin_service import cleanup_revoked_devices
from app.services.scheduler_lease_service import try_claim_scheduler_lease

logger = logging.getLogger(__name__)
_SCHEDULER_LEASE_SECONDS = 60 * 60


@dataclass
class DeviceCleanupSchedulerStatus:
    success_count: int = 0
    failed_count: int = 0
    last_error: str | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None


@dataclass
class DeviceCleanupScheduler:
    enabled: bool = False
    thread: threading.Thread | None = None
    stop_event: threading.Event | None = None
    config_error: str | None = None

    def stop(self) -> None:
        if self.stop_event is None or self.thread is None:
            return
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=5)


_status = DeviceCleanupSchedulerStatus()


def device_cleanup_status_snapshot() -> DeviceCleanupSchedulerStatus:
    return DeviceCleanupSchedulerStatus(
        success_count=_status.success_count,
        failed_count=_status.failed_count,
        last_error=_status.last_error,
        last_success_at=_status.last_success_at,
        last_attempt_at=_status.last_attempt_at,
    )


def _parse_daily_at(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _seconds_until_next_run(now: datetime, daily_at: time) -> float:
    candidate = now.replace(
        hour=daily_at.hour,
        minute=daily_at.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return max((candidate - now).total_seconds(), 1)


def _run_cleanup_once() -> tuple[int, int]:
    ledgers_scanned = 0
    devices_deleted = 0
    failed_ledgers = 0
    with SessionLocal() as db:
        ledger_ids = list(
            db.scalars(
                select(Ledger.ledger_id)
                .where(Ledger.archived_at.is_(None))
                .order_by(Ledger.ledger_id.asc())
            )
        )
        for ledger_id in ledger_ids:
            try:
                result = cleanup_revoked_devices(db, tenant_id=ledger_id)
            except Exception:  # noqa: BLE001 - one ledger must not abort the whole sweep
                failed_ledgers += 1
                # Reset the session so a half-applied failure doesn't poison the
                # next ledger's queries.
                db.rollback()
                logger.exception("device cleanup failed for ledger %s", ledger_id)
                continue
            ledgers_scanned += 1
            devices_deleted += result.deleted_devices
    if failed_ledgers:
        logger.warning(
            "device cleanup: %s ledger(s) failed and were skipped this run",
            failed_ledgers,
        )
    return ledgers_scanned, devices_deleted


def _scheduler_loop(
    stop_event: threading.Event,
    daily_at: time,
    timezone: ZoneInfo,
) -> None:
    while not stop_event.is_set():
        delay = _seconds_until_next_run(datetime.now(timezone), daily_at)
        if stop_event.wait(delay):
            return
        _status.last_attempt_at = datetime.now(timezone)
        try:
            with SessionLocal() as db:
                if not try_claim_scheduler_lease(
                    db,
                    name="device_cleanup",
                    lease_seconds=_SCHEDULER_LEASE_SECONDS,
                ):
                    logger.info("device cleanup skipped: scheduler lease is held")
                    continue
            ledgers_scanned, devices_deleted = _run_cleanup_once()
            _status.success_count += 1
            _status.last_success_at = datetime.now(timezone)
            logger.info(
                "device cleanup: ledgers=%s deleted_devices=%s",
                ledgers_scanned,
                devices_deleted,
            )
        except Exception as exc:  # noqa: BLE001 - daemon thread guard
            _status.failed_count += 1
            _status.last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("device cleanup failed")


def start_device_cleanup_scheduler() -> DeviceCleanupScheduler:
    settings = get_settings()
    if not settings.device_cleanup_auto_enabled:
        return DeviceCleanupScheduler()
    try:
        daily_at = _parse_daily_at(settings.device_cleanup_daily_at)
        timezone = ZoneInfo(settings.device_cleanup_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        logger.exception("device cleanup scheduler config invalid")
        return DeviceCleanupScheduler(config_error="invalid_config")

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(stop_event, daily_at, timezone),
        name="device-cleanup-scheduler",
        daemon=True,
    )
    thread.start()
    return DeviceCleanupScheduler(enabled=True, thread=thread, stop_event=stop_event)


__all__ = [
    "DeviceCleanupScheduler",
    "DeviceCleanupSchedulerStatus",
    "device_cleanup_status_snapshot",
    "start_device_cleanup_scheduler",
]
