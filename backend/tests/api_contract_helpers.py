from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

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
    ``expected_row_version`` field pre-filled from the row's current
    ``updated_at``, then submit. The helper does the GET-then-POST so
    test setup blocks don't repeat that boilerplate.
    """
    snapshot = client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert snapshot.status_code == 200, snapshot.text
    return client.post(
        f"/web/expenses/{expense_id}/save",
        data={**data, "expected_row_version": snapshot.json()["row_version"]},
        follow_redirects=follow_redirects,
    )


def confirm_expense_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
) -> httpx.Response:
    """ADR-0038 PR-2b helper: POST /api/expenses/{id}/confirm with
    fresh ``expected_row_version`` from a GET snapshot. Returns the GET
    response unchanged on non-200 (so callers can assert on 404/403)."""
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.post(
        f"/api/expenses/{expense_id}/confirm",
        headers=headers,
        json={"expected_row_version": snapshot.json()["row_version"]},
    )


def reject_expense_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
) -> httpx.Response:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.post(
        f"/api/expenses/{expense_id}/reject",
        headers=headers,
        json={"expected_row_version": snapshot.json()["row_version"]},
    )


def undo_expense_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
    expected_row_version: int | None = None,
) -> httpx.Response:
    """ADR-0038 undo: restore a recently-rejected expense (5-minute window).

    PR-A added the ``expected_row_version`` OCC token. Default snapshots
    the current row's ``updated_at`` (matches the realistic banner flow:
    user just rejected, banner reads new ``updated_at``, undo POST
    carries it). Pass an explicit string to simulate stale-token race
    tests.
    """
    if expected_row_version is None:
        snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
        if snapshot.status_code != 200:
            return snapshot
        expected_row_version = snapshot.json()["row_version"]
    return client.post(
        f"/api/expenses/{expense_id}/undo",
        headers=headers,
        json={"expected_row_version": expected_row_version},
    )


def mark_not_duplicate_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
) -> httpx.Response:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.post(
        f"/api/expenses/{expense_id}/mark-not-duplicate",
        headers=headers,
        json={"expected_row_version": snapshot.json()["row_version"]},
    )


def retry_ocr_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
) -> httpx.Response:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.post(
        f"/api/expenses/{expense_id}/ocr/retry",
        headers=headers,
        json={"expected_row_version": snapshot.json()["row_version"]},
    )


def recognize_text_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
    raw_text: str,
) -> httpx.Response:
    """ADR-0038 PR-2e helper: POST /api/expenses/{id}/recognize-text with
    a fresh ``expected_row_version`` from a GET snapshot.

    Returns the GET response unchanged on non-200 so callers can assert
    on 404/403 against rejected/confirmed/cross-tenant rows without
    paying a second roundtrip.
    """
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=headers,
        json={
            "expected_row_version": snapshot.json()["row_version"],
            "raw_text": raw_text,
        },
    )


def acknowledge_items_mismatch_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
) -> httpx.Response:
    """ADR-0038 PR-2e helper: POST /api/expenses/{id}/items/acknowledge-mismatch
    with a fresh ``expected_row_version`` from a GET snapshot."""
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.post(
        f"/api/expenses/{expense_id}/items/acknowledge-mismatch",
        headers=headers,
        json={"expected_row_version": snapshot.json()["row_version"]},
    )


def expense_row_version(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
) -> int:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    assert snapshot.status_code == 200, snapshot.text
    return int(snapshot.json()["row_version"])


def replace_items_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
    items: list[dict[str, Any]],
) -> httpx.Response:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.put(
        f"/api/expenses/{expense_id}/items",
        headers=headers,
        json={"expected_row_version": snapshot.json()["row_version"], "items": items},
    )


def replace_splits_api(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
    splits: list[dict[str, Any]],
) -> httpx.Response:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    return client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=headers,
        json={"expected_row_version": snapshot.json()["row_version"], "splits": splits},
    )


def web_confirm_expense(
    client: TestClient,
    expense_id: int,
    *,
    identity: TestIdentity,
    ledger_id: str = "owner",
    follow_redirects: bool = False,
) -> httpx.Response:
    """ADR-0038 PR-2b: /web confirm form POST with fresh token."""
    snapshot = client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert snapshot.status_code == 200, snapshot.text
    return client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": ledger_id,
            "expected_row_version": snapshot.json()["row_version"],
        },
        follow_redirects=follow_redirects,
    )


def web_reject_expense(
    client: TestClient,
    expense_id: int,
    *,
    identity: TestIdentity,
    ledger_id: str = "owner",
    follow_redirects: bool = False,
) -> httpx.Response:
    snapshot = client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert snapshot.status_code == 200, snapshot.text
    return client.post(
        f"/web/expenses/{expense_id}/reject",
        data={
            "ledger_id": ledger_id,
            "expected_row_version": snapshot.json()["row_version"],
        },
        follow_redirects=follow_redirects,
    )


def web_undo_expense(
    client: TestClient,
    expense_id: int,
    *,
    ledger_id: str = "owner",
    expected_row_version: int | None = None,
    follow_redirects: bool = False,
) -> httpx.Response:
    """ADR-0038 undo: /web/expenses/{id}/undo posted from the 5s 撤销 banner.

    PR-A added the OCC token form field. Default reads the row's current
    ``updated_at`` directly from the DB (no API call — /web is
    LocalOnly and doesn't carry the app auth headers; using SessionLocal
    matches the real banner flow where the template reads from
    ``fetch_expense_row_version_in_status``). Pass an explicit value to
    test stale-token races.
    """
    if expected_row_version is None:
        with SessionLocal() as db:
            row = db.scalar(_select_expense_for_test(expense_id))
            expected_row_version = row.row_version if row else None
    return client.post(
        f"/web/expenses/{expense_id}/undo",
        data={
            "ledger_id": ledger_id,
            "expected_row_version": expected_row_version,
        },
        follow_redirects=follow_redirects,
    )


def _select_expense_for_test(expense_id: int):
    from sqlalchemy import select

    from app.models import Expense
    return select(Expense).where(Expense.id == expense_id).limit(1)


def web_duplicates_action(
    client: TestClient,
    expense_id: int,
    *,
    identity: TestIdentity,
    action: str,
    ledger_id: str = "owner",
    follow_redirects: bool = False,
) -> httpx.Response:
    """ADR-0038 PR-2b: /web/duplicates/{id}/{action} where action ∈
    {keep, reject-current, reject-original}; carries client's token."""
    snapshot = client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert snapshot.status_code == 200, snapshot.text
    return client.post(
        f"/web/duplicates/{expense_id}/{action}",
        data={
            "ledger_id": ledger_id,
            "expected_row_version": snapshot.json()["row_version"],
        },
        follow_redirects=follow_redirects,
    )


