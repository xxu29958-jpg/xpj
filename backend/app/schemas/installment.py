"""Explicit dates and amounts from the actual agreement, never an average quote."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas._money import NonNegativeMoneyAggregate, NonNegativeMoneyMinor, PositiveMoneyMinor


class InstallmentPeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_on: date
    principal_minor: NonNegativeMoneyMinor
    planned_fee_minor: NonNegativeMoneyMinor = 0

    @model_validator(mode="after")
    def has_scheduled_amount(self):
        if not self.principal_minor and not self.planned_fee_minor:
            raise ValueError("没有待付本金或费用的期次请移除；费用减免请在修订依据中说明")
        return self


class InstallmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    supersedes_public_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=500)
    agreed_on: date
    draw_public_ids: list[str] = Field(max_length=120)
    periods: list[InstallmentPeriodInput] = Field(max_length=120)


class InstallmentPaymentPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_public_id: str
    principal_minor: NonNegativeMoneyMinor
    fee_minor: NonNegativeMoneyMinor = 0


class CreditDrawPaymentPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draw_public_id: str
    principal_minor: PositiveMoneyMinor


class InstallmentPeriodView(BaseModel):
    public_id: str
    position: int
    due_on: date
    principal_minor: NonNegativeMoneyMinor
    planned_fee_minor: NonNegativeMoneyMinor
    paid_principal_minor: NonNegativeMoneyAggregate
    paid_fee_minor: NonNegativeMoneyAggregate


class InstallmentView(BaseModel):
    public_id: str
    series_id: str
    revision: int
    name: str
    source: str
    agreed_on: date
    active: bool
    needs_review: bool
    remaining_principal_minor: NonNegativeMoneyAggregate
    periods: list[InstallmentPeriodView]
    draw_public_ids: list[str]


class CreditDrawView(BaseModel):
    public_id: str
    note: str
    occurred_on: date
    original_minor: NonNegativeMoneyMinor
    remaining_minor: NonNegativeMoneyMinor
    agreement_public_id: str | None = None


class InstallmentsView(BaseModel):
    account_public_id: str
    account_row_version: int
    currency_code: str
    agreements: list[InstallmentView]
    draws: list[CreditDrawView]
