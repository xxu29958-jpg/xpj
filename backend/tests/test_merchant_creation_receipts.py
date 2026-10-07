"""An original merchant/alias creation survives a lost reply and later governance."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey


def _payload(kind, name="Original store"):
    return {"display_name": name} if kind == "catalog" else {"canonical_merchant": "Canonical store", "alias": name}


@pytest.mark.parametrize("kind", ["catalog", "aliases"])
def test_creation_replays_first_receipt_after_object_changed_and_deleted(client, identity, kind):
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = _payload(kind)
    path = f"/api/merchants/{kind}"
    accepted = client.post(path, headers=headers, json=body)
    assert accepted.status_code == 201, accepted.text
    original = accepted.json()
    target = f"{path}/{original['public_id']}"
    updated = client.patch(target, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": original["row_version"],
              **({"display_name": "Peer renamed store"} if kind == "catalog" else {"alias": "Peer renamed alias"})})
    assert updated.status_code == 200, updated.text
    deleted = client.request("DELETE", target,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": updated.json()["row_version"]})
    assert deleted.status_code == 200, deleted.text

    replay = client.post(path, headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == original
    assert client.get(path, headers=identity.app_headers).json()["items"] == []
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == "owner",
            ApiIdempotencyKey.idempotency_key == key))
        assert claim.response_body == original


@pytest.mark.parametrize("kind", ["catalog", "aliases"])
def test_creation_key_cannot_change_intent_or_cross_ledger(client, identity, kind):
    key = str(uuid4())
    path = f"/api/merchants/{kind}"
    headers = {**identity.app_headers, "Idempotency-Key": key}
    first = client.post(path, headers=headers, json=_payload(kind))
    assert first.status_code == 201, first.text
    refused = client.post(path, headers=headers, json=_payload(kind, "A different intent"))
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"] == "idempotency_key_reused"
    other = client.post(path, headers={**identity.gray_app_headers, "Idempotency-Key": key}, json=_payload(kind))
    assert other.status_code == 201, other.text
    assert other.json()["public_id"] != first.json()["public_id"]
    assert client.get(path, headers=identity.app_headers).json()["items"] == [first.json()]
    assert client.get(path, headers=identity.gray_app_headers).json()["items"] == [other.json()]


@pytest.mark.parametrize("kind", ["catalog", "aliases"])
def test_creation_requires_original_key_without_writing(client, identity, kind):
    path = f"/api/merchants/{kind}"
    refused = client.post(path, headers=identity.app_headers, json=_payload(kind))
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"] == "idempotency_key_required"
    assert client.get(path, headers=identity.app_headers).json()["items"] == []


@pytest.mark.parametrize("kind", ["catalog", "aliases"])
def test_creation_and_receipt_roll_back_together(client, identity, monkeypatch, kind):
    from app.errors import AppError
    from app.services import merchant_creation_service as commands

    key = str(uuid4())
    mark = commands.mark_idempotency_succeeded

    def fail_before_commit(db, *args, **kwargs):
        mark(db, *args, **kwargs)
        db.flush()
        raise AppError("probe_failure", "Injected before the shared commit", status_code=409)

    monkeypatch.setattr(commands, "mark_idempotency_succeeded", fail_before_commit)
    path = f"/api/merchants/{kind}"
    failed = client.post(path, headers={**identity.app_headers, "Idempotency-Key": key}, json=_payload(kind))
    assert failed.status_code == 409, failed.text
    assert client.get(path, headers=identity.app_headers).json()["items"] == []
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None


@pytest.mark.parametrize("kind", ["catalog", "aliases"])
@pytest.mark.parametrize("damage", ["missing", "wrong_target", "newer_version"])
def test_creation_with_unverifiable_receipt_requires_review(client, identity, kind, damage):
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    path = f"/api/merchants/{kind}"
    first = client.post(path, headers=headers, json=_payload(kind))
    assert first.status_code == 201, first.text
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        receipt = dict(first.json())
        if damage == "wrong_target":
            receipt["public_id"] = str(uuid4())
        elif damage == "newer_version":
            receipt["row_version"] = 2
        claim.response_body = None if damage == "missing" else receipt
        db.commit()
    replay = client.post(path, headers=headers, json=_payload(kind))
    assert replay.status_code == 409, replay.text
    assert replay.json()["error"] == "merchant_creation_original_requires_review"
    assert client.get(path, headers=identity.app_headers).json()["items"] == [first.json()]


@pytest.mark.parametrize("kind", ["catalog", "aliases"])
def test_creation_receipt_cannot_bypass_revoked_write_permission(client, identity, kind):
    from tests._infra.merchant_catalog import demote_owner_ledger_to_viewer

    path = f"/api/merchants/{kind}"
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    first = client.post(path, headers=headers, json=_payload(kind))
    assert first.status_code == 201, first.text
    demote_owner_ledger_to_viewer()
    assert client.post(path, headers=headers, json=_payload(kind)).status_code == 403


@pytest.mark.parametrize("kind", ["catalog", "aliases"])
def test_web_original_form_replays_accepted_creation_after_peer_deletion(client, identity, kind):
    from contextlib import closing

    from app.routes.web_auth import SESSION_COOKIE_NAME
    from tests._web_native_form_support import hidden_post_forms
    from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

    token = mint_session(client, identity=identity)
    with closing(public_client()) as web:
        web.cookies.set(SESSION_COOKIE_NAME, token)
        headers = {"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json"}
        page = web.get("/web/merchants?ledger_id=owner&view=" + ("new" if kind == "catalog" else "aliases"))
        path = f"/web/merchants/{kind}/create"
        original_form = hidden_post_forms(page.text)[path]
        body = {**original_form, **_payload(kind, "  Original raw input  ")}
        accepted = web.post(path, data=body, headers=headers)
        assert accepted.status_code == 200, accepted.text
        result = accepted.json()
        assert result["ack"]["clientRef"] == original_form["idempotency_key"]
        receipt = result["receipt"]
        deleted = client.request("DELETE", f"/api/merchants/{kind}/{receipt['public_id']}",
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": receipt["row_version"]})
        assert deleted.status_code == 200, deleted.text
        replay = web.post(path, data=body, headers=headers)
        assert replay.status_code == 200, replay.text
        assert replay.json() == result
        assert client.get(f"/api/merchants/{kind}", headers=identity.app_headers).json()["items"] == []
