"""Durable claim and terminal-status publication for background-task workers."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.error_reporting import report_error
from app.errors import AppError
from app.models import BackgroundTask
from app.services import background_task_executor
from app.services.background_task_executor import BackgroundTaskSubmissionError
from app.services.background_task_handler_api import TaskCancelledError, stage_task_cancellation
from app.services.background_task_handler_api import mark_failed as _mark_failed
from app.services.background_task_registry import TaskHandlerRegistry, runtime_handler_registry
from app.services.recognition_resource_admission import RecognitionAdmissionDeferredError
from app.services.time_service import now_utc
from app.services.windows_recognition_resources import SAMPLE_SECONDS

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def run_task(
    task_id: int,
    payload: dict[str, Any],
    registry: TaskHandlerRegistry | None = None,
) -> None:
    """Claim one queued task and publish its handler's terminal outcome."""

    with SessionLocal() as db:
        task = claim_queued_task(db, task_id)
        if task is None:
            if db.get(BackgroundTask, task_id) is None:
                report_error(logger, "background task %s stage=claim vanished before run", task_id)
            return

        active_registry = registry or runtime_handler_registry()
        handler = active_registry.get(task.task_type)
        if handler is None:
            _mark_failed(
                db,
                task_id,
                expected_status="running",
                error_code="unknown_task_type",
                error_message=f"No handler registered for {task.task_type!r}.",
            )
            return

        try:
            handler(db, task, payload)
        except TaskCancelledError:
            _mark_cancelled(db, task_id)
        except Exception as exc:  # noqa: BLE001 - top-of-task outcome barrier
            db.rollback()
            db.refresh(task)
            if task.task_type in background_task_executor.OCR_TASK_TYPES and task.result_summary_json is not None:
                # A lost commit acknowledgement must not turn an already-applied
                # expense result into failure or execute the model again.
                _mark_completed(db, task_id, active_registry)
                return
            if task.task_type in background_task_executor.OCR_TASK_TYPES and isinstance(exc, RecognitionAdmissionDeferredError):
                _defer_recognition(db, task)
                return
            report_error(logger, "background task %s (%s) stage=handler failed", task_id, task.task_type, error=exc)
            _mark_failed(
                db,
                task_id,
                expected_status="running",
                error_code=exc.error if isinstance(exc, AppError) else type(exc).__name__,
                error_message=_failure_message(task.task_type, exc),
            )
        else:
            # The handler owns result_summary_json; this worker owns only the
            # final status transition after the handler returns successfully.
            _mark_completed(db, task_id, active_registry)


def _defer_recognition(db: Session, task: BackgroundTask) -> None:
    db.refresh(task, with_for_update=True)
    if task.status in _TERMINAL_STATUSES:
        return
    if task.cancellation_requested_at is not None:
        stage_task_cancellation(task)
    else:
        task.status = "queued"
        task.started_at = task.completed_at = None
        task.last_progress_at = now_utc()
        task.recovery_after = task.last_progress_at + timedelta(seconds=SAMPLE_SECONDS)
        task.error_code = task.error_message = None
        task.progress_current = 0
        task.progress_message = "本机资源暂时繁忙，任务已保留，稍后自动继续识别。"
    db.commit()


def _failure_message(task_type: str, error: Exception) -> str:
    if task_type in background_task_executor.OCR_TASK_TYPES:
        return error.message if isinstance(error, AppError) else "识别未能完成，原件和账单仍保留，请稍后重试。"
    return str(error)[:500]


def claim_queued_task(db: Session, task_id: int) -> BackgroundTask | None:
    """Atomically move one task from queued to running."""

    claimed_at = now_utc()
    result = db.execute(
        update(BackgroundTask)
        .where(BackgroundTask.id == task_id, BackgroundTask.status == "queued")
        .where(or_(BackgroundTask.recovery_after.is_(None), BackgroundTask.recovery_after <= claimed_at))
        .values(
            status="running",
            started_at=claimed_at,
            last_progress_at=claimed_at,
            recovery_after=None,
            error_code=None,
            error_message=None,
        )
    )
    db.commit()
    return db.get(BackgroundTask, task_id) if result.rowcount == 1 else None


def _mark_completed(db: Session, task_id: int, registry: TaskHandlerRegistry, *, recover_applied: bool = False) -> None:
    task = db.get(BackgroundTask, task_id)
    if task is None:
        return
    db.refresh(task, with_for_update=True)
    if task.status in _TERMINAL_STATUSES and not (recover_applied and task.status == "failed"):
        return
    try:
        task.status = "completed"
        task.completed_at = now_utc()
        task.error_code = task.error_message = task.recovery_after = None
        # Admission counts our flushed terminal transition in this transaction;
        # other sessions see the parent active until parent + child commit together.
        db.flush()
        continuation = registry.prepare_completion(db, task)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    if continuation is not None:
        # Dispatch refusal belongs to the durable child, never the completed parent.
        with suppress(BackgroundTaskSubmissionError):
            background_task_executor.submit_committed(db, continuation, runner=run_task)


def complete_applied_task(task_id: int) -> None:
    """Finish only a committed OCR receipt after process death, without inference."""
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        if (task is None or task.task_type not in background_task_executor.OCR_TASK_TYPES
                or task.result_summary_json is None):
            return
        _mark_completed(db, task_id, runtime_handler_registry(), recover_applied=True)


def _mark_cancelled(db: Session, task_id: int) -> None:
    task = db.get(BackgroundTask, task_id)
    if task is None:
        return
    db.refresh(task, with_for_update=True)
    if task.status in _TERMINAL_STATUSES:
        return
    stage_task_cancellation(task)
    db.commit()


__all__ = ["claim_queued_task", "run_task"]
