"""Durable claim and terminal-status publication for background-task workers."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BackgroundTask
from app.services import background_task_executor
from app.services.background_task_executor import BackgroundTaskSubmissionError
from app.services.background_task_handler_api import TaskCancelledError
from app.services.background_task_handler_api import mark_failed as _mark_failed
from app.services.background_task_registry import TaskHandlerRegistry, runtime_handler_registry
from app.services.time_service import now_utc

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
                logger.error("background task %s vanished before run", task_id)
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
            logger.exception("background task %s (%s) failed", task_id, task.task_type)
            _mark_failed(
                db,
                task_id,
                expected_status="running",
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )
        else:
            # The handler owns result_summary_json; this worker owns only the
            # final status transition after the handler returns successfully.
            _mark_completed(db, task_id, active_registry)


def claim_queued_task(db: Session, task_id: int) -> BackgroundTask | None:
    """Atomically move one task from queued to running."""

    claimed_at = now_utc()
    result = db.execute(
        update(BackgroundTask)
        .where(BackgroundTask.id == task_id, BackgroundTask.status == "queued")
        .values(
            status="running",
            started_at=claimed_at,
            last_progress_at=claimed_at,
        )
    )
    db.commit()
    return db.get(BackgroundTask, task_id) if result.rowcount == 1 else None


def _mark_completed(db: Session, task_id: int, registry: TaskHandlerRegistry) -> None:
    task = db.get(BackgroundTask, task_id)
    if task is None or task.status in _TERMINAL_STATUSES:
        return
    try:
        task.status = "completed"
        task.completed_at = now_utc()
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


def _mark_cancelled(db: Session, task_id: int) -> None:
    task = db.get(BackgroundTask, task_id)
    if task is None or task.status in _TERMINAL_STATUSES:
        return
    task.status = "cancelled"
    task.completed_at = now_utc()
    db.commit()


__all__ = ["claim_queued_task", "run_task"]
