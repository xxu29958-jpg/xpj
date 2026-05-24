"""v1.1 budget advisor request / response shapes.

This PR only ships the discretionary-cap endpoint. The advise endpoint
(which would expose ``BudgetAdvice``) is intentionally deferred to the
next PR alongside the BudgetInputs adapter that anonymises real data
into the ADR-0036 allowed-field shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
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
