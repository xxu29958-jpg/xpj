"""v1.2 ops — maintenance facade for the learning tables.

Pulls together three concerns the rest of the codebase wants from
"the v1.2 learning layer's ops surface":

* :func:`run_full_maintenance` — sweep stale active decisions, then
  prune expired rows, then stamp ``app_meta`` with the run timestamp.
  This is the entry point ``/api/maintenance/learning-cleanup`` calls.
* :func:`get_status_overview` — read-only snapshot for Owner Console:
  per-table row count, per-table expired-but-not-yet-pruned candidate
  count, last cleanup timestamp.

The functions live in ``learning_service`` (not the generic
``cleanup_service``) because everything they touch is internal to
this layer's contract. Routes / Owner Console templates import the
high-level functions; nothing outside this module knows the internal
table names or the per-row retention math.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, LedgerLearningEvent, OcrFact
from app.models.app_meta import LEARNING_CLEANUP_LAST_RUN_KEY
from app.services.app_meta_service import get_value, set_value
from app.services.learning_service._cleanup import (
    CleanupReport,
    cleanup_expired_learning_tables,
)
from app.services.learning_service._lifecycle import (
    sweep_stale_active_decisions,
)
from app.services.time_service import ensure_utc, now_utc


@dataclass(frozen=True)
class LearningTableSnapshot:
    """Per-table counters surfaced to Owner Console."""

    total_rows: int
    expired_candidate_rows: int


@dataclass(frozen=True)
class LearningStatusOverview:
    """Snapshot of the learning tables for the Owner Console panel."""

    algorithm_decisions: LearningTableSnapshot
    ledger_learning_events: LearningTableSnapshot
    ocr_facts: LearningTableSnapshot
    active_decisions: int
    stale_active_candidates: int
    last_cleanup_at: str | None


@dataclass(frozen=True)
class LearningMaintenanceResult:
    """What :func:`run_full_maintenance` actually did."""

    swept_stale_active: int
    cleanup: CleanupReport
    finished_at: str


def _stale_active_count(db: Session) -> int:
    """Cheap version of the sweep that counts but doesn't update — for
    the status overview. Same definition of "stale" as the real sweep."""

    from app.models import Expense

    candidates = list(
        db.scalars(
            select(AlgorithmDecision)
            .where(AlgorithmDecision.status == "active")
            .where(AlgorithmDecision.subject_kind == "expense")
            .where(AlgorithmDecision.subject_id.is_not(None))
        )
    )
    if not candidates:
        return 0
    expense_ids = {c.subject_id for c in candidates if c.subject_id is not None}
    live = dict(
        db.execute(
            select(Expense.id, Expense.status).where(Expense.id.in_(expense_ids))
        ).all()
    )
    stale = 0
    for c in candidates:
        status = live.get(c.subject_id)
        if status is None or status in ("confirmed", "rejected"):
            stale += 1
    return stale


def _expired_count(
    db: Session,
    *,
    model,
    timestamp_column,
    status_filter=None,
) -> int:
    """Count rows past their retention window.

    ``status_filter`` lets the caller exclude rows the real cleanup
    wouldn't touch — e.g. ``algorithm_decisions`` rows in
    ``status='active'`` are never pruned.
    """

    rows = list(
        db.scalars(
            select(model)
            .where(model.retention_days > 0)
        )
    )
    threshold = now_utc()
    expired = 0
    for row in rows:
        if status_filter is not None and not status_filter(row):
            continue
        anchor = ensure_utc(timestamp_column(row))
        if anchor is None:
            continue
        if anchor + timedelta(days=int(row.retention_days)) <= threshold:
            expired += 1
    return expired


def get_status_overview(db: Session) -> LearningStatusOverview:
    """Compose the Owner Console snapshot."""

    ad_total = int(db.scalar(select(func.count(AlgorithmDecision.id))) or 0)
    ad_active = int(
        db.scalar(
            select(func.count(AlgorithmDecision.id)).where(
                AlgorithmDecision.status == "active"
            )
        )
        or 0
    )
    ad_expired = _expired_count(
        db,
        model=AlgorithmDecision,
        timestamp_column=lambda r: r.created_at,
        status_filter=lambda r: r.status in ("superseded", "withdrawn"),
    )

    ev_total = int(
        db.scalar(select(func.count(LedgerLearningEvent.id))) or 0
    )
    ev_expired = _expired_count(
        db,
        model=LedgerLearningEvent,
        timestamp_column=lambda r: r.created_at,
    )

    oc_total = int(db.scalar(select(func.count(OcrFact.id))) or 0)
    oc_expired = _expired_count(
        db,
        model=OcrFact,
        timestamp_column=lambda r: r.extracted_at,
    )

    last_cleanup = get_value(db, LEARNING_CLEANUP_LAST_RUN_KEY)
    stale_active = _stale_active_count(db)

    return LearningStatusOverview(
        algorithm_decisions=LearningTableSnapshot(
            total_rows=ad_total, expired_candidate_rows=ad_expired
        ),
        ledger_learning_events=LearningTableSnapshot(
            total_rows=ev_total, expired_candidate_rows=ev_expired
        ),
        ocr_facts=LearningTableSnapshot(
            total_rows=oc_total, expired_candidate_rows=oc_expired
        ),
        active_decisions=ad_active,
        stale_active_candidates=stale_active,
        last_cleanup_at=last_cleanup,
    )


def run_full_maintenance(
    db: Session,
    *,
    batch_size: int = 500,
    now: datetime | None = None,
) -> LearningMaintenanceResult:
    """Sweep stale active rows, then prune expired ones, then stamp.

    The order matters: sweeping converts ``active`` rows attached to
    confirmed/rejected/deleted expenses into ``withdrawn`` first, so
    the subsequent cleanup picks them up under "expired non-active"
    rather than leaving them around for the next pass.

    Caller commits; this function uses ``db.commit()`` internally via
    the sub-functions but returns after the meta stamp is written.
    """

    swept = sweep_stale_active_decisions(db, batch_size=batch_size)
    if swept:
        db.commit()
    report = cleanup_expired_learning_tables(
        db, batch_size=batch_size, now=now
    )
    finished = (now or now_utc()).isoformat()
    set_value(db, LEARNING_CLEANUP_LAST_RUN_KEY, finished)
    return LearningMaintenanceResult(
        swept_stale_active=swept,
        cleanup=report,
        finished_at=finished,
    )


__all__ = [
    "LearningMaintenanceResult",
    "LearningStatusOverview",
    "LearningTableSnapshot",
    "get_status_overview",
    "run_full_maintenance",
]
