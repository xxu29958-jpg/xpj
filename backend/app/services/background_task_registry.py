"""Background task handler registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.models import BackgroundTask

TaskHandler = Callable[[Session, BackgroundTask, dict[str, Any]], None]


class TaskHandlerRegistry:
    def __init__(self, handlers: dict[str, TaskHandler] | None = None) -> None:
        self._handlers_by_type: dict[str, TaskHandler] = dict(handlers or {})

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self._handlers_by_type[task_type] = handler

    def get(self, task_type: str) -> TaskHandler | None:
        return self._handlers_by_type.get(task_type)

    def contains(self, task_type: str) -> bool:
        return task_type in self._handlers_by_type

    def snapshot(self) -> dict[str, TaskHandler]:
        return dict(self._handlers_by_type)

    def replace(self, handlers: dict[str, TaskHandler] | None = None) -> dict[str, TaskHandler]:
        previous = self.snapshot()
        self._handlers_by_type.clear()
        self._handlers_by_type.update(dict(handlers or {}))
        return previous


def runtime_handler_registry() -> TaskHandlerRegistry:
    """Build the production handler catalog.

    Returns a fresh registry every time instead of keeping a mutable
    module-level handler map, so runtime task types are explicit code
    dependencies. Tests that need stubs use background_task_service's isolated
    ContextVar registry.
    """
    from app.services.pending_enrichment_task_service import (
        PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
        run_pending_expense_enrichment_task,
    )

    return TaskHandlerRegistry(
        {
            PENDING_EXPENSE_ENRICHMENT_TASK_TYPE: run_pending_expense_enrichment_task,
        }
    )
