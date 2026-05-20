from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import select

from api_contract_helpers import (
    _stored_upload_files,
    make_heic_bytes,
    upload_png_as_raw_body,
)
from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember
from tests._infra.env import TEST_UPLOAD_RELATIVE
from tests._infra.assets import PNG_BYTES
def test_upload_screenshot_accepts_ios_file_body(client: TestClient, *, identity) -> None:
    expense_id = upload_png_as_raw_body(client, identity=identity)

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["status"] == "pending"
    assert item["image_path"].startswith("uploads/")
    assert item["image_path"].endswith(".png")
    assert item["image_hash"]


def test_upload_passes_client_timezone_to_background_ocr(
    client: TestClient, monkeypatch
, *, identity) -> None:
    captured: dict[str, object] = {}

    def fake_enrich(
        expense_id: int, tenant_id: str, timezone_name: str | None = None
    ) -> None:
        captured["expense_id"] = expense_id
        captured["tenant_id"] = tenant_id
        captured["timezone_name"] = timezone_name

    monkeypatch.setattr("app.routes.uploads.enrich_pending_expense", fake_enrich)

    response = client.post(
        identity.upload_url_path,
        headers={
            **identity.upload_headers,
            "Content-Type": "image/png",
            "X-Timezone": "America/Los_Angeles",
        },
        content=PNG_BYTES,
    )

    assert response.status_code == 200
    assert captured["expense_id"] == response.json()["id"]
    assert captured["tenant_id"] == "owner"
    assert captured["timezone_name"] == "America/Los_Angeles"


