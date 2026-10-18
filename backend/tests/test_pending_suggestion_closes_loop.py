"""Actual suggestion feedback, publication and retention share the same consumer path."""
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from api_contract_helpers import confirm_expense_api, patch_expense
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services.learning_service import CATEGORY_SUGGESTION, DecisionDraft, record_decision


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


def _suggestion(client, identity, expense_id):
    for _ in range(3):
        saved = client.post("/api/expenses/manual", headers=identity.app_headers, json={"client_ref": str(uuid4()),
            "amount_cents": 1000, "home_currency_code": "CNY", "merchant": "Cafe", "category": "餐饮"})
        assert saved.status_code == 200, saved.text
    response = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    return response.json()["category_suggestion"]["decision_public_id"]


@pytest.mark.parametrize("verdict,status", [("accept", "accepted"), ("reject", "dismissed")])
def test_explicit_feedback_is_stable_and_does_not_write_financial_facts(client, identity, verdict, status):
    expense_id = _seed_pending_expense()
    decision_id = _suggestion(client, identity, expense_id)
    url = f"/api/expenses/{expense_id}/suggestions/{decision_id}/{verdict}"
    for _ in range(2):
        response = client.post(url, headers=identity.app_headers)
        assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).category == "其他"
        decision = db.query(AlgorithmDecision).filter_by(public_id=decision_id).one()
        assert decision.status == status
        assert decision.retention_days == CATEGORY_SUGGESTION.retention_for_status(status)
        event = db.query(LedgerLearningEvent).filter_by(decision_id=decision.id).one()
        assert event.event_type == verdict and event.actor_account_id is not None
        assert event.signal_type == "category_suggestion" and event.signal_hash
        assert json.loads(event.signal_payload)["category"] == "餐饮"
    confirmed = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.text
    with SessionLocal() as db:
        decision = db.query(AlgorithmDecision).filter_by(public_id=decision_id).one()
        assert decision.status == status
        assert db.query(LedgerLearningEvent).filter_by(decision_id=decision.id).count() == 1


def test_adopt_suggestion_two_step(client, identity):
    expense_id = _seed_pending_expense()
    decision_id = _suggestion(client, identity, expense_id)
    changed = patch_expense(client, expense_id, headers=identity.app_headers, fields={"category": "餐饮"})
    assert changed.status_code == 200, changed.text
    response = client.post(f"/api/expenses/{expense_id}/suggestions/{decision_id}/accept", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).category == "餐饮"
        decision = db.query(AlgorithmDecision).filter_by(public_id=decision_id).one()
        events = db.query(LedgerLearningEvent).filter_by(decision_id=decision.id, event_type="accept").all()
        assert len(events) == 1
        assert json.loads(events[0].after_payload)["_source_context"]["category"] == "餐饮"


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
    _suggestion(client, identity, expense_id)
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

    response = confirm_expense_api(client, expense_id, headers=identity.app_headers)
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
