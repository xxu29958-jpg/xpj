"""Ledger calendar governance; rule changes affect future input only."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso


class LedgerCalendarChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone_name: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(strict=True, gt=0)


class LedgerCalendarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ledger_id: str
    revision: int
    timezone_name: str
    basis: str
    adopted_at: datetime

    @field_serializer("adopted_at")
    def serialize_adopted_at(self, value: datetime) -> str:
        return to_iso(value)
