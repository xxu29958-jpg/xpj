"""ADR-0030 in-process long-task execution model.

Design:
    - One module-level ``ThreadPoolExecutor`` (max_workers=2) bounds the
      number of concurrent background tasks per backend instance.
    - Production task implementations live in an explicit runtime catalog
      (see ``background_task_registry.runtime_handler_registry``). Tests may
      inject a per-test registry through :func:`isolated_registered_handlers_for_testing`;
      production code does not mutate a module-level handler map.
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
    restart the queue is empty). By default both states are therefore
    orphans the moment startup begins. Cloud/multi-worker deployments may
    set ``BACKGROUND_TASK_ORPHAN_GRACE_SECONDS`` to avoid a newly started
    worker force-failing fresh work still heartbeating in another process.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask
from app.services.background_task_recovery_service import (
    recover_orphaned_tasks as _recover_orphaned_tasks,
)
from app.services.background_task_registry import TaskHandler, TaskHandlerRegistry
from app.services.background_task_registry import (
    runtime_handler_registry as _runtime_handler_registry,
)
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


class BackgroundTaskRegistrationError(Exception):
    """Raised when test-only handler registration is used outside its scope."""


_handler_registry_context: ContextVar[TaskHandlerRegistry | None] = ContextVar(
    "xpj_background_task_handler_registry",
    default=None,
)


def _current_handler_registry() -> TaskHandlerRegistry:
    return _handler_registry_context.get() or _runtime_handler_registry()


def has_active_handler_registry_context() -> bool:
    """True when tests installed a temporary registry in this context."""

    return _handler_registry_context.get() is not None


@contextmanager
def isolated_registered_handlers_for_testing(
    handlers: dict[str, TaskHandler] | None = None,
) -> Iterator[None]:
    """Install a per-test handler registry without mutating runtime defaults."""

    token = _handler_registry_context.set(TaskHandlerRegistry(handlers))
    try:
        yield
    finally:
        _handler_registry_context.reset(token)


def register_handler(task_type: str, handler: TaskHandler) -> None:
    """Register a handler in the active test registry.

    Runtime handlers are not registered into module-level mutable state; they
    are declared in ``runtime_handler_registry``. This helper is intentionally
    scoped to ``isolated_registered_handlers_for_testing`` so parallel tests do
    not mutate production defaults.
    """
    registry = _handler_registry_context.get()
    if registry is None:
        raise BackgroundTaskRegistrationError(
            "register_handler is only valid inside isolated_registered_handlers_for_testing"
        )
    registry.register(task_type, handler)


def get_registered_handlers() -> dict[str, TaskHandler]:
    """Mostly for tests / debug. Returns a snapshot copy of the registry."""
    return _current_handler_registry().snapshot()


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
    registry = _current_handler_registry()
    if not registry.contains(task_type):
        raise AppError(
            "unknown_task_type",
            f"Background task type {task_type!r} is not registered.",
            status_code=400,
        )

    payload_copy = dict(payload or {})
    task = _insert_queued_task(
        db,
        task_type=task_type,
        initiator_account_id=initiator_account_id,
        initiator_device_id=initiator_device_id,
        ledger_id=ledger_id,
        progress_total=progress_total,
    )
    _submit_task(task.id, payload_copy, registry=registry)
    return task


def enqueue_or_get_active(
    db: Session,
    *,
    task_type: str,
    initiator_account_id: int | None,
    initiator_device_id: int | None = None,
    ledger_id: str | None = None,
    payload: dict[str, Any] | None = None,
    progress_total: int | None = None,
) -> tuple[BackgroundTask, bool]:
    """Insert a task unless an active one already exists.

    Returns ``(task, created)``. This is intentionally narrow: it is for
    singleton flows where a second click must point at the existing
    ``queued``/``running`` row rather than starting a duplicate run.
    """
    registry = _current_handler_registry()
    if not registry.contains(task_type):
        raise AppError(
            "unknown_task_type",
            f"Background task type {task_type!r} is not registered.",
            status_code=400,
        )
    payload_copy = dict(payload or {})
    try:
        # PG-only (债 #1): the SQLite-only BEGIN IMMEDIATE writer guard that
        # serialized this read-then-insert is gone. The singleton has no
        # lockable anchor row, so its proper PG close is a pg_advisory_xact_lock
        # deferred to the SQLite-removal slice (step 3); until then the
        # read-then-insert keeps the pre-existing accepted tail race that prod
        # (single-process) has run since the PG cut-over.
        existing = _active_task(
            db,
            task_type=task_type,
            ledger_id=ledger_id,
        )
        if existing is not None:
            db.commit()
            db.refresh(existing)
            return existing, False

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
    except Exception:
        db.rollback()
        raise

    _submit_task(task.id, payload_copy, registry=registry)
    return task, True


def _insert_queued_task(
    db: Session,
    *,
    task_type: str,
    initiator_account_id: int | None,
    initiator_device_id: int | None,
    ledger_id: str | None,
    progress_total: int | None,
) -> BackgroundTask:
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
    return task


def _submit_task(
    task_id: int,
    payload: dict[str, Any],
    *,
    registry: TaskHandlerRegistry,
) -> None:
    if _inline_mode():
        _run_task(task_id, payload, registry=registry)
    else:
        _get_executor().submit(_run_task, task_id, payload, registry)


def _active_task(
    db: Session,
    *,
    task_type: str,
    ledger_id: str | None,
) -> BackgroundTask | None:
    stmt = select(BackgroundTask).where(
        BackgroundTask.task_type == task_type,
        BackgroundTask.status.in_(_RECOVERABLE_STATUSES),
    )
    if ledger_id is None:
        stmt = stmt.where(BackgroundTask.tenant_id.is_(None))
    else:
        stmt = stmt.where(BackgroundTask.tenant_id == ledger_id)
    return db.scalar(stmt.order_by(BackgroundTask.created_at.desc()).limit(1))


def get_task(
    db: Session, public_id: str, *, account_id: int | None, tenant_id: str | None
) -> BackgroundTask:
    """Owner-scoped fetch. account_id=None means caller is system-scoped
    (no enforcement) — only safe in tests / startup hooks. When account_id is
    set, the task must also belong to the caller's active ledger (tenant_id):
    a multi-ledger account must not read another ledger's tasks just because it
    initiated them under a different binding."""
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == public_id))
    if task is None:
        raise AppError("task_not_found", status_code=404)
    if account_id is not None and (
        task.initiated_by_account_id != account_id or task.tenant_id != tenant_id
    ):
        # Don't leak existence — return same 404 as missing task.
        raise AppError("task_not_found", status_code=404)
    return task


def list_recent_tasks(
    db: Session, *, account_id: int | None, tenant_id: str | None, limit: int = 50
) -> list[BackgroundTask]:
    """Most-recent first; scoped to the caller's account AND active ledger so a
    user only sees their own ledger's tasks (system tasks with tenant_id=NULL
    are not surfaced through the user-facing task list)."""
    if account_id is None:
        return []
    rows = db.scalars(
        select(BackgroundTask)
        .where(BackgroundTask.initiated_by_account_id == account_id)
        .where(BackgroundTask.tenant_id == tenant_id)
        .order_by(BackgroundTask.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def request_cancellation(
    db: Session, public_id: str, *, account_id: int | None, tenant_id: str | None
) -> BackgroundTask:
    """Set ``cancellation_requested_at``. The handler observes it at the
    next chunk boundary and bails. Idempotent: cancelling an already-
    terminal task returns it unchanged."""
    task = get_task(db, public_id, account_id=account_id, tenant_id=tenant_id)
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

def _run_task(
    task_id: int,
    payload: dict[str, Any],
    registry: TaskHandlerRegistry | None = None,
) -> None:
    """Pulled from the executor (or called inline in tests). Owns a single
    SessionLocal so all writes go through one DB session even if the
    handler does its own commits."""
    with SessionLocal() as db:
        task = _claim_queued_task(db, task_id)
        if task is None:
            if db.get(BackgroundTask, task_id) is None:
                logger.error("background task %s vanished before run", task_id)
            return

        active_registry = registry or _current_handler_registry()
        handler = active_registry.get(task.task_type)
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


def _claim_queued_task(db: Session, task_id: int) -> BackgroundTask | None:
    """Atomically claim a queued task for this worker.

    The conditional UPDATE is the DB-backed guard that matters in shared-DB
    cloud deployments: if two workers are asked to run the same row, only one
    can move it from queued to running.
    """

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
    claimed: BackgroundTask | None = None
    if result.rowcount == 1:
        claimed = db.get(BackgroundTask, task_id)
    return claimed


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
    """Recover active tasks that the current deployment should treat as dead.

    Default behavior remains the single-process ADR-0030 rule: fail every
    ``running`` and ``queued`` row on startup because the previous in-memory
    executor and queue cannot be resumed. When
    ``BACKGROUND_TASK_ORPHAN_GRACE_SECONDS`` is positive, fresh active rows are
    preserved and only rows whose heartbeat/creation timestamp exceeded the
    grace window are failed. That is the cloud/multi-worker compatibility
    valve; it is not a durable distributed queue.
    """
    return _recover_orphaned_tasks()
