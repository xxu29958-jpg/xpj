"""Stable progress and cancellation API used by background-task handlers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import BackgroundTask
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


__all__ = ["TaskCancelledError", "check_cancellation_requested", "update_progress"]
