"""Monthly budget dashboard payloads (v0.8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "BudgetCategoryRequest",
    "BudgetCategoryResponse",
    "BudgetExcludedCategoryResponse",
    "BudgetMonthlyResponse",
    "BudgetMonthlyUpdateRequest",
]


# v0.8 — Ledger monthly budget dashboard
class BudgetCategoryRequest(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    amount_cents: int = Field(ge=0)


class BudgetMonthlyUpdateRequest(BaseModel):
    total_amount_cents: int = Field(ge=0)
    non_monthly_amount_cents: int = Field(default=0, ge=0)
    rollover_amount_cents: int = 0
    excluded_categories: list[str] = Field(default_factory=list)
    category_budgets: list[BudgetCategoryRequest] = Field(default_factory=list)


class BudgetCategoryResponse(BaseModel):
    category: str
    amount_cents: int
    spent_amount_cents: int
    remaining_amount_cents: int
    overspent_amount_cents: int


class BudgetExcludedCategoryResponse(BaseModel):
    category: str
    amount_cents: int
    count: int


class BudgetMonthlyResponse(BaseModel):
    ledger_id: str
    month: str
    configured: bool
    total_amount_cents: int
    rollover_amount_cents: int
    fixed_amount_cents: int
    non_monthly_amount_cents: int
    flex_budget_cents: int
    spent_amount_cents: int
    excluded_amount_cents: int
    remaining_amount_cents: int
    overspent_amount_cents: int
    excluded_categories: list[str]
    excluded_breakdown: list[BudgetExcludedCategoryResponse]
    category_budgets: list[BudgetCategoryResponse]
    updated_at: datetime | None = None

    @field_serializer("updated_at")
    def serialize_updated_at(self, value: datetime | None) -> str | None:
        return to_iso(value)
