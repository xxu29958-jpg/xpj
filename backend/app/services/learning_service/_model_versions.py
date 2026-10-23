"""v1.2 P3 — algorithm version inventory + one-click rollback.

``algorithm_decisions.algorithm_version`` is the existing column that
labels each suggestion with the algorithm + version that produced it.
This module reads that column for inventory ("how many decisions did
v1 emit vs. v2") and provides a single function to withdraw an entire
version when the user notices it's misbehaving.

Rollback semantics:

* "Withdraw" flips every ``active`` decision belonging to the named
  version to ``status='withdrawn'``. Nothing is deleted — the audit
  trail of "the model once thought X" stays intact.
* The corresponding ``ledger_learning_events`` rows are *not* touched.
  The user's feedback on a now-withdrawn decision is still a useful
  signal for any successor algorithm; we just unhook the suggestion
  itself.
* Withdrawal is tenant-scoped. A user complaining about category
  suggestions in their personal ledger doesn't withdraw decisions in a
  family ledger they happen to share.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, LedgerLearningEvent
from app.services.learning_service._algorithm_registry import (
    CATEGORY_SUGGESTION,
    DUPLICATE_CANDIDATE,
    RECOGNITION_TIME_CHOICE,
)
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._source_eligibility import _event_payload


@dataclass(frozen=True)
class AlgorithmVersionStats:
    """One row of the algorithm-version inventory.

    Owner Console reads ``withdrawn_count`` to find algorithm versions
    the owner rolled back; ``accepted_count`` and ``dismissed_count``
    describe decision lifecycle, separately from explicit feedback events."""

    decision_type: str
    algorithm_version: str
    active_count: int
    superseded_count: int
    withdrawn_count: int
    accepted_count: int = 0
    dismissed_count: int = 0
    explicit_accept_count: int = 0
    explicit_reject_count: int = 0
    manual_choice_count: int = 0
    unknown_feedback_count: int = 0
    closed_without_feedback_count: int = 0
    new_suggestions_enabled: bool = True
    training_enabled: bool = True


def _feedback_inventory(db: Session, *, tenant_id: str) -> dict:
    counts = {}
    rows = db.execute(select(LedgerLearningEvent, AlgorithmDecision.algorithm_version)
        .outerjoin(AlgorithmDecision, AlgorithmDecision.id == LedgerLearningEvent.decision_id)
        .where(LedgerLearningEvent.tenant_id == tenant_id)).all()
    explicit_decisions = set()
    for event, decision_version in rows:
        version = _event_payload(event).get("_algorithm_version") or decision_version or "unversioned"
        bucket = counts.setdefault((event.signal_type, version), Counter())
        bucket[event.event_type] += 1
        if event.event_type in {"accept", "reject", "edit", "manual_override"}:
            explicit_decisions.add(event.decision_id)
    closed = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == tenant_id,
        AlgorithmDecision.status == "dismissed"))
    for decision in closed:
        if decision.id not in explicit_decisions:
            counts.setdefault((decision.decision_type, decision.algorithm_version), Counter())["closed"] += 1
    return counts


_STATUS_BUCKETS = (
    "active",
    "superseded",
    "withdrawn",
    "accepted",
    "dismissed",
)


def list_algorithm_versions(
    db: Session, *, tenant_id: str
) -> list[AlgorithmVersionStats]:
    """Return per-status counts grouped by (decision_type,
    algorithm_version). Sorted by total descending so the UI surfaces
    the heaviest-hitter version first."""

    rows = db.execute(
        select(
            AlgorithmDecision.decision_type,
            AlgorithmDecision.algorithm_version,
            AlgorithmDecision.status,
            func.count().label("n"),
        )
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .group_by(
            AlgorithmDecision.decision_type,
            AlgorithmDecision.algorithm_version,
            AlgorithmDecision.status,
        )
    ).all()

    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for decision_type, algorithm_version, status, n in rows:
        key = (decision_type, algorithm_version)
        grouped.setdefault(key, dict.fromkeys(_STATUS_BUCKETS, 0))
        if status in grouped[key]:
            grouped[key][status] = int(n)
    feedback = _feedback_inventory(db, tenant_id=tenant_id)
    for entry in (CATEGORY_SUGGESTION, DUPLICATE_CANDIDATE, RECOGNITION_TIME_CHOICE):
        grouped.setdefault((entry.decision_type, entry.current_version), {})
    for key in feedback:
        if key[0] in {CATEGORY_SUGGESTION.decision_type, DUPLICATE_CANDIDATE.decision_type, RECOGNITION_TIME_CHOICE.decision_type}:
            grouped.setdefault(key, {})

    results = [
        AlgorithmVersionStats(
            decision_type=decision_type,
            algorithm_version=algorithm_version,
            active_count=counts.get("active", 0),
            superseded_count=counts.get("superseded", 0),
            withdrawn_count=counts.get("withdrawn", 0),
            accepted_count=counts.get("accepted", 0),
            dismissed_count=counts.get("dismissed", 0),
            explicit_accept_count=feedback.get((decision_type, algorithm_version), {}).get("accept", 0),
            explicit_reject_count=feedback.get((decision_type, algorithm_version), {}).get("reject", 0),
            manual_choice_count=feedback.get((decision_type, algorithm_version), {}).get("manual_override", 0),
            unknown_feedback_count=sum(n for kind, n in feedback.get((decision_type, algorithm_version), {}).items()
                if kind not in {"accept", "reject", "manual_override", "edit", "withdraw", "closed"}),
            closed_without_feedback_count=feedback.get((decision_type, algorithm_version), {}).get("closed", 0),
            new_suggestions_enabled=policy_enabled(db, tenant_id=tenant_id, decision_type=decision_type,
                version=algorithm_version, axis="new_suggestions"),
            training_enabled=policy_enabled(db, tenant_id=tenant_id, decision_type=decision_type,
                version=algorithm_version, axis="training"),
        )
        for (decision_type, algorithm_version), counts in grouped.items()
    ]
    results.sort(
        key=lambda r: sum(
            getattr(r, f"{bucket}_count") for bucket in _STATUS_BUCKETS
        ),
        reverse=True,
    )
    return results


def withdraw_algorithm_version(
    db: Session,
    *,
    tenant_id: str,
    decision_type: str,
    algorithm_version: str,
) -> int:
    """Flip every ``active`` decision for the (type, version) pair to
    ``status='withdrawn'``. Returns the number of rows updated. Does
    not auto-commit — caller decides transaction boundary."""

    result = db.execute(
        update(AlgorithmDecision)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.decision_type == decision_type)
        .where(AlgorithmDecision.algorithm_version == algorithm_version)
        .where(AlgorithmDecision.status == "active")
        .values(status="withdrawn")
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


__all__ = [
    "AlgorithmVersionStats",
    "list_algorithm_versions",
    "withdraw_algorithm_version",
]
