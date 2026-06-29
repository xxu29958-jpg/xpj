"""ADR-0051 current-ledger recycle-bin DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "RecycleBinItemResponse",
    "RecycleBinListResponse",
    "RecycleBinRestoreRequest",
    "RecycleBinRestoreResponse",
]


class RecycleBinItemResponse(BaseModel):
    kind: str
    kind_label: str
    resource_id: str
    title: str
    detail: str
    removed_at: datetime | None
    retention_label: str
    expected_row_version: int | None

    @field_serializer("removed_at")
    def serialize_removed_at(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RecycleBinListResponse(BaseModel):
    items: list[RecycleBinItemResponse]
    short_window_count: int


class RecycleBinRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=32)
    resource_id: str = Field(min_length=1, max_length=64)
    expected_row_version: int | None = None


class RecycleBinRestoreResponse(BaseModel):
    message: str
