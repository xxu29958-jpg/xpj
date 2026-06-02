"""Goals (spending limits / period targets) CRUD payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "GoalCreateRequest",
    "GoalListResponse",
    "GoalResponse",
    "GoalUpdateRequest",
]


class GoalCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    month: str = Field(min_length=7, max_length=7)
    category: str | None = Field(default=None, max_length=64)
    target_amount_cents: int = Field(gt=0)
    goal_type: str = "spending_limit"
    period: str = "monthly"


class GoalUpdateRequest(BaseModel):
    """ADR-0038 PR-2j: ``PATCH /api/goals/{public_id}`` body.

    ``expected_updated_at`` is the client's last-seen optimistic-
    concurrency token. Service issues atomic ``UPDATE WHERE id,
    tenant_id, updated_at = expected`` and returns 409 ``state_conflict``
    on stale snapshot. Same shape as the rest of the v1.3 PATCH surface.
    """

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime
    name: str | None = Field(default=None, min_length=1, max_length=80)
    month: str | None = Field(default=None, min_length=7, max_length=7)
    category: str | None = Field(default=None, max_length=64)
    target_amount_cents: int | None = Field(default=None, gt=0)


class GoalResponse(BaseModel):
    public_id: str
    ledger_id: str
    name: str
    goal_type: str
    period: str
    month: str
    category: str | None = None
    target_amount_cents: int
    spent_amount_cents: int
    remaining_amount_cents: int
    progress_percent: int
    progress_state: str
    status: str
    created_at: datetime
    updated_at: datetime
    row_version: int
    archived_at: datetime | None = None

    @field_serializer("created_at", "updated_at", "archived_at")
    def serialize_goal_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
