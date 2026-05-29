"""v1.1 budget advisor service — AI-augmented suggestions over the
privacy boundary codified in ADR-0036.

This package is the single entry point external callers should use. The
private sub-modules carry the implementation:

- ``_models``: ``BudgetInputs`` / ``BudgetAdvice`` dataclasses (the
  allowed-fields contract — see ADR-0036) + ``BudgetAdvisorProvider``
  Protocol.
- ``_aliases``: tenant-scoped real → opaque maps backed by the three
  ``ai_*_anon_map`` tables.
- ``_outbound_guard``: schema check that runs immediately before the
  HTTP body is built. Fail-closed on any drift.
- ``_providers``: ``EmptyBudgetAdvisor`` (default) / ``MockBudgetAdvisor``
  (dev) / ``OpenAiCompatBudgetAdvisor`` (production) + factory.
- ``_inputs_builder``: turns live DB state into a ready-to-send
  ``BudgetInputs`` — the trust boundary between raw data and the
  outbound payload.

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
from app.services.budget_advisor_service._audit import (
    LIVE_PROVIDER_NAMES,
    AdvisorStatus,
    advisor_status_for_tenant,
    cleanup_expired_audit_logs,
    complete_live_call_audit_row,
    compute_input_hash,
    enforce_live_call_budget,
    is_live_provider,
    latest_audit_row,
    mask_base_url,
    recent_audit_rows,
    record_audit_row,
    reserve_live_call_budget,
)
from app.services.budget_advisor_service._inputs_builder import (
    build_budget_inputs,
)
from app.services.budget_advisor_service._models import (
    BudgetAdvice,
    BudgetAdvisorProvider,
    BudgetInputs,
    BudgetSuggestion,
    CategorySnapshot,
    HistoricalBaseline,
)
from app.services.budget_advisor_service._outbound_guard import (
    ALLOWED_TOP_LEVEL_KEYS,
    to_outbound_dict,
    validate_outbound_payload,
)
from app.services.budget_advisor_service._provider_names import (
    canonical_provider_name,
    clean_provider_name,
    is_known_provider,
)
from app.services.budget_advisor_service._providers import (
    EmptyBudgetAdvisor,
    MockBudgetAdvisor,
    OpenAiCompatBudgetAdvisor,
    get_budget_advisor,
)
from app.services.budget_advisor_service._runner import AdvisorRunResult, run_budget_advisor

__all__ = [
    "ALLOWED_TOP_LEVEL_KEYS",
    "AdvisorRunResult",
    "AdvisorStatus",
    "BudgetAdvice",
    "BudgetAdvisorProvider",
    "BudgetInputs",
    "BudgetSuggestion",
    "CategorySnapshot",
    "EmptyBudgetAdvisor",
    "HistoricalBaseline",
    "LIVE_PROVIDER_NAMES",
    "MockBudgetAdvisor",
    "OpenAiCompatBudgetAdvisor",
    "advisor_status_for_tenant",
    "assign_transaction_temp_id",
    "build_budget_inputs",
    "canonical_provider_name",
    "cleanup_session",
    "cleanup_expired_audit_logs",
    "complete_live_call_audit_row",
    "clean_provider_name",
    "compute_input_hash",
    "enforce_live_call_budget",
    "get_budget_advisor",
    "get_or_create_member_anon",
    "get_or_create_merchant_anon",
    "is_live_provider",
    "is_known_provider",
    "latest_audit_row",
    "mask_base_url",
    "recent_audit_rows",
    "record_audit_row",
    "reserve_live_call_budget",
    "resolve_member_anon",
    "resolve_merchant_anon",
    "resolve_transaction_temp_id",
    "run_budget_advisor",
    "to_outbound_dict",
    "validate_outbound_payload",
]
