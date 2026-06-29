"""ADR-0038 undo: optional periodic purge of soft-deleted rows past retention.

Opt-in via ``SOFT_DELETE_PURGE_AUTO_ENABLED`` (default off), matching the other
cleanup schedulers. Soft-deleted rows are hidden from every read the moment they
are deleted, so the sweep cadence only bounds storage lag; the purge cutoff is
the explicit recycle-bin retention window, not the short undo-banner window.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.database import SessionLocal
from app.services.cleanup_service import purge_expired_soft_deletes
from app.services.scheduler_lease_service import try_claim_scheduler_lease
from app.services.time_service import now_utc

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 30 * 60
_SCHEDULER_LEASE_SECONDS = 30 * 60


@dataclass
class SoftDeletePurgeSchedulerStatus:
    success_count: int = 0
    failed_count: int = 0
    last_error: str | None = None
    last_purged: int = 0
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None


@dataclass
class SoftDeletePurgeScheduler:
    enabled: bool = False
    thread: threading.Thread | None = None
    stop_event: threading.Event | None = None

    def stop(self) -> None:
        if self.stop_event is None or self.thread is None:
            return
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=5)


_status = SoftDeletePurgeSchedulerStatus()


def soft_delete_purge_status_snapshot() -> SoftDeletePurgeSchedulerStatus:
    return SoftDeletePurgeSchedulerStatus(
        success_count=_status.success_count,
        failed_count=_status.failed_count,
        last_error=_status.last_error,
        last_purged=_status.last_purged,
        last_success_at=_status.last_success_at,
        last_attempt_at=_status.last_attempt_at,
    )


def _scheduler_loop(stop_event: threading.Event, interval_seconds: int) -> None:
    while not stop_event.is_set():
        if stop_event.wait(interval_seconds):
            return
        _status.last_attempt_at = now_utc()
        try:
            with SessionLocal() as db:
                if not try_claim_scheduler_lease(
                    db,
                    name="soft_delete_purge",
                    lease_seconds=_SCHEDULER_LEASE_SECONDS,
                ):
                    logger.info("soft-delete purge skipped: scheduler lease is held")
                    continue
            with SessionLocal() as db:
                purged = purge_expired_soft_deletes(db)
            _status.success_count += 1
            _status.last_purged = purged
            _status.last_success_at = now_utc()
            logger.info("soft-delete purge: purged=%s", purged)
        except Exception as exc:  # noqa: BLE001 - daemon thread guard
            _status.failed_count += 1
            _status.last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("soft-delete purge failed")


def start_soft_delete_purge_scheduler() -> SoftDeletePurgeScheduler:
    if not get_settings().soft_delete_purge_auto_enabled:
        return SoftDeletePurgeScheduler()
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(stop_event, _INTERVAL_SECONDS),
        name="soft-delete-purge-scheduler",
        daemon=True,
    )
    thread.start()
    return SoftDeletePurgeScheduler(enabled=True, thread=thread, stop_event=stop_event)


__all__ = [
    "SoftDeletePurgeScheduler",
    "SoftDeletePurgeSchedulerStatus",
    "soft_delete_purge_status_snapshot",
    "start_soft_delete_purge_scheduler",
]
