"""Outbound payload guard for BudgetAdvisor providers.

The guard is intentionally as narrow as the current builder. Future fields must
be added here only after the builder really populates them and the privacy
boundary has been reviewed.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.errors import DataIntegrityError
from app.services.budget_advisor_service._models import BudgetInputs
from app.services.category_common import DEFAULT_CATEGORIES

ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "month",
        "home_currency",
        "category_breakdown",
        "historical_baseline",
    }
)

ALLOWED_CATEGORY_KEYS = frozenset({"category", "amount_cents", "count"})
ALLOWED_BASELINE_KEYS = frozenset({"category", "median_cents", "p75_cents"})

_LIST_KEY_TO_ALLOWED_ROW_KEYS: dict[str, frozenset[str]] = {
    "category_breakdown": ALLOWED_CATEGORY_KEYS,
    "historical_baseline": ALLOWED_BASELINE_KEYS,
}
_ALLOWED_ADVISOR_CATEGORIES = frozenset(DEFAULT_CATEGORIES)


def to_outbound_dict(inputs: BudgetInputs) -> dict[str, Any]:
    """Canonical serialisation with fail-closed schema validation."""

    if not is_dataclass(inputs):
        raise DataIntegrityError(
            "budget_advisor_outbound: inputs must be a BudgetInputs dataclass"
        )
    payload = asdict(inputs)
    validate_outbound_payload(payload)
    return payload


def validate_outbound_payload(payload: dict[str, Any]) -> None:
    """Raise if ``payload`` includes keys outside the outbound contract."""

    if not isinstance(payload, dict):
        raise DataIntegrityError("budget_advisor_outbound: payload must be a dict")
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
            category = row.get("category")
            if category not in _ALLOWED_ADVISOR_CATEGORIES:
                raise DataIntegrityError(
                    "budget_advisor_outbound: unexpected category on "
                    f"'{list_key}[{index}]'"
                )
