"""v1.2 follow-up — small registry for algorithm types.

ADR-0037 left a TODO: ``decision_type`` and ``algorithm_version`` were
scattered as string constants across each suggestion service
(``"category_suggestion"`` in ``pending_suggestion_service``,
``ALGORITHM_VERSION = "category-history-v1"`` in
``_category_suggestion``, the same string repeated in tests, ...).
This module collapses them into one place.

Why this matters:

* No more silent typos. ``"catgory_suggestion"`` won't quietly write a
  row alongside the real ``"category_suggestion"`` rows.
* Listing live algorithm types is a function call, not a grep. Owner
  Console / future migration tools can enumerate them.
* When a service rolls a new algorithm version (``v1`` → ``v2``), the
  bump happens in *one* place; consumers (suggestion writer, model
  versioning UI, audit) all pick it up.

The registry is intentionally **flat** — frozen dataclasses + a dict.
No metaclass, no plugin discovery, no auto-registration. Adding a new
algorithm = add a new module-level constant + reference it from the
service module. The :func:`get` lookup raises on unknown types so the
caller fails fast instead of silently writing a row with a typo'd
``decision_type``.

Each entry carries enough metadata for the rest of the v1.2 layer to
work off the registry without hardcoding:

* ``display_label`` — what Owner Console shows the user instead of the
  internal snake_case identifier.
* ``default_retention_days`` — what a fresh ``algorithm_decisions``
  row gets if the writer doesn't override. Mirrors retention defaults
  from the v1.2 cleanup story.
* ``marker_keys`` — which fields of an algorithm's decision payload
  form the canonical "what was suggested" marker. Two different
  decisions whose marker_keys produce equal sub-dicts represent the
  same advice; the marker is what we hash to query "has the user
  rejected this advice before?" in O(index) instead of LIKE-scanning
  JSON text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ALGORITHM_TYPES",
    "AlgorithmType",
    "BUDGET_SUGGESTION",
    "CATEGORY_SUGGESTION",
    "DUPLICATE_CANDIDATE",
    "build_feedback_marker",
    "canonical_marker_hash",
    "decision_types",
    "get",
    "is_registered",
]


@dataclass(frozen=True)
class AlgorithmType:
    """One algorithm-type registration.

    ``marker_keys`` is the small set of payload fields that uniquely
    identify "what advice was given" for feedback de-duplication. For
    ``category_suggestion`` that's just ``("category",)`` — two
    different rationale strings for the same category are the same
    suggestion. For ``duplicate_candidate`` it's
    ``("amount_cents", "merchant")`` — same money to same merchant is
    the same proposed dup, regardless of the time-bucket reason.
    """

    decision_type: str
    current_version: str
    display_label: str
    description: str
    subject_kinds: tuple[str, ...]
    default_retention_days: int = 180
    marker_keys: tuple[str, ...] = field(default_factory=tuple)

    def build_marker(self, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        """Reduce a decision payload to its canonical marker.

        Returns ``None`` when the type has no ``marker_keys`` (e.g.
        budget suggestions don't currently take per-suggestion
        feedback). Otherwise returns a dict with exactly those keys —
        callers JSON-encode it and hash via
        :func:`canonical_marker_hash`.
        """

        if not self.marker_keys:
            return None
        return {key: payload.get(key) for key in self.marker_keys}


CATEGORY_SUGGESTION = AlgorithmType(
    decision_type="category_suggestion",
    current_version="category-history-v1",
    display_label="分类建议",
    description=(
        "merchant→category history aggregator with reject-based "
        "feedback down-weighting"
    ),
    subject_kinds=("expense",),
    default_retention_days=180,
    marker_keys=("category",),
)


DUPLICATE_CANDIDATE = AlgorithmType(
    decision_type="duplicate_candidate",
    current_version="duplicate-scoring-v1",
    display_label="疑似重复",
    description=(
        "image_hash / amount / merchant / time weighted score with "
        "recent-reject penalty"
    ),
    subject_kinds=("expense",),
    default_retention_days=180,
    marker_keys=("amount_cents", "merchant"),
)


BUDGET_SUGGESTION = AlgorithmType(
    decision_type="budget_suggestion",
    current_version="budget-quantile-v1",
    display_label="预算建议",
    description="trailing-window P50 / P75 monthly spend per category",
    subject_kinds=("expense", "month"),
    default_retention_days=365,
    marker_keys=(),
)


ALGORITHM_TYPES: dict[str, AlgorithmType] = {
    CATEGORY_SUGGESTION.decision_type: CATEGORY_SUGGESTION,
    DUPLICATE_CANDIDATE.decision_type: DUPLICATE_CANDIDATE,
    BUDGET_SUGGESTION.decision_type: BUDGET_SUGGESTION,
}


def get(decision_type: str) -> AlgorithmType:
    """Return the registry entry for ``decision_type``.

    Raises ``KeyError`` when the type is unregistered — typo'd
    decision_type at write time fails fast instead of silently
    writing a row no consumer knows how to interpret.
    """

    try:
        return ALGORITHM_TYPES[decision_type]
    except KeyError as exc:
        raise KeyError(
            f"unknown algorithm decision_type {decision_type!r}; "
            f"add it to learning_service._algorithm_registry"
        ) from exc


def is_registered(decision_type: str) -> bool:
    return decision_type in ALGORITHM_TYPES


def decision_types() -> tuple[str, ...]:
    """All known decision_type values, alphabetised for stable output."""

    return tuple(sorted(ALGORITHM_TYPES.keys()))


def build_feedback_marker(
    decision_type: str, payload: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Convenience: ``get(decision_type).build_marker(payload)`` without
    the per-call ``get`` boilerplate. Returns ``None`` for types that
    don't define a marker (no feedback-de-dup loop)."""

    return get(decision_type).build_marker(payload)


def canonical_marker_hash(marker: Mapping[str, Any] | None) -> str | None:
    """SHA-256 hex of the canonical JSON encoding of ``marker``.

    Canonical means ``sort_keys=True`` and ``ensure_ascii=False``, so
    two callers that pass logically-equal markers always hash equal.
    ``None`` in → ``None`` out — callers store NULL on the row, the
    index becomes a sparse one for hash-having rows.
    """

    if marker is None:
        return None
    encoded = json.dumps(marker, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
