"""BudgetAdvisor DTOs and provider protocol.

``BudgetInputs`` is the exact data envelope an external AI provider may see.
Keep it aligned with the builder: do not expose future or currently-empty
collections unless the builder really populates them and the privacy boundary
has been reviewed.

Intentionally excluded:

- real merchant names, store addresses, or chain identifiers
- expense notes, receipt images, thumbnail paths, and local file paths
- real family-member names or account identifiers
- phone, email, address, order id, transaction id, token, device, or ledger ids
- per-row timestamps finer than the aggregate month
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class CategorySnapshot:
    """Aggregate spend per category for a single period."""

    category: str
    amount_cents: int
    count: int


@dataclass(frozen=True)
class HistoricalBaseline:
    """Per-category historical baseline statistic."""

    category: str
    median_cents: int
    p75_cents: int


@dataclass(frozen=True)
class BudgetInputs:
    """Structured input handed to a ``BudgetAdvisorProvider``."""

    month: str
    home_currency: str
    category_breakdown: list[CategorySnapshot] = field(default_factory=list)
    historical_baseline: list[HistoricalBaseline] = field(default_factory=list)


@dataclass(frozen=True)
class BudgetSuggestion:
    """One suggestion line in the advisor response."""

    category: str | None
    suggested_amount_cents: int
    rationale: str


@dataclass(frozen=True)
class BudgetAdvice:
    """Advisor response. The caller must require explicit user confirmation."""

    summary: str
    suggestions: list[BudgetSuggestion] = field(default_factory=list)
    confidence: float | None = None


class BudgetAdvisorProvider(Protocol):
    def advise(self, inputs: BudgetInputs) -> BudgetAdvice | None:
        ...
