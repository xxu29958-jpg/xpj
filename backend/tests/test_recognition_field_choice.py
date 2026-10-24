"""Successful expense commands, not displayed defaults, supply field feedback."""
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent, OcrFact
from app.services.currency_binding_service import resolve_write_capability
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.ocr_service import OcrResult, ocr_fact_snapshot
from tests._infra.identity import seeded_owner_account_id
from tests._runtime_protocol import negotiated_headers
from tests._web_native_form_support import hidden_post_forms


def _seed(merchant="海棠咖啡", paid=1800, total=2500, raw_override=None):
    raw = raw_override or f"商户：{merchant}\n支付金额：{paid / 100:.2f}元\n合计：{total / 100:.2f}元\n支付时间：2026-10-20 12:30"
    with SessionLocal() as db:
        resolve_write_capability(db)
        row = Expense(tenant_id="owner", source="camera", status="pending", category="其他",
            merchant=merchant, amount_cents=paid, original_amount_minor=paid,
            original_currency_code="CNY", home_currency_code="CNY", image_hash=str(uuid4()),
            created_at=datetime(2026, 10, 20, tzinfo=UTC))
        db.add(row)
        db.flush()
        snapshot = ocr_fact_snapshot(OcrResult(raw_text=raw, confidence=None), expense=row, timezone_name="Asia/Shanghai")
        record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=row.id, ocr_provider="manual_text",
            raw_text=raw, evidence_json=json.dumps(snapshot.evidence)))
        db.commit()
        return row.id


def _choice(candidate):
    return {"field": candidate["field"], "evidence_public_id": candidate["evidence_public_id"],
        "candidate_id": candidate["id"], "parser_version": candidate["parser_version"]}


@pytest.mark.parametrize("explicit,merchant", [(False, "海棠咖啡"), (True, "海棠咖啡"), (True, "商户大厦")])
def test_original_amount_and_merchant_choices_are_scoped_and_replayed_once(client, identity, explicit, merchant):
    expense_id = _seed(merchant)
    headers = negotiated_headers(client, identity.app_headers)
    before = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    candidates = before.get("recognition_fields")
    assert candidates, "Original amount and merchant evidence never reaches the actual consumer"
    assert {("amount_cents", 1800), ("merchant", merchant)} <= {(item["field"], item["value"]) for item in candidates}, candidates
    chosen = [next(item for item in candidates if item["field"] == field and item["value"] == value)
        for field, value in (("amount_cents", 1800), ("merchant", merchant))]
    payload = {"expected_row_version": before["row_version"], "merchant": merchant,
        "original_currency_code": "CNY", "original_amount_minor": 1800}
    if explicit:
        payload["recognition_field_choices"] = [_choice(item) for item in chosen]
    headers = {**headers, "Idempotency-Key": str(uuid4())}
    saved = client.patch(f"/api/expenses/{expense_id}", json=payload, headers=headers)
    assert saved.status_code == 200, saved.text
    replay = client.patch(f"/api/expenses/{expense_id}", json=payload, headers=headers)
    assert replay.json() == saved.json()
    assert saved.json()["amount_cents"] == 1800 and saved.json()["status"] == "pending"
    actor_id = seeded_owner_account_id()
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(
            LedgerLearningEvent.subject_id == expense_id, LedgerLearningEvent.signal_type == "recognition_field_choice")))
        assert len(events) == (2 if explicit else 0)
        from app.services.learning_service._source_eligibility import eligible_feedback
        assert {event.id for event in eligible_feedback(db, tenant_id="owner", events=events, actor_account_id=actor_id)} == {event.id for event in events}
        for event in events:
            data = json.loads(event.after_payload)
            assert event.actor_account_id == actor_id and data["_learning_qualified"]
            assert data["field"] in {"amount_cents", "merchant"} and data["_action_outcome"] == "committed"


