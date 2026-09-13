"""Spending-goal creation and its accepted receipt commit together."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, Goal
from app.services import goal_create_command as commands
from tests.debt_repayment_goal_helpers import _create_external_debt


def _body(**changes):
    return {"name": "Travel", "month": "2026-09", "category": "交通",
        "target_amount_cents": 1200, "home_currency_code": "JPY", **changes}


def _headers(identity, key):
    return {**identity.app_headers, "Idempotency-Key": key}


@pytest.mark.parametrize("key", [None, "x" * 65])
def test_spending_create_requires_a_storable_original_key(client, identity, key):
    headers = identity.app_headers if key is None else _headers(identity, key)
    response = client.post("/api/goals", headers=headers, json=_body())
    assert response.status_code == 422, response.text
    assert response.json()["error"] == ("idempotency_key_required" if key is None else "invalid_request")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Goal)) == 0


def test_create_replays_original_receipt_after_edit_and_archive(client, identity):
    key = str(uuid4())
    headers = _headers(identity, key)
    first = client.post("/api/goals", headers=headers, json=_body())
    assert first.status_code == 201, first.text
    goal = first.json()
    later = client.patch(f"/api/goals/{goal['public_id']}", headers=_headers(identity, str(uuid4())),
        json={"home_currency_code": "JPY", "target_amount_cents": 2400, "expected_row_version": goal["row_version"]})
    assert later.status_code == 200, later.text
    archived = client.post(f"/api/goals/{goal['public_id']}/archive", headers=identity.app_headers)
    assert archived.status_code == 200, archived.text
    replay = client.post("/api/goals", headers=headers, json=_body())
    assert replay.status_code == 201, replay.text
    assert replay.json() == goal
    assert goal["home_currency_code"] == "JPY"
    assert goal["target_amount_cents"] == 1200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Goal)) == 1
        current = db.scalar(select(Goal).where(Goal.public_id == goal["public_id"]))
        assert (current.status, current.target_amount_cents) == ("archived", 2400)
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert receipt.response_body == goal
        assert receipt.resource_id == goal["public_id"]


@pytest.mark.parametrize("changes", [
    {"home_currency_code": "CNY"}, {"target_amount_cents": 1400}, {"name": "Different"},
    {"month": "2026-10"}, {"category": "餐饮"},
])
def test_create_same_key_cannot_change_original_intent(client, identity, changes):
    headers = _headers(identity, str(uuid4()))
    first = client.post("/api/goals", headers=headers, json=_body())
    assert first.status_code == 201, first.text
    reused = client.post("/api/goals", headers=headers, json=_body(**changes))
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"


def test_receipt_failure_rolls_back_goal_and_key_then_same_intent_can_retry(client, identity, monkeypatch):
    key = str(uuid4())
    original = commands.mark_idempotency_succeeded

    def fail_receipt(*args, **kwargs):
        raise AppError("server_error", status_code=503)

    monkeypatch.setattr(commands, "mark_idempotency_succeeded", fail_receipt)
    failed = client.post("/api/goals", headers=_headers(identity, key), json=_body())
    assert failed.status_code == 503, failed.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Goal)) == 0
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
    monkeypatch.setattr(commands, "mark_idempotency_succeeded", original)
    retried = client.post("/api/goals", headers=_headers(identity, key), json=_body())
    assert retried.status_code == 201, retried.text


def test_goal_create_key_is_scoped_to_ledger(client, identity):
    key = str(uuid4())
    first = client.post("/api/goals", headers=_headers(identity, key), json=_body())
    other = client.post("/api/goals", headers={**identity.gray_app_headers, "Idempotency-Key": key}, json=_body())
    assert first.status_code == other.status_code == 201, (first.text, other.text)
    assert first.json()["public_id"] != other.json()["public_id"]
    assert first.json()["ledger_id"] != other.json()["ledger_id"]


def test_debt_clearance_goal_keeps_keyless_nonmonetary_create(client, identity):
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    response = client.post("/api/goals", headers=identity.app_headers, json={
        "name": "Clear debt", "goal_type": "debt_repayment", "debt_public_ids": [debt["public_id"]],
    })
    assert response.status_code == 201, response.text
    assert response.json()["home_currency_code"] is None
    assert response.json()["target_amount_cents"] is None
    assert response.json()["debt_repayment"] is not None
