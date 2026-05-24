"""v1.2 P1 — category self-learning suggestion contract.

The suggestion service only reads confirmed expenses and recent
learning events; it never mutates the ledger. Tests cover:

* Suggestion happens when the user has a confirmed history for the
  merchant.
* Suggestion is suppressed when sample size is below threshold.
* Suggestion is suppressed when the user has recently rejected this
  exact (merchant, category) pair — closing the feedback loop.
* Tenant isolation: another tenant's history must not bleed in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.models import Expense
from app.services.learning_service import (
    EventDraft,
    compute_category_suggestion,
    record_event,
)


def _make_confirmed(
    tenant_id: str,
    merchant: str,
    category: str,
    *,
    amount_cents: int = 1000,
    days_ago: int = 1,
) -> int:
    confirmed_at = datetime.now(UTC) - timedelta(days=days_ago)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            amount_cents=amount_cents,
            merchant=merchant,
            category=category,
            source="pytest",
            raw_text="",
            status="confirmed",
            confirmed_at=confirmed_at,
            expense_time=confirmed_at,
        )
        db.add(expense)
        db.commit()
        return expense.id


def test_suggests_majority_category_for_merchant(*, identity) -> None:
    for _ in range(3):
        _make_confirmed("owner", "麦当劳", "餐饮")
    _make_confirmed("owner", "麦当劳", "购物")

    with SessionLocal() as db:
        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="麦当劳",
        )
        assert result is not None
        assert result.category == "餐饮"
        assert result.sample_size == 4
        assert result.score == 0.75
        assert result.algorithm_version == "category-history-v1"


def test_no_suggestion_when_under_sample_threshold(*, identity) -> None:
    _make_confirmed("owner", "Newshop", "购物")

    with SessionLocal() as db:
        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="Newshop",
        )
        assert result is None


def test_no_suggestion_when_merchant_empty(*, identity) -> None:
    with SessionLocal() as db:
        assert (
            compute_category_suggestion(
                db, tenant_id="owner", merchant=None
            )
            is None
        )
        assert (
            compute_category_suggestion(db, tenant_id="owner", merchant="   ")
            is None
        )


def test_suppressed_when_recently_rejected(*, identity) -> None:
    expense_ids = []
    for _ in range(3):
        expense_ids.append(_make_confirmed("owner", "Costa", "餐饮"))

    # The user explicitly rejected the "餐饮" suggestion for this
    # merchant twice in the recent past. Suppress further suggestions
    # for the same (merchant, category) pair.
    with SessionLocal() as db:
        for expense_id in expense_ids[:2]:
            record_event(
                db,
                EventDraft(
                    tenant_id="owner",
                    event_type="reject",
                    subject_kind="expense",
                    subject_id=expense_id,
                    before_payload={"category": "餐饮"},
                    after_payload={"category": "购物"},
                    signal_type="category_suggestion",
                    signal_marker={"category": "餐饮"},
                ),
            )
        db.commit()

        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="Costa",
        )
        assert result is None


def test_reject_suppression_is_merchant_scoped(*, identity) -> None:
    costa_ids = [
        _make_confirmed("owner", "Costa", "餐饮") for _ in range(3)
    ]
    for _ in range(3):
        _make_confirmed("owner", "Other Cafe", "餐饮")

    with SessionLocal() as db:
        for expense_id in costa_ids[:2]:
            record_event(
                db,
                EventDraft(
                    tenant_id="owner",
                    event_type="reject",
                    subject_kind="expense",
                    subject_id=expense_id,
                    before_payload={"category": "餐饮"},
                    after_payload={"category": "购物"},
                    signal_type="category_suggestion",
                    signal_marker={"category": "餐饮"},
                ),
            )
        db.commit()

        costa = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="Costa",
        )
        other = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="Other Cafe",
        )

    assert costa is None
    assert other is not None
    assert other.category == "餐饮"


def test_tenant_isolation(*, identity) -> None:
    for _ in range(4):
        _make_confirmed("owner", "瑞幸", "餐饮")

    with SessionLocal() as db:
        owner_view = compute_category_suggestion(
            db, tenant_id="owner", merchant="瑞幸"
        )
        tester_view = compute_category_suggestion(
            db, tenant_id="tester_1", merchant="瑞幸"
        )
        assert owner_view is not None
        assert owner_view.category == "餐饮"
        assert tester_view is None


def test_exclude_self_when_expense_id_provided(*, identity) -> None:
    # Two confirmed at "麦当劳 → 餐饮"; one of them is the row we're
    # currently asking about. Excluding it leaves only 1 sample which
    # is below the default min_samples threshold (3).
    for _ in range(2):
        _make_confirmed("owner", "麦当劳", "餐饮")
    # Plus one extra that the in-flight expense represents.
    self_id = _make_confirmed("owner", "麦当劳", "餐饮")
    with SessionLocal() as db:
        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="麦当劳",
            expense_id=self_id,
            min_samples=3,
        )
        # Two qualifying rows after exclusion → still below 3 → None.
        assert result is None
        # If we lower the threshold to 2, the suggestion should
        # re-appear.
        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="麦当劳",
            expense_id=self_id,
            min_samples=2,
        )
        assert result is not None
        assert result.sample_size == 2


def test_look_back_window_filters_old_rows(*, identity) -> None:
    # 4 confirmed rows but all more than 1000 days ago. With the
    # default 180-day window they're invisible.
    for _ in range(4):
        _make_confirmed("owner", "OldShop", "购物", days_ago=400)
    with SessionLocal() as db:
        assert (
            compute_category_suggestion(
                db, tenant_id="owner", merchant="OldShop"
            )
            is None
        )
        # Widening the window restores the suggestion.
        result = compute_category_suggestion(
            db,
            tenant_id="owner",
            merchant="OldShop",
            look_back_days=1000,
        )
        assert result is not None
        assert result.category == "购物"
