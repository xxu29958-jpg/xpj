"""Bounded PostgreSQL admission for the existing background-task owner."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BackgroundTask
from app.services.time_service import now_utc

_ACTIVE_STATUSES = ("queued", "running")
_ADMISSION_LOCK_LABEL = "ticketbox-background-task-admission"


class BackgroundTaskCapacityFullError(RuntimeError):
    """The durable executor has no bounded active slot available."""


def stage_queued_task(
    db: Session,
    *,
    task_type: str,
    initiator_account_id: int | None,
    initiator_device_id: int | None,
    ledger_id: str | None,
    progress_total: int | None,
) -> BackgroundTask:
    """Reserve one global executor slot and stage its durable task row.

    The transaction-scoped PostgreSQL advisory lock makes ``count + insert``
    one admission decision across concurrent request sessions.  The caller
    owns the transaction boundary so a business fact (for receipt uploads, the
    Pending expense) can commit atomically with this row.
    """

    _reserve_active_slot(db)
    task = BackgroundTask(
        task_type=task_type,
        tenant_id=ledger_id,
        initiated_by_account_id=initiator_account_id,
        initiated_by_device_id=initiator_device_id,
        progress_total=progress_total,
    )
    db.add(task)
    # Materialise id/public_id and surface deterministic insert failures before
    # the caller enters the commit-acknowledgement ambiguity window.
    db.flush()
    return task


def readmit_orphaned_task(db: Session, task_id: int) -> BackgroundTask | None:
    """Re-admit a domain-validated original; the caller commits before submitting it."""
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.id == task_id)
        .with_for_update().execution_options(populate_existing=True))
    if task is None:
        return None
    # A concurrent replay may already have committed re-admission, then lost its
    # acknowledgement. Its original queued task still needs a safe worker wakeup.
    if task.status == "queued":
        return task
    if (task.status != "failed" or task.error_code != "orphaned_after_restart"
            or task.cancellation_requested_at is not None):
        return None
    _reserve_active_slot(db)
    task.status = "queued"
    task.started_at = task.completed_at = None
    task.last_progress_at = now_utc()
    task.error_code = task.error_message = None
    if task.result_summary_json is None:
        task.progress_current = 0
        task.progress_message = None
    db.flush()
    return task


def _reserve_active_slot(db: Session) -> None:
    """One admission lock and capacity decision for both new and recovered tasks."""
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtext(current_database()), hashtext(:lock_label))"
        ),
        {"lock_label": _ADMISSION_LOCK_LABEL},
    )
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(BackgroundTask)
            .where(BackgroundTask.status.in_(_ACTIVE_STATUSES))
        )
        or 0
    )
    if active_count >= get_settings().background_task_max_active:
        raise BackgroundTaskCapacityFullError

__all__ = ["BackgroundTaskCapacityFullError", "readmit_orphaned_task", "stage_queued_task"]
