"""v1.1 budget advisor service — AI-augmented suggestions over the
privacy boundary codified in ADR-0036.

This package is the single entry point external callers should use. The
private sub-modules carry the implementation:

- ``_models``: ``BudgetInputs`` / ``BudgetAdvice`` dataclasses (the
  allowed-fields contract — see ADR-0036) + ``BudgetAdvisorProvider``
  Protocol.
- ``_providers``: ``EmptyBudgetAdvisor`` (default) + ``get_budget_advisor``
  factory. The OpenAI-compat provider lands in a follow-up PR.

The advisor is **suggestion only** — it never writes budgets directly.
All budget changes go through the existing budget_service mutation paths
with an explicit user-confirmation step.
"""

from __future__ import annotations

from app.services.budget_advisor_service._models import (
    BudgetAdvice,
    BudgetAdvisorProvider,
    BudgetInputs,
    BudgetSuggestion,
    CategorySnapshot,
    FixedExpense,
    HistoricalBaseline,
    IncomePlan,
    MemberRef,
    MerchantSummary,
)
from app.services.budget_advisor_service._providers import (
    EmptyBudgetAdvisor,
    MockBudgetAdvisor,
    get_budget_advisor,
)

__all__ = [
    "BudgetAdvice",
    "BudgetAdvisorProvider",
    "BudgetInputs",
    "BudgetSuggestion",
    "CategorySnapshot",
    "EmptyBudgetAdvisor",
    "FixedExpense",
    "HistoricalBaseline",
    "IncomePlan",
    "MemberRef",
    "MerchantSummary",
    "MockBudgetAdvisor",
    "get_budget_advisor",
]
