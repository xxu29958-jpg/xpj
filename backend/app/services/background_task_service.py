"""ADR-0030 in-process long-task execution model.

Design:
    - One module-owned executor pool (max_workers=2) bounds the number of
      concurrent background tasks per backend instance.
    - Production task implementations live in an explicit runtime catalog
      (see ``background_task_registry.runtime_handler_registry``). Tests may
      inject a per-test registry through :func:`isolated_registered_handlers_for_testing`;
      production code does not mutate a module-level handler map.
    - All progress writes go through ``background_task_handler_api`` so
      chunked transactions and ``last_progress_at`` heartbeats are consistent.
    - ``XPJ_BACKGROUND_TASK_INLINE=1`` runs ``enqueue`` synchronously
      (no executor thread) so unit tests can verify chunk / cancellation
      / handler outcomes without needing a real worker thread + a file-
      backed SQLite shared across threads.

Cancellation contract:
    Handlers must call ``background_task_handler_api.check_cancellation_requested`` at every chunk
    boundary. If it returns ``True`` the handler raises
    :class:`TaskCancelledError` (or returns a ``cancelled`` result) — the
    service does the rest.

Orphan recovery:
    :func:`recover_orphaned_tasks` is called from the FastAPI lifespan and
    finishes committed OCR receipts, including their FX handoff. Durable OCR
    input is discovered by the same recovery owner, preserving queued work and
    bounding interrupted attempts; replay cannot reset its budget or deadline.
    Other domains retain original-request recovery and the configurable orphan
    grace window. Startup never repeats inference for an applied receipt.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask
from app.services import background_task_executor, background_task_worker
from app.services.background_task_admission import stage_queued_task
from app.services.background_task_executor import BackgroundTaskSubmissionError as BackgroundTaskSubmissionError
from app.services.background_task_executor import (
    shutdown_executor as _shutdown_executor,
)
from app.services.background_task_recovery_service import (
    recover_orphaned_tasks as _recover_orphaned_tasks,
)
from app.services.background_task_registry import PreparedBackgroundTask, TaskHandler, TaskHandlerRegistry
from app.services.background_task_registry import (
    runtime_handler_registry as _runtime_handler_registry,
)
from app.services.background_task_worker import run_task as _run_background_task
from app.services.time_service import now_utc

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_RECOVERABLE_STATUSES = frozenset({"running", "queued"})


class BackgroundTaskRegistrationError(Exception):
    """Raised when test-only handler registration is used outside its scope."""


_handler_registry_context: ContextVar[TaskHandlerRegistry | None] = ContextVar(
    "xpj_background_task_handler_registry",
    default=None,
)


def _current_handler_registry() -> TaskHandlerRegistry:
    return _handler_registry_context.get() or _runtime_handler_registry()


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


def shutdown_executor(wait: bool = False) -> None:
    """For graceful shutdown / tests. After this, enqueue() will rebuild."""
    _shutdown_executor(wait=wait)


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
    try:
        prepared = prepare_enqueue(
            db,
            task_type=task_type,
            initiator_account_id=initiator_account_id,
            initiator_device_id=initiator_device_id,
            ledger_id=ledger_id,
            payload=payload,
            progress_total=progress_total,
        )
        db.commit()
    except Exception:  # noqa: BLE001 - caller-owned transaction rollback barrier
        db.rollback()
        raise
    return submit_committed(db, prepared)


def prepare_enqueue(
    db: Session,
    *,
    task_type: str,
    initiator_account_id: int | None,
    initiator_device_id: int | None = None,
    ledger_id: str | None = None,
    payload: dict[str, Any] | None = None,
    progress_total: int | None = None,
) -> PreparedBackgroundTask:
    """Validate, admit, and stage a task without committing it."""

    registry = _current_handler_registry()
    if not registry.contains(task_type):
        raise AppError(
            "unknown_task_type",
            f"Background task type {task_type!r} is not registered.",
            status_code=400,
        )

    payload_copy = dict(payload or {})
    task = stage_queued_task(
        db,
        task_type=task_type,
        initiator_account_id=initiator_account_id,
        initiator_device_id=initiator_device_id,
        ledger_id=ledger_id,
        progress_total=progress_total,
        source_expense_id=payload_copy.get("expense_id") if task_type in background_task_executor.OCR_TASK_TYPES else None,
    )
    return PreparedBackgroundTask(
        task=task,
        task_id=task.id,
        task_public_id=task.public_id,
        payload=payload_copy,
        registry=registry,
    )


def submit_committed(
    db: Session,
    prepared: PreparedBackgroundTask,
) -> BackgroundTask:
    """Submit an already-committed task, preserving its durable receipt on failure."""

    return background_task_executor.submit_committed(db, prepared, runner=_run_background_task)


def submit_existing(db: Session, task: BackgroundTask, payload: dict[str, object]) -> BackgroundTask:
    """Reconstruct execution for a domain-validated durable task, without new admission."""
    return submit_committed(db, PreparedBackgroundTask(
        task=task, task_id=task.id, task_public_id=task.public_id,
        payload=dict(payload), registry=_current_handler_registry(),
    ))


def complete_applied_task(task_id: int) -> None:
    """Finish only a committed OCR receipt after process death, without inference."""
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        if (task is None or task.task_type not in background_task_executor.OCR_TASK_TYPES
                or task.result_summary_json is None):
            return
        background_task_worker._mark_completed(db, task_id, _runtime_handler_registry(), recover_applied=True)


def get_task(db: Session, public_id: str, *, account_id: int | None, tenant_id: str | None) -> BackgroundTask:
    """Owner-scoped fetch. account_id=None means caller is system-scoped
    (no enforcement) — only safe in tests / startup hooks. When account_id is
    set, the task must also belong to the caller's active ledger (tenant_id):
    a multi-ledger account must not read another ledger's tasks just because it
    initiated them under a different binding."""
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == public_id))
    if task is None:
        raise AppError("task_not_found", status_code=404)
    if account_id is not None and (task.initiated_by_account_id != account_id or task.tenant_id != tenant_id):
        # Don't leak existence — return same 404 as missing task.
        raise AppError("task_not_found", status_code=404)
    return task


def list_recent_tasks(
    db: Session, *, account_id: int | None, tenant_id: str | None, limit: int = 50,
    task_type: str | None = None,
) -> list[BackgroundTask]:
    """Most-recent first; scoped to the caller's account AND active ledger so a
    user only sees their own ledger's tasks (system tasks with tenant_id=NULL
    are not surfaced through the user-facing task list)."""
    if account_id is None:
        return []
    query = (
        select(BackgroundTask)
        .where(BackgroundTask.initiated_by_account_id == account_id)
        .where(BackgroundTask.tenant_id == tenant_id)
    )
    if task_type is not None:
        query = query.where(BackgroundTask.task_type == task_type)
    rows = db.scalars(query.order_by(BackgroundTask.created_at.desc()).limit(limit))
    return list(rows)


def request_cancellation(
    db: Session, public_id: str, *, account_id: int | None, tenant_id: str | None
) -> BackgroundTask:
    """Set ``cancellation_requested_at``. The handler observes it at the
    next chunk boundary and bails. Idempotent: cancelling an already-
    terminal task returns it unchanged."""
    task = get_task(db, public_id, account_id=account_id, tenant_id=tenant_id)
    db.refresh(task, with_for_update=True)
    if task.status in _TERMINAL_STATUSES or task.result_summary_json is not None:
        return task
    if task.cancellation_requested_at is None:
        task.cancellation_requested_at = now_utc()
    if task.status == "queued" and task.task_type in background_task_executor.OCR_TASK_TYPES:
        from app.services.background_task_handler_api import stage_task_cancellation

        stage_task_cancellation(task)
    db.commit()
    db.refresh(task)
    return task


# -------------------------------------------------------------------------
# Orphan recovery (called from FastAPI lifespan)


def recover_orphaned_tasks() -> int:
    """Recover active tasks that the current deployment should treat as dead.

    Complete OCR rows that already own an applied receipt, retain queued input
    and bound interrupted OCR attempts; fence work owned by other domains. When
    ``BACKGROUND_TASK_ORPHAN_GRACE_SECONDS`` is positive, fresh active rows are
    preserved and only rows whose heartbeat/creation timestamp exceeded the
    grace window are failed. That is the cloud/multi-worker compatibility
    valve; it is not a durable distributed queue.
    """
    return _recover_orphaned_tasks()