def test_upload_screenshot_accepts_ios_image_form_field(client: TestClient, *, identity) -> None:
    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"image": ("shortcut-image.jpeg", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    expense_id = int(response.json()["id"])

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["image_path"].endswith(".png")
    assert item["image_hash"]


def test_upload_supports_absolute_upload_dir_outside_backend(
    client: TestClient,
    monkeypatch,
    tmp_path, *, identity,
) -> None:
    from app.services import file_service, thumb_service

    external_upload_dir = (tmp_path / "external-uploads").resolve()
    settings = file_service.get_settings()
    external_settings = replace(settings, upload_dir=external_upload_dir)
    monkeypatch.setattr(file_service, "get_settings", lambda: external_settings)
    monkeypatch.setattr(thumb_service, "get_settings", lambda: external_settings)

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"image": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.json()
    expense_id = int(response.json()["id"])

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["image_path"].startswith("uploads/owner/")
    assert (external_upload_dir / item["image_path"].removeprefix("uploads/")).is_file()

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 200
    assert image.content == PNG_BYTES
    if item["thumbnail_path"] is not None:
        assert item["thumbnail_path"].startswith("uploads/owner/")
        assert (external_upload_dir / item["thumbnail_path"].removeprefix("uploads/")).is_file()
        thumbnail = client.get(f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers)
        assert thumbnail.status_code == 200


def test_upload_rejects_invalid_token_before_saving_file(client: TestClient) -> None:
    response = client.post(
        "/u/bad-upload-key",
        headers={"Upload-Token": "bad-token", "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert _stored_upload_files() == []


def test_upload_link_rejects_viewer_after_role_downgrade_before_saving_file(
    client: TestClient, *, identity,
) -> None:
    with SessionLocal() as db:
        members = db.scalars(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner")
        ).all()
        assert members
        for member in members:
            member.role = "viewer"
        db.commit()

    response = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )

    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"
    assert _stored_upload_files() == []


def test_shortcut_upload_rejects_app_token_before_saving_file(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        "/api/upload-screenshot",
        headers={**identity.app_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert _stored_upload_files() == []


def test_upload_raw_body_uses_same_size_limit(client: TestClient, monkeypatch, *, identity) -> None:
    from app.routes import uploads as upload_routes
    from app.services import file_service

    small_settings = replace(file_service.get_settings(), max_upload_size_mb=0)
    monkeypatch.setattr(file_service, "get_settings", lambda: small_settings)
    monkeypatch.setattr(upload_routes, "get_settings", lambda: small_settings)

    response = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert response.status_code == 413
    assert response.json()["error"] == "file_too_large"
    assert _stored_upload_files() == []


def test_upload_rejects_empty_raw_body_and_empty_multipart_file(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=b"",
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert _stored_upload_files() == []

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_file_type"
    assert _stored_upload_files() == []


def test_upload_multipart_uses_same_size_limit(client: TestClient, monkeypatch, *, identity) -> None:
    from app.routes import uploads as upload_routes
    from app.services import file_service

    small_settings = replace(file_service.get_settings(), max_upload_size_mb=0)
    monkeypatch.setattr(file_service, "get_settings", lambda: small_settings)
    monkeypatch.setattr(upload_routes, "get_settings", lambda: small_settings)

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "file_too_large"
    assert _stored_upload_files() == []


def test_upload_rejects_unsupported_file_type(client: TestClient, *, identity) -> None:
    response = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=b"not really an image",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_file_type"
    assert _stored_upload_files() == []


def test_upload_rejects_spoofed_extension_and_content_type(client: TestClient, *, identity) -> None:
    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("fake.jpg", b"not really a jpeg", "image/jpeg")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_file_type"
    assert _stored_upload_files() == []

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("fake.png", b"\xff\xd8\xff\xe0not really a png", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_file_type"
    assert _stored_upload_files() == []


def test_upload_rejects_fake_heic_brand_without_decodable_image(
    client: TestClient, *, identity,
) -> None:
    fake_heic = b"\x00\x00\x00\x1cftypheic\x00\x00\x00\x00fake-heic-payload"

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("fake.heic", fake_heic, "image/heic")},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_file_type"
    assert _stored_upload_files() == []


def test_upload_accepts_decodable_heic_and_generates_jpeg_thumbnail(
    client: TestClient, *, identity,
) -> None:
    heic_bytes = make_heic_bytes()

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("ticket.heic", heic_bytes, "image/heic")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == payload["id"])
    assert item["image_path"].endswith(".heic")
    assert item["thumbnail_path"] is not None
    assert item["thumbnail_path"].endswith(".jpg")

    image = client.get(f"/api/expenses/{payload['id']}/image", headers=identity.app_headers)
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/heic")
    assert image.content == heic_bytes

    thumbnail = client.get(
        f"/api/expenses/{payload['id']}/thumbnail", headers=identity.app_headers
    )
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/jpeg")
    assert thumbnail.content.startswith(b"\xff\xd8")


def test_upload_uses_image_header_instead_of_spoofed_metadata(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("ticket.txt", PNG_BYTES, "text/plain")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == payload["id"])
    assert item["image_path"].endswith(".png")


def test_upload_randomizes_path_traversal_filename(client: TestClient, *, identity) -> None:
    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("../../evil.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    expense_id = int(response.json()["id"])

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["status"] == "pending"
    assert item["image_path"].startswith(f"{TEST_UPLOAD_RELATIVE}/owner/")
    assert ".." not in item["image_path"]
    assert "evil" not in item["image_path"]
    assert "\\" not in item["image_path"]
    assert ":" not in item["image_path"]


def test_upload_cleans_saved_file_when_pending_creation_fails(
    client: TestClient, monkeypatch
, *, identity) -> None:
    from app.routes import uploads as upload_routes

    def fail_create_pending(*args, **kwargs):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(upload_routes, "create_pending_expense", fail_create_pending)

    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        response = no_raise_client.post(
            identity.upload_url_path,
            headers=identity.upload_headers,
            files={"file": ("ticket.png", PNG_BYTES, "image/png")},
        )
    assert response.status_code == 500
    assert response.json()["error"] == "server_error"
    assert _stored_upload_files() == []


def test_upload_thumbnail_failure_does_not_block_pending(
    client: TestClient, monkeypatch
, *, identity) -> None:
    def fail_thumbnail(_: str | None) -> str | None:
        raise RuntimeError("thumbnail backend unavailable")

    monkeypatch.setattr(
        "app.services.expense_service._helpers.generate_thumbnail", fail_thumbnail
    )

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["thumbnail_path"] is None

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == payload["id"])
    assert item["status"] == "pending"
    assert item["thumbnail_path"] is None


def test_upload_same_image_marks_suspected_duplicate_without_rejecting(
    client: TestClient, *, identity,
) -> None:
    first = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("first.png", PNG_BYTES, "image/png")},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["status"] == "pending"

    second = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("second.png", PNG_BYTES, "image/png")},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["status"] == "pending"
    assert second_payload["duplicate_status"] == "suspected"
    assert second_payload["duplicate_of_id"] == first_payload["id"]
    assert second_payload["image_hash"] == first_payload["image_hash"]


def test_rejecting_duplicate_original_clears_other_pending_reference(
    client: TestClient, *, identity,
) -> None:
    first = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("first.png", PNG_BYTES, "image/png")},
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    second = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("second.png", PNG_BYTES, "image/png")},
    )
    assert second.status_code == 200
    second_id = second.json()["id"]
    assert second.json()["duplicate_of_id"] == first_id

    rejected = client.post(f"/api/expenses/{first_id}/reject", headers=identity.app_headers)
    assert rejected.status_code == 200

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    second_after = next(item for item in pending.json() if item["id"] == second_id)
    assert second_after["duplicate_status"] == "none"
    assert second_after["duplicate_of_id"] is None
    assert second_after["duplicate_reason"] is None


def test_upload_stores_relative_paths_and_never_confirms(client: TestClient, *, identity) -> None:
    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("user-original-name.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"

    detail = client.get(f"/api/expenses/{payload['id']}", headers=identity.app_headers)
    assert detail.status_code == 200
    expense = detail.json()
    assert expense["status"] == "pending"
    assert expense["confirmed_at"] is None
    assert expense["image_path"].startswith("uploads/")
    assert "user-original-name" not in expense["image_path"]
    assert "\\" not in expense["image_path"]
    assert ":\\" not in expense["image_path"]
    assert expense["thumbnail_path"] is None or expense["thumbnail_path"].startswith(
        "uploads/"
    )


def test_upload_screenshot_rejects_multipart_without_image_file(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"note": (None, "not an image")},
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_request",
        "message": "表单里没有找到图片文件。",
    }
