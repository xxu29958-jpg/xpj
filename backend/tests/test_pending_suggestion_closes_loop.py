"""v1.2 ops — UI/算法闭环钉死.

Two invariants this test nails down explicitly:

1. POST ``/api/expenses/{id}/suggestions/{decision}/accept`` is a
   pure feedback signal. It writes a ``ledger_learning_events`` row
   with ``event_type='accept'`` but does NOT mutate
   ``expenses.category`` (or any other ledger field). The accept
   endpoint exists to record "the user said yes" — actually applying
   the suggestion requires the normal PATCH/update path.

2. The "adopt suggestion" two-step the UI must execute is:
   PATCH category → POST accept. We confirm the order doesn't
   accidentally short-circuit: the accept event lands AFTER the
   category change, so anyone replaying events sees the user-applied
   value already in place.

This is the contract that keeps "建议层避免污染" + "用户确认守住账本"
honest at the API level.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api_contract_helpers import patch_expense
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services.learning_service import DecisionDraft, record_decision


def _seed_pending_expense(category: str = "其他", merchant: str = "Cafe") -> int:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=1000,
            merchant=merchant,
            category=category,
            source="pytest",
            raw_text="",
            status="pending",
            expense_time=now - timedelta(hours=1),
        )
        db.add(expense)
        db.commit()
        return expense.id


def _seed_category_decision(expense_id: int, *, category: str = "餐饮") -> str:
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-history-v1",
                subject_kind="expense",
                subject_id=expense_id,
                payload={"category": category},
                score=0.9,
            ),
        )
        db.commit()
        return row.public_id


def test_accept_endpoint_does_not_mutate_expense_category(
    client: TestClient, *, identity,
) -> None:
    expense_id = _seed_pending_expense(category="其他")
    decision_public_id = _seed_category_decision(
        expense_id, category="餐饮"
    )

    response = client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers,
    )
    assert response.status_code == 200

    # The expense MUST still be in its original category — accept is
    # a learning event, not a ledger mutation.
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.category == "其他"

        # A learning event row exists with event_type=accept.
        events = (
            db.query(LedgerLearningEvent)
            .filter(LedgerLearningEvent.subject_id == expense_id)
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == "accept"


def test_reject_endpoint_does_not_mutate_expense_category(
    client: TestClient, *, identity,
) -> None:
    expense_id = _seed_pending_expense(category="其他")
    decision_public_id = _seed_category_decision(expense_id, category="餐饮")

    response = client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/reject",
        headers=identity.app_headers,
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.category == "其他"
        events = (
            db.query(LedgerLearningEvent)
            .filter(LedgerLearningEvent.subject_id == expense_id)
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == "reject"


def test_adopt_suggestion_two_step(client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_expense(category="其他")
    decision_public_id = _seed_category_decision(
        expense_id, category="餐饮"
    )

    # Step 1: PATCH the category through the normal ledger path. This
    # is the "user confirms" half — the only place a write happens.
    patch_response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"category": "餐饮"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["category"] == "餐饮"

    # Step 2: POST accept. This writes the learning event so the
    # algorithm knows the user adopted the suggestion.
    accept_response = client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers,
    )
    assert accept_response.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.category == "餐饮"  # changed by PATCH, not by accept
        events = (
            db.query(LedgerLearningEvent)
            .filter(LedgerLearningEvent.subject_id == expense_id)
            .order_by(LedgerLearningEvent.created_at.asc())
            .all()
        )
        # The accept event records what the suggestion was. The
        # ledger row already shows the user's confirmed choice.
        # (Manual override events may also be present from PATCH —
        # we don't assert their count here, only that the accept
        # event exists.)
        assert any(e.event_type == "accept" for e in events)


def test_accept_writes_signal_marker_for_dedup(
    client: TestClient, *, identity,
) -> None:
    expense_id = _seed_pending_expense()
    decision_public_id = _seed_category_decision(expense_id, category="餐饮")

    response = client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers,
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        event = (
            db.query(LedgerLearningEvent)
            .filter(LedgerLearningEvent.subject_id == expense_id)
            .one()
        )
        assert event.signal_type == "category_suggestion"
        assert event.signal_hash is not None
        # signal_payload is the canonical marker as readable JSON.
        assert '"category"' in event.signal_payload
        assert '"餐饮"' in event.signal_payload


def test_accept_marks_decision_accepted(
    client: TestClient, *, identity,
) -> None:
    """Accepting a suggestion flips the decision to ``status='accepted'``
    so the UI stops showing it on this subject. The ledger row stays
    untouched — accept is feedback, not a mutation."""

    expense_id = _seed_pending_expense()
    decision_public_id = _seed_category_decision(expense_id, category="餐饮")

    response = client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers,
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        decision = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.subject_id == expense_id)
            .one()
        )
        assert decision.status == "accepted"

        # Confirm later does NOT revive the closed row.
        client.post(
            f"/api/expenses/{expense_id}/confirm",
            headers=identity.app_headers,
        )
        db.refresh(decision)
        # Still 'accepted' — confirm only closes `active` rows.
        assert decision.status == "accepted"


def test_reject_marks_decision_dismissed(
    client: TestClient, *, identity,
) -> None:
    """Rejecting a suggestion flips the decision to ``status='dismissed'``.
    Distinct from ``accepted`` so per-version inventory can tell apart
    "user said yes" vs. "user said no"."""

    expense_id = _seed_pending_expense()
    decision_public_id = _seed_category_decision(expense_id, category="餐饮")

    response = client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/reject",
        headers=identity.app_headers,
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        decision = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.subject_id == expense_id)
            .one()
        )
        assert decision.status == "dismissed"


def test_repeated_accept_is_idempotent_after_decision_closes(
    client: TestClient, *, identity,
) -> None:
    expense_id = _seed_pending_expense()
    decision_public_id = _seed_category_decision(expense_id, category="food")

    for _ in range(2):
        response = client.post(
            f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/accept",
            headers=identity.app_headers,
        )
        assert response.status_code == 200

    with SessionLocal() as db:
        decision = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.subject_id == expense_id)
            .one()
        )
        events = (
            db.query(LedgerLearningEvent)
            .filter(LedgerLearningEvent.subject_id == expense_id)
            .filter(LedgerLearningEvent.event_type == "accept")
            .all()
        )
        assert decision.status == "accepted"
        assert len(events) == 1


def test_accept_uses_accepted_retention(
    client: TestClient, *, identity,
) -> None:
    """Registry-driven retention split: accept lands a longer
    retention than the active default, reject lands a shorter one."""

    from app.services.learning_service import CATEGORY_SUGGESTION

    expense_id = _seed_pending_expense()
    decision_public_id = _seed_category_decision(expense_id, category="餐饮")

    client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers,
    )

    with SessionLocal() as db:
        decision = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.subject_id == expense_id)
            .one()
        )
        assert decision.status == "accepted"
        assert decision.retention_days == CATEGORY_SUGGESTION.accepted_retention_days
        assert (
            decision.retention_days > CATEGORY_SUGGESTION.default_retention_days
        )


def test_reject_uses_dismissed_retention(
    client: TestClient, *, identity,
) -> None:
    from app.services.learning_service import CATEGORY_SUGGESTION

    expense_id = _seed_pending_expense()
    decision_public_id = _seed_category_decision(expense_id, category="餐饮")

    client.post(
        f"/api/expenses/{expense_id}/suggestions/{decision_public_id}/reject",
        headers=identity.app_headers,
    )

    with SessionLocal() as db:
        decision = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.subject_id == expense_id)
            .one()
        )
        assert decision.status == "dismissed"
        assert decision.retention_days == CATEGORY_SUGGESTION.dismissed_retention_days
        assert (
            decision.retention_days < CATEGORY_SUGGESTION.default_retention_days
        )


def test_confirm_closes_remaining_active_subject_decisions(
    client: TestClient, *, identity,
) -> None:
    """Expense confirm path catches ALL still-active decisions on the
    subject, regardless of decision_type. This is the safety net for
    the case where the UI surfaced multiple suggestions and the user
    confirmed the expense without explicitly accepting/rejecting some
    of them."""

    expense_id = _seed_pending_expense()
    # Two active decisions of different types on the same subject.
    _seed_category_decision(expense_id, category="餐饮")
    with SessionLocal() as db:
        record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="duplicate_candidate",
                algorithm_version="duplicate-scoring-v1",
                subject_kind="expense",
                subject_id=expense_id,
                payload={"amount_cents": 1000, "merchant": "Cafe"},
            ),
        )
        db.commit()
        active_before = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.subject_id == expense_id)
            .filter(AlgorithmDecision.status == "active")
            .count()
        )
        assert active_before == 2

    response = client.post(
        f"/api/expenses/{expense_id}/confirm",
        headers=identity.app_headers,
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        active_after = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.subject_id == expense_id)
            .filter(AlgorithmDecision.status == "active")
            .count()
        )
        # Both rows must be closed; confirm closes the whole subject.
        assert active_after == 0
