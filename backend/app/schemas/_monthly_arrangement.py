"""Monthly intentions in captured currency, independent from budget and balances."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_serializer

from app.schemas._money import NonNegativeMoneyMinor
from app.services.time_service import to_iso


class MonthlyArrangementSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_currency_code: str = Field(min_length=3, max_length=3)
    savings_target_cents: NonNegativeMoneyMinor
    reserved_buffer_cents: NonNegativeMoneyMinor
    expected_row_version: Annotated[int, Field(strict=True, ge=1)] | None


class MonthlyArrangementDto(BaseModel):
    ledger_id: str
    month: str
    home_currency_code: str
    savings_target_cents: NonNegativeMoneyMinor
    reserved_buffer_cents: NonNegativeMoneyMinor
    row_version: PositiveInt
    updated_at: datetime

    @field_serializer("updated_at")
    def serialize_updated_at(self, value: datetime) -> str:
        return to_iso(value)


class MonthlyArrangementState(BaseModel):
    ledger_id: str
    month: str
    arrangement: MonthlyArrangementDto | None


class MonthlyArrangementRevisionDto(BaseModel):
    row_version: PositiveInt
    recorded_at: datetime
    home_currency_code: str
    savings_target_cents: NonNegativeMoneyMinor
    reserved_buffer_cents: NonNegativeMoneyMinor

    @field_serializer("recorded_at")
    def serialize_recorded_at(self, value: datetime) -> str:
        return to_iso(value)


class MonthlyArrangementHistory(BaseModel):
    ledger_id: str
    month: str
    items: list[MonthlyArrangementRevisionDto]
    next_before_version: PositiveInt | None = None
