"""Catalog governance retries return the accepted operation, not today's object."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey
from app.services.merchant_catalog_service import restore_merchant_catalog


def _create(client, identity, name):
    response = client.post("/api/merchants/catalog",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={"display_name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _operation(client, identity, action):
    source = _create(client, identity, "Original source")
    path = f"/api/merchants/catalog/{source['public_id']}"
    body = {"expected_row_version": source["row_version"]}
    if action in {"merge", "merge_alias"}:
        target = _create(client, identity, "Original target")
        return "POST", path + "/merge", {**body, "target_public_id": target["public_id"],
            "target_row_version": target["row_version"],
            "alias_policy": "create_source_alias" if action == "merge_alias" else "none",
            "rewrite_historical_expenses": False}
    if action == "delete":
        return "DELETE", path, body
    return "PATCH", path, {**body, **({"status": "hidden"} if action == "hide" else {"display_name": "  Original rename  "})}


@pytest.mark.parametrize("action", ["rename", "hide", "delete", "merge", "merge_alias"])
def test_catalog_command_replays_first_receipt_after_later_governance(client, identity, action):
    method, path, body = _operation(client, identity, action)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    accepted = client.request(method, path, headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    original = accepted.json()
    source = original.get("source", original)
    assert source["row_version"] == body["expected_row_version"] + 1
    if action == "delete":
        with SessionLocal() as db:
            restore_merchant_catalog(db, tenant_id="owner", public_id=source["public_id"],
                expected_row_version=source["row_version"])
    else:
        current = original.get("target", original)
        peer = client.patch(f"/api/merchants/catalog/{current['public_id']}",
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": current["row_version"],
                **({"status": "hidden"} if "target" in original else {"display_name": "Peer rename"})})
        assert peer.status_code == 200, peer.text
    before = client.get("/api/merchants/catalog", headers=identity.app_headers).json()
    aliases = client.get("/api/merchants/aliases", headers=identity.app_headers).json()
    replay = client.request(method, path, headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == original
    assert client.get("/api/merchants/catalog", headers=identity.app_headers).json() == before
    assert client.get("/api/merchants/aliases", headers=identity.app_headers).json() == aliases
    assert len(aliases["items"]) == (1 if action == "merge_alias" else 0)
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == "owner",
            ApiIdempotencyKey.idempotency_key == key))
        assert claim.response_body == original
        assert claim.resource_id == source["public_id"]


@pytest.mark.parametrize("action", ["rename", "delete", "merge"])
def test_catalog_commands_require_original_key_before_writing(client, identity, action):
    method, path, body = _operation(client, identity, action)
    before = client.get("/api/merchants/catalog", headers=identity.app_headers).json()
    refused = client.request(method, path, headers=identity.app_headers, json=body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"] == "idempotency_key_required"
    assert client.get("/api/merchants/catalog", headers=identity.app_headers).json() == before


@pytest.mark.parametrize("action", ["rename", "hide", "delete", "merge", "merge_alias"])
def test_catalog_command_key_cannot_change_original_intent(client, identity, action):
    method, path, body = _operation(client, identity, action)
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    accepted = client.request(method, path, headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    before = client.get("/api/merchants/catalog", headers=identity.app_headers).json()
    refused = client.request(method, path, headers=headers, json={**body, "expected_row_version": 999})
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"] == "idempotency_key_reused"
    assert client.get("/api/merchants/catalog", headers=identity.app_headers).json() == before


@pytest.mark.parametrize("action", ["rename", "delete", "merge_alias"])
def test_catalog_command_and_receipt_roll_back_together(client, identity, monkeypatch, action):
    from app.errors import AppError
    from app.services import merchant_catalog_command_service as commands

    method, path, body = _operation(client, identity, action)
    before = client.get("/api/merchants/catalog", headers=identity.app_headers).json()
    key = str(uuid4())
    mark = commands.mark_idempotency_succeeded

    def fail_before_commit(db, *args, **kwargs):
        mark(db, *args, **kwargs)
        db.flush()
        raise AppError("probe_failure", "Injected before the shared commit", status_code=409)

    monkeypatch.setattr(commands, "mark_idempotency_succeeded", fail_before_commit)
    refused = client.request(method, path,
        headers={**identity.app_headers, "Idempotency-Key": key}, json=body)
    assert refused.status_code == 409, refused.text
    assert client.get("/api/merchants/catalog", headers=identity.app_headers).json() == before
    assert client.get("/api/merchants/aliases", headers=identity.app_headers).json()["items"] == []
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None


@pytest.mark.parametrize(("action", "damage"), [
    ("rename", "missing"), ("delete", "newer"), ("merge", "source"),
    ("merge", "target"), ("merge", "newer"),
])
def test_catalog_receipt_must_match_original_pair_and_versions(client, identity, action, damage):
    method, path, body = _operation(client, identity, action)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    accepted = client.request(method, path, headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    before = client.get("/api/merchants/catalog", headers=identity.app_headers).json()
    receipt = accepted.json()
    if damage in {"source", "target"}:
        receipt[damage]["public_id"] = str(uuid4())
    elif damage == "newer":
        receipt.get("target", receipt)["row_version"] += 1
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        claim.response_body = None if damage == "missing" else receipt
        db.commit()
    refused = client.request(method, path, headers=headers, json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "merchant_catalog_original_requires_review"
    assert client.get("/api/merchants/catalog", headers=identity.app_headers).json() == before


@pytest.mark.parametrize("action", ["rename", "delete", "merge"])
def test_catalog_receipt_cannot_cross_ledger_or_bypass_revoked_write_permission(client, identity, action):
    from tests._infra.merchant_catalog import demote_owner_ledger_to_viewer

    method, path, body = _operation(client, identity, action)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    accepted = client.request(method, path, headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    other = client.request(method, path, headers={**identity.gray_app_headers, "Idempotency-Key": key}, json=body)
    assert other.status_code == 404, other.text
    demote_owner_ledger_to_viewer()
    assert client.request(method, path, headers=headers, json=body).status_code == 403
