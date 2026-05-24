"""v1.1 monthly income plan request / response shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "IncomePlanCreateRequest",
    "IncomePlanListResponse",
    "IncomePlanResponse",
    "IncomePlanUpdateRequest",
]


class IncomePlanCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    source_type: str = Field(default="salary", min_length=1, max_length=32)
    amount_cents: int = Field(ge=0)
    pay_day: int = Field(ge=1, le=31)


class IncomePlanUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    source_type: str | None = Field(default=None, min_length=1, max_length=32)
    amount_cents: int | None = Field(default=None, ge=0)
    pay_day: int | None = Field(default=None, ge=1, le=31)


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
