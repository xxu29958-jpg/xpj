"""BudgetAdvisor DTOs + Protocol (leaf).

Every field on ``BudgetInputs`` and its nested dataclasses is part of the
allowed-fields contract codified in ADR-0036 (v1.1 AI Budget Provider
Privacy Boundary). Adding a field here is a load-bearing privacy change
and **must update ADR-0036 first** — outbound payload guards (PR-2) will
reject any payload key that is not on this surface.

What is intentionally NOT modeled here (per ADR-0036):

- real merchant names / store addresses / chain identifiers
- expense notes (default-off; per-row opt-in only)
- receipt images / thumbnail paths / file system paths
- real family-member display names (use anonymised ``member_1`` ids)
- phone / email / address / order id / transaction id
- per-row timestamps finer than day
- ledger / device / token / any identity field
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class CategorySnapshot:
    """Aggregate spend per category for a single period (e.g. month-to-date)."""

    category: str
    amount_cents: int
    count: int


@dataclass(frozen=True)
class MerchantSummary:
    """One row per merchant after anonymisation. ``anon_id`` is opaque
    (``merchant_001``); ``category_class`` is the merchant's coarse class
    (e.g. ``超市`` / ``外卖`` / ``订阅``), NOT the real merchant name."""

    anon_id: str
    category_class: str
    amount_cents: int
    count: int


@dataclass(frozen=True)
class IncomePlan:
    """Planned income line — recurring, no per-event timestamps."""

    source_type: str  # "salary" / "bonus" / "freelance" / "rental" / etc
    amount_cents: int
    pay_day: int  # 1-31 day of month


@dataclass(frozen=True)
class FixedExpense:
    """Recurring fixed outflow (rent / subscription / insurance)."""

    anon_id: str
    category_class: str
    amount_cents: int
    frequency: str  # "monthly" / "weekly" / "quarterly" / "yearly"


@dataclass(frozen=True)
class HistoricalBaseline:
    """Per-category historical baseline statistic. ``median_cents`` and
    ``p75_cents`` are aggregates over user history — not per-row data."""

    category: str
    median_cents: int
    p75_cents: int


@dataclass(frozen=True)
class MemberRef:
    """Anonymised family-member reference. ``anon_id`` is ``member_1`` /
    ``member_2`` etc — real display names stay local in the alias table."""

    anon_id: str


@dataclass(frozen=True)
class BudgetInputs:
    """Full structured input handed to a ``BudgetAdvisorProvider``.

    This is the entire envelope of what an external AI provider can see.
    Outbound payload guards (PR-2) serialise this and assert no other keys
    appear in the final HTTP body.
    """

    month: str  # "YYYY-MM" — no day / hour precision
    home_currency: str  # ISO 4217, e.g. "CNY"
    members: list[MemberRef] = field(default_factory=list)
    category_breakdown: list[CategorySnapshot] = field(default_factory=list)
    merchant_summary: list[MerchantSummary] = field(default_factory=list)
    income_plan: list[IncomePlan] = field(default_factory=list)
    fixed_expenses: list[FixedExpense] = field(default_factory=list)
    historical_baseline: list[HistoricalBaseline] = field(default_factory=list)


@dataclass(frozen=True)
class BudgetSuggestion:
    """One suggestion line in the advisor's response. ``category=None``
    means a whole-budget suggestion (e.g. "raise overall savings to 25%")."""

    category: str | None
    suggested_amount_cents: int
    rationale: str


@dataclass(frozen=True)
class BudgetAdvice:
    """Advisor response. Never written to budgets directly — caller must
    surface this to the user and require explicit confirmation, per
    ADR-0036 ("AI does not write budgets")."""

    summary: str
    suggestions: list[BudgetSuggestion] = field(default_factory=list)
    confidence: float | None = None


class BudgetAdvisorProvider(Protocol):
    def advise(self, inputs: BudgetInputs) -> BudgetAdvice | None:
        ...
