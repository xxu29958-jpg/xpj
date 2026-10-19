"""Incurred credit fees are distinct from future quotes and principal."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._money import NonNegativeMoneyMinor, PositiveMoneyMinor


class CreditFeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    calendar_revision: int = Field(ge=1)
    amount_minor: PositiveMoneyMinor
    occurred_on: date
    note: str = Field(min_length=1, max_length=255)
    period_public_id: str | None = None


class CreditFeePaymentPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expense_id: int = Field(ge=1)
    amount_minor: PositiveMoneyMinor


class CreditFeeView(BaseModel):
    expense_id: int
    note: str
    occurred_on: date
    original_minor: PositiveMoneyMinor
    remaining_minor: NonNegativeMoneyMinor
    period_public_id: str | None
