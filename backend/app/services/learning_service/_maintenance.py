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

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, LedgerLearningEvent, OcrFact
from app.models.app_meta import (
    LEARNING_CLEANUP_LAST_RUN_KEY,
    LEARNING_CLEANUP_LAST_SUMMARY_KEY,
)
from app.services.app_meta_service import get_value, set_value
from app.services.learning_service._cleanup import (
    CleanupReport,
    cleanup_expired_learning_tables,
)
from app.services.learning_service._lifecycle import (
    TERMINAL_DECISION_STATUSES,
    stale_active_count,
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
    last_cleanup_summary: dict | None = None


@dataclass(frozen=True)
class LearningMaintenanceResult:
    """What :func:`run_full_maintenance` actually did.

    ``elapsed_ms`` is the wall-clock time the whole sweep + prune
    sequence took. Owner Console shows it so a "cleanup took 8
    seconds" surfaces visibly instead of as a silent slowdown.
    """

    swept_stale_active: int
    cleanup: CleanupReport
    finished_at: str
    elapsed_ms: int


# ``_stale_active_count`` used to pull every active decision and join
# in Python — fine for fixtures, brutal once a real ledger fills the
# table. The replacement is a single SQL LEFT JOIN in
# ``stale_active_count`` (lifecycle module), used directly here.


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
        # Every terminal status is cleanup-eligible; active rows are
        # never pruned regardless of age.
        status_filter=lambda r: r.status in TERMINAL_DECISION_STATUSES,
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
    last_summary_raw = get_value(db, LEARNING_CLEANUP_LAST_SUMMARY_KEY)
    last_summary: dict | None = None
    if last_summary_raw:
        try:
            parsed = json.loads(last_summary_raw)
            if isinstance(parsed, dict):
                last_summary = parsed
        except (json.JSONDecodeError, ValueError):
            last_summary = None
    stale_active = stale_active_count(db)

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
        last_cleanup_summary=last_summary,
    )


def run_full_maintenance(
    db: Session,
    *,
    batch_size: int = 500,
    now: datetime | None = None,
) -> LearningMaintenanceResult:
    """Sweep stale active rows, then prune expired ones, then stamp.

    The order matters: sweeping converts ``active`` rows attached to
    confirmed/rejected/deleted expenses into ``dismissed`` first, so
    the subsequent cleanup picks them up under "expired non-active"
    rather than leaving them around for the next pass.

    Times the wall-clock duration and stamps a compact JSON summary
    (``elapsed_ms`` + counters) into ``app_meta`` so Owner Console can
    surface "last cleanup took N ms" without a separate audit table.
    """

    started = perf_counter()
    swept = sweep_stale_active_decisions(db, batch_size=batch_size)
    if swept:
        db.commit()
    report = cleanup_expired_learning_tables(
        db, batch_size=batch_size, now=now
    )
    elapsed_ms = max(0, int((perf_counter() - started) * 1000))
    finished = (now or now_utc()).isoformat()
    set_value(db, LEARNING_CLEANUP_LAST_RUN_KEY, finished)
    summary = {
        "finished_at": finished,
        "elapsed_ms": elapsed_ms,
        "swept_stale_active": swept,
        "algorithm_decisions_deleted": report.algorithm_decisions,
        "ledger_learning_events_deleted": report.ledger_learning_events,
        "ocr_facts_deleted": report.ocr_facts,
        "total_deleted": report.total,
    }
    set_value(
        db,
        LEARNING_CLEANUP_LAST_SUMMARY_KEY,
        json.dumps(summary, sort_keys=True, ensure_ascii=False),
    )
    return LearningMaintenanceResult(
        swept_stale_active=swept,
        cleanup=report,
        finished_at=finished,
        elapsed_ms=elapsed_ms,
    )


__all__ = [
    "LearningMaintenanceResult",
    "LearningStatusOverview",
    "LearningTableSnapshot",
    "get_status_overview",
    "run_full_maintenance",
]
