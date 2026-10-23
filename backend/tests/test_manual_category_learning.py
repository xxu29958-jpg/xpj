"""Manual intent survives actual commands without turning defaults into labels."""
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerLearningEvent
from tests.api_contract_helpers import patch_expense
from tests.expense_correction_support import idem
from tests.test_owner_console import local_client as local_client


def _history(client, identity, *, intent="manual", note=""):
    saved = []
    for index in range(3):
        payload = {"client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1200 + index,
            "merchant": "分类用途商店", "category": "餐饮", "note": note,
            "spent_at": (datetime.now(UTC) - timedelta(days=index + 1)).isoformat()}
        if intent is not None:
            payload["category_choice"] = intent
        first = client.post("/api/expenses/manual", headers=identity.app_headers, json=payload)
        replay = client.post("/api/expenses/manual", headers=identity.app_headers, json=payload)
        assert first.status_code == replay.status_code == 200, first.text
        assert first.json()["id"] == replay.json()["id"]
        saved.append(first.json())
    return saved


def _next(client, identity, *, note=""):
    response = client.post("/api/expenses/notification-drafts", headers=identity.app_headers,
        json={"source": "alipay", "notification_key": str(uuid4()), "amount_cents": 1900,
            "merchant": "分类用途商店"})
    assert response.status_code == 200, response.text
    expense_id = response.json()["id"]
    if note:
        changed = patch_expense(client, expense_id, headers=identity.app_headers, fields={"note": note})
        assert changed.status_code == 200, changed.text
    return client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()


@pytest.mark.parametrize("intent", [None, "manual", "one_off"])
def test_create_and_replay_count_only_explicit_personal_examples(client, identity, intent):
    saved = _history(client, identity, intent=intent)
    with SessionLocal() as db:
        events = list(db.scalars(select(LedgerLearningEvent).where(
            LedgerLearningEvent.subject_id.in_([row["id"] for row in saved]))))
        assert len(events) == (0 if intent is None else 3)
        assert all(json.loads(row.after_payload)["_category_intent"] == intent for row in events)
    detail = _next(client, identity)
    assert bool(detail["category_suggestion"]) == (intent == "manual")
    if intent == "manual":
        assert detail["category_suggestion"]["sample_size"] == 3
    assert (detail["category"], detail["amount_cents"]) == ("其他", 1900)


def test_manual_context_and_rejection_do_not_cross_purposes(client, identity):
    _history(client, identity, note="家庭聚餐")
    assert _next(client, identity)["category_suggestion"] is None
    for _ in range(2):
        detail = _next(client, identity, note="家庭聚餐")
        advice = detail["category_suggestion"]
        assert advice is not None
        rejected = client.post(f"/api/expenses/{detail['id']}/suggestions/{advice['decision_public_id']}/reject",
            headers=identity.app_headers)
        assert rejected.status_code == 200, rejected.text
    assert _next(client, identity, note="家庭聚餐")["category_suggestion"] is None
    _history(client, identity, note="工作餐")
    assert _next(client, identity, note="工作餐")["category_suggestion"]["category"] == "餐饮"


@pytest.mark.parametrize("revision", ["one_off", "changed_purpose", "withdraw", "quarantine"])
@pytest.mark.usefixtures("local_client")
def test_correct_or_withdraw_examples_changes_future_advice_not_other_facts(client, identity, revision):
    saved = _history(client, identity)
    assert _next(client, identity)["category_suggestion"]["sample_size"] == 3
    first = saved[0]
    if revision in {"one_off", "changed_purpose"}:
        fields = {"category": "购物", "category_choice": "one_off"} if revision == "one_off" else {"note": "临时用途"}
        body = {"reason": "修正这笔的用途", "expected_row_version": first["row_version"], **fields}
        headers = idem(identity.app_headers)
        response = client.post(f"/api/expenses/{first['id']}/corrections", headers=headers, json=body)
        assert response.status_code == 201, response.text
        replay = client.post(f"/api/expenses/{first['id']}/corrections", headers=headers, json=body)
        assert replay.status_code == 201 and replay.json() == response.json()
    else:
        with SessionLocal() as db:
            event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == first["id"]))
            event_id = event.public_id
        if revision == "withdraw":
            url, data = "/owner/algorithm-versions/withdraw-feedback", {"ledger_id": "owner", "event_public_id": event_id}
        else:
            url, data = "/owner/algorithm-versions/policy", {"ledger_id": "owner", "decision_type": "category_suggestion",
                "algorithm_version": "manual-choice-v2", "axis": "training", "enabled": "false"}
        response = client.post(url, data=data)
        assert response.status_code == 200, response.text
    assert _next(client, identity)["category_suggestion"] is None
    with SessionLocal() as db:
        for original in saved[1:]:
            row = db.get(Expense, original["id"])
            assert (row.category, row.amount_cents, row.row_version) == (
                original["category"], original["amount_cents"], original["row_version"])
    page = client.get("/owner/algorithm-versions?ledger_id=owner")
    assert page.status_code == 200 and "本人手动分类" in page.text
