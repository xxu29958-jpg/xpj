"""v1.1 budget advisor request / response shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "BudgetAdviceDto",
    "BudgetAdviseRequest",
    "BudgetAdviseResponse",
    "BudgetSuggestionDto",
    "DiscretionaryResponse",
]


class DiscretionaryResponse(BaseModel):
    """Inspectable breakdown of "本月可自由支配".

    Mirrors :class:`DiscretionaryBreakdown` so the UI can render the
    subtraction step by step.
    """

    monthly_income_cents: int = Field(ge=0)
    fixed_expenses_cents: int = Field(ge=0)
    savings_target_cents: int = Field(ge=0)
    reserved_buffer_cents: int = Field(ge=0)
    discretionary_cents: int = Field(ge=0)


class BudgetAdviseRequest(BaseModel):
    """Caller picks the month (YYYY-MM); other inputs are read from the
    user's existing data (income plan, recurring items, confirmed
    expenses, personal baseline) by the builder service."""

    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    timezone: str | None = None


class BudgetSuggestionDto(BaseModel):
    category: str | None
    suggested_amount_cents: int
    rationale: str


class BudgetAdviceDto(BaseModel):
    summary: str
    suggestions: list[BudgetSuggestionDto]
    confidence: float | None


class BudgetAdviseResponse(BaseModel):
    """Wrapper so an empty advisor (default config) can return a clean
    "no advice this time" without ambiguity."""

    advice: BudgetAdviceDto | None
    provider_name: str
