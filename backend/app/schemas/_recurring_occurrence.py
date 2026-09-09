"""Explicit monthly obligation/payment relationship, never an Expense write."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas._money import NonNegativeMoneyMinor, PositiveMoneyMinor


class RecurringOccurrenceWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Explicit and required: missing/old payloads must never mean "unlink".
    action: Literal["link", "clear"]
    expense_public_id: str | None = Field(default=None, min_length=1, max_length=36)
    expected_expense_row_version: int | None = Field(default=None, ge=1)
    expected_row_version: int = Field(ge=0)
    expected_series_row_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_payment_revision(self):
        if self.action == "link" and (self.expense_public_id is None or self.expected_expense_row_version is None):
            raise ValueError("link requires the selected payment and revision")
        if self.action == "clear" and (self.expense_public_id is not None or self.expected_expense_row_version is not None):
            raise ValueError("payment identity and revision must be supplied together")
        return self


class RecurringOccurrenceResponse(BaseModel):
    home_currency_code: str | None = None
    paid_home_currency_code: str | None = None
    series_public_id: str
    period: str
    series_row_version: int
    row_version: int
    state: Literal["unfulfilled", "fulfilled", "needs_review"]
    planned_amount_cents: PositiveMoneyMinor
    reserved_amount_cents: NonNegativeMoneyMinor
    expense_public_id: str | None
    expense_id: int | None
    expense_row_version: int | None
    paid_amount_cents: NonNegativeMoneyMinor | None
    next_due_date: date | None
