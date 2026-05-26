from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from tests._infra.assets import PNG_BYTES
from tests._infra.env import TEST_UPLOAD_DIR
from tests._infra.identity import TestIdentity


def web_save_expense(
    client: TestClient,
    expense_id: int,
    *,
    identity: TestIdentity,
    data: dict[str, Any],
    follow_redirects: bool = False,
) -> httpx.Response:
    """Test helper for the /web edit form save flow (ADR-0038 PR-2a).

    Mirrors what the real edit page does: render the form with a hidden
    ``expected_updated_at`` field pre-filled from the row's current
    ``updated_at``, then submit. The helper does the GET-then-POST so
    test setup blocks don't repeat that boilerplate.
    """
    snapshot = client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert snapshot.status_code == 200, snapshot.text
    return client.post(
        f"/web/expenses/{expense_id}/save",
        data={**data, "expected_updated_at": snapshot.json()["updated_at"]},
        follow_redirects=follow_redirects,
    )


def patch_expense(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
    fields: dict[str, Any],
) -> httpx.Response:
    """Test helper: GET the expense to snapshot ``updated_at`` then PATCH
    with ``expected_updated_at`` filled in (ADR-0038 PR-2a contract).

    Mirrors the production client flow (Android / /web read the row,
    then PATCH with the snapshot's ``updated_at`` as the optimistic-
    concurrency token). Tests should call this helper instead of
    bypassing the contract; the explicit stale-write tests build
    their own stale ``updated_at`` and call ``client.patch`` directly.

    Pass non-expected fields only in ``fields``; the helper fills in
    ``expected_updated_at``. If the GET returns non-200 (e.g. 404
    cross-tenant), the helper returns that response so the caller can
    assert on it.
    """
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.patch(
        f"/api/expenses/{expense_id}",
        headers=headers,
        json={**fields, "expected_updated_at": snapshot.json()["updated_at"]},
    )


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
