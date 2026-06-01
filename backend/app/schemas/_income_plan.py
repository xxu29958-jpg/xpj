"""v1.1 monthly income plan request / response shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "IncomePlanCreateRequest",
    "IncomePlanListResponse",
    "IncomePlanResponse",
    "IncomePlanTokenRequest",
    "IncomePlanUpdateRequest",
]


class IncomePlanCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    source_type: str = Field(default="salary", min_length=1, max_length=32)
    amount_cents: int = Field(ge=0)
    pay_day: int = Field(ge=1, le=31)


class IncomePlanUpdateRequest(BaseModel):
    """ADR-0038 PR-2j: ``PATCH /api/income-plans/{public_id}`` body.

    ``expected_updated_at`` is the client's last-seen optimistic-
    concurrency token. Service issues atomic ``UPDATE WHERE id,
    tenant_id, status='active', updated_at = expected`` and returns
    409 ``state_conflict`` on stale snapshot.
    """

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime
    label: str | None = Field(default=None, min_length=1, max_length=64)
    source_type: str | None = Field(default=None, min_length=1, max_length=32)
    amount_cents: int | None = Field(default=None, ge=0)
    pay_day: int | None = Field(default=None, ge=1, le=31)


class IncomePlanTokenRequest(BaseModel):
    """ADR-0038 PR-B: ``DELETE /api/income-plans/{public_id}`` (archive) and
    ``POST .../{public_id}/restore`` body — carries the client's last-seen
    optimistic-concurrency token so a stale archive/restore against a
    concurrently-modified plan is rejected with 409 ``state_conflict``
    instead of silently flipping status.
    """

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime


class IncomePlanResponse(BaseModel):
    public_id: str
    label: str
    source_type: str
    amount_cents: int
    pay_day: int
    status: Literal["active", "archived"]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    @field_serializer("created_at", "updated_at", "archived_at")
    def _iso(self, value: datetime | None) -> str | None:
        return to_iso(value)


class IncomePlanListResponse(BaseModel):
    items: list[IncomePlanResponse]
    total_active_amount_cents: int
