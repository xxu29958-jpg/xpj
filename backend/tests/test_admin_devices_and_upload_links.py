"""v0.3.1-alpha2 Phase 3 / 4 — admin device & UploadLink management tests.

These tests assert:

* Only admin-scope sessions can reach ``/api/admin/*`` (Phase 3 #2 + #1).
* Listings never leak token hashes or session tokens (Phase 3 #5/#6, Phase 4 #7).
* Public ids are UUIDs distinct from the database autoincrement id
  (Phase 3 #7, Phase 4 #1).
* Revoking a device kills every active auth_token + upload_link belonging to it
  (Phase 3 #3) but does not affect other devices (Phase 3 #4).
* Admins cannot revoke their own device — that requires the local PowerShell
  script (Phase 3 #10).
* Rotating an upload link issues a fresh key and immediately invalidates the
  old one (Phase 4 #3-#4). The full URL is only revealed once (Phase 4 #3).
* UploadLinks cannot read accounts, confirm expenses, or hit stats
  (Phase 4 #5-#7).
"""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AuthToken, Device, UploadLink
from app.services.identity_service import hash_secret
from conftest import (
    PNG_BYTES,
    admin_headers,
    app_headers,
    upload_url_path,
)


# ---------------------------------------------------------------------------
# Auth scope guards
# ---------------------------------------------------------------------------


def test_admin_endpoints_reject_app_scope_session(client: TestClient) -> None:
    cases = [
        ("get", "/api/admin/devices", None),
        ("get", "/api/admin/upload-links", None),
        ("post", "/api/admin/upload-links", {}),
    ]
    for method, path, body in cases:
        if body is None:
            response = getattr(client, method)(path, headers=app_headers())
        else:
            response = getattr(client, method)(path, headers=app_headers(), json=body)
        assert response.status_code in {401, 403}, (path, response.status_code)


def test_admin_endpoints_reject_anonymous(client: TestClient) -> None:
    response = client.get("/api/admin/devices")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Phase 3 — devices
# ---------------------------------------------------------------------------


def test_list_devices_returns_public_ids_not_db_ids(client: TestClient) -> None:
    response = client.get("/api/admin/devices", headers=admin_headers())
    assert response.status_code == 200
    devices = response.json()
    assert len(devices) >= 1
    for device in devices:
        # public_id must be a uuid, not a numeric autoincrement id
        UUID(device["public_id"])
        assert "id" not in device  # no leaking of internal pkey
        assert "token_hash" not in device
        assert "session_token" not in device
        assert "admin_token" not in device
        assert "Bearer" not in str(device)


