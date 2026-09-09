"""API and database proof of rule original-receipt transactions."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, CategoryRule
from app.services import rule_command_service as commands


def _body(**changes):
    return {"keyword": "Travel", "category": "交通", "enabled": True, "priority": 100,
        "amount_min_cents": 1200, "home_currency_code": "JPY", **changes}


def _headers(identity, key=None):
    return {**identity.app_headers, "Idempotency-Key": key or str(uuid4())}


def _create(client, identity, *, key=None, body=None):
    response = client.post("/api/rules/categories", headers=_headers(identity, key), json=body or _body())
    assert response.status_code == 200, response.text
    return response.json()


def test_create_replay_keeps_original_receipt_after_later_edit_and_delete(client, identity):
    with SessionLocal() as db:
        baseline_ids = set(db.scalars(select(CategoryRule.id)))
    key = str(uuid4())
    original = _create(client, identity, key=key)
    path = f"/api/rules/categories/{original['id']}"
    updated = client.patch(path, headers=_headers(identity), json={"expected_row_version": original["row_version"],
        "home_currency_code": "JPY", "amount_min_cents": 2400, "keyword": "Later"})
    assert updated.status_code == 200, updated.text
    deleted = client.request("DELETE", path, headers=_headers(identity),
        json={"expected_row_version": updated.json()["row_version"]})
    assert deleted.status_code == 200, deleted.text
    assert _create(client, identity, key=key) == original
    with SessionLocal() as db:
        assert set(db.scalars(select(CategoryRule.id))) == baseline_ids | {original["id"]}
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert receipt.response_body == original
        assert receipt.resource_id == str(original["id"])


def test_update_replay_keeps_original_snapshot_after_target_is_deleted(client, identity):
    created = _create(client, identity)
    key = str(uuid4())
    body = {"expected_row_version": created["row_version"], "home_currency_code": "JPY", "amount_min_cents": 2400}
    path = f"/api/rules/categories/{created['id']}"
    accepted = client.patch(path, headers=_headers(identity, key), json=body)
    assert accepted.status_code == 200, accepted.text
    deleted = client.request("DELETE", path, headers=_headers(identity),
        json={"expected_row_version": accepted.json()["row_version"]})
    assert deleted.status_code == 200, deleted.text
    replay = client.patch(path, headers=_headers(identity, key), json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == accepted.json()


@pytest.mark.parametrize("changes", [
    {"keyword": "Other"}, {"category": "餐饮"}, {"enabled": False}, {"priority": 7},
    {"amount_min_cents": 1400}, {"home_currency_code": "CNY"}, {"source_contains": "wallet"}, {"tag_contains": "trip"},
])
def test_create_key_cannot_relabel_any_original_field(client, identity, changes):
    key = str(uuid4())
    _create(client, identity, key=key)
    response = client.post("/api/rules/categories", headers=_headers(identity, key), json=_body(**changes))
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "idempotency_key_reused"


@pytest.mark.parametrize("updating", [False, True])
def test_receipt_failure_rolls_back_business_write_and_claim(client, identity, monkeypatch, updating):
    original = _create(client, identity) if updating else None
    with SessionLocal() as db:
        baseline_ids = set(db.scalars(select(CategoryRule.id)))
    key = str(uuid4())
    mark = commands.mark_idempotency_succeeded

    def fail_receipt(*args, **kwargs):
        raise AppError("server_error", status_code=503)

    monkeypatch.setattr(commands, "mark_idempotency_succeeded", fail_receipt)
    method = "PATCH" if updating else "POST"
    path = f"/api/rules/categories/{original['id']}" if original else "/api/rules/categories"
    body = {"expected_row_version": original["row_version"], "enabled": False} if original else _body()
    failed = client.request(method, path, headers=_headers(identity, key), json=body)
    assert failed.status_code == 503, failed.text
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
        assert set(db.scalars(select(CategoryRule.id))) == baseline_ids
        if original:
            rule = db.get(CategoryRule, original["id"])
            assert rule.enabled is True
            assert rule.row_version == original["row_version"]
    monkeypatch.setattr(commands, "mark_idempotency_succeeded", mark)
    retried = client.request(method, path, headers=_headers(identity, key), json=body)
    assert retried.status_code == 200, retried.text
    with SessionLocal() as db:
        assert set(db.scalars(select(CategoryRule.id))) == baseline_ids | {retried.json()["id"]}


def test_missing_accepted_receipt_never_fetches_latest_as_success(client, identity):
    original = _create(client, identity)
    key = str(uuid4())
    body = {"expected_row_version": original["row_version"], "enabled": False}
    path = f"/api/rules/categories/{original['id']}"
    accepted = client.patch(path, headers=_headers(identity, key), json=body)
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        receipt.response_body = None
        db.commit()
    replay = client.patch(path, headers=_headers(identity, key), json=body)
    assert replay.status_code == 409, replay.text
    assert replay.json()["error"] == "rule_original_requires_review"


def test_create_key_is_ledger_scoped_and_pure_keyword_rules_need_no_currency(client, identity):
    key = str(uuid4())
    body = _body(amount_min_cents=None, home_currency_code=None)
    original = _create(client, identity, key=key, body=body)
    assert original["home_currency_code"] is None
    assert _create(client, identity, key=key, body=body) == original
    other = client.post("/api/rules/categories", headers={**identity.gray_app_headers, "Idempotency-Key": key}, json=body)
    assert other.status_code == 200, other.text
    assert other.json()["id"] != original["id"]
