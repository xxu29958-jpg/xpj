"""ADR-0030 in-process long-task execution model.

Design:
    - One module-level ``ThreadPoolExecutor`` (max_workers=2) bounds the
      number of concurrent background tasks per backend instance.
    - Task implementations register themselves via :func:`register_handler`
      keyed by ``task_type``. PR-1 ships zero handlers; csv-import and
      v1-migration each ship their own handler in their own PR.
    - All progress writes go through this module so chunked transactions
      and ``last_progress_at`` heartbeats are consistent.
    - ``XPJ_BACKGROUND_TASK_INLINE=1`` runs ``enqueue`` synchronously
      (no executor thread) so unit tests can verify chunk / cancellation
      / handler outcomes without needing a real worker thread + a file-
      backed SQLite shared across threads.

Cancellation contract:
    Handlers must call :func:`check_cancellation_requested` at every chunk
    boundary. If it returns ``True`` the handler raises
    :class:`TaskCancelledError` (or returns a ``cancelled`` result) — the
    service does the rest.

Orphan recovery:
    :func:`recover_orphaned_tasks` is called from the FastAPI lifespan and
    force-fails any task in ``running`` or ``queued`` state. The
    in-process executor model means that a backend restart immediately
    voids every in-flight task (the ThreadPoolExecutor died with the
    previous process; nothing in this process can resume it) and every
    queued-but-not-yet-started task (executor never dequeued it; on
    restart the queue is empty). Both states are therefore orphans the
    moment startup begins — no heartbeat threshold is required, and a
    threshold actively leaks phantom rows under fast restart cadence.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask
from app.services.time_service import now_utc

logger = logging.getLogger(__name__)

MAX_WORKERS = 2
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_RECOVERABLE_STATUSES = frozenset({"running", "queued"})

# Sentinel: set XPJ_BACKGROUND_TASK_INLINE=1 in tests for synchronous runs.
def _inline_mode() -> bool:
    return os.environ.get("XPJ_BACKGROUND_TASK_INLINE") == "1"


class TaskCancelledError(Exception):
    """Raised by a task handler when it observes cancellation_requested_at."""


# -------------------------------------------------------------------------
# Handler registry (populated by csv-import / v1-migration / etc. modules)

TaskHandler = Callable[[Session, BackgroundTask, dict[str, Any]], None]
_handlers: dict[str, TaskHandler] = {}


def register_handler(task_type: str, handler: TaskHandler) -> None:
    """Register a handler for a given task_type.

    Idempotent. Calling with the same task_type twice replaces the previous
    handler, which makes tests using stub handlers straightforward.
    """
    _handlers[task_type] = handler


def get_registered_handlers() -> dict[str, TaskHandler]:
    """Mostly for tests / debug. Returns a snapshot copy of the registry."""
    return dict(_handlers)


# -------------------------------------------------------------------------
# Executor lifecycle

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=MAX_WORKERS, thread_name_prefix="xpj-bgtask"
        )
    return _executor


def shutdown_executor(wait: bool = False) -> None:
    """For graceful shutdown / tests. After this, enqueue() will rebuild."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=True)
        _executor = None


# -------------------------------------------------------------------------
# Public API: enqueue / get / list / cancel


def enqueue(
    db: Session,
    *,
    task_type: str,
    initiator_account_id: int | None,
    initiator_device_id: int | None = None,
    ledger_id: str | None = None,
    payload: dict[str, Any] | None = None,
    progress_total: int | None = None,
) -> BackgroundTask:
    """Insert a new ``queued`` row and submit it to the executor."""
    if task_type not in _handlers:
        raise AppError(
            "unknown_task_type",
            f"Background task type {task_type!r} is not registered.",
            status_code=400,
        )

    task = BackgroundTask(
        task_type=task_type,
        tenant_id=ledger_id,
        initiated_by_account_id=initiator_account_id,
        initiated_by_device_id=initiator_device_id,
        progress_total=progress_total,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    payload_copy = dict(payload or {})
    if _inline_mode():
        _run_task(task.id, payload_copy)
    else:
        _get_executor().submit(_run_task, task.id, payload_copy)
    return task


def get_task(db: Session, public_id: str, *, account_id: int | None) -> BackgroundTask:
    """Owner-scoped fetch. account_id=None means caller is system-scoped
    (no enforcement) — only safe in tests / startup hooks."""
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == public_id))
    if task is None:
        raise AppError("task_not_found", status_code=404)
    if account_id is not None and task.initiated_by_account_id != account_id:
        # Don't leak existence — return same 404 as missing task.
        raise AppError("task_not_found", status_code=404)
    return task