def test_revoke_device_invalidates_its_tokens_and_upload_links(
    client: TestClient,
) -> None:
    # The seed creates: an "owner" admin device, plus pytest-android + tester.
    # We grab a non-admin device (the pytest-android app device) and revoke it.
    target_device_public_id = None
    target_token_hashes: list[str] = []
    target_upload_token_hashes: list[str] = []
    with SessionLocal() as db:
        for d in db.query(Device).all():
            if d.device_name == "pytest-android":
                target_device_public_id = d.public_id
                for tok in db.query(AuthToken).filter(AuthToken.device_id == d.id).all():
                    target_token_hashes.append(tok.token_hash)
                for link in db.query(UploadLink).filter(UploadLink.device_id == d.id).all():
                    target_upload_token_hashes.append(link.token_hash)
                break
    assert target_device_public_id is not None

    response = client.post(
        f"/api/admin/devices/{target_device_public_id}/revoke",
        headers=admin_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["revoked_at"]

    # The previously valid app-scope session token must now fail.
    check = client.get("/api/auth/check", headers=app_headers())
    assert check.status_code == 401
    assert check.json()["error"] == "invalid_token"

    # All matching tokens must be revoked in the database.
    with SessionLocal() as db:
        for token_hash in target_token_hashes:
            tok = (
                db.query(AuthToken)
                .filter(AuthToken.token_hash == token_hash)
                .one()
            )
            assert tok.revoked_at is not None
        for link_hash in target_upload_token_hashes:
            link = (
                db.query(UploadLink)
                .filter(UploadLink.token_hash == link_hash)
                .one()
            )
            assert link.revoked_at is not None


def test_revoke_device_does_not_affect_other_devices(client: TestClient) -> None:
    # Find the owner/admin device and the gray (tester_1) android device.
    gray_device_public_id = None
    with SessionLocal() as db:
        for d in db.query(Device).all():
            if d.device_name == "pytest-gray-android":
                gray_device_public_id = d.public_id
                break
    assert gray_device_public_id is not None

    pytest_android_pid = None
    with SessionLocal() as db:
        for d in db.query(Device).all():
            if d.device_name == "pytest-android":
                pytest_android_pid = d.public_id
                break
    assert pytest_android_pid is not None

    # Revoke the pytest-android device
    response = client.post(
        f"/api/admin/devices/{pytest_android_pid}/revoke",
        headers=admin_headers(),
    )
    assert response.status_code == 200

    # Admin still works
    listing = client.get("/api/admin/devices", headers=admin_headers())
    assert listing.status_code == 200

    # Gray device's token should not have been touched.
    with SessionLocal() as db:
        gray_device = (
            db.query(Device).filter(Device.public_id == gray_device_public_id).one()
        )
        assert gray_device.revoked_at is None
        for tok in (
            db.query(AuthToken).filter(AuthToken.device_id == gray_device.id).all()
        ):
            assert tok.revoked_at is None


def test_admin_cannot_revoke_own_device(client: TestClient) -> None:
    own_pid = None
    with SessionLocal() as db:
        for d in db.query(Device).all():
            if d.device_name == "pytest-owner":
                own_pid = d.public_id
                break
    assert own_pid is not None
    response = client.post(
        f"/api/admin/devices/{own_pid}/revoke", headers=admin_headers()
    )
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_request"


def test_revoke_unknown_device_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/admin/devices/00000000-0000-0000-0000-000000000000/revoke",
        headers=admin_headers(),
    )
    assert response.status_code == 404


def test_rename_device(client: TestClient) -> None:
    pid = None
    with SessionLocal() as db:
        for d in db.query(Device).all():
            if d.device_name == "pytest-android":
                pid = d.public_id
                break
    assert pid is not None
    response = client.post(
        f"/api/admin/devices/{pid}/rename",
        headers=admin_headers(),
        json={"device_name": "客厅 iPhone"},
    )
    assert response.status_code == 200
    assert response.json()["device_name"] == "客厅 iPhone"


# ---------------------------------------------------------------------------
# Phase 4 — UploadLinks
# ---------------------------------------------------------------------------


def test_list_upload_links_masks_full_url(client: TestClient) -> None:
    response = client.get("/api/admin/upload-links", headers=admin_headers())
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 1
    for item in items:
        UUID(item["public_id"])
        assert item["masked_url_path"] == "/u/***"
        # No raw upload key or token hash anywhere in the body
        body = str(item)
        assert "token_hash" not in body
        # The original seeded upload key value (CURRENT_UPLOAD_KEY) is a 32-char
        # hex token from new_upload_key(); make sure it is never exposed in the
        # listing.
        from conftest import CURRENT_UPLOAD_KEY  # noqa: PLC0415

        assert CURRENT_UPLOAD_KEY not in body


