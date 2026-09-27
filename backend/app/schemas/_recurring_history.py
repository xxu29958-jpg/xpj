"""A recorded definition is evidence at recording time, not a month-effective rule."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.schemas._money import NonNegativeMoneyMinor
from app.services.time_service import to_iso


class RecurringItemSnapshot(BaseModel):
    merchant: str
    merchant_key: str
    frequency: Literal["monthly"]
    home_currency_code: str | None
    baseline_amount_cents: NonNegativeMoneyMinor
    next_expected_date: date | None
    status: Literal["active", "paused", "archived"]
    source: str


class RecurringItemRevisionResponse(BaseModel):
    row_version: int = Field(ge=1)
    change_kind: Literal["baseline", "create", "edit", "pause", "resume", "archive", "restore"]
    recorded_at: datetime
    actor_account_id: int | None
    snapshot: RecurringItemSnapshot

    @field_serializer("recorded_at")
    def serialize_time(self, value: datetime) -> str:
        return to_iso(value)


class RecurringItemHistoryResponse(BaseModel):
    ledger_id: str
    public_id: str
    items: list[RecurringItemRevisionResponse]
    next_before_version: int | None


class RecordedRecurringDefinition(BaseModel):
    series_row_version: int = Field(ge=1)
    recorded_at: datetime
    snapshot: RecurringItemSnapshot

    @field_serializer("recorded_at")
    def serialize_time(self, value: datetime) -> str:
        return to_iso(value)
