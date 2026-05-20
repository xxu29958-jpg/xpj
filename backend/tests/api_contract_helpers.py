from __future__ import annotations

from datetime import datetime
from io import BytesIO
from uuid import UUID

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from tests._infra.assets import PNG_BYTES
from tests._infra.env import TEST_UPLOAD_DIR
from tests._infra.identity import TestIdentity


def upload_png(
    client: TestClient,
    *,
    identity: TestIdentity,
    headers: dict[str, str] | None = None,
    path: str | None = None,
) -> int:
    response = client.post(
        path or identity.upload_url_path,
        headers=headers if headers is not None else identity.upload_headers,
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    UUID(payload["public_id"])
    assert payload["upload_size_bytes"] == len(PNG_BYTES)
    if payload["thumbnail_path"] is not None:
        assert payload["thumbnail_path"].startswith("uploads/")
        assert ".." not in payload["thumbnail_path"]
        assert "\\" not in payload["thumbnail_path"]
        assert ":" not in payload["thumbnail_path"]
    assert "token" not in str(payload).lower()
    assert "E:\\" not in str(payload)
    assert payload["duration_ms"] >= 0
    assert payload["timing_ms"]["total_ms"] >= 0
    assert payload["timing_ms"]["form_parse_ms"] >= 0
    assert payload["timing_ms"]["file_save_ms"] >= 0
    assert payload["timing_ms"]["db_create_ms"] >= 0
    return int(payload["id"])


def upload_png_as_raw_body(client: TestClient, *, identity: TestIdentity) -> int:
    response = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["upload_size_bytes"] == len(PNG_BYTES)
    if payload["thumbnail_path"] is not None:
        assert payload["thumbnail_path"].startswith("uploads/")
        assert ".." not in payload["thumbnail_path"]
        assert "\\" not in payload["thumbnail_path"]
        assert ":" not in payload["thumbnail_path"]
    assert "token" not in str(payload).lower()
    assert "E:\\" not in str(payload)
    assert payload["duration_ms"] >= 0
    assert payload["timing_ms"]["total_ms"] >= 0
    assert payload["timing_ms"]["body_read_ms"] >= 0
    assert payload["timing_ms"]["file_save_ms"] >= 0
    assert payload["timing_ms"]["db_create_ms"] >= 0
    return int(payload["id"])


def _stored_upload_files() -> list[str]:
    if not TEST_UPLOAD_DIR.exists():
        return []
    return [str(path) for path in TEST_UPLOAD_DIR.rglob("*") if path.is_file()]


def insert_confirmed_expense(
    *,
    amount_cents: int,
    merchant: str,
    category: str,
    expense_time: datetime | None,
    confirmed_at: datetime,
) -> int:
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            merchant=merchant,
            category=category,
            note="",
            source="pytest",
            status="confirmed",
            expense_time=expense_time,
            created_at=confirmed_at,
            updated_at=confirmed_at,
            confirmed_at=confirmed_at,
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        return expense.id


def make_heic_bytes() -> bytes:
    from PIL import Image
    from pillow_heif import register_heif_opener

    register_heif_opener()
    output = BytesIO()
    Image.new("RGB", (8, 8), (31, 127, 255)).save(output, format="HEIF")
    return output.getvalue()
