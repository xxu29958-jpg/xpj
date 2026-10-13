"""Reference Library creation is useful before the first expense and safe to retry."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, CategoryPreference, Expense, Tag
from tests._infra.tag_helpers import demote_owner_to_viewer
from tests._web_native_form_support import hidden_post_forms


@pytest.fixture(params=[("tag", "/api/tags", "/api/expenses/tags", Tag),
                        ("category", "/api/expenses/categories/preferences", "/api/expenses/categories", CategoryPreference)])
def reference(request):
    return request.param


def test_create_before_first_expense_is_selectable_and_keeps_original_receipt(client, identity, reference):
    kind, path, choices, model = reference
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    created = client.post(path, headers=headers, json={"name": "  暑期旅行  "})
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert receipt["name"] == "暑期旅行" and receipt["kind"] == kind
    assert "暑期旅行" in client.get(choices, headers=identity.app_headers).json()["items"]
    listed = client.get(path, headers=identity.app_headers).json()["items"]
    assert [(item["public_id"], item["usage_count"]) for item in listed] == [(receipt["public_id"], 0)]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 0

    # A response can be lost and the reference removed before the original task retries.
    removed = client.post(f"{path}/{receipt['public_id']}/delete", headers=identity.app_headers,
                          json={"expected_row_version": receipt["row_version"]})
    assert removed.status_code == 200, removed.text
    replay = client.post(path, headers=headers, json={"name": "  暑期旅行  "})
    assert replay.status_code == 201 and replay.json() == receipt
    assert "暑期旅行" not in client.get(choices, headers=identity.app_headers).json()["items"]
    with SessionLocal() as db:
        row = db.scalar(select(model).where(model.public_id == receipt["public_id"]))
        assert row.deleted_at is not None and row.row_version == receipt["row_version"] + 1
        assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.scalar(select(func.count()).select_from(ApiIdempotencyKey)) == 1


def test_duplicate_and_deleted_names_do_not_replace_identity_or_consume_restore(client, identity, reference):
    kind, path, _, model = reference
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    created = client.post(path, headers=headers, json={"name": "Trip"})
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert client.post(path, headers=headers, json={"name": "Changed"}).json()["error"] == "idempotency_key_reused"
    for deleted in (False, True):
        if deleted:
            response = client.post(f"{path}/{receipt['public_id']}/delete", headers=identity.app_headers,
                                   json={"expected_row_version": receipt["row_version"]})
            assert response.status_code == 200, response.text
        duplicate = client.post(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
                                json={"name": " trip "})
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"] == "reference_name_conflict"
        assert duplicate.json()["deleted"] is deleted
        assert duplicate.json()["public_id"] == receipt["public_id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.scalar(select(func.count()).select_from(ApiIdempotencyKey)) == 1
    if kind == "tag":
        restored = client.post(f"/api/tags/mutations/{response.json()['mutation_public_id']}/undo",
            headers=identity.app_headers, json={"expected_row_version": response.json()["source_tag_row_version"]})
    else:
        restored = client.post(f"{path}/{receipt['public_id']}/restore", headers=identity.app_headers,
            json={"expected_row_version": response.json()["row_version"]})
    assert restored.status_code == 200, restored.text


def test_creation_requires_writer_and_key_without_leaving_facts(client, identity, reference):
    _, path, _, model = reference
    assert client.post(path, headers=identity.app_headers, json={"name": "Trip"}).status_code == 422
    demote_owner_to_viewer()
    response = client.post(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={"name": "Trip"})
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(ApiIdempotencyKey)) == 0


def test_first_financial_use_consumes_the_prepared_reference(client, identity, reference):
    kind, path, _, model = reference
    response = client.post(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={"name": "Trip"})
    assert response.status_code == 201, response.text
    public_id = response.json()["public_id"]
    created = client.post("/api/expenses/manual", headers=identity.app_headers, json={
        "client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1250,
        "merchant": "提前准备资料", "category": "Trip" if kind == "category" else "餐饮",
        "tags": "Trip" if kind == "tag" else None, "expense_time": "2026-10-07T12:00:00Z"})
    assert created.status_code == 200, created.text
    items = client.get(path, headers=identity.app_headers).json()["items"]
    assert [(item["public_id"], item["usage_count"]) for item in items] == [(public_id, 1)]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(model)) == 1
        expense = db.scalar(select(Expense))
        assert expense.amount_cents == 1250 and expense.merchant == "提前准备资料"


def test_native_web_failure_retains_name_key_and_return_context(web_client, reference):
    kind, _, _, _ = reference
    target = f"/web/reference/{kind}/create"
    opened = web_client.get(f"/web/reference/{kind}/new?ledger_id=owner&month=2026-09&unused=1")
    assert opened.status_code == 200, opened.text
    original = hidden_post_forms(opened.text)[target]
    original["name"] = "Trip"
    accepted = web_client.post(target, data=original, follow_redirects=False)
    assert accepted.status_code == 303, accepted.text
    assert "month=2026-09" in accepted.headers["location"] and "unused=1" in accepted.headers["location"]
    duplicate = {**original, "idempotency_key": str(uuid4()), "name": "trip"}
    rejected = web_client.post(target, data=duplicate, follow_redirects=False)
    assert rejected.status_code == 409, rejected.text
    retained = hidden_post_forms(rejected.text)[target]
    assert all(retained[field] == duplicate[field] for field in ("ledger_id", "month", "unused", "idempotency_key", "draft_scope"))
    assert 'value="trip"' in rejected.text
    # Explicit review prepares a distinct intent without creating anything.
    prepared = web_client.post(target, data={**duplicate, "review_new": "true"})
    assert prepared.status_code == 200
    continued = hidden_post_forms(prepared.text)[target]
    assert continued["idempotency_key"] != duplicate["idempotency_key"] and 'value="trip"' in prepared.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ApiIdempotencyKey)) == 1


@pytest.mark.parametrize("path,name", [("/api/tags", "one,two"), ("/api/tags", "one\ntwo"),
    ("/api/tags", "ß" * 64), ("/api/expenses/categories/preferences", "ß" * 64),
    ("/api/expenses/categories/preferences", "   ")])
def test_names_cannot_split_one_reference_or_overflow_the_lookup_key(client, identity, path, name):
    response = client.post(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={"name": name})
    assert response.status_code == 422, response.text
