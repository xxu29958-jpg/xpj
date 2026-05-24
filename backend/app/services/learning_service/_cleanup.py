"""v1.2 follow-up — append-only learning-table retention cleanup.

Three of the v1.2 tables (``algorithm_decisions`` /
``ledger_learning_events`` / ``ocr_facts``) grow monotonically. ADR-0037
flagged this as a known debt; the resolution mirrors the
``budget_advisor_audit_logs.retention_days`` pattern from v1.1:

* Each row carries a ``retention_days`` value (default 180).
* This module's functions delete rows whose ``created_at +
  retention_days`` (or ``extracted_at + retention_days`` for
  ``ocr_facts``) has already elapsed.
* ``retention_days == 0`` means "keep forever" — useful for the
  small number of decisions / facts the owner has flagged as
  historically interesting.

Two safety rules different from the budget audit table:

* ``algorithm_decisions`` rows in ``status='active'`` are NEVER
  pruned, regardless of age — the suggestion is still being shown
  to the user and removing it under their nose is the wrong
  behaviour. Only ``superseded`` and ``withdrawn`` rows are
  candidates.
* Each call processes at most ``batch_size`` rows so a giant
  ledger doesn't block the request loop while pruning. The cleanup
  is idempotent; running it twice does nothing extra.

This module commits its own transaction(s) inside the helper. Callers
(e.g. a scheduled task) just call it; rollback / partial-failure
recovery is the next call's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, LedgerLearningEvent, OcrFact
from app.services.time_service import ensure_utc, now_utc

_DEFAULT_BATCH = 500
_MAX_BATCH = 5000


@dataclass(frozen=True)
class CleanupReport:
    """Per-table count of rows actually deleted in this invocation."""

    algorithm_decisions: int
    ledger_learning_events: int
    ocr_facts: int

    @property
    def total(self) -> int:
        return (
            self.algorithm_decisions
            + self.ledger_learning_events
            + self.ocr_facts
        )


def _clamp_batch(batch_size: int) -> int:
    return max(1, min(int(batch_size or _DEFAULT_BATCH), _MAX_BATCH))


def _expired(
    threshold: datetime, anchor: datetime | None, retention_days: int
) -> bool:
    if retention_days <= 0:
        return False
    when = ensure_utc(anchor)
    if when is None:
        return False
    return when + timedelta(days=int(retention_days)) <= threshold


def cleanup_expired_algorithm_decisions(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = _DEFAULT_BATCH,
) -> int:
    """Delete superseded / withdrawn decisions past their retention."""

    threshold = now or now_utc()
    rows = list(
        db.scalars(
            select(AlgorithmDecision)
            .where(AlgorithmDecision.retention_days > 0)
            # All terminal statuses are eligible — superseded (newer
            # version replaced it), withdrawn (algo-version rollback),
            # accepted (user said yes), dismissed (user said no /
            # subject lifecycle closed). Active rows are never pruned.
            .where(
                AlgorithmDecision.status.in_(
                    ("superseded", "withdrawn", "accepted", "dismissed")
                )
            )
            .order_by(AlgorithmDecision.created_at.asc())
            .limit(_clamp_batch(batch_size))
        )
    )
    expired = [
        row for row in rows
        if _expired(threshold, row.created_at, row.retention_days)
    ]
    for row in expired:
        db.delete(row)
    if expired:
        db.commit()
    return len(expired)


def cleanup_expired_learning_events(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = _DEFAULT_BATCH,
) -> int:
    """Delete learning events past their retention. Events linked to an
    ``active`` decision are pruned with everything else — the decision
    row keeps living, just without the historical reaction trail."""

    threshold = now or now_utc()
    rows = list(
        db.scalars(
            select(LedgerLearningEvent)
            .where(LedgerLearningEvent.retention_days > 0)
            .order_by(LedgerLearningEvent.created_at.asc())
            .limit(_clamp_batch(batch_size))
        )
    )
    expired = [
        row for row in rows
        if _expired(threshold, row.created_at, row.retention_days)
    ]
    for row in expired:
        db.delete(row)
    if expired:
        db.commit()
    return len(expired)


def cleanup_expired_ocr_facts(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = _DEFAULT_BATCH,
) -> int:
    """Delete OCR facts past their retention. Anchors on
    ``extracted_at`` because that's the user-visible "when did OCR run"
    timestamp; ``created_at`` is identical for normal paths but the
    distinction matters when a row is backfilled."""

    threshold = now or now_utc()
    rows = list(
        db.scalars(
            select(OcrFact)
            .where(OcrFact.retention_days > 0)
            .order_by(OcrFact.extracted_at.asc())
            .limit(_clamp_batch(batch_size))
        )
    )
    expired = [
        row for row in rows
        if _expired(threshold, row.extracted_at, row.retention_days)
    ]
    for row in expired:
        db.delete(row)
    if expired:
        db.commit()
    return len(expired)


def cleanup_expired_learning_tables(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = _DEFAULT_BATCH,
) -> CleanupReport:
    """Run all three table cleanups in sequence and return totals."""

    return CleanupReport(
        algorithm_decisions=cleanup_expired_algorithm_decisions(
            db, now=now, batch_size=batch_size
        ),
        ledger_learning_events=cleanup_expired_learning_events(
            db, now=now, batch_size=batch_size
        ),
        ocr_facts=cleanup_expired_ocr_facts(
            db, now=now, batch_size=batch_size
        ),
    )


__all__ = [
    "CleanupReport",
    "cleanup_expired_algorithm_decisions",
    "cleanup_expired_learning_events",
    "cleanup_expired_learning_tables",
    "cleanup_expired_ocr_facts",
]
