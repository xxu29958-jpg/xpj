"""Recovered original forms must retain the provenance of visible suggestions."""
import json
import re
from contextlib import closing
from html import unescape
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import Account, AlgorithmDecision, Device, Expense, LedgerLearningEvent, OcrFact
from app.services.learning_service._withdrawal import withdraw_feedback
from app.services.recognition_review_service import recognition_review_context
from tests._runtime_protocol import negotiated_headers
from tests._web_native_form_support import hidden_post_forms
from tests.test_recognition_field_choice import _choice, _rounding_case, _seed

pytestmark = pytest.mark.real_db


@pytest.mark.parametrize("entry", ["review", "failed_save"])
def test_recovered_form_records_the_learned_amount_it_displays(web_client, identity, monkeypatch, entry):
    headers = negotiated_headers(web_client, identity.app_headers)
    source, target = _rounding_case(web_client, headers, "new_items")
    with SessionLocal() as db:
        version = db.get(Expense, target).row_version
        for device in db.scalars(select(Device)):
            device.platform = "desktop"
        db.commit()
    with closing(TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 52000))) as desktop:
        web_headers = {**identity.auth_headers, "X-Ticketbox-Desktop-Bridge": "v1"}
        settings = desktop.get("/web/settings", headers=web_headers)
        assert settings.status_code == 200, settings.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', settings.text).group(1)
        fields = {"csrf_token": csrf,
            "ledger_id": "owner", "expected_row_version": str(version),
            "amount_yuan": "88.88", "original_currency": "CNY",
            "review_latest": "true", "command_action": "save"}
        with monkeypatch.context() as patch:
            if entry == "failed_save":
                source_page = desktop.get(f"/web/expenses/{source}/edit?ledger_id=owner", headers=web_headers)
                scope = hidden_post_forms(source_page.text)[f"/web/expenses/{source}/save"]["draft_scope"]
                fields.update(review_latest="false", draft_scope=scope, idempotency_key=str(uuid4()))
                # Fail after the real amount update but before its atomic receipt.
                patch.setattr("app.services.expense_edit_command_service.mark_idempotency_succeeded", _fail_receipt)
            response = desktop.post(f"/web/expenses/{target}/save", headers={
                **web_headers, "Origin": "http://127.0.0.1:8000"}, data=fields)
    assert response.status_code == (200 if entry == "review" else 409), response.text
    assert "同类原件" in response.text
    assert 'value="88.88"' in response.text
    candidates = [json.loads(unescape(value)) for value in re.findall(r"data-recognized-field='([^']+)'", response.text)]
    selected = next(row for row in candidates if row["field"] == "amount_cents")
    assert selected["value"] == 2600 and selected["selection_intent"] == "bookkeeping"
    with SessionLocal() as db:
        visible = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.subject_id == target,
            AlgorithmDecision.decision_type == "recognition_field_choice", AlgorithmDecision.status == "active")).all()
        expense = db.get(Expense, target)
        assert (expense.amount_cents, expense.row_version, expense.status) == (1900, version, "pending")
    # An older consumer omits selection_intent. The server still must know that
    # this candidate was exposed as a learned suggestion before it was adopted.
    accepted = web_client.patch(f"/api/expenses/{target}", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": version, "original_currency_code": "CNY", "original_amount_minor": 2600,
            "recognition_field_choices": [{**_choice(selected), "intent": "candidate"}]})
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        adopted = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == target,
            LedgerLearningEvent.signal_type == "recognition_field_choice")).one()
        assert not json.loads(adopted.after_payload)["_learning_qualified"], "Recovery suggestion adoption became independent training"
        assert len(visible) == 1 and adopted.decision_id == visible[0].id
        original = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == source,
            LedgerLearningEvent.signal_type == "recognition_field_choice")).one()
        withdraw_feedback(db, tenant_id="owner", public_id=original.public_id)
        raw = db.scalars(select(OcrFact.raw_text).where(OcrFact.expense_id == target)).one()
        db.commit()
    future = _seed(paid=2000, raw_override=raw.replace("牛奶", "豆浆").replace("26.01", "27.01").replace("26.00", "27.00"))
    after = web_client.get(f"/api/expenses/{future}", headers=headers).json()
    assert not any("同类原件" in c["explanation"] for c in after["recognition_fields"])
    assert after["amount_cents"] == 2000 and after["status"] == "pending"


def _fail_receipt(*args, **kwargs):
    raise AppError("state_conflict", "Controlled receipt failure after the real update", status_code=409)


def test_review_exposure_does_not_commit_the_callers_unsaved_financial_change(web_client, identity):
    headers = negotiated_headers(web_client, identity.app_headers)
    _source, target = _rounding_case(web_client, headers, "new_items")
    with SessionLocal() as caller:
        expense = caller.get(Expense, target)
        actor = caller.scalars(select(Account.id)).first()
        expense.amount_cents = 8888
        context = recognition_review_context(tenant_id="owner", expense_id=target, actor_account_id=actor)
        assert any("同类原件" in choice.explanation for choice in context["recognition_fields"])
        caller.rollback()
    with SessionLocal() as db:
        assert db.get(Expense, target).amount_cents == 1900
        assert db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.subject_id == target,
            AlgorithmDecision.decision_type == "recognition_field_choice")).one().status == "active"