def patch_expense(
    client: TestClient,
    expense_id: int,
    *,
    headers: dict[str, str],
    fields: dict[str, Any],
    idempotency_key: str | None = None,
) -> httpx.Response:
    """Test helper: GET the expense to snapshot ``updated_at`` then PATCH
    with ``expected_row_version`` filled in (ADR-0038 PR-2a contract).

    Mirrors the production client flow (Android / /web read the row,
    then PATCH with the snapshot's ``updated_at`` as the optimistic-
    concurrency token). Tests should call this helper instead of
    bypassing the contract; the explicit stale-write tests build
    their own stale ``updated_at`` and call ``client.patch`` directly.

    ADR-0042: PATCH now requires an ``Idempotency-Key`` header. The helper
    mints a fresh UUID per call by default (each helper call is a distinct
    intent), so existing callers keep working unchanged. Pass an explicit
    ``idempotency_key`` to replay the SAME key (committed-but-unseen tests).

    Pass non-expected fields only in ``fields``; the helper fills in
    ``expected_row_version``. If the GET returns non-200 (e.g. 404
    cross-tenant), the helper returns that response so the caller can
    assert on it.
    """
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    if snapshot.status_code != 200:
        return snapshot
    key = idempotency_key or str(uuid4())
    return client.patch(
        f"/api/expenses/{expense_id}",
        headers={**headers, "Idempotency-Key": key},
        json={**fields, "expected_row_version": snapshot.json()["row_version"]},
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