@pytest.mark.parametrize("source_change", ["amount", "ocr_fact", "ocr_fact_tie"])
def test_personal_field_case_reorders_a_new_source_and_stops_when_its_source_changes(client, identity, source_change):
    from app.services.learning_service._cleanup import cleanup_expired_learning_tables

    headers = negotiated_headers(client, identity.app_headers)
    source_id = _seed()
    saved = _choose_amount(client, headers, source_id, 2500)
    next_id = _seed(paid=1900, total=2600)
    with SessionLocal() as db:
        fact = db.scalars(select(OcrFact).where(OcrFact.expense_id == source_id)).one()
        fact.extracted_at = datetime.now(UTC) - timedelta(days=400)
        db.commit()
        cleanup_expired_learning_tables(db, tenant_id="owner")
    suggested = client.get(f"/api/expenses/{next_id}", headers=headers).json()
    amounts = [item for item in suggested["recognition_fields"] if item["field"] == "amount_cents"]
    assert amounts[0]["value"] == 2600 and "同类原件" in amounts[0]["explanation"]
    assert suggested["amount_cents"] == 1900 and suggested["status"] == "pending"
    if source_change == "amount":
        changed = client.patch(f"/api/expenses/{source_id}", headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": saved.json()["row_version"], "original_amount_minor": 1700, "original_currency_code": "CNY"})
        assert changed.status_code == 200, changed.text
    else:
        from app.services.expense_service._ocr_facts import append_ocr_fact
        with SessionLocal() as db:
            append_ocr_fact(db, expense=db.get(Expense, source_id), provider_name="mock", timezone_name="Asia/Shanghai",
                result=OcrResult(raw_text="商户：海棠咖啡\n实付：25元", confidence=0.9))
            latest = db.scalar(select(OcrFact).where(OcrFact.expense_id == source_id).order_by(OcrFact.id.desc()))
            latest.extracted_at = fact.extracted_at if source_change == "ocr_fact_tie" else datetime.now(UTC) - timedelta(days=350)
            current_fact_id = latest.id
            # A later-inserted backfill is not the current source. Neither it nor
            # an expired current source may reactivate the superseded feedback.
            record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=source_id,
                ocr_provider="mock", raw_text="更早的补录原件"), now=datetime.now(UTC) - timedelta(days=450))
            db.commit()
    after = client.get(f"/api/expenses/{next_id}", headers=headers).json()
    assert not any("同类原件" in item["explanation"] for item in after["recognition_fields"])
    assert after["amount_cents"] == 1900 and after["row_version"] == suggested["row_version"]
    with SessionLocal() as db:
        assert db.query(AlgorithmDecision).filter_by(subject_id=next_id,
            decision_type="recognition_field_choice", status="active").count() == 0
    if source_change != "amount":
        from app.services.learning_service import read_ocr_facts
        with SessionLocal() as db:
            cleanup_expired_learning_tables(db, tenant_id="owner")
            current = read_ocr_facts(db, tenant_id="owner", expenses=[db.get(Expense, source_id)])
            assert current[source_id].id == current_fact_id, "Cleanup must not resurrect the referenced predecessor"
        after_cleanup = client.get(f"/api/expenses/{next_id}", headers=headers).json()
        assert not any("同类原件" in item["explanation"] for item in after_cleanup["recognition_fields"])
        assert after_cleanup["amount_cents"] == 1900 and after_cleanup["row_version"] == suggested["row_version"]


@pytest.mark.real_db
def test_concurrent_original_field_readers_share_one_display_decision(client, identity):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.services.learning_service import read_ocr_facts
    from app.services.recognition_field_memory import load_field_memory, recall_field_choices
    from app.services.recognition_field_service import recognition_fields

    headers = negotiated_headers(client, identity.app_headers)
    source_id = _seed()
    _choose_amount(client, headers, source_id, 2500)
    next_id = _seed(paid=1900, total=2600)
    actor = seeded_owner_account_id()
    ready = Barrier(2)

    def read_and_commit():
        with SessionLocal() as db:
            expense = db.get(Expense, next_id)
            fact = read_ocr_facts(db, tenant_id="owner", expenses=[expense])[next_id]
            memory = load_field_memory(db, tenant_id="owner", actor_account_id=actor, expense_ids=[next_id])
            ready.wait(timeout=10)
            candidates = recall_field_choices(db, expense=expense, actor_account_id=actor, fact=fact,
                candidates=recognition_fields(fact), memory=memory)
            db.commit()
            return candidates[0].value

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read_and_commit) for _ in range(2)]
        assert [f.result(timeout=15) for f in futures] == [2600, 2600]
    with SessionLocal() as db:
        assert db.query(AlgorithmDecision).filter_by(subject_id=next_id,
            decision_type="recognition_field_choice", status="active").count() == 1


