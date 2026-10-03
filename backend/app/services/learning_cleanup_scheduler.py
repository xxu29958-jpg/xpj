"""v1.2 ops — scheduled retention cleanup for the learning tables.

Daemon thread, modelled after :mod:`fx_rate_scheduler`. Fires once a
day at ``LEARNING_CLEANUP_DAILY_AT`` (config; default ``03:30`` in
``LEARNING_CLEANUP_TIMEZONE`` — Asia/Shanghai by default since the
backend lives on a Chinese-timezone home server).

Disabled by default (``LEARNING_CLEANUP_AUTO_ENABLED=false``) so an
existing deployment does not begin deleting expired records; the
manual ``/api/maintenance/cleanup-learning`` button + Owner Console
"立即清理" still work whether or not the scheduler is on.

The thread catches its own exceptions and increments
``failed_count`` so a silent failure (DB locked at 3:30am) doesn't
take the worker down or hide from observability.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.database import SessionLocal
from app.services.learning_service import run_full_maintenance
from app.services.runtime_maintenance_schedule import parse_daily_at, wait_for_daily_run
from app.services.scheduler_lease_service import try_claim_scheduler_lease

logger = logging.getLogger(__name__)
_SCHEDULER_LEASE_SECONDS = 60 * 60


@dataclass
class LearningCleanupSchedulerStatus:
    """In-process counters shown in Owner cleanup settings."""

    success_count: int = 0
    failed_count: int = 0
    last_error: str | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None


_status = LearningCleanupSchedulerStatus()


def learning_cleanup_status_snapshot() -> LearningCleanupSchedulerStatus:
    """Read-only snapshot of the scheduler counters."""
    return LearningCleanupSchedulerStatus(
        success_count=_status.success_count,
        failed_count=_status.failed_count,
        last_error=_status.last_error,
        last_success_at=_status.last_success_at,
        last_attempt_at=_status.last_attempt_at,
    )


@dataclass
class LearningCleanupScheduler:
    thread: threading.Thread
    stop_event: threading.Event
    enabled: bool = False
    config_error: str | None = None

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=5)


def _scheduler_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        attempted_at = wait_for_daily_run(stop_event, "learning_cleanup")
        if attempted_at is None:
            return
        _status.last_attempt_at = attempted_at
        try:
            with SessionLocal() as db:
                if not try_claim_scheduler_lease(
                    db,
                    name="learning_cleanup",
                    lease_seconds=_SCHEDULER_LEASE_SECONDS,
                ):
                    logger.info("learning cleanup skipped: scheduler lease is held")
                    continue
            with SessionLocal() as db:
                result = run_full_maintenance(db)
            _status.success_count += 1
            _status.last_success_at = datetime.now(attempted_at.tzinfo)
            logger.info(
                "learning cleanup: swept=%s deleted=%s elapsed_ms=%s",
                result.swept_stale_active,
                result.cleanup.total,
                result.elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001 - daemon thread guard
            # A propagating exception would kill the daemon thread
            # silently. Catch broadly so an upstream surprise can't
            # take the worker down; record the failure for visibility.
            _status.failed_count += 1
            _status.last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("learning cleanup failed")


def start_learning_cleanup_scheduler() -> LearningCleanupScheduler:
    settings = get_settings()
    enabled = settings.learning_cleanup_auto_enabled
    config_error = None
    if enabled:
        try:
            parse_daily_at(settings.learning_cleanup_daily_at)
            ZoneInfo(settings.learning_cleanup_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            enabled, config_error = False, "invalid_config"
    stop_event = threading.Event()
    thread = threading.Thread(target=_scheduler_loop, args=(stop_event,),
                              name="learning-cleanup-scheduler", daemon=True)
    thread.start()
    return LearningCleanupScheduler(enabled=enabled, thread=thread, stop_event=stop_event, config_error=config_error)


__all__ = [
    "LearningCleanupScheduler",
    "LearningCleanupSchedulerStatus",
    "learning_cleanup_status_snapshot",
    "start_learning_cleanup_scheduler",
]
