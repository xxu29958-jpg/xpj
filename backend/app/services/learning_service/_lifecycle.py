"""v1.2 ops — active-decision lifecycle closing.

``algorithm_decisions`` rows in ``status='active'`` represent
suggestions the system would still surface today. The cleanup service
intentionally never touches active rows. That leaves one growth
vector: subjects whose lifecycle has *ended* (an expense was confirmed
/ rejected / deleted, a month closed out) keep their active decisions
forever even though no UI will ever show them again.

This module closes those decisions explicitly. It does NOT delete
anything — closed rows flip to terminal statuses and stay in the
table until the regular retention cleanup harvests them. That keeps
the audit trail intact ("we did suggest X for expense 42 before it
was confirmed") while bounding the live ``active`` working set to
"subjects still up for review".

Two surfaces:

* :func:`close_active_decisions_for_subject` — explicit close, called
  from the expense confirm / reject / pending-suggestion accept-and-
  done paths. Cheap targeted UPDATE.
* :func:`set_decision_status` — flip ONE specific decision (used by
  the pending-suggestion accept/reject endpoints to tag a single row
  with the user's verdict).
* :func:`sweep_stale_active_decisions` — periodic sweep that catches
  rows missed by the explicit path (subjects deleted out of band,
  legacy data, etc). Runs ahead of the retention cleanup.

Status choice rationale: ``dismissed`` is the user-lifecycle terminal
state, distinct from ``withdrawn`` (algorithm-version rollback) and
``accepted`` (user explicit acceptance of one decision). Model-
versions inventory groups by status so Owner Console can tell apart
"user said no" / "user closed this expense" / "owner rolled back this
algorithm version".
"""

from __future__ import annotations

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense

# Statuses on the parent subject that mean "no UI will ever ask us to
# surface this suggestion again". The sweep transitions any active
# decision whose subject lives in these statuses (or no longer exists
# at all) to ``dismissed``.
TERMINAL_EXPENSE_STATUSES = frozenset({"confirmed", "rejected"})

# Statuses a decision row can hold. Used by cleanup eligibility and
# the inventory aggregate. Exported as a frozenset so callers can do
# membership checks without re-typing the literals.
DECISION_STATUSES = frozenset(
    {"active", "superseded", "withdrawn", "accepted", "dismissed"}
)

# Subset of statuses that mean "the user-facing decision row is closed,
# safe to age out". ``active`` is excluded on purpose; ``superseded``
# means a newer row of the same type took over, so the old row is
# safe to age out as well.
TERMINAL_DECISION_STATUSES = frozenset(
    {"superseded", "withdrawn", "accepted", "dismissed"}
)


