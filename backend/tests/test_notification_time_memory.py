"""A chosen notification time helps an independent source without losing either origin."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent, PaymentCapture
from app.services.expense_service._ocr_facts import append_ocr_fact
from app.services.learning_service._withdrawal import withdraw_feedback
from app.services.ocr_service import OcrResult
from tests.test_recognition_choice import _choose


def _capture(client, identity, day, *, image=False, truncated=False):
    fragments = [{"field": "text", "label": label, "literal": f"2026-10-{day:02d} {clock}"}
        for label, clock in (("支付时间", "12:30"), ("消费时间", "12:20"))]
    response = client.post("/api/payment-captures", headers=identity.app_headers, json={
        "notification_key": str(uuid4()), "source": "alipay", "captured_at": "2026-10-23T04:00:00Z",
        "original_currency": "CNY", "original_amount_minor": 2500, "merchant": "便利店", "suggested_kind": "expense",
        "parser_version": "transaction-evidence-v4", "candidates": [],
        "time_evidence": {"source_timezone": "Asia/Shanghai", "fragments": fragments, "truncated": truncated}})
    assert response.status_code == 201, response.text
    created = response.json()
    if image:
        with SessionLocal() as db:
            expense = db.get(Expense, created["expense_id"])
            expense.image_hash = str(uuid4())
            append_ocr_fact(db, expense=expense, provider_name="mock", timezone_name="Asia/Shanghai",
                result=OcrResult(raw_text="\n".join(f"{item['label']}：{item['literal']}" for item in fragments), confidence=0.9))
            db.commit()
    return created


@pytest.mark.parametrize("stop", ["withdraw", "capture_revision"])
def test_notification_time_choice_learns_then_retires_on_original_invalidation(client, identity, stop):
    first, later = _capture(client, identity, 18), _capture(client, identity, 19)
    response, url, headers, body, chosen = _choose(client, identity, first["expense_id"])
    assert response.status_code == 200, response.text
    assert client.patch(url, headers=headers, json=body).json() == response.json()
    target_url = f"/api/expenses/{later['expense_id']}"
    suggested = client.get(target_url, headers=identity.app_headers).json()
    top = suggested["recognition_time"]["candidates"][0]
    assert top["role"] == chosen["role"] and "你曾" in top["explanation"]
    assert suggested["expense_time"] is None and suggested["amount_cents"] == 2500
    with SessionLocal() as db:
        event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == first["expense_id"],
            LedgerLearningEvent.signal_type == "recognition_time_choice"))
        assert json.loads(event.after_payload)["_capture_context"]["public_id"] == first["public_id"]
        if stop == "withdraw":
            withdraw_feedback(db, tenant_id="owner", public_id=event.public_id)
        else:
            capture = db.scalar(select(PaymentCapture).where(PaymentCapture.public_id == first["public_id"]))
            capture.row_version += 1
        db.commit()
    after = client.get(target_url, headers=identity.app_headers).json()
    assert "你曾" not in after["recognition_time"]["candidates"][0]["explanation"]
    with SessionLocal() as db:
        assert not list(db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.subject_id == later["expense_id"],
            AlgorithmDecision.decision_type == "recognition_time_choice", AlgorithmDecision.status == "active")))


def test_time_ranking_keeps_image_and_notification_even_with_identical_candidate_ids(client, identity):
    first, target = _capture(client, identity, 18, image=True), _capture(client, identity, 19, image=True)
    response, *_ = _choose(client, identity, first["expense_id"], index=1)
    assert response.status_code == 200, response.text
    before = client.get(f"/api/expenses/{target['expense_id']}", headers=identity.app_headers).json()["recognition_time"]
    candidates = before["candidates"]
    assert len(candidates) == 4 and {c["source"] for c in candidates} == {"image", "notification"}
    assert len({c["id"] for c in candidates}) == 2
    assert len({(c["id"], c["evidence_public_id"], c["source"]) for c in candidates}) == 4


@pytest.mark.parametrize("legacy_qualified", [False, True])
def test_truncated_time_can_be_saved_but_cannot_teach_another_notification(client, identity, legacy_qualified):
    from app.services.learning_service._source_eligibility import feedback_assessments

    first = _capture(client, identity, 18, truncated=True)
    response, *_ = _choose(client, identity, first['expense_id'])
    assert response.status_code == 200 and response.json()['expense_time'] is not None
    with SessionLocal() as db:
        event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == first['expense_id'],
            LedgerLearningEvent.signal_type == 'recognition_time_choice'))
        payload = json.loads(event.after_payload)
        if legacy_qualified:
            # Existing bad qualification is retired from immutable source evidence too.
            payload['_learning_qualified'] = True
            event.after_payload = json.dumps(payload)
            event.event_type = 'accept'
            db.commit()
        else:
            assert payload['_learning_qualified'] is False
        assert feedback_assessments(db, tenant_id='owner', events=[event])[event.id][0] != 'valid'
    later = _capture(client, identity, 19, truncated=True)
    current = client.get(f"/api/expenses/{later['expense_id']}", headers=identity.app_headers).json()
    assert all('你曾' not in c['explanation'] for c in current['recognition_time']['candidates'])
    assert current['expense_time'] is None
