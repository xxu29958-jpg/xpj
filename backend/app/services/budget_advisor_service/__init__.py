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

from app.services.budget_advisor_service._aliases import (
    assign_transaction_temp_id,
    cleanup_session,
    get_or_create_member_anon,
    get_or_create_merchant_anon,
    resolve_member_anon,
    resolve_merchant_anon,
    resolve_transaction_temp_id,
)
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
from app.services.budget_advisor_service._outbound_guard import (
    ALLOWED_TOP_LEVEL_KEYS,
    to_outbound_dict,
    validate_outbound_payload,
)
from app.services.budget_advisor_service._providers import (
    EmptyBudgetAdvisor,
    MockBudgetAdvisor,
    OpenAiCompatBudgetAdvisor,
    get_budget_advisor,
)

__all__ = [
    "ALLOWED_TOP_LEVEL_KEYS",
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
    "OpenAiCompatBudgetAdvisor",
    "assign_transaction_temp_id",
    "cleanup_session",
    "get_budget_advisor",
    "get_or_create_member_anon",
    "get_or_create_merchant_anon",
    "resolve_member_anon",
    "resolve_merchant_anon",
    "resolve_transaction_temp_id",
    "to_outbound_dict",
    "validate_outbound_payload",
]