def close_active_decisions_for_subject(
    db: Session,
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: int,
    new_status: str = "dismissed",
) -> int:
    """Mark every ``active`` decision attached to ``(subject_kind,
    subject_id)`` as ``new_status``. Tenant-scoped; cross-tenant calls
    silently match zero rows. Caller commits.

    ``new_status`` defaults to ``dismissed`` (subject lifecycle ended
    or user rejected the row). Callers in the accept path can pass
    ``accepted`` to record "the user said yes" on the same row.
    """

    if new_status not in TERMINAL_DECISION_STATUSES:
        raise ValueError(
            f"close_active_decisions_for_subject: invalid status "
            f"{new_status!r}; expected one of {sorted(TERMINAL_DECISION_STATUSES)}"
        )
    result = db.execute(
        update(AlgorithmDecision)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.subject_kind == subject_kind)
        .where(AlgorithmDecision.subject_id == subject_id)
        .where(AlgorithmDecision.status == "active")
        .values(status=new_status)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def set_decision_status(
    db: Session,
    *,
    tenant_id: str,
    decision_id: int,
    new_status: str,
) -> int:
    """Flip exactly one decision row's status. Tenant-scoped; the
    caller's tenant must match the row's tenant or the update is a
    no-op. ``new_status`` must be a terminal status; the
    ``active → terminal`` transition is the only legal one (we never
    revive a closed decision from this helper)."""

    if new_status not in TERMINAL_DECISION_STATUSES:
        raise ValueError(
            f"set_decision_status: invalid status {new_status!r}; "
            f"expected one of {sorted(TERMINAL_DECISION_STATUSES)}"
        )
    result = db.execute(
        update(AlgorithmDecision)
        .where(AlgorithmDecision.id == decision_id)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.status == "active")
        .values(status=new_status)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def stale_active_count(
    db: Session, *, tenant_id: str | None = None
) -> int:
    """Count active decisions whose subject is no longer "live".

    SQL ``LEFT JOIN`` so the count is one round-trip; same definition
    of "stale" as :func:`sweep_stale_active_decisions`. Owner Console
    uses this for the dashboard counter without paying the price of
    pulling every active row into Python.
    """

    join_cond = Expense.id == AlgorithmDecision.subject_id
    stmt = (
        select(func.count(AlgorithmDecision.id))
        .select_from(AlgorithmDecision)
        .outerjoin(Expense, join_cond)
        .where(AlgorithmDecision.status == "active")
        .where(AlgorithmDecision.subject_kind == "expense")
        .where(AlgorithmDecision.subject_id.is_not(None))
        .where(
            (Expense.id.is_(None))
            | (Expense.tenant_id != AlgorithmDecision.tenant_id)
            | (Expense.status.in_(tuple(TERMINAL_EXPENSE_STATUSES)))
        )
    )
    if tenant_id is not None:
        stmt = stmt.where(AlgorithmDecision.tenant_id == tenant_id)
    return int(db.scalar(stmt) or 0)


def sweep_stale_active_decisions(
    db: Session, *, tenant_id: str | None = None, batch_size: int = 500
) -> int:
    """Close active decisions whose subject is no longer "live".

    Today this only inspects ``subject_kind='expense'``: a decision is
    stale when the referenced expense has ``status IN ('confirmed',
    'rejected')`` or no longer exists at all. ``subject_kind='month'``
    suggestions (budget P50/P75) intentionally aren't swept here —
    the user can still act on last month's suggestion next month.

    ``tenant_id=None`` sweeps every tenant (cron use). Caller commits.
    ``batch_size`` caps how many active rows we inspect per call so a
    huge ledger doesn't lock the table.
    """

    join_cond = Expense.id == AlgorithmDecision.subject_id
    stale_id_q = (
        select(AlgorithmDecision.id)
        .select_from(AlgorithmDecision)
        .outerjoin(Expense, join_cond)
        .where(AlgorithmDecision.status == "active")
        .where(AlgorithmDecision.subject_kind == "expense")
        .where(AlgorithmDecision.subject_id.is_not(None))
        .where(
            (Expense.id.is_(None))
            | (Expense.tenant_id != AlgorithmDecision.tenant_id)
            | (Expense.status.in_(tuple(TERMINAL_EXPENSE_STATUSES)))
        )
        .order_by(AlgorithmDecision.id.asc())
        .limit(max(1, min(int(batch_size), 5000)))
    )
    if tenant_id is not None:
        stale_id_q = stale_id_q.where(
            AlgorithmDecision.tenant_id == tenant_id
        )
    stale_ids = [int(row) for row in db.scalars(stale_id_q)]
    if not stale_ids:
        return 0
    result = db.execute(
        update(AlgorithmDecision)
        .where(AlgorithmDecision.id.in_(stale_ids))
        .where(AlgorithmDecision.status == "active")
        .values(status="dismissed")
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


__all__ = [
    "DECISION_STATUSES",
    "TERMINAL_DECISION_STATUSES",
    "TERMINAL_EXPENSE_STATUSES",
    "close_active_decisions_for_subject",
    "set_decision_status",
    "stale_active_count",
    "sweep_stale_active_decisions",
]
