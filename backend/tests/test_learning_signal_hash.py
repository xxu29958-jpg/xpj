"""v1.2 ops — signal_hash index path replaces JSON LIKE."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.models import Expense, LedgerLearningEvent
from app.services.learning_service import (
    CATEGORY_SUGGESTION,
    DUPLICATE_CANDIDATE,
    EventDraft,
    build_feedback_marker,
    canonical_marker_hash,
    compute_category_suggestion,
    record_event,
)
from app.services.learning_service._duplicate_scoring import (
    _has_recent_reject,
)


def _seed_confirmed(category: str, *, merchant: str = "麦当劳") -> int:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=1000,
            merchant=merchant,
            category=category,
            source="pytest",
            raw_text="",
            status="confirmed",
            expense_time=now - timedelta(days=2),
            confirmed_at=now - timedelta(days=2),
        )
        db.add(expense)
        db.commit()
        return expense.id


def test_marker_hash_is_deterministic() -> None:
    a = canonical_marker_hash({"category": "餐饮"})
    b = canonical_marker_hash({"category": "餐饮"})
    c = canonical_marker_hash({"category": "购物"})
    assert a == b
    assert a != c
    # SHA-256 hex length.
    assert len(a) == 64


def test_record_event_populates_signal_columns(*, identity) -> None:
    marker = build_feedback_marker(
        CATEGORY_SUGGESTION.decision_type, {"category": "餐饮"}
    )
    expected_hash = canonical_marker_hash(marker)
    with SessionLocal() as db:
        row = record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=42,
                signal_type=CATEGORY_SUGGESTION.decision_type,
                signal_marker=marker,
            ),
        )
        db.commit()
        assert row.signal_type == CATEGORY_SUGGESTION.decision_type
        assert row.signal_hash == expected_hash
        # signal_payload is the human-readable JSON of the marker.
        assert row.signal_payload == '{"category": "餐饮"}'


def test_event_without_marker_keeps_signal_columns_null(*, identity) -> None:
    with SessionLocal() as db:
        row = record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="manual_override",
                subject_kind="expense",
                subject_id=1,
            ),
        )
        db.commit()
        assert row.signal_type is None
        assert row.signal_hash is None
        assert row.signal_payload is None


def test_category_reject_via_signal_hash_suppresses_suggestion(
    *, identity,
) -> None:
    # Build the merchant→category history first.
    for _ in range(4):
        _seed_confirmed("餐饮", merchant="老乡鸡")

    marker = build_feedback_marker(
        CATEGORY_SUGGESTION.decision_type, {"category": "餐饮"}
    )

    with SessionLocal() as db:
        for _ in range(2):
            record_event(
                db,
                EventDraft(
                    tenant_id="owner",
                    event_type="reject",
                    subject_kind="expense",
                    subject_id=1,
                    signal_type=CATEGORY_SUGGESTION.decision_type,
                    signal_marker=marker,
                    # Intentionally leave before_payload empty so the
                    # legacy LIKE fallback cannot save the test — the
                    # signal_hash path has to do the work.
                ),
            )
        db.commit()

        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="老乡鸡",
            reject_threshold=2,
        )
        # Two indexed rejects → suppressed.
        assert result is None


def test_duplicate_reject_via_signal_hash(*, identity) -> None:
    marker = build_feedback_marker(
        DUPLICATE_CANDIDATE.decision_type,
        {"amount_cents": 2000, "merchant": "cafe"},
    )
    with SessionLocal() as db:
        record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=10,
                signal_type=DUPLICATE_CANDIDATE.decision_type,
                signal_marker=marker,
            ),
        )
        db.commit()

        # _has_recent_reject reads the indexed path — no
        # before_payload is set on the event above, so a working test
        # confirms the index branch fires.
        assert (
            _has_recent_reject(
                db,
                tenant_id="owner",
                merchant="cafe",
                amount_cents=2000,
                horizon_days=90,
            )
            is True
        )
        assert (
            _has_recent_reject(
                db,
                tenant_id="owner",
                merchant="other",
                amount_cents=2000,
                horizon_days=90,
            )
            is False
        )


def test_legacy_rows_still_counted_via_payload_fallback(*, identity) -> None:
    # Simulate a pre-migration row: write an event the old way, with
    # the marker inside before_payload but no signal_hash column set.
    for _ in range(4):
        _seed_confirmed("餐饮", merchant="legacy_path")

    with SessionLocal() as db:
        for _ in range(2):
            legacy = LedgerLearningEvent(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=1,
                before_payload='{"category": "餐饮"}',
                after_payload=None,
                # signal_type / signal_hash / signal_payload all NULL
            )
            db.add(legacy)
        db.commit()

        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="legacy_path",
            reject_threshold=2,
        )
        # Legacy rows still feed the feedback loop via the LIKE
        # fallback inside the OR branch.
        assert result is None