def _choose_amount(client, headers, source_id, value):
    source = client.get(f"/api/expenses/{source_id}", headers=headers).json()
    selected = next(item for item in source["recognition_fields"] if item["field"] == "amount_cents" and item["value"] == value)
    choice = _choice(selected)
    saved = client.patch(f"/api/expenses/{source_id}", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": source["row_version"], "original_currency_code": "CNY", "original_amount_minor": value,
            "recognition_field_choices": [choice]})
    assert saved.status_code == 200, saved.text
    return saved


def _rounding_case(client, headers, variation):
    def material(items, total, rounded, change, header="门店A", extra=""):
        return f"海棠咖啡\n收款小票\n{header}\n{items}\nTOTAL\n￥{total}\nTOTAL ROUNDED\n￥{rounded}\nCASH\n￥30.00\nCHANGE\n￥{change}{extra}"

    source_id = _seed(raw_override=material("咖啡豆", "25.01", "25.00", "5.00"))
    if variation == "literal_correction":
        source = client.get(f"/api/expenses/{source_id}", headers=headers).json()
        selected = next(c for c in source["recognition_fields"] if c["field"] == "amount_cents" and c["value"] == 2501)
        choice = {**_choice(selected), "intent": "original_correction"}
        response = client.patch(f"/api/expenses/{source_id}", headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": source["row_version"], "original_currency_code": "CNY", "original_amount_minor": 2500,
                "recognition_field_choices": [choice]})
        assert response.status_code == 200, response.text
    else:
        _choose_amount(client, headers, source_id, 2500)
    raw = material("牛奶\n面包", "26.01", "26.00", "4.00",
        header="门店B" if variation == "changed_header" else "门店A",
        extra="\n手续费\n￥0.50" if variation == "changed_structure" else "")
    if variation == "duplicate_label":
        raw += "\nTOTAL ROUNDED\n￥27.00"
    if variation == "other_currency":
        raw = raw.replace("￥26.00", "USD 26.00")
    return source_id, _seed(paid=1900, raw_override=raw)


@pytest.mark.parametrize("variation", ["new_items", "changed_header", "changed_structure", "literal_correction", "duplicate_label", "other_currency"])
def test_local_amount_role_survives_new_items_but_not_changed_context_or_withdrawal(client, identity, variation):
    headers = negotiated_headers(client, identity.app_headers)
    source_id, target_id = _rounding_case(client, headers, variation)
    suggested = client.get(f"/api/expenses/{target_id}", headers=headers).json()
    amounts = [c for c in suggested["recognition_fields"] if c["field"] == "amount_cents"]
    learned = variation == "new_items"
    assert any("同类原件" in c["explanation"] for c in amounts) == learned, amounts
    if learned:
        assert amounts[0]["value"] == 2600
    assert suggested["amount_cents"] == 1900 and suggested["status"] == "pending"
    # A later explicit selection supersedes this source's role preference.
    _choose_amount(client, headers, source_id, 2501)
    after = client.get(f"/api/expenses/{target_id}", headers=headers).json()
    assert after["amount_cents"] == 1900 and after["row_version"] == suggested["row_version"]
    if learned:
        amounts = [c for c in after["recognition_fields"] if c["field"] == "amount_cents"]
        assert amounts[0]["value"] == 2601, "The superseded rounded-total case still affects this new receipt"
        from app.services.learning_service._withdrawal import withdraw_feedback
        with SessionLocal() as db:
            event = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == source_id,
                LedgerLearningEvent.signal_type == "recognition_field_choice").order_by(LedgerLearningEvent.id.desc())).first()
            withdraw_feedback(db, tenant_id="owner", public_id=event.public_id)
            db.commit()
        withdrawn = client.get(f"/api/expenses/{target_id}", headers=headers).json()
        assert not any("同类原件" in c["explanation"] for c in withdrawn["recognition_fields"])
        assert withdrawn["amount_cents"] == 1900 and withdrawn["row_version"] == suggested["row_version"]


