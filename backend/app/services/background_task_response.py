"""Background task DTO conversion helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TypedDict, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundTask, Expense
from app.services._json_types import JsonObject

logger = logging.getLogger(__name__)


class BackgroundTaskResponsePayload(TypedDict):
    public_id: str
    task_type: str
    status: str
    progress_current: int
    progress_total: int | None
    progress_message: str | None
    error_code: str | None
    error_message: str | None
    result_summary: JsonObject | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_progress_at: datetime | None
    cancellation_requested_at: datetime | None
    source_expense_id: int | None


def task_response_dicts(
    db: Session, tasks: list[BackgroundTask], *, tenant_id: str,
) -> list[BackgroundTaskResponsePayload]:
    """Project original task sources in one ledger-scoped query; never replay work."""
    sources = {task.id: _source_expense_id(task, tenant_id=tenant_id) for task in tasks}
    ids = {source_id for source_id in sources.values() if source_id is not None}
    available = set(db.scalars(select(Expense.id).where(
        Expense.tenant_id == tenant_id,
        Expense.id.in_(ids),
        Expense.status.in_(("pending", "confirmed")),
    ))) if ids else set()
    source_ids = {task_id: source_id for task_id, source_id in sources.items() if source_id in available}
    return [_to_response_dict(task, source_expense_id=source_ids.get(task.id)) for task in tasks]


def _source_expense_id(task: BackgroundTask, *, tenant_id: str) -> int | None:
    if task.task_type not in {"expense_enrichment", "expense_fx"} or task.tenant_id != tenant_id:
        return None
    return task.source_expense_id


def _to_response_dict(task: BackgroundTask, *, source_expense_id: int | None) -> BackgroundTaskResponsePayload:
    """Convert an ORM row into a BackgroundTaskResponse-compatible dict."""

    result_summary: JsonObject | None = None
    if task.result_summary_json:
        try:
            decoded = json.loads(task.result_summary_json)
            if isinstance(decoded, dict):
                result_summary = cast(JsonObject, decoded)
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
        "source_expense_id": source_expense_id,
    }
