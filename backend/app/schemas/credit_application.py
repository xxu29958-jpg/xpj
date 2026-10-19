"""Reviewed destinations for money already present in a credit account."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._money import NonNegativeMoneyMinor, PositiveMoneyMinor


class CreditApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    credit_public_id: str = Field(min_length=1)
    draw_public_id: str = Field(min_length=1)
    amount_minor: PositiveMoneyMinor
    reason: str = Field(min_length=1, max_length=255)


class CreditApplicationVoid(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    review_public_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=255)


class CreditApplicationChoice(BaseModel):
    public_id: str
    note: str
    occurred_on: date
    remaining_minor: PositiveMoneyMinor


class CreditApplicationHistory(BaseModel):
    public_id: str
    credit_note: str
    draw_note: str
    amount_minor: PositiveMoneyMinor
    applied_minor: NonNegativeMoneyMinor
    reason: str
    created_at: datetime
    void_reason: str | None


class CreditApplicationsView(BaseModel):
    credits: list[CreditApplicationChoice]
    obligations: list[CreditApplicationChoice]
    history: list[CreditApplicationHistory]
