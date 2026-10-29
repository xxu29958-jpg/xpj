"""No OCR candidate is needed; successful expense commands own pixel feedback."""
import io
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerLearningEvent, OcrFact
from app.services.currency_binding_service import resolve_write_capability
from app.services.file_service import save_upload_bytes
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.learning_service._source_eligibility import feedback_assessments
from app.services.learning_service._withdrawal import withdraw_feedback
from tests._runtime_protocol import negotiated_headers


def seed_original():
    data = io.BytesIO()
    Image.new("RGB", (400, 800), "white").save(data, format="PNG")
    image = save_upload_bytes(data.getvalue(), tenant_id="owner", filename="original.png", content_type="image/png")
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(tenant_id="owner", source="camera", status="pending", category="其他",
            merchant="", amount_cents=None, original_amount_minor=None, original_currency_code="CNY", home_currency_code="CNY",
            image_path=image.relative_path, image_hash=image.image_hash, created_at=datetime.now(UTC))
        db.add(expense)
        db.commit()
        return expense.id, image.image_hash


def annotation(digest, location="verified_region"):
    return {"field": "amount_cents", "image_sha256": digest, "width": 400, "height": 800,
        "location_state": location, "box": [10, 40, 390, 70] if "region" in location else None,
        "point": [20, 50] if location == "coarse_point" else None, "verbatim_text": "实付：78.00",
        "role": "payment", "issue": "missing", "text_verified": True}


def save(client, headers, expense_id, feedback, *, expected=None, amount=1700):
    version = expected if expected is not None else client.get(f"/api/expenses/{expense_id}", headers=headers).json()["row_version"]
    payload = {"expected_row_version": version, "original_currency_code": "CNY", "original_amount_minor": amount,
        "merchant": "本人简称", "original_text_feedback": feedback}
    return client.patch(f"/api/expenses/{expense_id}", headers=headers, json=payload), payload


@pytest.mark.parametrize("location", [None, "unlocated", "coarse_point", "suggested_region", "verified_region"])
def test_no_candidate_save_keeps_finance_prediction_and_transcription_separate(client, identity, location):
    expense_id, digest = seed_original()
    headers = {**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())}
    before = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert before["recognition_fields"] == []
    saved, body = save(client, headers, expense_id, [annotation(digest, location)] if location else None)
    assert saved.status_code == 200, saved.text
    assert saved.json()["original_amount_minor"] == 1700
    replay = client.patch(f"/api/expenses/{expense_id}", headers=headers, json=body)
    assert replay.json() == saved.json()
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id,
            LedgerLearningEvent.signal_type == "original_text_feedback")))
        assert len(events) == bool(location)
        assert not list(db.scalars(select(OcrFact).where(OcrFact.expense_id == expense_id)))
        if events:
            payload = json.loads(events[0].after_payload)
            assert payload["verbatim_text"] == "实付：78.00" and payload["_source_context"]["original_amount_minor"] == 1700
            assert events[0].decision_id is None and payload.get("evidence_public_id") is None
            expected = "valid" if location == "verified_region" else "needs_review"
            assert feedback_assessments(db, tenant_id="owner", events=events)[events[0].id][0] == expected


@pytest.mark.parametrize("change,status", [({"image_sha256": "b" * 64}, 409), ({"width": 401}, 409),
    ({"box": [-1, 1, 20, 30]}, 422), ({"location_state": "coarse_point", "box": None}, 422),
    ({"evidence_public_id": "not-an-evidence"}, 409)])
def test_invalid_original_does_not_partially_save_finance_or_feedback(client, identity, change, status):
    expense_id, digest = seed_original()
    headers = {**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())}
    before = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    saved, _ = save(client, headers, expense_id, [{**annotation(digest), **change}])
    assert saved.status_code == status, saved.text
    after = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert (after["original_amount_minor"], after["row_version"]) == (None, before["row_version"])
    with SessionLocal() as db:
        assert not list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id)))


