"""Shared task progress, cancellation and conditional failure publication."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundTask
from app.services.time_service import now_utc

OCR_TASK_TYPES = frozenset({"expense_enrichment", "expense_ocr_retry"})
OCR_RECOVERY_DELAYS = (10, 30, 90)
_TRANSIENT_CODES = frozenset({"orphaned_after_restart", "task_submission_failed", "ocr_timeout", "ocr_worker_exited"})
_STOP_ON_REPEAT = frozenset({"ocr_timeout", "ocr_worker_exited"})


class TaskCancelledError(Exception):
    """Raised by a task handler after observing a cancellation request."""


def can_recover_task(task: BackgroundTask) -> bool:
    """One total budget across worker failure, restart and original-request replay."""
    if (task.task_type not in OCR_TASK_TYPES or not task.input_payload_json
            or task.result_summary_json is not None or task.cancellation_requested_at is not None
            or task.error_code not in _TRANSIENT_CODES or task.recovery_attempts >= len(OCR_RECOVERY_DELAYS)):
        return False
    try:
        history = json.loads(task.recovery_history_json)
        return isinstance(history, list) and not (task.error_code in _STOP_ON_REPEAT
            and any(entry["error_code"] == task.error_code for entry in history))
    except (TypeError, ValueError, KeyError):
        return False


def schedule_task_recovery(task: BackgroundTask) -> bool:
    """Keep accepted work in its durable quota; preserve the failed attempt separately."""
    if not can_recover_task(task):
        return False
    stamp = now_utc()
    after = stamp + timedelta(seconds=OCR_RECOVERY_DELAYS[task.recovery_attempts])
    history = json.loads(task.recovery_history_json)
    history.append({"attempt": task.recovery_attempts + 1, "error_code": task.error_code,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "failed_at": (task.completed_at or stamp).isoformat(), "resume_after": after.isoformat(),
        "execution_context": json.loads(task.execution_context_json) if task.execution_context_json else None})
    task.recovery_history_json = json.dumps(history, separators=(",", ":"), sort_keys=True)
    task.execution_context_json = None
    task.recovery_attempts += 1
    task.recovery_after = after
    task.status = "queued"
    task.started_at = task.completed_at = None
    task.last_progress_at = stamp
    task.progress_current = 0
    task.progress_message = "上次识别中断，稍后自动继续；也可先手填核对。"
    return True


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
           "stage_task_cancellation", "update_progress", "can_recover_task", "schedule_task_recovery",
           "OCR_TASK_TYPES", "OCR_RECOVERY_DELAYS"]
