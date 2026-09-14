"""Monthly budget dashboard payloads (v0.8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_serializer

from app.schemas._exchange import ProjectionReferenceDto
from app.schemas._money import (
    NonNegativeMoneyAggregate,
    NonNegativeMoneyMinor,
    SignedMoneyAggregate,
    SignedMoneyMinor,
)
from app.services.time_service import to_iso

__all__ = [
    "BudgetMonthlyArchiveRequest",
    "BudgetMonthlyArchiveResponse",
    "BudgetCategoryRequest",
    "BudgetCategoryResponse",
    "BudgetExcludedCategoryResponse",
    "BudgetMonthlyResponse",
    "BudgetMonthlyUpdateRequest",
]


# v0.8 — Ledger monthly budget dashboard
class BudgetCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    amount_cents: NonNegativeMoneyMinor


class BudgetMonthlyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_currency_code: str = Field(min_length=3, max_length=3)
    expected_row_version: PositiveInt | None
    total_amount_cents: NonNegativeMoneyMinor
    non_monthly_amount_cents: NonNegativeMoneyMinor = 0
    rollover_amount_cents: SignedMoneyMinor = 0
    excluded_categories: list[str] = Field(default_factory=list)
    category_budgets: list[BudgetCategoryRequest] = Field(default_factory=list)


class BudgetMonthlyArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int


class BudgetMonthlyArchiveResponse(BaseModel):
    message: str


class BudgetCategoryResponse(BaseModel):
    category: str
    amount_cents: NonNegativeMoneyMinor
    spent_amount_cents: SignedMoneyAggregate | None
    remaining_amount_cents: SignedMoneyAggregate | None
    overspent_amount_cents: NonNegativeMoneyAggregate | None


class BudgetExcludedCategoryResponse(BaseModel):
    category: str
    amount_cents: SignedMoneyAggregate | None
    count: int


class BudgetMonthlyResponse(BaseModel):
    ledger_id: str
    home_currency_code: str | None
    month: str
    configured: bool
    row_version: int | None = None
    total_amount_cents: NonNegativeMoneyMinor
    rollover_amount_cents: SignedMoneyMinor
    fixed_amount_cents: NonNegativeMoneyAggregate | None
    non_monthly_amount_cents: NonNegativeMoneyMinor
    flex_budget_cents: NonNegativeMoneyAggregate | None
    spent_amount_cents: SignedMoneyAggregate | None
    excluded_amount_cents: SignedMoneyAggregate | None
    remaining_amount_cents: SignedMoneyAggregate | None
    overspent_amount_cents: NonNegativeMoneyAggregate | None
    missing_currency_codes: list[str] = Field(default_factory=list)
    reference_rates: list[ProjectionReferenceDto] = Field(default_factory=list)
    excluded_categories: list[str]
    excluded_breakdown: list[BudgetExcludedCategoryResponse]
    category_budgets: list[BudgetCategoryResponse]
    updated_at: datetime | None = None

    @field_serializer("updated_at")
    def serialize_updated_at(self, value: datetime | None) -> str | None:
        return to_iso(value)