def test_pixel_annotation_survives_financial_edit_and_new_ocr_but_stops_on_replacement_or_withdrawal(client, identity):
    expense_id, digest = seed_original()
    headers = negotiated_headers(client, identity.app_headers)
    saved, _ = save(client, {**headers, "Idempotency-Key": str(uuid4())}, expense_id, [annotation(digest)])
    assert saved.status_code == 200, saved.text
    changed, _ = save(client, {**headers, "Idempotency-Key": str(uuid4())}, expense_id, None, amount=2300)
    assert changed.status_code == 200, changed.text
    with SessionLocal() as db:
        record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=expense_id, ocr_provider="mock", raw_text="新的识别结果"))
        db.commit()
        event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id,
            LedgerLearningEvent.signal_type == "original_text_feedback"))
        assert feedback_assessments(db, tenant_id="owner", events=[event])[event.id][0] == "valid"
        expense = db.get(Expense, expense_id)
        expense.image_hash = "c" * 64
        db.flush()
        assert feedback_assessments(db, tenant_id="owner", events=[event])[event.id][0] == "superseded"
        db.rollback()
        expense = db.get(Expense, expense_id)
        expense.image_deleted_at = datetime.now(UTC)
        db.flush()
        assert feedback_assessments(db, tenant_id="owner", events=[event])[event.id][0] == "invalid"
        db.rollback()
        withdraw_feedback(db, tenant_id="owner", public_id=event.public_id)
        db.commit()
        assert feedback_assessments(db, tenant_id="owner", events=[event])[event.id][0] == "invalid"
        assert json.loads(event.after_payload)["verbatim_text"] == "实付：78.00"
        assert db.get(Expense, expense_id).original_amount_minor == 2300


def test_stale_original_feedback_command_cannot_overwrite_a_later_edit(client, identity):
    expense_id, digest = seed_original()
    headers = negotiated_headers(client, identity.app_headers)
    version = client.get(f"/api/expenses/{expense_id}", headers=headers).json()["row_version"]
    changed, _ = save(client, {**headers, "Idempotency-Key": str(uuid4())}, expense_id, None, amount=2300)
    assert changed.status_code == 200, changed.text
    refused, _ = save(client, {**headers, "Idempotency-Key": str(uuid4())}, expense_id, [annotation(digest)], expected=version)
    assert refused.status_code == 409
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).original_amount_minor == 2300
        assert not list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id)))


@pytest.mark.parametrize("issue", ["unreadable", "cropped", "absent"])
def test_missing_source_information_has_a_diagnostic_exit_without_false_transcription(client, identity, issue):
    expense_id, digest = seed_original()
    headers = {**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())}
    feedback = {**annotation(digest, "unlocated"), "issue": issue, "verbatim_text": "", "text_verified": False}
    response, _ = save(client, headers, expense_id, [feedback])
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id,
            LedgerLearningEvent.signal_type == "original_text_feedback"))
        assert json.loads(event.after_payload)["label_usage"] == "diagnostic"
        assert db.get(Expense, expense_id).original_amount_minor == 1700
        assert feedback_assessments(db, tenant_id="owner", events=[event])[event.id][0] == "needs_review"


def test_confirmed_correction_keeps_original_annotation_revision_independent(client, identity):
    expense_id, digest = seed_original()
    headers = negotiated_headers(client, identity.app_headers)
    saved, _ = save(client, {**headers, "Idempotency-Key": str(uuid4())}, expense_id, [annotation(digest)])
    confirmed = client.post(f"/api/expenses/{expense_id}/confirm", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": saved.json()["row_version"]})
    assert confirmed.status_code == 200, confirmed.text
    correction = {"expected_row_version": confirmed.json()["row_version"], "reason": "核对原件后调整记账",
        "original_currency_code": "CNY", "original_amount_minor": 2200,
        "original_text_feedback": [{**annotation(digest), "verbatim_text": "实付：78.80"}]}
    correction_headers = {**headers, "Idempotency-Key": str(uuid4())}
    result = client.post(f"/api/expenses/{expense_id}/corrections", headers=correction_headers, json=correction)
    assert result.status_code == 201, result.text
    assert client.post(f"/api/expenses/{expense_id}/corrections", headers=correction_headers, json=correction).json() == result.json()
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id,
            LedgerLearningEvent.signal_type == "original_text_feedback").order_by(LedgerLearningEvent.id)))
        assert len(events) == 2
        payloads = [json.loads(row.after_payload) for row in events]
        assert [item["verbatim_text"] for item in payloads] == ["实付：78.00", "实付：78.80"]
        assert payloads[1]["_supersedes_event_public_id"] == events[0].public_id
        assert payloads[1]["_feedback_revision"] == 2
        assert [feedback_assessments(db, tenant_id="owner", events=events)[row.id][0] for row in events] == ["superseded", "valid"]
        assert db.get(Expense, expense_id).original_amount_minor == 2200
