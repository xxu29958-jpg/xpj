"""v1.2 P1 — duplicate candidate scoring contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import Expense
from app.services.learning_service import (
    EventDraft,
    OcrFactDraft,
    record_event,
    record_ocr_fact,
    score_duplicate_candidates,
)
from tests._infra.identity import seeded_owner_account_id


def _make_expense(
    *,
    tenant_id: str = "owner",
    amount_cents: int | None = 1000,
    merchant: str | None = "Cafe",
    image_hash: str | None = None,
    expense_time: datetime | None = None,
    status: str = "confirmed",
    currency: str = "CNY",
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
            home_currency_code=currency,
            original_currency_code=currency,
            original_amount_minor=amount_cents,
            expense_time=base_time,
            confirmed_at=base_time if status == "confirmed" else None,
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        return expense


@pytest.mark.parametrize("conflict", ["amount", "currency", "time", "transaction_id"])
def test_visual_recall_cannot_override_transaction_conflicts(conflict, *, identity):
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    a = _make_expense(image_hash="same-image", expense_time=base)
    b = _make_expense(image_hash="same-image", amount_cents=2000 if conflict == "amount" else 1000,
        currency="JPY" if conflict == "currency" else "CNY",
        expense_time=base + timedelta(days=2) if conflict == "time" else base)
    with SessionLocal() as db:
        if conflict == "transaction_id":
            for row, identifier in ((a, "202605010001"), (b, "202605010002")):
                stored = db.get(Expense, row.id)
                stored.source = "alipay"
                stored.merchant = f"OCR merchant {row.id}"
                record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=row.id,
                    ocr_provider="manual_text", raw_text=f"交易号：{identifier}"))
            db.flush()
        scores = score_duplicate_candidates(db, tenant_id="owner", expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, b.id)], actor_account_id=seeded_owner_account_id())
        assert scores == []


def test_confirmation_clock_does_not_supply_transaction_time(*, identity):
    a, b = _make_expense(), _make_expense()
    with SessionLocal() as db:
        current, candidate = db.get(Expense, a.id), db.get(Expense, b.id)
        current.expense_time = candidate.expense_time = None
        scores = score_duplicate_candidates(db, tenant_id="owner", expense=current,
            candidates=[candidate], actor_account_id=seeded_owner_account_id())
        assert scores == []


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
            actor_account_id=seeded_owner_account_id(),
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
            actor_account_id=seeded_owner_account_id(),
        )
        # amount + merchant + time_within_24h = 0.30 + 0.15 + 0.05
        assert scores[0].score == pytest.approx(0.50)
        assert "time_within_24h" in scores[0].reasons


def test_unrelated_reject_does_not_suppress_current_transaction_evidence(*, identity) -> None:
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
                actor_account_id=seeded_owner_account_id(),
            ),
        )
        db.commit()
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, b.id)],
            actor_account_id=seeded_owner_account_id(),
        )
        assert scores[0].score == pytest.approx(0.60)
        assert "recent_user_reject" not in scores[0].reasons


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
            actor_account_id=seeded_owner_account_id(),
        )
        ordered_ids = [s.candidate_id for s in scores]
        assert ordered_ids == [high.id, medium.id]
        # Each strictly greater than the next.
        assert scores[0].score > scores[1].score


def test_self_candidate_excluded(*, identity) -> None:
    a = _make_expense(amount_cents=1000, merchant="Cafe")
    with SessionLocal() as db:
        scores = score_duplicate_candidates(
            db,
            tenant_id="owner",
            expense=db.get(Expense, a.id),
            candidates=[db.get(Expense, a.id)],
            actor_account_id=seeded_owner_account_id(),
        )
        assert scores == []