@pytest.mark.parametrize("client_intent", ["projected", "legacy", "historic"])
def test_accepting_a_learned_amount_does_not_recreate_withdrawn_source_feedback(client, identity, client_intent):
    from app.services.learning_service._withdrawal import withdraw_feedback

    headers = negotiated_headers(client, identity.app_headers)
    source_id, target_id = _rounding_case(client, headers, "new_items")
    proposed = client.get(f"/api/expenses/{target_id}", headers=headers).json()
    selected = next(c for c in proposed["recognition_fields"] if c["field"] == "amount_cents")
    assert selected["value"] == 2600
    accepted = client.patch(f"/api/expenses/{target_id}", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": proposed["row_version"], "original_currency_code": "CNY", "original_amount_minor": 2600,
            "recognition_field_choices": [{**_choice(selected), "intent": selected["selection_intent"] if client_intent == "projected" else "candidate"}]})
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        adopted = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == target_id,
            LedgerLearningEvent.signal_type == "recognition_field_choice")).one()
        assert not json.loads(adopted.after_payload)["_learning_qualified"]
        if client_intent == "historic":
            # Old clients had no decision link and incorrectly qualified adoption.
            from app.services.learning_service._cleanup import cleanup_expired_algorithm_decisions

            exposure = db.get(AlgorithmDecision, adopted.decision_id)
            assert exposure is not None
            exposure.status = "superseded"
            payload = json.loads(adopted.after_payload)
            payload.update(intent="candidate", _learning_qualified=True)
            payload.pop("_adopted_suggestion_public_id", None)
            adopted.after_payload, adopted.decision_id = json.dumps(payload), None
            db.commit()
            cleanup_expired_algorithm_decisions(db, tenant_id="owner", now=datetime.now(UTC) + timedelta(days=400))
            assert db.get(AlgorithmDecision, exposure.id) is not None, "Cleanup erased the evidence that this was suggestion adoption"
        original = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == source_id,
            LedgerLearningEvent.signal_type == "recognition_field_choice")).one()
        withdraw_feedback(db, tenant_id="owner", public_id=original.public_id)
        raw = db.scalars(select(OcrFact.raw_text).where(OcrFact.expense_id == target_id)).one()
        db.commit()
    future = _seed(paid=2000, raw_override=raw.replace("牛奶", "豆浆").replace("26.01", "27.01").replace("26.00", "27.00"))
    after = client.get(f"/api/expenses/{future}", headers=headers).json()
    assert not any("同类原件" in c["explanation"] for c in after["recognition_fields"]), "An accepted suggestion resurrected the withdrawn original judgement"
    assert after["amount_cents"] == 2000 and after["status"] == "pending"


@pytest.mark.parametrize("problem", ["foreign_source", "parser_version", "edited_value"])
def test_unmatched_source_or_user_bookkeeping_never_becomes_original_field_training(client, identity, problem):
    from app.services.learning_service._source_eligibility import eligible_feedback

    headers = negotiated_headers(client, identity.app_headers)
    expense_id = _seed()
    url = f"/api/expenses/{expense_id}"
    before = client.get(url, headers=headers).json()
    candidate = next(item for item in before["recognition_fields"] if item["field"] == "amount_cents" and item["value"] == 1800)
    choice = _choice(candidate)
    if problem == "foreign_source":
        choice["evidence_public_id"] = str(uuid4())
    elif problem == "parser_version":
        choice["parser_version"] = "different-source-parser"
    saved = client.patch(url, headers={**headers, "Idempotency-Key": str(uuid4())}, json={
        "expected_row_version": before["row_version"], "original_currency_code": "CNY",
        "original_amount_minor": 1700, "recognition_field_choices": [choice]})
    assert saved.status_code == 200 and saved.json()["amount_cents"] == 1700
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == expense_id,
            LedgerLearningEvent.signal_type == "recognition_field_choice")))
        assert len(events) == (1 if problem == "edited_value" else 0)
        assert eligible_feedback(db, tenant_id="owner", events=events, actor_account_id=seeded_owner_account_id()) == []
        if events:
            payload = json.loads(events[0].after_payload)
            assert payload["intent"] == "bookkeeping" and payload["final_value"] == 1700


