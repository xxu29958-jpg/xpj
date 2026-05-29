"""Startup recovery for orphaned background tasks."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import BackgroundTask
from app.services.time_service import ensure_utc, now_utc

_RECOVERABLE_STATUSES = frozenset({"running", "queued"})


def _should_recover_active_task(task: BackgroundTask, *, grace_seconds: int) -> bool:
    if grace_seconds <= 0:
        return True
    stamp = ensure_utc(task.last_progress_at) or ensure_utc(task.created_at)
    if stamp is None:
        return True
    return stamp <= now_utc() - timedelta(seconds=grace_seconds)


def recover_orphaned_tasks() -> int:
    """Force-fail orphaned ``running`` and ``queued`` tasks on startup.

    The default grace is zero seconds, preserving the single-process ADR-0030
    behavior. Cloud/multi-worker deployments can set a positive
    ``BACKGROUND_TASK_ORPHAN_GRACE_SECONDS`` so a newly started worker does not
    immediately fail fresh work still heartbeating in another worker.
    """

    grace_seconds = get_settings().background_task_orphan_grace_seconds
    with SessionLocal() as db:
        active_tasks = list(
            db.scalars(
                select(BackgroundTask).where(
                    BackgroundTask.status.in_(_RECOVERABLE_STATUSES)
                )
            )
        )
        orphans = [
            task
            for task in active_tasks
            if _should_recover_active_task(task, grace_seconds=grace_seconds)
        ]
        for task in orphans:
            task.status = "failed"
            task.completed_at = now_utc()
            task.error_code = "orphaned_after_restart"
            if grace_seconds > 0:
                task.error_message = (
                    "Task heartbeat exceeded BACKGROUND_TASK_ORPHAN_GRACE_SECONDS; "
                    "the worker that owned it is assumed dead."
                )
            else:
                task.error_message = (
                    "Task was running or queued when the backend restarted; "
                    "single-process executor cannot resume across restarts."
                )
        if orphans:
            db.commit()
        return len(orphans)


__all__ = ["recover_orphaned_tasks"]
