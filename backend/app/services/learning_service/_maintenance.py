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

import hashlib
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


def _scoped_meta_key(base_key: str, tenant_id: str | None) -> str:
    if tenant_id is None:
        return base_key
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    return f"{base_key}:t:{digest}"


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
    tenant_id: str | None = None,
) -> int:
    """Count rows past their retention window.

    ``status_filter`` lets the caller exclude rows the real cleanup
    wouldn't touch — e.g. ``algorithm_decisions`` rows in
    ``status='active'`` are never pruned.
    """

    stmt = select(model).where(model.retention_days > 0)
    if tenant_id is not None:
        stmt = stmt.where(model.tenant_id == tenant_id)
    rows = list(db.scalars(stmt))
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


def _count_algorithm_decisions(
    db: Session, *, tenant_id: str | None = None, active_only: bool = False
) -> int:
    stmt = select(func.count(AlgorithmDecision.id))
    if active_only:
        stmt = stmt.where(AlgorithmDecision.status == "active")
    if tenant_id is not None:
        stmt = stmt.where(AlgorithmDecision.tenant_id == tenant_id)
    return int(db.scalar(stmt) or 0)


def _count_ledger_learning_events(
    db: Session, *, tenant_id: str | None = None
) -> int:
    stmt = select(func.count(LedgerLearningEvent.id))
    if tenant_id is not None:
        stmt = stmt.where(LedgerLearningEvent.tenant_id == tenant_id)
    return int(db.scalar(stmt) or 0)


def _count_ocr_facts(db: Session, *, tenant_id: str | None = None) -> int:
    stmt = select(func.count(OcrFact.id))
    if tenant_id is not None:
        stmt = stmt.where(OcrFact.tenant_id == tenant_id)
    return int(db.scalar(stmt) or 0)


def _algorithm_decision_snapshot(
    db: Session, *, tenant_id: str | None = None
) -> LearningTableSnapshot:
    return LearningTableSnapshot(
        total_rows=_count_algorithm_decisions(db, tenant_id=tenant_id),
        expired_candidate_rows=_expired_count(
            db,
            model=AlgorithmDecision,
            timestamp_column=lambda r: r.created_at,
            # Every terminal status is cleanup-eligible; active rows are
            # never pruned regardless of age.
            status_filter=lambda r: r.status in TERMINAL_DECISION_STATUSES,
            tenant_id=tenant_id,
        ),
    )


def _ledger_learning_event_snapshot(
    db: Session, *, tenant_id: str | None = None
) -> LearningTableSnapshot:
    return LearningTableSnapshot(
        total_rows=_count_ledger_learning_events(db, tenant_id=tenant_id),
        expired_candidate_rows=_expired_count(
            db,
            model=LedgerLearningEvent,
            timestamp_column=lambda r: r.created_at,
            tenant_id=tenant_id,
        ),
    )


def _ocr_fact_snapshot(
    db: Session, *, tenant_id: str | None = None
) -> LearningTableSnapshot:
    return LearningTableSnapshot(
        total_rows=_count_ocr_facts(db, tenant_id=tenant_id),
        expired_candidate_rows=_expired_count(
            db,
            model=OcrFact,
            timestamp_column=lambda r: r.extracted_at,
            tenant_id=tenant_id,
        ),
    )


def _last_cleanup_summary(db: Session, *, tenant_id: str | None = None) -> dict | None:
    last_summary_raw = get_value(
        db, _scoped_meta_key(LEARNING_CLEANUP_LAST_SUMMARY_KEY, tenant_id)
    )
    if not last_summary_raw:
        return None
    try:
        parsed = json.loads(last_summary_raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def get_status_overview(
    db: Session, *, tenant_id: str | None = None
) -> LearningStatusOverview:
    """Compose the Owner Console snapshot.

    ``tenant_id=None`` aggregates across every tenant — that's wrong
    for any caller that's identified to a single ledger and was the
    cross-tenant leak codex flagged on PR #124. Routes MUST pass the
    authenticated admin's tenant; only background cron-style callers
    (none today) should keep the None default.
    """
    last_cleanup = get_value(
        db, _scoped_meta_key(LEARNING_CLEANUP_LAST_RUN_KEY, tenant_id)
    )

    return LearningStatusOverview(
        algorithm_decisions=_algorithm_decision_snapshot(db, tenant_id=tenant_id),
        ledger_learning_events=_ledger_learning_event_snapshot(
            db, tenant_id=tenant_id
        ),
        ocr_facts=_ocr_fact_snapshot(db, tenant_id=tenant_id),
        active_decisions=_count_algorithm_decisions(
            db, tenant_id=tenant_id, active_only=True
        ),
        stale_active_candidates=stale_active_count(db, tenant_id=tenant_id),
        last_cleanup_at=last_cleanup,
        last_cleanup_summary=_last_cleanup_summary(db, tenant_id=tenant_id),
    )


def run_full_maintenance(
    db: Session,
    *,
    tenant_id: str | None = None,
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

    ``tenant_id=None`` (the cron / scheduler default) sweeps every
    tenant. Route handlers MUST pass the authenticated tenant — the
    earlier PR #124 review caught this as a real cross-tenant data
    mutation when the admin endpoint operated globally.
    """

    started = perf_counter()
    swept = sweep_stale_active_decisions(
        db, tenant_id=tenant_id, batch_size=batch_size
    )
    if swept:
        db.commit()
    report = cleanup_expired_learning_tables(
        db, tenant_id=tenant_id, batch_size=batch_size, now=now
    )
    elapsed_ms = max(0, int((perf_counter() - started) * 1000))
    finished = (now or now_utc()).isoformat()
    run_key = _scoped_meta_key(LEARNING_CLEANUP_LAST_RUN_KEY, tenant_id)
    summary_key = _scoped_meta_key(
        LEARNING_CLEANUP_LAST_SUMMARY_KEY, tenant_id
    )
    set_value(db, run_key, finished)
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
        summary_key,
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
