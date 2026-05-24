"""ADR-0036 outbound payload guard.

Confirmation #1 in ADR-0036 mandates: every outbound advisor payload is
schema-checked against the allowed field set. New keys appearing without
an ADR update **must fail** before the HTTP call goes out.

This guard runs in two places:

- :func:`to_outbound_dict` is the canonical serialiser; the provider
  passes its output to the HTTP request body. It produces exactly the
  fields the ADR enumerates and nothing more.
- :func:`validate_outbound_payload` re-checks the same shape so any
  future PR that hand-rolls a payload (instead of going through
  ``to_outbound_dict``) is rejected at runtime.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.errors import DataIntegrityError
from app.services.budget_advisor_service._models import BudgetInputs

# Top-level keys allowed on the outbound payload. Adding one means
# ADR-0036's "allowed fields" list also gains an entry — keep the two in
# lockstep.
ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "month",
        "home_currency",
        "members",
        "category_breakdown",
        "merchant_summary",
        "income_plan",
        "fixed_expenses",
        "historical_baseline",
    }
)

# Per-list-row key sets. Same rule: ADR-driven only.
ALLOWED_MEMBER_KEYS = frozenset({"anon_id"})
ALLOWED_CATEGORY_KEYS = frozenset({"category", "amount_cents", "count"})
ALLOWED_MERCHANT_KEYS = frozenset({"anon_id", "category_class", "amount_cents", "count"})
ALLOWED_INCOME_KEYS = frozenset({"source_type", "amount_cents", "pay_day"})
ALLOWED_FIXED_KEYS = frozenset(
    {"anon_id", "category_class", "amount_cents", "frequency"}
)
ALLOWED_BASELINE_KEYS = frozenset({"category", "median_cents", "p75_cents"})

_LIST_KEY_TO_ALLOWED_ROW_KEYS: dict[str, frozenset[str]] = {
    "members": ALLOWED_MEMBER_KEYS,
    "category_breakdown": ALLOWED_CATEGORY_KEYS,
    "merchant_summary": ALLOWED_MERCHANT_KEYS,
    "income_plan": ALLOWED_INCOME_KEYS,
    "fixed_expenses": ALLOWED_FIXED_KEYS,
    "historical_baseline": ALLOWED_BASELINE_KEYS,
}


def to_outbound_dict(inputs: BudgetInputs) -> dict[str, Any]:
    """Canonical serialisation. ``asdict`` over a frozen dataclass tree
    plus a pass through the guard — anything new on the dataclass that
    is not in the allow-list above raises here, not in production."""

    if not is_dataclass(inputs):
        raise DataIntegrityError(
            "budget_advisor_outbound: inputs must be a BudgetInputs dataclass"
        )
    payload = asdict(inputs)
    validate_outbound_payload(payload)
    return payload


def validate_outbound_payload(payload: dict[str, Any]) -> None:
    """Raise :class:`DataIntegrityError` if ``payload`` includes any key
    outside the ADR-0036 allow-list. Called once before the HTTP request
    body is built — fail-closed."""

    if not isinstance(payload, dict):
        raise DataIntegrityError(
            "budget_advisor_outbound: payload must be a dict"
        )
    extra_top = set(payload.keys()) - ALLOWED_TOP_LEVEL_KEYS
    if extra_top:
        raise DataIntegrityError(
            "budget_advisor_outbound: unexpected top-level key(s): "
            + ", ".join(sorted(extra_top))
        )
    for list_key, allowed_row_keys in _LIST_KEY_TO_ALLOWED_ROW_KEYS.items():
        rows = payload.get(list_key, [])
        if not isinstance(rows, list):
            raise DataIntegrityError(
                f"budget_advisor_outbound: '{list_key}' must be a list"
            )
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise DataIntegrityError(
                    f"budget_advisor_outbound: '{list_key}[{index}]' must be a dict"
                )
            extra = set(row.keys()) - allowed_row_keys
            if extra:
                raise DataIntegrityError(
                    "budget_advisor_outbound: unexpected key(s) on "
                    f"'{list_key}[{index}]': {', '.join(sorted(extra))}"
                )