def test_create_upload_link_returns_secret_once(client: TestClient) -> None:
    response = client.post(
        "/api/admin/upload-links",
        headers=admin_headers(),
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["upload_url_path"].startswith("/u/")
    assert "tz=Asia/Shanghai" in payload["upload_url_path"]
    public_id = payload["link"]["public_id"]
    UUID(public_id)
    upload_path = payload["upload_url_path"].split("?")[0]
    upload_key = upload_path[len("/u/"):]

    # Listing must not expose this key.
    listing = client.get("/api/admin/upload-links", headers=admin_headers())
    listed = next(item for item in listing.json() if item["public_id"] == public_id)
    assert listed["masked_url_path"] == "/u/***"
    assert upload_key not in str(listing.json())

    # The fresh link must accept an upload (pending only) immediately.
    upload = client.post(
        f"/u/{upload_key}",
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert upload.status_code == 200
    assert upload.json()["status"] == "pending"


def test_rotate_upload_link_invalidates_old_key(client: TestClient) -> None:
    # First create one so we have a known key to rotate.
    create = client.post(
        "/api/admin/upload-links",
        headers=admin_headers(),
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200
    old_path = create.json()["upload_url_path"].split("?")[0]
    old_key = old_path[len("/u/"):]
    public_id = create.json()["link"]["public_id"]

    rotate = client.post(
        f"/api/admin/upload-links/{public_id}/rotate", headers=admin_headers()
    )
    assert rotate.status_code == 200, rotate.text
    new_payload = rotate.json()
    new_path = new_payload["upload_url_path"].split("?")[0]
    new_key = new_path[len("/u/"):]
    assert new_key != old_key

    # The new key must be a different DB record (rotate creates a new public_id).
    assert new_payload["link"]["public_id"] != public_id

    # The old key must no longer accept uploads.
    old_upload = client.post(
        f"/u/{old_key}", files={"file": ("ticket.png", PNG_BYTES, "image/png")}
    )
    assert old_upload.status_code == 401
    assert old_upload.json()["error"] == "invalid_token"

    # The new key works.
    new_upload = client.post(
        f"/u/{new_key}", files={"file": ("ticket.png", PNG_BYTES, "image/png")}
    )
    assert new_upload.status_code == 200


def test_revoke_upload_link_blocks_further_uploads(client: TestClient) -> None:
    create = client.post(
        "/api/admin/upload-links",
        headers=admin_headers(),
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200
    public_id = create.json()["link"]["public_id"]
    key = create.json()["upload_url_path"].split("?")[0][len("/u/"):]

    revoke = client.post(
        f"/api/admin/upload-links/{public_id}/revoke", headers=admin_headers()
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked_at"]

    response = client.post(
        f"/u/{key}", files={"file": ("ticket.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"

    rotate = client.post(
        f"/api/admin/upload-links/{public_id}/rotate", headers=admin_headers()
    )
    assert rotate.status_code == 409
    assert rotate.json()["error"] == "invalid_request"


def test_upload_link_cannot_read_or_confirm(client: TestClient) -> None:
    # The seeded /u/{CURRENT_UPLOAD_KEY} is an UploadLink. Use it to confirm
    # that none of the app-scope routes accept it as authentication.
    upload_path = upload_url_path()  # /u/<key>
    upload_key = upload_path[len("/u/"):]
    bearer = {"Authorization": f"Bearer {upload_key}"}

    # /api/auth/check requires app/admin scope, never upload scope.
    auth_check = client.get("/api/auth/check", headers=bearer)
    assert auth_check.status_code == 401

    # /api/expenses/pending requires app scope.
    pending = client.get("/api/expenses/pending", headers=bearer)
    assert pending.status_code == 401

    # /api/stats/monthly requires app scope.
    stats = client.get("/api/stats/monthly", headers=bearer)
    assert stats.status_code == 401


# ---------------------------------------------------------------------------
# Stored secret hygiene
# ---------------------------------------------------------------------------


def test_admin_listings_never_contain_token_hashes(client: TestClient) -> None:
    """Belt-and-braces: even after creating/rotating links and renaming
    devices, no admin response body should ever contain a known token hash.
    """

    create = client.post(
        "/api/admin/upload-links",
        headers=admin_headers(),
        json={"default_timezone": "Asia/Shanghai"},
    )
    assert create.status_code == 200

    devices = client.get("/api/admin/devices", headers=admin_headers()).json()
    links = client.get("/api/admin/upload-links", headers=admin_headers()).json()

    with SessionLocal() as db:
        token_hashes = [t.token_hash for t in db.query(AuthToken).all()]
        link_hashes = [link.token_hash for link in db.query(UploadLink).all()]

    body = str(devices) + str(links)
    for h in token_hashes + link_hashes:
        assert h not in body
    assert hash_secret("any") not in body
