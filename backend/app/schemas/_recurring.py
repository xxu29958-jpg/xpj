"""Recurring candidates (insights) and v0.6 formal recurring items."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "RecurringCandidateConfirmRequest",
    "RecurringCandidateItem",
    "RecurringCandidatesResponse",
    "RecurringItemListResponse",
    "RecurringItemResponse",
]


# v0.4-alpha3 — Recurring candidates (read-only insights)
class RecurringCandidateItem(BaseModel):
    merchant: str
    amount_cents: int
    occurrence_count: int
    last_seen_at: datetime | None
    confidence: str
    reason: str

    @field_serializer("last_seen_at")
    def serialize_last_seen_at(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RecurringCandidatesResponse(BaseModel):
    items: list[RecurringCandidateItem]


# v0.6 — Formal recurring items
class RecurringCandidateConfirmRequest(BaseModel):
    merchant: str = Field(min_length=1, max_length=255)
    amount_cents: int = Field(ge=1)
    occurrence_count: int = Field(default=0, ge=0)
    last_seen_at: datetime | None = None
    confidence: str | None = Field(default=None, max_length=32)
    frequency: str = Field(default="monthly", max_length=32)
    next_expected_date: date | None = None


class RecurringItemResponse(BaseModel):
    public_id: str
    ledger_id: str
    merchant: str
    merchant_key: str
    frequency: str
    baseline_amount_cents: int
    last_amount_cents: int
    occurrence_count: int
    last_seen_at: datetime | None = None
    next_expected_date: date | None = None
    status: str
    confidence: str | None = None
    source: str
    anomaly_status: str = "none"
    current_month_amount_cents: int | None = None
    historical_average_amount_cents: int | None = None
    amount_delta_percent: int | None = None
    created_at: datetime
    updated_at: datetime
    paused_at: datetime | None = None
    archived_at: datetime | None = None

    @field_serializer("last_seen_at", "created_at", "updated_at", "paused_at", "archived_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RecurringItemListResponse(BaseModel):
    items: list[RecurringItemResponse]
