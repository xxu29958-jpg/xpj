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

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision


@dataclass(frozen=True)
class AlgorithmVersionStats:
    """One row of the algorithm-version inventory."""

    decision_type: str
    algorithm_version: str
    active_count: int
    superseded_count: int
    withdrawn_count: int


def list_algorithm_versions(
    db: Session, *, tenant_id: str
) -> list[AlgorithmVersionStats]:
    """Return active / superseded / withdrawn counts grouped by
    (decision_type, algorithm_version). Sorted by total descending so
    the UI surfaces the heaviest-hitter version first."""

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
        grouped.setdefault(
            key, {"active": 0, "superseded": 0, "withdrawn": 0}
        )
        grouped[key][status] = int(n)

    results = [
        AlgorithmVersionStats(
            decision_type=decision_type,
            algorithm_version=algorithm_version,
            active_count=counts.get("active", 0),
            superseded_count=counts.get("superseded", 0),
            withdrawn_count=counts.get("withdrawn", 0),
        )
        for (decision_type, algorithm_version), counts in grouped.items()
    ]
    results.sort(
        key=lambda r: (
            r.active_count + r.superseded_count + r.withdrawn_count
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
