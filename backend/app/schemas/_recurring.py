"""Recurring candidates (insights) and v0.6 formal recurring items."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.schemas._money import NonNegativeMoneyMinor, PositiveMoneyMinor
from app.services.recurring_merchant_capacity import RECURRING_MERCHANT_MAX_LENGTH
from app.services.time_service import to_iso

__all__ = [
    "RecurringCandidateConfirmRequest",
    "RecurringCandidateItem",
    "RecurringCandidatesResponse",
    "RecurringItemListResponse",
    "RecurringItemCreateRequest",
    "RecurringItemResponse",
    "RecurringItemTokenRequest",
    "RecurringItemUpdateRequest",
]


def _preserve_recurring_merchant_length_error(value: object) -> object:
    if isinstance(value, str) and len(value) > RECURRING_MERCHANT_MAX_LENGTH:
        raise PydanticCustomError(
            "recurring_merchant_too_long",
            "recurring merchant must fit storage",
        )
    return value


class RecurringItemTokenRequest(BaseModel):
    """ADR-0038 PR-A: ``POST /api/recurring/items/{public_id}/{pause,resume}``
    body. The OCC token rejects stale toggle requests across the
    pause↔active state-machine pair — without it, a stale pause arriving
    after a user-intentional resume would silently re-pause (atomic
    UPDATE WHERE status!='archived' matches either state)."""

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int


# v0.4-alpha3 — Recurring candidates (read-only insights)
class RecurringCandidateItem(BaseModel):
    merchant: str
    amount_cents: PositiveMoneyMinor
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
    model_config = ConfigDict(extra="forbid")

    merchant: str = Field(min_length=1, max_length=RECURRING_MERCHANT_MAX_LENGTH)
    _merchant_length_error = field_validator("merchant", mode="before")(_preserve_recurring_merchant_length_error)
    amount_cents: PositiveMoneyMinor
    occurrence_count: int = Field(
        default=0,
        ge=0,
        deprecated=True,
        description="Compatibility input only; confirmation uses the current server-side candidate observation.",
    )
    last_seen_at: datetime | None = Field(
        default=None,
        deprecated=True,
        description="Compatibility input only; confirmation uses the current server-side candidate observation.",
    )
    confidence: str | None = Field(
        default=None,
        max_length=32,
        deprecated=True,
        description="Compatibility input only; confirmation uses the current server-side candidate observation.",
    )
    frequency: str = Field(default="monthly", max_length=32)
    next_expected_date: date | None = None


class RecurringItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: str = Field(min_length=1, max_length=RECURRING_MERCHANT_MAX_LENGTH)
    _merchant_length_error = field_validator("merchant", mode="before")(_preserve_recurring_merchant_length_error)
    baseline_amount_cents: PositiveMoneyMinor
    next_expected_date: date | None = None


class RecurringItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: str | None = Field(
        default=None,
        min_length=1,
        max_length=RECURRING_MERCHANT_MAX_LENGTH,
    )
    _merchant_length_error = field_validator("merchant", mode="before")(_preserve_recurring_merchant_length_error)
    baseline_amount_cents: PositiveMoneyMinor | None = None
    next_expected_date: date | None = None
    expected_row_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_edit(self) -> RecurringItemUpdateRequest:
        if not ({"merchant", "baseline_amount_cents", "next_expected_date"} & self.model_fields_set):
            raise ValueError("at least one editable field is required")
        return self


class RecurringItemResponse(BaseModel):
    public_id: str
    ledger_id: str
    merchant: str
    merchant_key: str
    frequency: str
    baseline_amount_cents: PositiveMoneyMinor
    last_amount_cents: PositiveMoneyMinor
    occurrence_count: int
    last_seen_at: datetime | None = None
    next_expected_date: date | None = None
    status: str
    confidence: str | None = None
    source: str
    anomaly_status: str = "none"
    current_month_amount_cents: NonNegativeMoneyMinor | None = None
    historical_average_amount_cents: NonNegativeMoneyMinor | None = None
    amount_delta_percent: int | None = None
    created_at: datetime
    updated_at: datetime
    row_version: int
    paused_at: datetime | None = None
    archived_at: datetime | None = None

    @field_serializer("last_seen_at", "created_at", "updated_at", "paused_at", "archived_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RecurringItemListResponse(BaseModel):
    items: list[RecurringItemResponse]
