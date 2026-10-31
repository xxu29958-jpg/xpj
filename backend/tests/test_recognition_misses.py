"""Unmatched saves remain bookkeeping unless the original is explicitly corrected."""
import json
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import Expense, LedgerLearningEvent
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import update_expense
from app.services.learning_service._source_eligibility import eligible_feedback
from app.services.learning_service._withdrawal import withdraw_feedback
from tests._infra.identity import seeded_owner_account_id
from tests._runtime_protocol import negotiated_headers
from tests.test_recognition_field_choice import _choice, _seed


def _events(db, expense_id):
    return db.query(LedgerLearningEvent).filter(LedgerLearningEvent.subject_id == expense_id,
        LedgerLearningEvent.signal_type.in_(("recognition_field_choice", "recognition_time_choice"))).all()


@pytest.mark.parametrize("field", ["merchant", "expense_time"])
def test_diagnostics_do_not_evict_learning_but_same_source_edits_still_supersede(client, identity, field):
    from app.services.learning_service import EventDraft, record_event
    from app.services.recognition_field_memory import load_field_memory
    from app.services.recognition_memory_service import load_time_memory
    from tests.test_recognition_choice import _choose, _image
    from tests.test_recognition_field_corrections import _save

    if field == "merchant":
        source = _seed()
        headers = negotiated_headers(client, identity.app_headers)
        reading = next(item for item in client.get(f"/api/expenses/{source}", headers=headers).json()["recognition_fields"]
            if item["field"] == field)
        _save(client, headers, source, reading, "新名称", "original_correction")
        loader = load_field_memory
    else:
        source = _image(identity)
        assert _choose(client, identity, source)[0].status_code == 200
        loader = load_time_memory
    noise = _seed(merchant="其他来源")
    with SessionLocal() as db:
        original = _events(db, source)[0]
        actor = seeded_owner_account_id()

        def diagnostic(subject):
            record_event(db, EventDraft(tenant_id="owner", subject_kind="expense", subject_id=subject,
                actor_account_id=actor, event_type="edit", signal_type=original.signal_type,
                signal_marker={"field": field, "evidence_public_id": json.loads(original.after_payload)["evidence_public_id"]},
                after_payload={"field": field, "_learning_target": "candidate_miss", "_learning_qualified": False}))

        for _ in range(200):
            diagnostic(noise)
        memory = loader(db, tenant_id="owner", actor_account_id=actor, expense_ids=[noise])
        assert original.id in {row.id for row in memory.cases}
        diagnostic(source)
        after = loader(db, tenant_id="owner", actor_account_id=actor, expense_ids=[noise])
        assert original.id not in {row.id for row in after.cases}


@pytest.mark.parametrize("field,changes", [
    ("merchant", {"merchant": "新名称"}),
    ("amount_cents", {"original_currency_code": "CNY", "original_amount_minor": 1857}),
    ("expense_time", {"time_input": {"precision": "date_only", "calendar_revision": 1,
        "user_local_date": "2026-10-23"}}),
])
def test_unmatched_manual_save_is_idempotent_and_never_qualifies(client, identity, field, changes):
    expense_id = _seed()
    headers = negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    url = f"/api/expenses/{expense_id}"
    before = client.get(url, headers=headers).json()
    body = {"expected_row_version": before["row_version"], **changes}
    saved = client.patch(url, headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert client.patch(url, headers=headers, json=body).json() == saved.json()
    with SessionLocal() as db:
        events = _events(db, expense_id)
        assert len(events) == 1
        payload = json.loads(events[0].after_payload)
        assert payload["field"] == field
        assert payload["_candidate_miss"] == {"kind": "diagnostic", "text_present": False}
        assert not eligible_feedback(db, tenant_id="owner", events=events, actor_account_id=seeded_owner_account_id())
    # Saving the same resulting values under a new command does not inflate misses.
    again = client.patch(url, headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**body, "expected_row_version": saved.json()["row_version"]})
    assert again.status_code == 200, again.text
    with SessionLocal() as db:
        assert len(_events(db, expense_id)) == 1


