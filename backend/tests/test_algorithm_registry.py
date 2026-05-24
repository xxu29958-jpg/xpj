"""v1.2 follow-up — small algorithm type registry contract."""

from __future__ import annotations

import pytest

from app.services.learning_service import (
    ALGORITHM_TYPES,
    BUDGET_QUANTILE_VERSION,
    BUDGET_SUGGESTION,
    CATEGORY_SUGGESTION,
    CATEGORY_SUGGESTION_VERSION,
    DUPLICATE_CANDIDATE,
    DUPLICATE_SCORING_VERSION,
    AlgorithmType,
    decision_types,
    get_algorithm_type,
    is_algorithm_type_registered,
)


def test_registry_contains_known_types() -> None:
    assert is_algorithm_type_registered("category_suggestion")
    assert is_algorithm_type_registered("duplicate_candidate")
    assert is_algorithm_type_registered("budget_suggestion")
    assert decision_types() == (
        "budget_suggestion",
        "category_suggestion",
        "duplicate_candidate",
    )


def test_get_returns_full_entry() -> None:
    entry = get_algorithm_type("category_suggestion")
    assert isinstance(entry, AlgorithmType)
    assert entry.decision_type == "category_suggestion"
    assert entry.current_version == "category-history-v1"
    assert "expense" in entry.subject_kinds


def test_get_raises_on_unknown_type() -> None:
    with pytest.raises(KeyError, match="unknown algorithm decision_type"):
        get_algorithm_type("not_a_real_type")


def test_typo_detection_is_strict() -> None:
    # Common typos should NOT silently land in the registry.
    assert not is_algorithm_type_registered("category_suggestions")  # plural
    assert not is_algorithm_type_registered("catgory_suggestion")  # missing e
    assert not is_algorithm_type_registered("CATEGORY_SUGGESTION")  # casing


def test_service_modules_pull_version_from_registry() -> None:
    # The per-service ALGORITHM_VERSION shim must equal the registry
    # entry's ``current_version``. If someone bumps the version in the
    # service module without updating the registry (or vice versa),
    # this test catches the drift before it ships.
    assert CATEGORY_SUGGESTION_VERSION == CATEGORY_SUGGESTION.current_version
    assert DUPLICATE_SCORING_VERSION == DUPLICATE_CANDIDATE.current_version
    assert BUDGET_QUANTILE_VERSION == BUDGET_SUGGESTION.current_version


def test_registry_entries_are_frozen() -> None:
    # AlgorithmType is a frozen dataclass — mutating it at runtime
    # would let one consumer poison another's view.
    with pytest.raises(Exception):
        CATEGORY_SUGGESTION.current_version = "hacked"  # type: ignore[misc]


def test_subject_kinds_constraint_is_iterable_tuple() -> None:
    for entry in ALGORITHM_TYPES.values():
        assert isinstance(entry.subject_kinds, tuple)
        assert all(isinstance(k, str) for k in entry.subject_kinds)
        assert len(entry.subject_kinds) >= 1
