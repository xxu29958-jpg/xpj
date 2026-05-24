"""v1.2 follow-up — retention cleanup for the three append-only tables."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.models import (
    AlgorithmDecision,
    Expense,
    LedgerLearningEvent,
    OcrFact,
)
from app.services.learning_service import (
    DecisionDraft,
    EventDraft,
    OcrFactDraft,
    cleanup_expired_algorithm_decisions,
    cleanup_expired_learning_events,
    cleanup_expired_learning_tables,
    cleanup_expired_ocr_facts,
    record_decision,
    record_event,
    record_ocr_fact,
    supersede_decision,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _seed_expense(tenant_id: str = "owner") -> int:
    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            source="pytest",
            raw_text="",
            status="pending",
        )
        db.add(expense)
        db.commit()
        return expense.id


def _seed_decision(
    *,
    status: str = "active",
    retention_days: int = 180,
    created_at: datetime,
) -> int:
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="v1",
                subject_kind="expense",
                subject_id=1,
                payload={"category": "餐饮"},
            ),
            now=created_at,
        )
        row.status = status
        row.retention_days = retention_days
        db.commit()
        return row.id


def test_active_decisions_never_pruned(*, identity) -> None:
    # An active decision created 9999 days ago must still survive.
    _seed_decision(
        status="active",
        retention_days=30,
        created_at=NOW - timedelta(days=9999),
    )
    with SessionLocal() as db:
        removed = cleanup_expired_algorithm_decisions(db, now=NOW)
        assert removed == 0
        assert db.query(AlgorithmDecision).count() == 1


def test_superseded_decision_pruned_when_past_retention(*, identity) -> None:
    _seed_decision(
        status="superseded",
        retention_days=30,
        created_at=NOW - timedelta(days=45),
    )
    with SessionLocal() as db:
        removed = cleanup_expired_algorithm_decisions(db, now=NOW)
        assert removed == 1
        assert db.query(AlgorithmDecision).count() == 0


def test_superseded_decision_kept_when_within_retention(*, identity) -> None:
    _seed_decision(
        status="superseded",
        retention_days=30,
        created_at=NOW - timedelta(days=10),
    )
    with SessionLocal() as db:
        removed = cleanup_expired_algorithm_decisions(db, now=NOW)
        assert removed == 0
        assert db.query(AlgorithmDecision).count() == 1


def test_retention_zero_opts_out(*, identity) -> None:
    _seed_decision(
        status="withdrawn",
        retention_days=0,
        created_at=NOW - timedelta(days=9999),
    )
    with SessionLocal() as db:
        removed = cleanup_expired_algorithm_decisions(db, now=NOW)
        assert removed == 0


def test_learning_events_pruned_by_age(*, identity) -> None:
    with SessionLocal() as db:
        old = record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="manual_override",
                subject_kind="expense",
                subject_id=1,
            ),
            now=NOW - timedelta(days=200),
        )
        old.retention_days = 30
        record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="manual_override",
                subject_kind="expense",
                subject_id=2,
            ),
            now=NOW - timedelta(days=10),
        )
        db.commit()
        removed = cleanup_expired_learning_events(db, now=NOW)
        assert removed == 1
        remaining = db.query(LedgerLearningEvent).all()
        assert len(remaining) == 1
        assert remaining[0].subject_id == 2


def test_ocr_facts_pruned_by_extracted_at(*, identity) -> None:
    expense_id = _seed_expense()
    with SessionLocal() as db:
        old = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="old",
            ),
            now=NOW - timedelta(days=400),
        )
        old.retention_days = 365
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="recent",
            ),
            now=NOW - timedelta(days=30),
        )
        db.commit()
        removed = cleanup_expired_ocr_facts(db, now=NOW)
        assert removed == 1
        rows = db.query(OcrFact).all()
        assert len(rows) == 1
        assert rows[0].raw_text == "recent"


def test_cleanup_all_tables_returns_total(*, identity) -> None:
    # One eligible row in each table → total == 3.
    _seed_decision(
        status="superseded",
        retention_days=30,
        created_at=NOW - timedelta(days=200),
    )
    expense_id = _seed_expense()
    with SessionLocal() as db:
        event = record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="manual_override",
                subject_kind="expense",
                subject_id=1,
            ),
            now=NOW - timedelta(days=200),
        )
        event.retention_days = 30
        fact = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="x",
            ),
            now=NOW - timedelta(days=200),
        )
        fact.retention_days = 30
        db.commit()

        report = cleanup_expired_learning_tables(db, now=NOW)
        assert report.algorithm_decisions == 1
        assert report.ledger_learning_events == 1
        assert report.ocr_facts == 1
        assert report.total == 3


def test_supersede_then_cleanup_preserves_active(*, identity) -> None:
    # Realistic pattern: v1 emits decision A; v2 emits decision B and
    # supersedes A; some days later cleanup runs. A must be eligible
    # for pruning (status=superseded), B must be kept (status=active).
    a = _seed_decision(
        status="active",
        retention_days=30,
        created_at=NOW - timedelta(days=200),
    )
    b = _seed_decision(
        status="active",
        retention_days=30,
        created_at=NOW - timedelta(days=200),
    )
    with SessionLocal() as db:
        supersede_decision(
            db, tenant_id="owner", old_decision_id=a, new_decision_id=b
        )
        db.commit()
        removed = cleanup_expired_algorithm_decisions(db, now=NOW)
        assert removed == 1
        remaining = db.query(AlgorithmDecision).all()
        assert len(remaining) == 1
        assert remaining[0].id == b
        assert remaining[0].status == "active"


def test_batch_size_caps_one_call(*, identity) -> None:
    # Seed 5 expired rows, batch_size=2 → only 2 deleted per call.
    for _ in range(5):
        _seed_decision(
            status="superseded",
            retention_days=30,
            created_at=NOW - timedelta(days=200),
        )
    with SessionLocal() as db:
        removed = cleanup_expired_algorithm_decisions(
            db, now=NOW, batch_size=2
        )
        assert removed == 2
        assert db.query(AlgorithmDecision).count() == 3
