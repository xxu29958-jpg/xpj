"""Exercise qualified transcription consumption through the real Owner reader."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Expense, LedgerLearningEvent, OcrFact
from app.services.file_service import resolve_protected_image
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.learning_service._algorithm_registry import ORIGINAL_TEXT_FEEDBACK
from app.services.learning_service._policy import set_policy
from app.services.learning_service._withdrawal import withdraw_feedback
from tests._infra.identity import seeded_owner_account_id
from tests._runtime_protocol import negotiated_headers
from tests.test_original_text_feedback import annotation, save, seed_original

PATH = "/owner/learning-maintenance/original-text-evaluation"


@pytest.fixture()
def local_client(client):
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as local:
        yield local


def seed_feedback(client, identity, *, text="实付：7B.OO", location="verified_region", box=None):
    expense_id, digest = seed_original()
    with SessionLocal.begin() as db:
        fact = record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=expense_id, ocr_provider="mock",
            raw_text=text, evidence_json=json.dumps({"width": 400, "height": 800,
                "input_sha256": digest, "coordinate_space": "exif-transposed-pixels", "blocks": [
                    {"text": text, "box": box or [[20, 45], [380, 45], [380, 65], [20, 65]]}]})))
        fact_id = fact.public_id
    headers = {**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())}
    result, _ = save(client, headers, expense_id, [annotation(digest, location)])
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id,
            LedgerLearningEvent.signal_type == "original_text_feedback"))
        return expense_id, event.public_id, fact_id, result.json()["row_version"]


def evaluate(client, events, **scope):
    params = [("ledger_id", scope.get("ledger_id", "owner")),
        ("actor_account_id", scope.get("actor_account_id", seeded_owner_account_id()))]
    params.extend(("event_public_id", event) for event in events)
    response = client.get(PATH, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def test_actual_transcription_labels_score_prediction_without_rewriting_it_or_finance(local_client, identity):
    first = seed_feedback(local_client, identity)
    second = seed_feedback(local_client, identity, text="实付：78.00")
    result = evaluate(local_client, [first[1], second[1]])
    assert (result["cohort_count"], result["qualified_count"], result["scored_count"], result["exact_match_count"]) == (2, 2, 2, 1)
    assert [row["exact_match"] for row in result["rows"]] == [False, True]
    assert result["rows"][0]["evidence_public_id"] == first[2]
    assert "实付" not in json.dumps(result, ensure_ascii=False)
    with SessionLocal() as db:
        assert db.scalar(select(OcrFact.raw_text).where(OcrFact.public_id == first[2])) == "实付：7B.OO"
        for expense_id, _, _, version in [first, second]:
            expense = db.get(Expense, expense_id)
            assert (expense.original_amount_minor, expense.row_version) == (1700, version)


@pytest.mark.parametrize("control", ["withdraw", "quarantine", "supersede", "replace_original", "remove_original"])
def test_frozen_cohort_keeps_denominator_when_feedback_loses_eligibility(local_client, identity, control):
    expense_id, public_id, _, _ = seed_feedback(local_client, identity, text="实付：78.00")
    before = evaluate(local_client, [public_id])
    with SessionLocal.begin() as db:
        if control == "withdraw":
            withdraw_feedback(db, tenant_id="owner", public_id=public_id)
        if control == "quarantine":
            set_policy(db, tenant_id="owner", decision_type="original_text_feedback",
                version=ORIGINAL_TEXT_FEEDBACK.current_version, axis="training", enabled=False)
        if control == "replace_original":
            db.get(Expense, expense_id).image_hash = "e" * 64
        if control == "remove_original":
            db.get(Expense, expense_id).image_path = None
    if control == "supersede":
        headers = {**negotiated_headers(local_client, identity.app_headers), "Idempotency-Key": str(uuid4())}
        with SessionLocal() as db:
            digest = db.get(Expense, expense_id).image_hash
        response, _ = save(local_client, headers, expense_id, [{**annotation(digest), "verbatim_text": "实付：78.80"}])
        assert response.status_code == 200
    after = evaluate(local_client, [public_id])
    assert after["cohort_sha256"] == before["cohort_sha256"]
    assert (after["cohort_count"], after["qualified_count"], after["scored_count"]) == (1, 0, 0)
    assert after["rows"][0]["status"] == "ineligible"
    assert "reference_sha256" not in after["rows"][0]


@pytest.mark.parametrize("scope", [{"ledger_id": "tester_1"}, {"actor_account_id": 999999}])
def test_feedback_isolated_by_ledger_and_person(local_client, identity, scope):
    _, public_id, _, _ = seed_feedback(local_client, identity)
    result = evaluate(local_client, [public_id], **scope)
    assert result["rows"] == [{"event_public_id": public_id, "status": "ineligible", "reason": "not_found"}]
    assert result["cohort_count"] == 1 and result["qualified_count"] == 0


@pytest.mark.parametrize("location", ["unlocated", "coarse_point", "suggested_region"])
def test_unverified_regions_do_not_become_evaluation_labels(local_client, identity, location):
    _, public_id, _, _ = seed_feedback(local_client, identity, location=location)
    result = evaluate(local_client, [public_id])
    assert result["qualified_count"] == 0 and result["rows"][0]["reason"] == "needs_review"


def test_partial_lines_abstain_instead_of_scoring_the_unselected_text(local_client, identity):
    _, public_id, _, _ = seed_feedback(local_client, identity, box=[[20, 45], [399, 45], [399, 65], [20, 65]])
    result = evaluate(local_client, [public_id])
    assert (result["cohort_count"], result["qualified_count"], result["scored_count"]) == (1, 1, 0)
    assert result["rows"][0]["reason"] == "partial_line"


def test_original_bytes_are_rechecked_before_consuming_the_label(local_client, identity):
    expense_id, public_id, _, _ = seed_feedback(local_client, identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        path, _ = resolve_protected_image(expense.image_path, expense.tenant_id)
    original = path.read_bytes()
    try:
        path.write_bytes(b"changed source")
        result = evaluate(local_client, [public_id])
        assert result["scored_count"] == 0 and result["rows"][0]["reason"] == "original_unavailable"
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("change", ["unversioned_label", "text_without_pixels"])
def test_unsupported_label_or_prediction_abstains_without_using_financial_values(local_client, identity, change):
    expense_id, public_id, _, _ = seed_feedback(local_client, identity)
    with SessionLocal.begin() as db:
        if change == "unversioned_label":
            event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.public_id == public_id))
            payload = json.loads(event.after_payload)
            payload["_algorithm_version"] = "unversioned"
            event.after_payload = json.dumps(payload)
        else:
            record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=expense_id, ocr_provider="mock",
                raw_text="实付：78.00"))
    result = evaluate(local_client, [public_id])
    assert result["cohort_count"] == 1 and result["scored_count"] == 0
    assert result["rows"][0]["reason"] == ("unsupported_label_contract" if change == "unversioned_label" else "no_comparable_prediction")


def test_evaluation_is_local_only_and_rejects_duplicate_denominators(client, local_client, identity):
    _, public_id, _, _ = seed_feedback(local_client, identity)
    params = {"ledger_id": "owner", "actor_account_id": seeded_owner_account_id(), "event_public_id": public_id}
    assert client.get(PATH, params=params).status_code == 403
    params["event_public_id"] = [public_id, public_id]
    assert local_client.get(PATH, params=params).status_code == 422
