"""v1.1 budget advisor request / response shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "BudgetAdviceDto",
    "BudgetAdviseRequest",
    "BudgetAdviseResponse",
    "BudgetAdvisorStatusResponse",
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
    reason_code: str | None = None


class BudgetAdvisorStatusResponse(BaseModel):
    """v1.1 Batch 2 owner-facing visibility surface.

    Surfaces the configured AI provider, the explicit owner-confirmation
    flag, and the most recent audit row so the Owner Console panel can
    answer "is this thing on?" / "did the last call succeed?" without
    running a fresh call.
    """

    provider: str
    model: str | None
    base_url: str | None
    owner_confirmed: bool
    is_live: bool
    needs_confirmation: bool
    last_called_at: str | None
    last_success: bool | None
    last_error_code: str | None
    last_suggestion_count: int | None
    last_duration_ms: int | None
