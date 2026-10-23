"""v1.2 follow-up — small algorithm type registry contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.learning_service import (
    BUDGET_QUANTILE_VERSION,
    BUDGET_SUGGESTION,
    CATEGORY_SUGGESTION,
    CATEGORY_SUGGESTION_VERSION,
    DUPLICATE_CANDIDATE,
    DUPLICATE_SCORING_VERSION,
    AlgorithmType,
    get_algorithm_type,
)


def test_get_returns_full_entry() -> None:
    entry = get_algorithm_type("category_suggestion")
    assert isinstance(entry, AlgorithmType)
    assert entry.decision_type == "category_suggestion"
    assert "expense" in entry.subject_kinds


def test_get_raises_on_unknown_type() -> None:
    with pytest.raises(KeyError, match="unknown algorithm decision_type"):
        get_algorithm_type("not_a_real_type")


def test_service_modules_pull_version_from_registry() -> None:
    # The per-service ALGORITHM_VERSION shim must equal the registry
    # entry's ``current_version``. If someone bumps the version in the
    # service module without updating the registry (or vice versa),
    # this test catches the drift before it ships.
    assert CATEGORY_SUGGESTION.current_version == CATEGORY_SUGGESTION_VERSION
    assert DUPLICATE_CANDIDATE.current_version == DUPLICATE_SCORING_VERSION
    assert BUDGET_SUGGESTION.current_version == BUDGET_QUANTILE_VERSION


def test_registry_entries_are_frozen() -> None:
    # AlgorithmType is a frozen dataclass — mutating it at runtime
    # would let one consumer poison another's view.
    with pytest.raises(FrozenInstanceError):
        CATEGORY_SUGGESTION.current_version = "hacked"  # type: ignore[misc]
