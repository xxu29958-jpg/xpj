"""v1.2 ops — active-decision lifecycle closing.

``algorithm_decisions`` rows in ``status='active'`` represent
suggestions the system would still surface today. The cleanup service
intentionally never touches active rows. That leaves one growth
vector: subjects whose lifecycle has *ended* (an expense was confirmed
/ rejected / deleted, a month closed out) keep their active decisions
forever even though no UI will ever show them again.

This module closes those decisions explicitly. It does NOT delete
anything — closed rows flip to ``status='withdrawn'`` and stay in the
table until the regular retention cleanup harvests them. That keeps
the audit trail intact ("we did suggest X for expense 42 before it
was confirmed") while bounding the live ``active`` working set to
"subjects still up for review".

Two surfaces:

* :func:`close_active_decisions_for_subject` — explicit close, called
  from the expense confirm / reject / pending-suggestion accept-and-
  done paths. Cheap targeted UPDATE.
* :func:`sweep_stale_active_decisions` — periodic sweep that catches
  rows missed by the explicit path (subjects deleted out of band,
  legacy data, etc). Runs ahead of the retention cleanup.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense

# Statuses on the parent subject that mean "no UI will ever ask us to
# surface this suggestion again". The sweep transitions any active
# decision whose subject lives in these statuses (or no longer exists
# at all) to ``withdrawn``.
TERMINAL_EXPENSE_STATUSES = frozenset({"confirmed", "rejected"})


def close_active_decisions_for_subject(
    db: Session,
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: int,
) -> int:
    """Mark every ``active`` decision attached to ``(subject_kind,
    subject_id)`` as ``withdrawn``. Tenant-scoped; cross-tenant calls
    silently match zero rows. Caller commits.

    Returns the number of rows updated.
    """

    result = db.execute(
        update(AlgorithmDecision)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.subject_kind == subject_kind)
        .where(AlgorithmDecision.subject_id == subject_id)
        .where(AlgorithmDecision.status == "active")
        .values(status="withdrawn")
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


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

    candidates_q = (
        select(AlgorithmDecision)
        .where(AlgorithmDecision.status == "active")
        .where(AlgorithmDecision.subject_kind == "expense")
        .where(AlgorithmDecision.subject_id.is_not(None))
        .order_by(AlgorithmDecision.id.asc())
        .limit(max(1, min(int(batch_size), 5000)))
    )
    if tenant_id is not None:
        candidates_q = candidates_q.where(
            AlgorithmDecision.tenant_id == tenant_id
        )
    candidates = list(db.scalars(candidates_q))
    if not candidates:
        return 0

    expense_ids = {row.subject_id for row in candidates if row.subject_id is not None}
    live_status_by_id: dict[int, str] = {}
    if expense_ids:
        rows = db.execute(
            select(Expense.id, Expense.status, Expense.tenant_id).where(
                Expense.id.in_(expense_ids)
            )
        ).all()
        live_status_by_id = {
            int(eid): (status, etenant) for eid, status, etenant in rows
        }

    stale_ids: list[int] = []
    for decision in candidates:
        live = live_status_by_id.get(int(decision.subject_id))
        if live is None:
            # Subject deleted out of band — close the decision.
            stale_ids.append(decision.id)
            continue
        live_status, live_tenant = live
        if live_tenant != decision.tenant_id:
            # Subject reassigned to another tenant (shouldn't happen,
            # but if it does the original decision is moot).
            stale_ids.append(decision.id)
            continue
        if live_status in TERMINAL_EXPENSE_STATUSES:
            stale_ids.append(decision.id)

    if not stale_ids:
        return 0
    result = db.execute(
        update(AlgorithmDecision)
        .where(AlgorithmDecision.id.in_(stale_ids))
        .where(AlgorithmDecision.status == "active")
        .values(status="withdrawn")
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


__all__ = [
    "TERMINAL_EXPENSE_STATUSES",
    "close_active_decisions_for_subject",
    "sweep_stale_active_decisions",
]
