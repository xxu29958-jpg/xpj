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

The registry is intentionally **flat** — three dataclasses + a dict.
No metaclass, no plugin discovery, no auto-registration. Adding a new
algorithm = add a new module-level constant + reference it from the
service module. The :func:`get` lookup raises on unknown types so the
caller fails fast instead of silently writing a row with a typo'd
``decision_type``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ALGORITHM_TYPES",
    "AlgorithmType",
    "BUDGET_SUGGESTION",
    "CATEGORY_SUGGESTION",
    "DUPLICATE_CANDIDATE",
    "decision_types",
    "get",
    "is_registered",
]


@dataclass(frozen=True)
class AlgorithmType:
    """One algorithm-type registration.

    ``decision_type`` is the discriminator stored on
    ``algorithm_decisions.decision_type``. ``current_version`` is what
    new rows are written with; old rows can carry older version strings
    and stay queryable through ``list_algorithm_versions``.
    ``subject_kinds`` constrains what kind of object a decision of this
    type can attach to — caller code can assert against it before
    calling ``record_decision``.
    """

    decision_type: str
    current_version: str
    description: str
    subject_kinds: tuple[str, ...]


CATEGORY_SUGGESTION = AlgorithmType(
    decision_type="category_suggestion",
    current_version="category-history-v1",
    description=(
        "merchant→category history aggregator with reject-based "
        "feedback down-weighting"
    ),
    subject_kinds=("expense",),
)


DUPLICATE_CANDIDATE = AlgorithmType(
    decision_type="duplicate_candidate",
    current_version="duplicate-scoring-v1",
    description=(
        "image_hash / amount / merchant / time weighted score with "
        "recent-reject penalty"
    ),
    subject_kinds=("expense",),
)


BUDGET_SUGGESTION = AlgorithmType(
    decision_type="budget_suggestion",
    current_version="budget-quantile-v1",
    description="trailing-window P50 / P75 monthly spend per category",
    subject_kinds=("expense", "month"),
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
