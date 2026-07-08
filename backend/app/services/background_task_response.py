"""Background task DTO conversion helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TypedDict, cast

from app.models import BackgroundTask
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


def to_response_dict(task: BackgroundTask) -> BackgroundTaskResponsePayload:
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
    }
