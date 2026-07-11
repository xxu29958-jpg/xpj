"""Admin UploadLink lifecycle, isolation, and secret-hygiene tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AuthToken, UploadLink
from app.services.identity_service import hash_secret
from app.services.time_service import ensure_utc, now_utc
from tests._infra.admin_device_upload_link import (
    insert_external_device_and_upload_link,
)
from tests._infra.assets import PNG_BYTES


def test_list_upload_links_masks_full_url(client: TestClient, *, identity) -> None:
    response = client.get("/api/admin/upload-links", headers=identity.admin_headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 1
    for item in items:
        UUID(item["public_id"])
        assert item["masked_url_path"] == "/u/***"
        assert item["expires_at"] is not None
        assert item["is_expired"] is False
        body = str(item)
        assert "token_hash" not in body
        assert identity.upload_key not in body


def test_admin_upload_link_management_is_scoped_to_visible_ledgers(
    client: TestClient,
    *,
    identity,
) -> None:
    _, external_link_public_id = insert_external_device_and_upload_link()

    response = client.get("/api/admin/upload-links", headers=identity.admin_headers)
    assert response.status_code == 200
    assert external_link_public_id not in response.text

    revoke = client.post(
        f"/api/admin/upload-links/{external_link_public_id}/revoke",
        headers=identity.admin_headers,
    )
    assert revoke.status_code == 404

    create = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"ledger_id": "external_admin_boundary", "default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 404


def test_create_upload_link_returns_secret_once(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["upload_url_path"].startswith("/u/")
    assert "tz=Asia/Shanghai" in payload["upload_url_path"]
    public_id = payload["link"]["public_id"]
    assert payload["link"]["expires_at"] is not None
    assert payload["link"]["is_expired"] is False
    UUID(public_id)
    upload_path = payload["upload_url_path"].split("?")[0]
    upload_key = upload_path[len("/u/") :]

    listing = client.get("/api/admin/upload-links", headers=identity.admin_headers)
    listed = next(item for item in listing.json() if item["public_id"] == public_id)
    assert listed["masked_url_path"] == "/u/***"
    assert upload_key not in str(listing.json())

    upload = client.post(
        f"/u/{upload_key}",
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert upload.status_code == 200
    assert upload.json()["status"] == "pending"


def test_rotate_upload_link_invalidates_old_key(client: TestClient, *, identity) -> None:
    create = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200
    old_path = create.json()["upload_url_path"].split("?")[0]
    old_key = old_path[len("/u/") :]
    public_id = create.json()["link"]["public_id"]

    rotate = client.post(
        f"/api/admin/upload-links/{public_id}/rotate", headers=identity.admin_headers
    )
    assert rotate.status_code == 200, rotate.text
    new_payload = rotate.json()
    new_path = new_payload["upload_url_path"].split("?")[0]
    new_key = new_path[len("/u/") :]
    assert new_key != old_key
    assert new_payload["link"]["public_id"] != public_id

    old_upload = client.post(
        f"/u/{old_key}", files={"file": ("ticket.png", PNG_BYTES, "image/png")}
    )
    assert old_upload.status_code == 401
    assert old_upload.json()["error"] == "invalid_token"
    new_upload = client.post(
        f"/u/{new_key}", files={"file": ("ticket.png", PNG_BYTES, "image/png")}
    )
    assert new_upload.status_code == 200


def test_rotate_upload_link_rejects_expired_link(
    client: TestClient,
    *,
    identity,
) -> None:
    create = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200
    public_id = create.json()["link"]["public_id"]
    with SessionLocal() as db:
        link = db.query(UploadLink).filter(UploadLink.public_id == public_id).one()
        link.expires_at = now_utc() - timedelta(minutes=1)
        db.commit()

    response = client.post(
        f"/api/admin/upload-links/{public_id}/rotate", headers=identity.admin_headers
    )
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_request"


def test_extend_upload_link_renews_expiry_without_rotating_key(
    client: TestClient,
    *,
    identity,
) -> None:
    create = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200
    public_id = create.json()["link"]["public_id"]
    key = create.json()["upload_url_path"].split("?")[0][len("/u/") :]
    old_expiry = now_utc() + timedelta(days=1)
    with SessionLocal() as db:
        link = db.query(UploadLink).filter(UploadLink.public_id == public_id).one()
        link.expires_at = old_expiry
        db.commit()

    response = client.post(
        f"/api/admin/upload-links/{public_id}/extend",
        headers=identity.admin_headers,
    )
    assert response.status_code == 200, response.text
    new_expiry = ensure_utc(
        datetime.fromisoformat(response.json()["expires_at"].replace("Z", "+00:00"))
    )
    assert new_expiry is not None
    assert new_expiry > ensure_utc(old_expiry + timedelta(days=89))
    upload = client.post(
        f"/u/{key}", files={"file": ("ticket.png", PNG_BYTES, "image/png")}
    )
    assert upload.status_code == 200


def test_extend_upload_link_rejects_expired_link(
    client: TestClient,
    *,
    identity,
) -> None:
    create = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200
    public_id = create.json()["link"]["public_id"]
    with SessionLocal() as db:
        link = db.query(UploadLink).filter(UploadLink.public_id == public_id).one()
        link.expires_at = now_utc() - timedelta(minutes=1)
        db.commit()

    response = client.post(
        f"/api/admin/upload-links/{public_id}/extend",
        headers=identity.admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_request"


def test_revoke_upload_link_blocks_further_uploads(
    client: TestClient,
    *,
    identity,
) -> None:
    create = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200
    public_id = create.json()["link"]["public_id"]
    key = create.json()["upload_url_path"].split("?")[0][len("/u/") :]

    revoke = client.post(
        f"/api/admin/upload-links/{public_id}/revoke", headers=identity.admin_headers
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked_at"]

    response = client.post(
        f"/u/{key}", files={"file": ("ticket.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    rotate = client.post(
        f"/api/admin/upload-links/{public_id}/rotate", headers=identity.admin_headers
    )
    assert rotate.status_code == 409
    assert rotate.json()["error"] == "invalid_request"


def test_upload_link_cannot_read_or_confirm(client: TestClient, *, identity) -> None:
    upload_key = identity.upload_url_path[len("/u/") :]
    bearer = {"Authorization": f"Bearer {upload_key}"}

    assert client.get("/api/auth/check", headers=bearer).status_code == 401
    assert client.get("/api/expenses/pending", headers=bearer).status_code == 401
    assert client.get("/api/stats/monthly", headers=bearer).status_code == 401


def test_admin_listings_never_contain_token_hashes(
    client: TestClient,
    *,
    identity,
) -> None:
    create = client.post(
        "/api/admin/upload-links",
        headers=identity.admin_headers,
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200

    devices = client.get("/api/admin/devices", headers=identity.admin_headers).json()
    links = client.get("/api/admin/upload-links", headers=identity.admin_headers).json()
    with SessionLocal() as db:
        token_hashes = [token.token_hash for token in db.query(AuthToken).all()]
        link_hashes = [link.token_hash for link in db.query(UploadLink).all()]

    body = str(devices) + str(links)
    for secret_hash in token_hashes + link_hashes:
        assert secret_hash not in body
    assert hash_secret("any") not in body