@pytest.mark.parametrize("explicit", [False, True])
def test_literal_miss_preserves_original_correction_qualification_and_withdrawal(client, identity, explicit):
    expense_id = _seed(merchant="旧名称", raw_override="商户：旧名称\n说明文字：新名称\n实付18.00元")
    headers = negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    url = f"/api/expenses/{expense_id}"
    before = client.get(url, headers=headers).json()
    candidate = next(item for item in before["recognition_fields"] if item["field"] == "merchant")
    body = {"expected_row_version": before["row_version"], "merchant": "新名称"}
    if explicit:
        body["recognition_field_choices"] = [{**_choice(candidate), "intent": "original_correction"}]
    saved = client.patch(url, headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        events = _events(db, expense_id)
        assert len(events) == 1
        data = json.loads(events[0].after_payload)
        assert data["final_value"] == "新名称"
        assert data["_candidate_miss"] == {"kind": "reading" if explicit else "diagnostic", "text_present": True}
        assert bool(eligible_feedback(db, tenant_id="owner", events=events,
            actor_account_id=seeded_owner_account_id())) == explicit
        withdraw_feedback(db, tenant_id="owner", public_id=events[0].public_id)
        db.commit()
        assert not eligible_feedback(db, tenant_id="owner", events=_events(db, expense_id),
            actor_account_id=seeded_owner_account_id())
    after = client.get(url, headers=headers).json()
    assert (after["merchant"], after["amount_cents"], after["row_version"]) == (
        "新名称", 1800, saved.json()["row_version"])


@pytest.mark.real_db
def test_miss_rolls_back_with_its_save(identity):
    expense_id = _seed()
    with SessionLocal() as db:
        before = db.get(Expense, expense_id)
        version, merchant = before.row_version, before.merchant
        update_expense(db, expense_id, "owner", ExpenseUpdateRequest(
            expected_row_version=version, merchant="回滚名称"), commit=False,
            actor_account_id=seeded_owner_account_id())
        assert len(_events(db, expense_id)) == 1
        db.rollback()
    with SessionLocal() as db:
        restored = db.get(Expense, expense_id)
        assert (restored.row_version, restored.merchant) == (version, merchant)
        assert not _events(db, expense_id)


def _confirmed_source(client, identity):
    expense_id = _seed()
    headers = negotiated_headers(client, identity.app_headers)
    url = f"/api/expenses/{expense_id}"
    current = client.get(url, headers=headers).json()
    timed = client.patch(url, headers={**headers, "Idempotency-Key": str(uuid4())}, json={
        "expected_row_version": current["row_version"], "time_input": {
            "precision": "date_only", "calendar_revision": 1, "user_local_date": "2026-10-20"}})
    assert timed.status_code == 200, timed.text
    confirmed = client.post(url + "/confirm", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": timed.json()["row_version"]})
    assert confirmed.status_code == 200, confirmed.text
    return url, headers, confirmed.json()


def test_confirmed_correction_miss_is_ineligible_after_reversal(client, identity):
    url, headers, original = _confirmed_source(client, identity)
    candidate = next(item for item in original["recognition_fields"] if item["field"] == "merchant")
    body = {"expected_row_version": original["row_version"], "reason": "核对原文",
        "merchant": "修正商户", "recognition_field_choices": [{**_choice(candidate), "intent": "original_correction"}]}
    command_headers = {**headers, "Idempotency-Key": str(uuid4())}
    saved = client.post(url + "/corrections", headers=command_headers, json=body)
    assert saved.status_code == 201, saved.text
    assert client.post(url + "/corrections", headers=command_headers, json=body).json() == saved.json()
    with SessionLocal() as db:
        events = [event for event in _events(db, original["id"]) if json.loads(event.after_payload)["field"] == "merchant"]
        assert len(events) == 1
        assert json.loads(events[0].after_payload)["_candidate_miss"]["kind"] == "reading"
        assert len(eligible_feedback(db, tenant_id="owner", events=events, actor_account_id=seeded_owner_account_id())) == 1
    current = client.get(url, headers=headers).json()
    reversed_response = client.post(url + "/offsets", headers={**headers, "Idempotency-Key": str(uuid4())}, json={
        "kind": "reversal", "accounting_date": "2026-10-21", "reason": "冲正测试", "expected_row_version": current["row_version"]})
    assert reversed_response.status_code == 201, reversed_response.text
    with SessionLocal() as db:
        assert not eligible_feedback(db, tenant_id="owner", events=_events(db, original["id"]),
            actor_account_id=seeded_owner_account_id())
        row = db.get(Expense, original["id"])
        assert (row.merchant, row.amount_cents) == ("修正商户", 1800)
