"""Bounded PostgreSQL admission for the existing background-task owner."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BackgroundTask

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


__all__ = ["BackgroundTaskCapacityFullError", "stage_queued_task"]
