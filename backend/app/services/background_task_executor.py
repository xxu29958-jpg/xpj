"""Process-local executor lifecycle for durable background-task rows."""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from app.services.background_task_registry import TaskHandlerRegistry

MAX_WORKERS = 2

TaskRunner = Callable[[int, dict[str, Any], TaskHandlerRegistry], None]


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


__all__ = ["MAX_WORKERS", "shutdown_executor", "submit_task"]
