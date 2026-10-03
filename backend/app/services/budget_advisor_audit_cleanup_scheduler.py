"""Optional daily retention cleanup for AI budget advisor audit rows."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.database import SessionLocal
from app.services.budget_advisor_service import cleanup_expired_audit_logs
from app.services.runtime_maintenance_schedule import parse_daily_at, wait_for_daily_run
from app.services.scheduler_lease_service import try_claim_scheduler_lease

logger = logging.getLogger(__name__)
_SCHEDULER_LEASE_SECONDS = 60 * 60


@dataclass
class BudgetAdvisorAuditCleanupSchedulerStatus:
    success_count: int = 0
    failed_count: int = 0
    last_error: str | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None


@dataclass
class BudgetAdvisorAuditCleanupScheduler:
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


_status = BudgetAdvisorAuditCleanupSchedulerStatus()


def budget_advisor_audit_cleanup_status_snapshot() -> BudgetAdvisorAuditCleanupSchedulerStatus:
    return BudgetAdvisorAuditCleanupSchedulerStatus(
        success_count=_status.success_count,
        failed_count=_status.failed_count,
        last_error=_status.last_error,
        last_success_at=_status.last_success_at,
        last_attempt_at=_status.last_attempt_at,
    )


def _scheduler_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        attempted_at = wait_for_daily_run(stop_event, "budget_advisor_audit_cleanup")
        if attempted_at is None:
            return
        _status.last_attempt_at = attempted_at
        try:
            with SessionLocal() as db:
                if not try_claim_scheduler_lease(
                    db,
                    name="budget_advisor_audit_cleanup",
                    lease_seconds=_SCHEDULER_LEASE_SECONDS,
                ):
                    logger.info(
                        "budget advisor audit cleanup skipped: scheduler lease is held"
                    )
                    continue
            with SessionLocal() as db:
                deleted = cleanup_expired_audit_logs(db)
            _status.success_count += 1
            _status.last_success_at = datetime.now(attempted_at.tzinfo)
            logger.info("budget advisor audit cleanup: deleted=%s", deleted)
        except Exception as exc:  # noqa: BLE001 - daemon thread guard
            _status.failed_count += 1
            _status.last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("budget advisor audit cleanup failed")


def start_budget_advisor_audit_cleanup_scheduler() -> BudgetAdvisorAuditCleanupScheduler:
    settings = get_settings()
    enabled = settings.budget_advisor_audit_cleanup_auto_enabled
    config_error = None
    if enabled:
        try:
            parse_daily_at(settings.budget_advisor_audit_cleanup_daily_at)
            ZoneInfo(settings.budget_advisor_audit_cleanup_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            enabled, config_error = False, "invalid_config"
    stop_event = threading.Event()
    thread = threading.Thread(target=_scheduler_loop, args=(stop_event,),
                              name="budget-advisor-audit-cleanup-scheduler", daemon=True)
    thread.start()
    return BudgetAdvisorAuditCleanupScheduler(enabled=enabled, thread=thread, stop_event=stop_event, config_error=config_error)


__all__ = [
    "BudgetAdvisorAuditCleanupScheduler",
    "BudgetAdvisorAuditCleanupSchedulerStatus",
    "budget_advisor_audit_cleanup_status_snapshot",
    "start_budget_advisor_audit_cleanup_scheduler",
]
