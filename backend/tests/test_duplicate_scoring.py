"""v1.2 P1 — duplicate candidate scoring contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import Expense
from app.services.learning_service import (
    EventDraft,
    record_event,
    score_duplicate_candidates,
)


def _make_expense(
    *,
    tenant_id: str = "owner",
    amount_cents: int | None = 1000,
    merchant: str | None = "Cafe",
    image_hash: str | None = None,
    expense_time: datetime | None = None,
    status: str = "confirmed",
) -> Expense:
    base_time = expense_time or datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            amount_cents=amount_cents,
            merchant=merchant,
            category="餐饮",
            image_hash=image_hash,
            source="pytest",
            raw_text="",
            status=status,
            expense_time=base_time,
            confirmed_at=base_time if status == "confirmed" else None,
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        return expense


def test_image_hash_match_dominates_score(*, identity) -> None:
    a = _make_expense(image_hash="aabb", amount_cents=999, merchant="X")
    b = _make_expense(image_hash="aabb", amount_cents=1234, merchant="Y")
    with SessionLocal() as db:
        candidates = [db.get(Expense, b.id)]
        scores = score_duplicate_candidates(
            db, tenant_id="owner", expense=db.get(Expense, a.id),
            candidates=candidates,
        )
        assert len(scores) == 1
        # Image hash alone = 0.50; no amount, no merchant, no time
        # overlap (same default base_time gives time_within_1h = +0.15).
        assert scores[0].score == pytest.approx(0.65)
        assert "image_hash_match" in scores[0].reasons
        assert "time_within_1h" in scores[0].reasons


def test_amount_plus_merchant_plus_time_stacks(*, identity) -> None:
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    a = _make_expense(
        amount_cents=1500, merchant="Starbucks", expense_time=base
    )
    b = _make_expense(
        amount_cents=1500,
        merchant="STARBUCKS",
        expense_time=base + timedelta(minutes=30),
    )
    with SessionLocal() as db:
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, b.id)],
        )
        assert len(scores) == 1
        # 0.30 amount + 0.15 merchant + 0.15 time_within_1h = 0.60
        assert scores[0].score == pytest.approx(0.60)
        assert "amount_match" in scores[0].reasons
        assert "merchant_match" in scores[0].reasons
        assert "time_within_1h" in scores[0].reasons


def test_far_time_only_gets_24h_bucket(*, identity) -> None:
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    a = _make_expense(amount_cents=2000, merchant="Cafe", expense_time=base)
    b = _make_expense(
        amount_cents=2000,
        merchant="Cafe",
        expense_time=base + timedelta(hours=20),
    )
    with SessionLocal() as db:
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, b.id)],
        )
        # amount + merchant + time_within_24h = 0.30 + 0.15 + 0.05
        assert scores[0].score == pytest.approx(0.50)
        assert "time_within_24h" in scores[0].reasons


def test_recent_user_reject_applies_penalty(*, identity) -> None:
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    a = _make_expense(
        amount_cents=2000, merchant="Cafe", expense_time=base
    )
    b = _make_expense(
        amount_cents=2000, merchant="Cafe", expense_time=base
    )
    marker = {"amount_cents": 2000, "merchant": "cafe"}
    with SessionLocal() as db:
        record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=a.id,
                before_payload=marker,
                signal_type="duplicate_candidate",
                signal_marker=marker,
            ),
        )
        db.commit()
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, b.id)],
        )
        # Without penalty: amount + merchant + time_within_1h = 0.60.
        # Penalty: -0.40 → 0.20.
        assert scores[0].score == pytest.approx(0.20)
        assert "recent_user_reject" in scores[0].reasons


def test_candidates_ranked_descending(*, identity) -> None:
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    a = _make_expense(
        amount_cents=1000, merchant="Cafe", expense_time=base, image_hash="aa"
    )
    high = _make_expense(
        amount_cents=1000,
        merchant="Cafe",
        expense_time=base,
        image_hash="aa",
    )
    medium = _make_expense(
        amount_cents=1000, merchant="Cafe", expense_time=base
    )
    low = _make_expense(
        amount_cents=999,
        merchant="OtherCafe",
        expense_time=base + timedelta(hours=20),
    )
    with SessionLocal() as db:
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[
                db.get(Expense, low.id),
                db.get(Expense, medium.id),
                db.get(Expense, high.id),
            ],
        )
        ordered_ids = [s.candidate_id for s in scores]
        assert ordered_ids == [high.id, medium.id, low.id]
        # Each strictly greater than the next.
        assert scores[0].score > scores[1].score > scores[2].score


def test_self_candidate_excluded(*, identity) -> None:
    a = _make_expense(amount_cents=1000, merchant="Cafe")
    with SessionLocal() as db:
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, a.id)],
        )
        assert scores == []


def test_score_clamped_to_unit_range(*, identity) -> None:
    # Concoct a pathological scenario where penalties exceed signal.
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    a = _make_expense(amount_cents=500, merchant="Other", expense_time=base)
    b = _make_expense(amount_cents=999, merchant="Mismatch", expense_time=base)
    marker = {"amount_cents": 500, "merchant": "other"}
    with SessionLocal() as db:
        record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="reject",
                subject_kind="expense",
                subject_id=a.id,
                before_payload=marker,
                signal_type="duplicate_candidate",
                signal_marker=marker,
            ),
        )
        db.commit()
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, b.id)],
        )
        # Penalty alone with no positive buckets → would be negative,
        # clamped to 0.
        assert scores[0].score == pytest.approx(0.0)
