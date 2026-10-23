"""v1.2 ops — signal_hash index path replaces JSON LIKE."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import Expense, LedgerLearningEvent
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
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
    duplicate_feedback_expense_ids,
)
from tests._infra.identity import seeded_owner_account_id


def _seed_confirmed(category: str, *, merchant: str = "麦当劳") -> int:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        resolve_write_capability(db)
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
        refresh_legacy_expense_time(db, expense)
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
                actor_account_id=seeded_owner_account_id(),
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
                actor_account_id=seeded_owner_account_id(),
            ),
        )
        db.commit()
        assert row.signal_type is None
        assert row.signal_hash is None
        assert row.signal_payload is None


@pytest.mark.real_db
def test_category_reject_via_signal_hash_suppresses_suggestion(
    *, identity,
) -> None:
    # Build the merchant→category history first.
    history_ids = [_seed_confirmed("餐饮", merchant="老乡鸡") for _ in range(4)]

    marker = build_feedback_marker(
        CATEGORY_SUGGESTION.decision_type, {"category": "餐饮"}
    )

    with SessionLocal() as db:
        for subject_id in history_ids[:2]:
            record_event(
                db,
                EventDraft(
                    tenant_id="owner",
                    event_type="reject",
                    subject_kind="expense",
                    subject_id=subject_id,
                    signal_type=CATEGORY_SUGGESTION.decision_type,
                    signal_marker=marker,
                    # Intentionally leave before_payload empty so the
                    # legacy LIKE fallback cannot save the test — the
                    # signal_hash path has to do the work.
                    actor_account_id=seeded_owner_account_id(),
                ),
            )
        db.commit()

        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="老乡鸡",
            reject_threshold=2,
            actor_account_id=seeded_owner_account_id(),
        )
        # Two indexed rejects → suppressed.
        assert result is None


def test_unpaired_legacy_reject_is_not_current_pair_evidence(*, identity) -> None:
    source_id = _seed_confirmed("餐饮", merchant="Cafe")
    marker = build_feedback_marker(
        DUPLICATE_CANDIDATE.decision_type,
        {"amount_cents": 1000, "merchant": "cafe"},
    )
    with SessionLocal() as db:
        record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=source_id,
                signal_type=DUPLICATE_CANDIDATE.decision_type,
                signal_marker=marker,
                actor_account_id=seeded_owner_account_id(),
            ),
        )
        db.commit()

        source = db.get(Expense, source_id)
        assert duplicate_feedback_expense_ids(db, tenant_id="owner", expenses=[source],
            actor_account_id=seeded_owner_account_id()) == set()
        assert duplicate_feedback_expense_ids(db, tenant_id="owner", expenses=[source],
            actor_account_id=None) == set()
        from app.services.learning_service._source_eligibility import feedback_impact_preview
        assert feedback_impact_preview(db, tenant_id="owner")["needs_review"] == 1
        assert source.amount_cents == 1000 and source.status == "confirmed"



def test_legacy_rows_with_null_signal_hash_no_longer_counted(
    *, identity,
) -> None:
    """Document the post-migration contract: the OR(indexed, LIKE)
    fallback was removed in favour of a backfill migration. Rows
    written before signal_hash existed AND not yet backfilled will
    not feed the feedback loop. Production rollout depends on
    ``c5b9a324c535`` running before this code path executes — the
    backfill makes the fallback unnecessary."""

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
            actor_account_id=seeded_owner_account_id(),
        )
        # Pre-backfill legacy rows are NOT picked up anymore; the
        # suggestion fires normally.
        assert result is not None
        assert result.category == "餐饮"


@pytest.mark.real_db
def test_backfilled_marker_without_source_context_stays_reviewable(
    *, identity,
) -> None:
    """After the backfill migration runs, rows that used to live with
    NULL signal_hash get populated and the feedback loop works
    through the index. We simulate that by populating signal_*
    columns explicitly (matches what the migration does)."""

    for _ in range(4):
        _seed_confirmed("餐饮", merchant="backfilled_path")

    marker = build_feedback_marker(
        CATEGORY_SUGGESTION.decision_type, {"category": "餐饮"}
    )
    expected_hash = canonical_marker_hash(marker)

    with SessionLocal() as db:
        for _ in range(2):
            backfilled = LedgerLearningEvent(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=1,
                before_payload='{"category": "餐饮"}',
                # These three are what the migration writes.
                signal_type=CATEGORY_SUGGESTION.decision_type,
                signal_hash=expected_hash,
                signal_payload='{"category": "餐饮"}',
            )
            db.add(backfilled)
        db.commit()

        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="backfilled_path",
            reject_threshold=2,
            actor_account_id=seeded_owner_account_id(),
        )
        assert result is not None  # A marker backfill cannot invent source or actor evidence.
