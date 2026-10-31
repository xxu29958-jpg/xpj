"""Abstained fields use source geometry/text, with auditable legacy and history limits."""
import json
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import LedgerLearningEvent
from app.services.recognition_field_service import recognition_fields, review_fields
from tests._runtime_protocol import negotiated_headers
from tests.test_recognition_choice import _choose, _image
from tests.test_recognition_field_choice import _choice, _seed
from tests.test_recognition_source import source_fact


@pytest.mark.parametrize("geometry", [True, False])
def test_abstained_source_order_overrides_score_and_retains_identity(geometry):
    fact = source_fact()
    evidence = json.loads(fact.evidence_json)
    for decision in evidence["field_parse"]["decisions"]:
        if decision["field"] == "amount_cents":
            decision.update(status="ambiguous", selected_id=None)
    if not geometry:
        evidence.pop("blocks")
    fact.evidence_json = json.dumps(evidence)
    readings = [item for item in review_fields(fact, recognition_fields(fact)) if item.field == "amount_cents"]
    ranked = sorted(readings, key=lambda item: item.role == "payment", reverse=True)
    result = review_fields(fact, ranked)
    assert [item.role for item in result] == ["original_price", "payment"]
    assert {item.id for item in result} == {item.id for item in readings}
    assert all(item.presentation == f"source-order-v1:{'image' if geometry else 'text'}" for item in result)
    assert all(item.evidence_public_id == fact.public_id for item in result)


@pytest.mark.parametrize("echo", [True, False, "stale-version"])
def test_choice_records_only_a_verified_client_echo(client, identity, echo):
    expense_id = _seed()
    headers = negotiated_headers(client, identity.app_headers)
    url = f"/api/expenses/{expense_id}"
    before = client.get(url, headers=headers).json()
    chosen = next(item for item in before["recognition_fields"] if item["field"] == "merchant")
    choice = _choice(chosen)
    if echo:
        choice["presentation"] = chosen["presentation"] if echo is True else echo
    response = client.patch(url, headers={**headers, "Idempotency-Key": str(uuid4())}, json={
        "expected_row_version": before["row_version"], "merchant": chosen["value"], "recognition_field_choices": [choice]})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        event = db.query(LedgerLearningEvent).filter_by(subject_id=expense_id, signal_type="recognition_field_choice").one()
        payload = json.loads(event.after_payload)
    assert payload["presentation"] == (chosen["presentation"] if echo is True else None)
    assert payload["_history_exposed"] is False
    assert payload["_learning_qualified"] is True


def test_time_choice_echo_survives_the_actual_financial_command(client, identity):
    expense_id = _image(identity)
    candidate = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()["recognition_time"]["candidates"][0]
    choice = {key: candidate[key] for key in ("evidence_public_id", "parser_version", "source", "presentation")}
    choice["candidate_id"] = candidate["id"]
    response = _choose(client, identity, expense_id, choice=choice, index=0)[0]
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        event = db.query(LedgerLearningEvent).filter_by(subject_id=expense_id, signal_type="recognition_time_choice").one()
        payload = json.loads(event.after_payload)
    assert payload["presentation"] == candidate["presentation"]
    assert payload["_history_exposed"] is False
