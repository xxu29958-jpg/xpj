"""Recorded income estimates, separate from current forecasts and command receipts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas._money import NonNegativeMoneyMinor
from app.services.time_service import to_iso

Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class IncomePlanDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    source_type: str
    frequency: Literal["monthly", "one_time"]
    income_month: Month | None
    amount_cents: NonNegativeMoneyMinor
    home_currency_code: str | None
    pay_day: int = Field(ge=1, le=31)
    status: Literal["active", "archived"]


class IncomePlanRevisionResponse(BaseModel):
    row_version: int = Field(ge=1)
    change_kind: Literal["baseline", "create", "edit", "archive", "restore"]
    recorded_at: datetime
    intent_month: Month | None
    effective_month: Month | None
    snapshot: IncomePlanDefinition

    @field_serializer("recorded_at")
    def serialize_time(self, value: datetime) -> str:
        return to_iso(value)


class IncomePlanHistoryResponse(BaseModel):
    ledger_id: str
    public_id: str
    items: list[IncomePlanRevisionResponse]
    next_before_version: int | None
