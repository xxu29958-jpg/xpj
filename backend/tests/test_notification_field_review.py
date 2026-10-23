"""Original notification fragments follow real capture, save, replay and withdrawal."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AlgorithmDecision, LedgerLearningEvent, PaymentCapture
from app.services.learning_service._withdrawal import withdraw_feedback
from tests._infra.identity import seeded_owner_account_id
from tests._runtime_protocol import negotiated_headers


def _capture(client, headers, *, evidence=True, truncated=False):
    payload = {"notification_key": str(uuid4()), "source": "alipay", "captured_at": "2026-10-20T04:30:00Z",
        "original_currency": "CNY", "original_amount_minor": 1800, "merchant": "海棠咖吽", "suggested_kind": "expense",
        "parser_version": "transaction-evidence-v4", "candidates": []}
    if evidence:
        payload["field_evidence"] = {"fragments": [
            {"field": "text", "literal": "商户：海棠咖吽"}, {"field": "text", "literal": "支付金额：18.00元"}],
            "truncated": truncated}
    response = client.post("/api/payment-captures", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


def _save(client, headers, expense, choice, value, intent):
    current = client.get(f"/api/expenses/{expense}", headers=headers).json()
    proof = {key: choice[key] for key in ("field", "source", "evidence_public_id", "parser_version")}
    proof.update(candidate_id=choice["id"], intent=intent)
    payload = {"expected_row_version": current["row_version"], "recognition_field_choices": [proof]}
    payload.update({"merchant": value} if choice["field"] == "merchant" else
        {"original_currency_code": "CNY", "original_amount_minor": value})
    command = {**headers, "Idempotency-Key": str(uuid4())}
    saved = client.patch(f"/api/expenses/{expense}", headers=command, json=payload)
    assert saved.status_code == 200, saved.text
    assert client.patch(f"/api/expenses/{expense}", headers=command, json=payload).json() == saved.json()


@pytest.mark.parametrize("field,corrected,stop", [("amount_cents", 180, "withdraw"), ("merchant", "海棠咖啡", "capture_revision")])
def test_notification_source_correction_reaches_consumer_without_self_training(client, identity, field, corrected, stop):
    headers = negotiated_headers(client, identity.app_headers)
    original, payload = _capture(client, headers)
    source_id = original["expense_id"]
    current = client.get(f"/api/expenses/{source_id}", headers=headers).json()
    chosen = next(c for c in current["recognition_fields"] if c["field"] == field)
    assert chosen["source"] == "notification" and chosen["evidence_public_id"] == original["public_id"]
    assert "通知" in chosen["label"] and current["raw_text"] is None
    # Redelivery cannot replace the original fragments, even with a different amount.
    payload["field_evidence"]["fragments"][-1]["literal"] = "支付金额：999元"
    assert client.post("/api/payment-captures", headers=headers, json=payload).json() == original
    assert client.get(f"/api/expenses/{source_id}", headers=headers).json()["recognition_fields"] == current["recognition_fields"]
    _save(client, headers, source_id, chosen, corrected, "original_correction")
    target, _ = _capture(client, headers)
    target_id = target["expense_id"]
    suggested = client.get(f"/api/expenses/{target_id}", headers=headers).json()
    correction = next(c for c in suggested["recognition_fields"] if c["field"] == field and c["value"] == corrected)
    assert correction["selection_intent"] == "bookkeeping"
    assert suggested["amount_cents"] == 1800 and suggested["merchant"] == "海棠咖吽"
    _save(client, headers, target_id, correction, corrected, correction["selection_intent"])
    remaining, _ = _capture(client, headers)
    url = f"/api/expenses/{remaining['expense_id']}"
    assert any(c["value"] == corrected for c in client.get(url, headers=headers).json()["recognition_fields"])
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(
            LedgerLearningEvent.signal_type == "recognition_field_choice").order_by(LedgerLearningEvent.id)))
        assert len(events) == 2
        assert json.loads(events[0].after_payload)["_learning_qualified"] is True
        assert json.loads(events[1].after_payload)["_learning_qualified"] is False
        if stop == "withdraw":
            withdraw_feedback(db, tenant_id="owner", public_id=events[0].public_id)
        else:
            capture = db.scalar(select(PaymentCapture).where(PaymentCapture.public_id == original["public_id"]))
            capture.row_version += 1
        db.commit()
    after = client.get(url, headers=headers).json()
    assert not any(c["field"] == field and c["value"] == corrected for c in after["recognition_fields"])
    with SessionLocal() as db:
        assert not list(db.scalars(select(AlgorithmDecision).where(
            AlgorithmDecision.subject_id == remaining["expense_id"], AlgorithmDecision.decision_type == "recognition_field_choice",
            AlgorithmDecision.status == "active")))


def test_notification_fragments_are_personal_and_missing_evidence_stays_unknown(client, identity):
    from app.services.recognition_field_memory import load_field_memory

    headers = negotiated_headers(client, identity.app_headers)
    old, _ = _capture(client, headers, evidence=False)
    assert not client.get(f"/api/expenses/{old['expense_id']}", headers=headers).json()["recognition_fields"]
    current, _ = _capture(client, headers)
    with SessionLocal() as db:
        memory = load_field_memory(db, tenant_id="owner", actor_account_id=seeded_owner_account_id() + 100,
            expense_ids=[current["expense_id"]])
        assert memory.notification_sources == {}


@pytest.mark.parametrize("untrusted", ["another_capture", "truncated"])
def test_incomplete_or_mismatched_source_never_becomes_a_learning_label(client, identity, untrusted):
    headers = negotiated_headers(client, identity.app_headers)
    original, _ = _capture(client, headers, truncated=untrusted == "truncated")
    current = client.get(f"/api/expenses/{original['expense_id']}", headers=headers).json()
    chosen = next(c for c in current["recognition_fields"] if c["field"] == "amount_cents")
    if untrusted == "another_capture":
        other, _ = _capture(client, headers)
        chosen["evidence_public_id"] = other["public_id"]
    else:
        assert not chosen["can_apply"]
    _save(client, headers, original["expense_id"], chosen, 180, "original_correction")
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(
            LedgerLearningEvent.signal_type == "recognition_field_choice")))
        assert all(not json.loads(event.after_payload)["_learning_qualified"] for event in events)
    next_capture, _ = _capture(client, headers)
    projected = client.get(f"/api/expenses/{next_capture['expense_id']}", headers=headers).json()
    assert not any(c["field"] == "amount_cents" and c["value"] == 180 for c in projected["recognition_fields"])
