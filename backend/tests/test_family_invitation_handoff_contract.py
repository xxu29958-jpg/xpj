"""Invitation entry must reuse identity and the destination session policy."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import AuthToken, Device, Invitation
from app.services.identity_service import hash_secret
from app.services.server_identity_service import read_server_data_identity
from app.services.time_service import ensure_utc, now_utc
from tests.pairing_test_support import invitation_accept_payload
from tests.test_family_ledger_permissions import (
    _assert_existing_session_invitation_rows,
    _create_family_ledger,
    _mint_foreign_ledger_invitation,
    _prepare_existing_session_invitation,
    _switch_to,
)


@pytest.mark.parametrize("public_origin", ["https://family.example.com", "", "http://localhost:8000"])
def test_created_invitation_links_use_configured_public_origin(client, identity, monkeypatch, public_origin):
    monkeypatch.setenv("PUBLIC_BASE_URL", public_origin)
    get_settings.cache_clear()
    family_id = _create_family_ledger(client, identity=identity)
    token = _switch_to(client, family_id, identity.app_headers)

    created = client.post(
        f"/api/ledgers/{family_id}/invitations",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "member"},
    )

    assert created.status_code == 201
    body = created.json()
    if public_origin == "https://family.example.com":
        assert body.get("invite_url") == f"https://family.example.com/web/auth/join#invite={body['invite_token']}"
    else:
        assert body.get("invite_url") is None
    listed = client.get(f"/api/ledgers/{family_id}/invitations", headers={"Authorization": f"Bearer {token}"})
    assert body["invite_token"] not in listed.text


def test_invitation_preview_identifies_the_server_without_consuming_it(client):
    _, invite = _mint_foreign_ledger_invitation()
    with SessionLocal() as db:
        server = read_server_data_identity(db)

    preview = client.post("/api/invitations/preview", json={"invite_token": invite})

    assert preview.status_code == 200
    assert preview.json().get("server_id") == server.server_id
    assert preview.json().get("data_generation") == server.data_generation
    with SessionLocal() as db:
        row = db.scalar(select(Invitation).where(Invitation.token_hash == hash_secret(invite)))
        assert row.used_at is None


def test_existing_identity_accepts_without_reentering_names(client, identity):
    family_id, invite = _mint_foreign_ledger_invitation()
    token = identity.app_headers["Authorization"].removeprefix("Bearer ")
    expected_expiry, account_id, counts = _prepare_existing_session_invitation(token)

    accepted = client.post(
        "/api/invitations/accept",
        headers=identity.app_headers,
        json={"invite_token": invite, "platform": "android"},
    )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["session_token"] == token
    _assert_existing_session_invitation_rows(
        family_id=family_id, account_id=account_id, token=token, counts_before=counts,
    )
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert ensure_utc(row.expires_at) == expected_expiry


def test_new_browser_invitation_uses_web_expiry_and_recovers_same_result(client):
    _, invite = _mint_foreign_ledger_invitation()
    payload = invitation_accept_payload(invite, account_name="阿青", platform="web")
    before = now_utc()

    accepted = client.post("/api/invitations/accept", json=payload)

    after = now_utc()
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["soft_refresh_after"] is None
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(body["session_token"])))
        assert db.get(Device, row.device_id).platform == "web"
        expiry = ensure_utc(row.expires_at)
        assert before + timedelta(hours=8) <= expiry <= after + timedelta(hours=8)

    retried = client.post("/api/invitations/accept", json=payload)
    assert retried.status_code == 200, retried.text
    assert retried.json() == body


def test_new_identity_requires_a_name_without_consuming_invitation(client):
    _, invite = _mint_foreign_ledger_invitation()
    payload = invitation_accept_payload(invite, account_name="   ")

    rejected = client.post("/api/invitations/accept", json=payload)

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"] == "invitation_account_name_required"
    with SessionLocal() as db:
        row = db.scalar(select(Invitation).where(Invitation.token_hash == hash_secret(invite)))
        assert row.used_at is None
