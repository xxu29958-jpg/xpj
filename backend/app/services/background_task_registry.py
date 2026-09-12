"""Background task handler registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.models import BackgroundTask

if TYPE_CHECKING:
    from app.services.background_task_service import PreparedBackgroundTask

TaskHandler = Callable[[Session, BackgroundTask, dict[str, Any]], None]
TaskCompletion = Callable[[Session, BackgroundTask], "PreparedBackgroundTask | None"]


class TaskHandlerRegistry:
    def __init__(self, handlers: dict[str, TaskHandler] | None = None, *,
        completions: dict[str, TaskCompletion] | None = None) -> None:
        self._handlers_by_type: dict[str, TaskHandler] = dict(handlers or {})
        self._completions_by_type = dict(completions or {})

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self._handlers_by_type[task_type] = handler
        self._completions_by_type.pop(task_type, None)

    def get(self, task_type: str) -> TaskHandler | None:
        return self._handlers_by_type.get(task_type)

    def contains(self, task_type: str) -> bool:
        return task_type in self._handlers_by_type

    def prepare_completion(self, db: Session, task: BackgroundTask) -> PreparedBackgroundTask | None:
        completion = self._completions_by_type.get(task.task_type)
        return completion(db, task) if completion is not None else None

    def snapshot(self) -> dict[str, TaskHandler]:
        return dict(self._handlers_by_type)

    def replace(self, handlers: dict[str, TaskHandler] | None = None) -> dict[str, TaskHandler]:
        previous = self.snapshot()
        self._handlers_by_type.clear()
        self._handlers_by_type.update(dict(handlers or {}))
        self._completions_by_type.clear()
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
        prepare_pending_enrichment_completion,
        run_pending_expense_enrichment_task,
    )
    from app.services.pending_fx_task_service import PENDING_EXPENSE_FX_TASK_TYPE, run_pending_expense_fx_task

    return TaskHandlerRegistry(
        {
            PENDING_EXPENSE_ENRICHMENT_TASK_TYPE: run_pending_expense_enrichment_task,
            PENDING_EXPENSE_FX_TASK_TYPE: run_pending_expense_fx_task,
        },
        completions={PENDING_EXPENSE_ENRICHMENT_TASK_TYPE: prepare_pending_enrichment_completion},
    )
