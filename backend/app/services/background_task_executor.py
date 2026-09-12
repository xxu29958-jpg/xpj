"""Process-local executor lifecycle for durable background-task rows."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import BackgroundTask
from app.services.background_task_handler_api import mark_failed
from app.services.background_task_registry import PreparedBackgroundTask, TaskHandlerRegistry

logger = logging.getLogger(__name__)

MAX_WORKERS = 2

TaskRunner = Callable[[int, dict[str, Any], TaskHandlerRegistry], None]


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
        logger.exception("background task %s could not be submitted", prepared.task_id)
        try:
            mark_failed(db, prepared.task_id, expected_status="queued", error_code="task_submission_failed",
                error_message="Task execution could not be started.")
        except SQLAlchemyError:
            # The receipt is durable; startup recovery owns a queued orphan if
            # this secondary status publication fails.
            db.rollback()
            logger.exception("background task %s failure status could not be persisted", prepared.task_id)
        raise BackgroundTaskSubmissionError(prepared.task_public_id) from exc
    return prepared.task


class _ExecutorPool:
    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._lock = Lock()

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
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=MAX_WORKERS,
                    thread_name_prefix="xpj-bgtask",
                )
            self._executor.submit(runner, task_id, payload, registry)

    def shutdown(self, *, wait: bool) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=True)


_EXECUTOR_POOL = _ExecutorPool()


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


__all__ = ["BackgroundTaskSubmissionError", "MAX_WORKERS", "shutdown_executor", "submit_committed", "submit_task"]