def test_owner_field_memory_controls_do_not_rewrite_facts_or_revive_withdrawn_feedback(client, identity):
    from app.main import app
    from app.routes.owner_console._shared import _require_local
    from app.services.learning_service._algorithm_registry import RECOGNITION_FIELD_CHOICE

    headers = negotiated_headers(client, identity.app_headers)
    source, target = _seed(), _seed(paid=1900, total=2600)
    _choose_amount(client, headers, source, 2500)
    url = f"/api/expenses/{target}"
    learned = client.get(url, headers=headers).json()
    assert any("同类原件" in row["explanation"] for row in learned["recognition_fields"])
    policy = {"ledger_id": "owner", "decision_type": RECOGNITION_FIELD_CHOICE.decision_type,
        "algorithm_version": RECOGNITION_FIELD_CHOICE.current_version}
    app.dependency_overrides[_require_local] = lambda: None
    try:
        page = client.get("/owner/algorithm-versions?ledger_id=owner")
        controls = _field_owner_controls(page.text, policy)
        paused = client.post("/owner/algorithm-versions/policy", data=controls["new_suggestions"])
        assert paused.status_code == 200 and "少重复找金额与商户" in paused.text
        assert client.get(url, headers=headers).json()["recognition_fields"] == learned["recognition_fields"]
        fresh_url = f"/api/expenses/{_seed(paid=2000, total=2700)}"
        fresh = client.get(fresh_url, headers=headers).json()["recognition_fields"]
        assert all("同类原件" not in row["explanation"] for row in fresh)
        assert client.post("/owner/algorithm-versions/withdraw", data=policy).status_code == 200
        assert all("同类原件" not in row["explanation"] for row in client.get(url, headers=headers).json()["recognition_fields"])
        assert client.post("/owner/algorithm-versions/policy", data={**policy, "axis": "training", "enabled": "false"}).status_code == 200
        assert client.post("/owner/algorithm-versions/policy", data={**policy, "axis": "new_suggestions", "enabled": "true"}).status_code == 200
        assert client.get(fresh_url, headers=headers).json()["recognition_fields"] == fresh
        assert client.post("/owner/algorithm-versions/policy", data={**policy, "axis": "training", "enabled": "true"}).status_code == 200
        assert any("同类原件" in row["explanation"] for row in client.get(fresh_url, headers=headers).json()["recognition_fields"])
        with SessionLocal() as db:
            event_id = db.scalar(select(LedgerLearningEvent.public_id).where(LedgerLearningEvent.subject_id == source,
                LedgerLearningEvent.signal_type == "recognition_field_choice"))
        for _ in range(2):
            assert client.post("/owner/algorithm-versions/withdraw-feedback",
                data={"ledger_id": "owner", "event_public_id": event_id}).status_code == 200
        assert client.get(fresh_url, headers=headers).json()["recognition_fields"] == fresh
        after = client.get(url, headers=headers).json()
        assert (after["amount_cents"], after["status"], after["row_version"]) == (learned["amount_cents"], learned["status"], learned["row_version"])
    finally:
        app.dependency_overrides.pop(_require_local, None)


def _field_owner_controls(html, policy):
    forms = [hidden_post_forms(form) for form in re.findall(r"<form\b.*?</form>", html, re.S)]
    choices = [form["/owner/algorithm-versions/policy"] for form in forms if "/owner/algorithm-versions/policy" in form]
    controls = {form["axis"]: form for form in choices if all(form.get(key) == value for key, value in policy.items())}
    assert set(controls) == {"new_suggestions", "training"}, "Owner must be able to operate both controls from the rendered page"
    return controls