def list_recent_tasks(
    db: Session, *, account_id: int | None, limit: int = 50
) -> list[BackgroundTask]:
    """Most-recent first; account-scoped so user only sees their own."""
    if account_id is None:
        return []
    rows = db.scalars(
        select(BackgroundTask)
        .where(BackgroundTask.initiated_by_account_id == account_id)
        .order_by(BackgroundTask.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def request_cancellation(
    db: Session, public_id: str, *, account_id: int | None
) -> BackgroundTask:
    """Set ``cancellation_requested_at``. The handler observes it at the
    next chunk boundary and bails. Idempotent: cancelling an already-
    terminal task returns it unchanged."""
    task = get_task(db, public_id, account_id=account_id)
    if task.status in _TERMINAL_STATUSES:
        return task
    if task.cancellation_requested_at is None:
        task.cancellation_requested_at = now_utc()
        db.commit()
        db.refresh(task)
    return task


# -------------------------------------------------------------------------
# Handler-facing API: progress + cancellation polling


def update_progress(
    db: Session,
    task_id: int,
    *,
    current: int,
    total: int | None = None,
    message: str | None = None,
) -> None:
    """Handler calls this every chunk. Writes are small (single row update)
    so chunk size should be tuned by the handler (50-100 row range)."""
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
    """Handler calls this at every chunk boundary. Cheap single-row read."""
    task = db.get(BackgroundTask, task_id)
    if task is None:
        return False
    db.refresh(task)
    return task.cancellation_requested_at is not None


# -------------------------------------------------------------------------
# Internal: the worker that wraps a registered handler

def _run_task(task_id: int, payload: dict[str, Any]) -> None:
    """Pulled from the executor (or called inline in tests). Owns a single
    SessionLocal so all writes go through one DB session even if the
    handler does its own commits."""
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        if task is None:
            logger.error("background task %s vanished before run", task_id)
            return
        if task.status != "queued":
            # double-submit / retry guard
            return

        task.status = "running"
        task.started_at = now_utc()
        task.last_progress_at = task.started_at
        db.commit()

        handler = _handlers.get(task.task_type)
        if handler is None:
            _mark_failed(
                db, task_id,
                error_code="unknown_task_type",
                error_message=f"No handler registered for {task.task_type!r}.",
            )
            return

        try:
            handler(db, task, payload)
        except TaskCancelledError:
            _mark_cancelled(db, task_id)
        except Exception as exc:  # noqa: BLE001 - top-of-task barrier
            logger.exception("background task %s (%s) failed", task_id, task.task_type)
            _mark_failed(
                db, task_id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )
        else:
            # Handler responsible for setting result_summary_json before
            # returning; just promote to completed.
            _mark_completed(db, task_id)


def _mark_completed(db: Session, task_id: int) -> None:
    task = db.get(BackgroundTask, task_id)
    if task is None or task.status in _TERMINAL_STATUSES:
        return
    task.status = "completed"
    task.completed_at = now_utc()
    db.commit()


def _mark_failed(
    db: Session, task_id: int, *, error_code: str, error_message: str
) -> None:
    task = db.get(BackgroundTask, task_id)
    if task is None or task.status in _TERMINAL_STATUSES:
        return
    task.status = "failed"
    task.completed_at = now_utc()
    task.error_code = error_code
    task.error_message = error_message
    db.commit()


def _mark_cancelled(db: Session, task_id: int) -> None:
    task = db.get(BackgroundTask, task_id)
    if task is None or task.status in _TERMINAL_STATUSES:
        return
    task.status = "cancelled"
    task.completed_at = now_utc()
    db.commit()


# -------------------------------------------------------------------------
# Orphan recovery (called from FastAPI lifespan)


def recover_orphaned_tasks() -> int:
    """Force-fail every ``running`` and ``queued`` task on startup.

    Why no heartbeat threshold (was 5 min, removed):

    Single-process in-memory executor model. A backend restart kills the
    ThreadPoolExecutor that owned the in-flight ``running`` tasks (no
    other process can resume them in this architecture), and discards
    the in-memory queue that held ``queued`` tasks (they were never
    persisted as work — just as DB rows + executor.submit handles).
    Both states are orphans the instant a new process starts, regardless
    of how recent ``last_progress_at`` was.

    The previous 5-minute threshold leaked phantom rows under fast
    restart: any ``running`` task whose heartbeat was less than 5 min
    old would be kept ``running`` forever (no worker to advance it; the
    next recovery sweep only happens on the *next* restart). It also
    never covered ``queued`` rows at all — those were silently dropped
    on shutdown and left stuck.

    Returns the count of recovered rows.
    """
    with SessionLocal() as db:
        orphans = list(
            db.scalars(
                select(BackgroundTask).where(
                    BackgroundTask.status.in_(_RECOVERABLE_STATUSES)
                )
            )
        )
        for task in orphans:
            task.status = "failed"
            task.completed_at = now_utc()
            task.error_code = "orphaned_after_restart"
            task.error_message = (
                "Task was running or queued when the backend restarted; "
                "single-process executor cannot resume across restarts."
            )
        if orphans:
            db.commit()
        return len(orphans)


# -------------------------------------------------------------------------
# DTO conversion helper for routes


def to_response_dict(task: BackgroundTask) -> dict[str, Any]:
    """Convert ORM row → BackgroundTaskResponse-compatible dict; decodes
    ``result_summary_json`` string into a real dict (or None)."""
    result_summary: dict[str, Any] | None = None
    if task.result_summary_json:
        try:
            decoded = json.loads(task.result_summary_json)
            if isinstance(decoded, dict):
                result_summary = decoded
        except json.JSONDecodeError:
            logger.warning(
                "background_task %s has malformed result_summary_json", task.id
            )
    return {
        "public_id": task.public_id,
        "task_type": task.task_type,
        "status": task.status,
        "progress_current": task.progress_current,
        "progress_total": task.progress_total,
        "progress_message": task.progress_message,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "result_summary": result_summary,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "last_progress_at": task.last_progress_at,
        "cancellation_requested_at": task.cancellation_requested_at,
    }
