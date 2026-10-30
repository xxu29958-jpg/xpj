"""A verified original correction may help the next source, never train on itself."""
import json
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import LedgerLearningEvent
from app.services.learning_service._withdrawal import withdraw_feedback
from tests._runtime_protocol import negotiated_headers
from tests.test_recognition_field_choice import _choice, _seed


def _save(client, headers, expense_id, candidate, value, intent):
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    payload = {"expected_row_version": current["row_version"],
        "recognition_field_choices": [{**_choice(candidate), "intent": intent}]}
    if candidate["field"] == "merchant":
        payload["merchant"] = value
    else:
        payload.update(original_currency_code="CNY", original_amount_minor=value)
    response = client.patch(f"/api/expenses/{expense_id}", json=payload,
        headers={**headers, "Idempotency-Key": str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("field,original,corrected", [
    ("amount_cents", 1800, 180), ("merchant", "海棠咖吽", "海棠咖啡"),
])
@pytest.mark.parametrize("review", ["adopt", "verify_correction", "verify_unchanged"])
def test_original_correction_keeps_source_reading_separate_from_recall(client, identity, field, original, corrected, review):
    headers = negotiated_headers(client, identity.app_headers)
    source = _seed(merchant="海棠咖吽")
    before = client.get(f"/api/expenses/{source}", headers=headers).json()
    chosen = next(c for c in before["recognition_fields"] if c["field"] == field and c["value"] == original)
    assert chosen["source_reading_value"] == original
    _save(client, headers, source, chosen, corrected, "original_correction")

    target = _seed(merchant="海棠咖吽")
    proposed = client.get(f"/api/expenses/{target}", headers=headers).json()
    corrections = [c for c in proposed["recognition_fields"] if c["field"] == field and c["value"] == corrected]
    assert len(corrections) == 1, "Explicit source correction never reaches the next similar original"
    correction = corrections[0]
    assert correction["source_reading_value"] == original
    assert correction["selection_intent"] == "bookkeeping", "Accepting a learned value is not a new source annotation"
    assert "纠正" in correction["explanation"] and correction["original_text"] == chosen["original_text"]
    assert proposed["amount_cents"] == 1800 and proposed["merchant"] == "海棠咖吽"

    # A different literal amount must not inherit a divide-by-ten rule; a
    # different source name must not inherit an unconditional merchant alias.
    other = _seed(merchant="海棠咖吽" if field == "amount_cents" else "另一家店", paid=1900)
    unrelated = client.get(f"/api/expenses/{other}", headers=headers).json()
    assert not any(c["field"] == field and c["value"] == corrected for c in unrelated["recognition_fields"])

    final = original if review == "verify_unchanged" else corrected
    intent = correction["selection_intent"] if review == "adopt" else "original_correction"
    _save(client, headers, target, correction, final, intent)
    with SessionLocal() as db:
        origin = db.query(LedgerLearningEvent).filter_by(subject_id=source, signal_type="recognition_field_choice").one()
        accepted = db.query(LedgerLearningEvent).filter_by(subject_id=target, signal_type="recognition_field_choice").one()
        original_payload, accepted_payload = json.loads(origin.after_payload), json.loads(accepted.after_payload)
        assert original_payload["_learning_qualified"] is True
        assert "source_reading_value" not in original_payload["selected"], "Wire diagnostics must not change stored feedback"
        assert accepted_payload["selected"]["value"] == original
        assert accepted_payload["_learning_qualified"] is (review == "verify_correction")
        withdraw_feedback(db, tenant_id="owner", public_id=origin.public_id)
        if review == "verify_correction":
            # This second explicit verification is independent feedback; revoke
            # it too before asserting that no qualified correction remains.
            withdraw_feedback(db, tenant_id="owner", public_id=accepted.public_id)
        db.commit()
    fresh = _seed(merchant="海棠咖吽")
    after = client.get(f"/api/expenses/{fresh}", headers=headers).json()
    assert not any(c["field"] == field and c["value"] == corrected for c in after["recognition_fields"])
    assert after["amount_cents"] == 1800 and after["merchant"] == "海棠咖吽"
