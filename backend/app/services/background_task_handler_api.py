"""Shared task progress, cancellation and conditional failure publication."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundTask
from app.services.background_task_recovery_service import schedule_task_recovery
from app.services.background_task_registry import OCR_TASK_TYPES
from app.services.time_service import now_utc


class TaskCancelledError(Exception):
    """Raised by a task handler after observing a cancellation request."""


def update_progress(
    db: Session,
    task_id: int,
    *,
    current: int,
    total: int | None = None,
    message: str | None = None,
) -> None:
    """Persist one handler-owned progress checkpoint."""
    task = db.get(BackgroundTask, task_id)
    if task is None:
        return
    task.progress_current = max(0, current)
    if total is not None:
        task.progress_total = total
    if message is not None:
        task.progress_message = message
    task.last_progress_at = now_utc()
    db.commit()


def check_cancellation_requested(db: Session, task_id: int) -> bool:
    """Refresh and read the cancellation flag at a handler checkpoint."""
    task = db.get(BackgroundTask, task_id)
    if task is None:
        return False
    db.refresh(task)
    return task.cancellation_requested_at is not None


def mark_failed(
    db: Session, task_id: int, *, expected_status: Literal["queued", "running"],
    error_code: str, error_message: str,
) -> None:
    """Publish failure only while the caller still owns the expected task phase."""
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.id == task_id)
        .with_for_update().execution_options(populate_existing=True))
    if task is not None and task.status == expected_status:
        if task.task_type in OCR_TASK_TYPES and task.cancellation_requested_at is not None:
            stage_task_cancellation(task)
        else:
            task.status, task.completed_at, task.recovery_after = "failed", now_utc(), None
            task.error_code, task.error_message = error_code, error_message
            schedule_task_recovery(task)
    db.commit()


def stage_task_cancellation(task: BackgroundTask) -> None:
    """End a cancelled task in its current owner's transaction, including deferred wakeups."""
    task.status, task.completed_at, task.recovery_after = "cancelled", now_utc(), None
    if task.task_type in OCR_TASK_TYPES:
        task.error_code = task.error_message = None
        task.progress_message = "识别已取消，账单仍保留。"


def retire_obsolete_task(db: Session, task: BackgroundTask) -> None:
    """Stage domain-proved retirement; the caller commits it with its replacement.

    A durable result already owns acceptance, even before worker publication.
    Otherwise cancellation fences both a queued claim and a running handler.
    """
    db.refresh(task, with_for_update=True)
    if task.status not in {"queued", "running"}:
        return
    task.completed_at = now_utc()
    if task.result_summary_json is not None:
        task.status = "completed"
    else:
        task.status = "cancelled"
        task.cancellation_requested_at = task.cancellation_requested_at or task.completed_at


__all__ = ["TaskCancelledError", "check_cancellation_requested", "mark_failed", "retire_obsolete_task",
           "stage_task_cancellation", "update_progress"]
