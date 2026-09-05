"""A member supplies a rate for one bill, reviews it, then confirms the fact."""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.schemas import ExpenseCorrectionRequest


def test_correction_contract_does_not_offer_pending_only_rate_input():
    assert "manual_exchange_rate" not in ExpenseCorrectionRequest.model_json_schema()["properties"]


def _pending(client, identity, *, currency="USD", amount=12345):
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": currency,
            "original_amount_minor": amount,
            "merchant": f"Foreign receipt {uuid4()}",
            "spent_at": "2026-05-04T02:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    return response.json()


def _patch(client, identity, expense, fields, *, key=None):
    return client.patch(
        f"/api/expenses/{expense['id']}",
        headers={**identity.app_headers, "Idempotency-Key": key or str(uuid4())},
        json={"expected_row_version": expense["row_version"], **fields},
    )


def test_rate_recovery_is_one_bill_snapshot_and_does_not_confirm(client: TestClient, identity):
    first = _pending(client, identity)
    other = _pending(client, identity)
    key = str(uuid4())
    fields = {"manual_exchange_rate": "7"}
    response = _patch(client, identity, first, fields, key=key)
    assert response.status_code == 200, response.text
    ready = response.json()
    assert ready["status"] == "pending"
    assert ready["fx_status"] == "ready"
    assert ready["amount_cents"] == 86415
    assert Decimal(ready["fx_rate"]) == Decimal("7")
    assert ready["fx_source"] == "manual"
    assert ready["fx_rate_date"] == "2026-05-04"
    before_confirm = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert before_confirm.json()["total_amount_cents"] == 0

    replay = _patch(client, identity, first, fields, key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["row_version"] == ready["row_version"]
    unchanged = client.get(f"/api/expenses/{other['id']}", headers=identity.app_headers).json()
    assert unchanged["fx_status"] == "pending"
    assert unchanged["amount_cents"] is None
    rates = client.get("/api/exchange-rates", headers=identity.app_headers)
    assert rates.json()["items"] == []

    confirmed = client.post(
        f"/api/expenses/{first['id']}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": ready["row_version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["amount_cents"] == 86415
    after_confirm = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert after_confirm.json()["total_amount_cents"] == 86415


def test_rate_and_edited_original_facts_save_atomically_and_remain_editable(client, identity):
    initial = _pending(client, identity)
    response = _patch(
        client,
        identity,
        initial,
        {
            "original_amount_minor": 10000,
            "spent_at": "2026-05-04T17:00:00Z",
            "manual_exchange_rate": "8",
        },
    )
    assert response.status_code == 200, response.text
    ready = response.json()
    assert ready["amount_cents"] == 80000
    assert ready["fx_rate_date"] == "2026-05-05"

    corrected = _patch(client, identity, ready, {"manual_exchange_rate": "7.5"})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["amount_cents"] == 75000
    amount_edit = _patch(client, identity, corrected.json(), {"original_amount_minor": 20000})
    assert amount_edit.status_code == 200, amount_edit.text
    assert amount_edit.json()["amount_cents"] == 150000
    assert Decimal(amount_edit.json()["fx_rate"]) == Decimal("7.5")

    changed_date = _patch(client, identity, amount_edit.json(), {"spent_at": "2026-05-06T02:00:00Z"})
    assert changed_date.status_code == 200, changed_date.text
    assert changed_date.json()["fx_status"] == "pending"
    assert changed_date.json()["fx_rate"] is None
    assert changed_date.json()["amount_cents"] is None


def test_stale_rate_and_reused_intent_key_leave_snapshot_unchanged(client, identity):
    initial = _pending(client, identity)
    key = str(uuid4())
    accepted = _patch(client, identity, initial, {"manual_exchange_rate": "7"}, key=key)
    assert accepted.status_code == 200, accepted.text
    for attempt_key in (str(uuid4()), key):
        refused = _patch(client, identity, initial, {"manual_exchange_rate": "9"}, key=attempt_key)
        assert refused.status_code in (409, 422), refused.text
    current = client.get(f"/api/expenses/{initial['id']}", headers=identity.app_headers).json()
    assert current["row_version"] == accepted.json()["row_version"]
    assert current["amount_cents"] == 86415


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", "1e3", "0.000000001", "10000000000", 7.2, True])
def test_invalid_rate_cannot_partially_edit_the_bill(client, identity, rate):
    initial = _pending(client, identity)
    response = _patch(client, identity, initial, {"manual_exchange_rate": rate, "note": "must not commit"})
    assert response.status_code == 422, response.text
    current = client.get(f"/api/expenses/{initial['id']}", headers=identity.app_headers).json()
    assert current["row_version"] == initial["row_version"]
    assert current["note"] == initial["note"]


def test_pending_rate_reuses_ledger_and_writer_permissions(client, identity):
    initial = _pending(client, identity)
    body = {"expected_row_version": initial["row_version"], "manual_exchange_rate": "7"}
    other_ledger = client.patch(
        f"/api/expenses/{initial['id']}",
        headers={**identity.gray_app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert other_ledger.status_code == 404
    with SessionLocal() as db:
        for member in db.scalars(select(LedgerMember).where(LedgerMember.ledger_id == "owner")):
            member.role = "viewer"
        db.commit()
    viewer = _patch(client, identity, initial, {"manual_exchange_rate": "7"})
    assert viewer.status_code == 403


def test_pending_rate_cannot_leak_into_confirmed_corrections(client, identity):
    initial = _pending(client, identity, currency="JPY", amount=1200)
    ready = _patch(client, identity, initial, {"manual_exchange_rate": "0.048"})
    assert ready.status_code == 200, ready.text
    assert ready.json()["amount_cents"] == 5760
    confirmed = client.post(
        f"/api/expenses/{initial['id']}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": ready.json()["row_version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    response = client.post(
        f"/api/expenses/{initial['id']}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": confirmed.json()["row_version"],
            "reason": "Not a pending edit",
            "manual_exchange_rate": "0.05",
        },
    )
    assert response.status_code == 422, response.text
    current = client.get(f"/api/expenses/{initial['id']}", headers=identity.app_headers).json()
    assert current["amount_cents"] == 5760
