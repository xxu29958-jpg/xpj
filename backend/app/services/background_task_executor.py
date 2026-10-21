"""Process-local executor lifecycle for durable background-task rows."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.error_reporting import report_error
from app.models import BackgroundTask
from app.services.background_task_handler_api import mark_failed
from app.services.background_task_registry import PreparedBackgroundTask, TaskHandlerRegistry

logger = logging.getLogger(__name__)

MAX_WORKERS = 2
OCR_TASK_TYPES = frozenset({"expense_enrichment", "expense_ocr_retry"})

TaskRunner = Callable[[int, dict[str, Any], TaskHandlerRegistry], None]


class ExecutorLifecycleError(RuntimeError):
    """The previous pool must finish stopping before accepting work."""


class BackgroundTaskSubmissionError(RuntimeError):
    """A durable task row exists, but its in-process execution was not submitted."""

    def __init__(self, task_public_id: str) -> None:
        super().__init__("background task submission failed")
        self.task_public_id = task_public_id


def submit_committed(db: Session, prepared: PreparedBackgroundTask, *, runner: TaskRunner) -> BackgroundTask:
    """Submit a durable task and publish only that task's conditional refusal."""
    try:
        submit_task(prepared.task_id, prepared.payload, registry=prepared.registry, runner=runner)
    except Exception as exc:  # noqa: BLE001 - executor submission barrier
        report_error(logger, "background task %s stage=submit could not be submitted", prepared.task_id, error=exc)
        try:
            mark_failed(db, prepared.task_id, expected_status="queued", error_code="task_submission_failed",
                error_message="Task execution could not be started.")
        except SQLAlchemyError as status_error:
            # The receipt is durable; startup recovery owns a queued orphan if
            # this secondary status publication fails.
            db.rollback()
            report_error(logger, "background task %s stage=submit_failure_status could not be persisted",
                prepared.task_id, error=status_error)
        raise BackgroundTaskSubmissionError(prepared.task_public_id) from exc
    return prepared.task


class _ExecutorPool:
    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._lock = RLock()
        self._active: dict[int, str] = {}
        self._waiting: dict[int, tuple[str, dict[str, Any], TaskHandlerRegistry, TaskRunner]] = {}
        self._stopping = False

    def start(self) -> None:
        with self._lock:
            if self._active:
                raise ExecutorLifecycleError("previous background executor still owns running tasks")
            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None
            self._stopping = False

    def submit(
        self,
        task_id: int,
        payload: dict[str, Any],
        registry: TaskHandlerRegistry,
        runner: TaskRunner,
    ) -> None:
        if os.environ.get("XPJ_BACKGROUND_TASK_INLINE") == "1":
            runner(task_id, payload, registry)
            return
        with SessionLocal() as db:
            task = db.get(BackgroundTask, task_id)
            if task is None or task.status != "queued":
                return
            task_type = task.task_type
        with self._lock:
            if self._stopping:
                raise ExecutorLifecycleError("background executor is stopping")
            if task_id in self._active or task_id in self._waiting:
                return
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=MAX_WORKERS,
                    thread_name_prefix="xpj-bgtask",
                )
            # These are wakeup bindings for already durable PG rows. They have
            # not been submitted to a pool and remain queued until capacity is
            # reserved. Startup recovery still uses the original PG receipt.
            self._waiting[task_id] = (task_type, payload, registry, runner)
            self._dispatch()

    def _dispatch(self) -> None:
        while not self._stopping and len(self._active) < MAX_WORKERS:
            ocr_busy = any(kind in OCR_TASK_TYPES for kind in self._active.values())
            candidate = next((task_id for task_id, value in self._waiting.items()
                              if not (ocr_busy and value[0] in OCR_TASK_TYPES)), None)
            if candidate is None:
                return
            task_type, payload, registry, runner = self._waiting.pop(candidate)
            self._active[candidate] = task_type
            try:
                future = self._executor.submit(runner, candidate, payload, registry)
            except RuntimeError:
                self._active.pop(candidate)
                raise
            future.add_done_callback(lambda finished, task_id=candidate: self._finished(task_id, finished))

    def _finished(self, task_id: int, future: Future[None]) -> None:
        _report_worker_outcome(task_id, future)
        with self._lock:
            self._active.pop(task_id, None)
            try:
                self._dispatch()
            except RuntimeError as exc:
                # A refused wakeup still has its original queued PG receipt.
                # A callback has no HTTP caller to observe this pool failure.
                report_error(logger, "background task %s stage=dispatch could not wake queued work",
                    task_id, error=exc)

    def shutdown(self, *, wait: bool) -> None:
        with self._lock:
            self._stopping = True
            self._waiting.clear()
            executor = self._executor
            # Retain the stopped pool so a later joined shutdown/start can wait
            # for threads left by a nonwaiting application stop.
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=True)


_EXECUTOR_POOL = _ExecutorPool()


def _report_worker_outcome(task_id: int, future: Future[None]) -> None:
    # A pool Future otherwise retains outside-handler errors without an observer.
    # Inline execution already propagates to the existing submission boundary.
    if not future.cancelled() and (error := future.exception()) is not None:
        report_error(logger, "background task %s stage=worker_boundary failed", task_id, error=error)


def submit_task(
    task_id: int,
    payload: dict[str, Any],
    *,
    registry: TaskHandlerRegistry,
    runner: TaskRunner,
) -> None:
    _EXECUTOR_POOL.submit(task_id, payload, registry, runner)


def shutdown_executor(*, wait: bool) -> None:
    _EXECUTOR_POOL.shutdown(wait=wait)


def start_executor() -> None:
    _EXECUTOR_POOL.start()


__all__ = ["BackgroundTaskSubmissionError", "MAX_WORKERS", "shutdown_executor", "start_executor",
           "submit_committed", "submit_task"]
