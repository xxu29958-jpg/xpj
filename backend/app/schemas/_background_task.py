"""ADR-0030 background_tasks DTOs.

Single response shape covers all task_types. ``result_summary`` is a free-
form JSON object whose shape depends on task_type (csv_import returns
``rows_imported`` / ``errors``; v1_migration returns ``shadow_db_path``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "BackgroundTaskListResponse",
    "BackgroundTaskResponse",
    "BackgroundTaskStatus",
]

BackgroundTaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class BackgroundTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    task_type: str
    status: BackgroundTaskStatus
    progress_current: int = 0
    progress_total: int | None = None
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_progress_at: datetime | None = None
    cancellation_requested_at: datetime | None = None

    @field_serializer(
        "created_at", "started_at", "completed_at", "last_progress_at",
        "cancellation_requested_at",
    )
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class BackgroundTaskListResponse(BaseModel):
    items: list[BackgroundTaskResponse] = Field(default_factory=list)
