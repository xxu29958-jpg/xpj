"""Actual image route responses with temporary files and a scoped row lookup."""

from __future__ import annotations

import asyncio
import hashlib
from email.utils import formatdate
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth import get_current_app_context
from app.database import get_db
from app.errors import AppError, add_exception_handlers
from app.routes import expenses, web_media
from app.services import file_service
from app.services.expense_service import _image

ORIGINAL = b"the admitted original image bytes"


@pytest.fixture
def image_route(monkeypatch, tmp_path):
    upload_root = tmp_path / "uploads"
    original = upload_root / "owner" / "receipt.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(ORIGINAL)
    row = SimpleNamespace(
        id=1, tenant_id="owner", image_path="uploads/owner/receipt.png",
        image_hash=hashlib.sha256(ORIGINAL).hexdigest(), image_deleted_at=None,
    )
    monkeypatch.setattr(file_service, "get_settings", lambda: SimpleNamespace(upload_dir=upload_root))

    def lookup(_db, expense_id, tenant_id):
        assert expense_id == 1
        if tenant_id != row.tenant_id:
            raise AppError("expense_not_found", status_code=404)
        return row

    monkeypatch.setattr(_image, "get_expense", lookup)
    monkeypatch.setattr(web_media, "_resolve_selected_ledger_id", lambda _db, ledger_id, **_kw: ledger_id)

    def route(surface, ledger_id="owner"):
        if surface == "api":
            return expenses.get_expense_image(1, auth=SimpleNamespace(tenant_id=ledger_id), db=object())
        return web_media.web_image(
            Request({"type": "http", "headers": []}), 1, ledger_id=ledger_id, db=object(),
        )

    return original, row, route


async def _deliver(response, *, method="GET", headers=(), extensions=None, fail_send=None):
    messages = []

    async def send(message):
        if message["type"] == "http.response.body" and fail_send is not None:
            raise fail_send
        messages.append(message)

    async def receive():
        return {"type": "http.disconnect"}

    await response(
        {"type": "http", "method": method, "headers": list(headers), "extensions": extensions or {}},
        receive, send,
    )
    return messages


@pytest.mark.parametrize("surface", ["api", "web"])
def test_image_route_rejects_replaced_original(image_route, surface):
    original, row, route = image_route
    original.write_bytes(b"different image behind the same reference")
    with pytest.raises(AppError) as rejected:
        route(surface)
    assert (rejected.value.error, rejected.value.status_code) == ("image_integrity_mismatch", 409)
    assert row.image_hash == hashlib.sha256(ORIGINAL).hexdigest()


@pytest.mark.parametrize("surface", ["api", "web"])
def test_route_delivers_checked_snapshot_after_original_changes(image_route, surface):
    original, row, route = image_route
    response = route(surface)
    snapshot = Path(response.path)
    assert snapshot != original
    original.write_bytes(b"a later replacement")
    messages = asyncio.run(_deliver(response, extensions={"http.response.pathsend": {}}))
    assert messages[0]["status"] == 200
    assert all(message["type"] != "http.response.pathsend" for message in messages)
    assert b"".join(message.get("body", b"") for message in messages) == ORIGINAL
    assert not snapshot.exists()
    assert original.read_bytes() == b"a later replacement"
    assert row.image_deleted_at is None


@pytest.mark.parametrize("surface", ["api", "web"])
def test_image_route_keeps_scoped_lookup_and_deleted_guard(image_route, surface):
    _, row, route = image_route
    with pytest.raises(AppError) as forbidden:
        route(surface, "another-ledger")
    assert forbidden.value.error == "expense_not_found"
    row.image_deleted_at = "intentionally cleaned"
    with pytest.raises(AppError) as cleaned:
        route(surface)
    assert cleaned.value.error == "image_not_found"


@pytest.mark.parametrize("method,range_value,status", [
    ("GET", None, 200), ("HEAD", None, 200), ("GET", b"bytes=4-9", 206),
    ("HEAD", b"bytes=4-9", 206), ("GET", b"bytes=0-2,8-10", 206),
    ("GET", b"bytes=900-", 416), ("GET", b"nonsense", 400),
])
def test_file_response_range_head_and_error_cleanup(image_route, method, range_value, status):
    _, _, route = image_route
    response = route("api")
    snapshot = Path(response.path)
    headers = [(b"range", range_value)] if range_value is not None else []
    messages = asyncio.run(_deliver(response, method=method, headers=headers))
    assert messages[0]["status"] == status
    response_headers = dict(messages[0]["headers"])
    body = b"".join(message.get("body", b"") for message in messages)
    if method == "HEAD":
        assert body == b""
    elif range_value == b"bytes=4-9":
        assert body == ORIGINAL[4:10]
        assert response_headers[b"content-range"] == f"bytes 4-9/{len(ORIGINAL)}".encode()
    elif range_value == b"bytes=0-2,8-10":
        assert response_headers[b"content-type"].startswith(b"multipart/byteranges;")
        assert ORIGINAL[0:3] in body and ORIGINAL[8:11] in body
    elif status == 200:
        assert body == ORIGINAL
        assert response_headers[b"accept-ranges"] == b"bytes"
        assert b"content-encoding" not in response_headers
    assert not snapshot.exists()


@pytest.mark.parametrize("failure", [OSError("disconnected"), asyncio.CancelledError()])
def test_send_failure_or_cancel_cleans_snapshot(image_route, failure):
    original, _, route = image_route
    response = route("web")
    snapshot = Path(response.path)
    with pytest.raises(type(failure)):
        asyncio.run(_deliver(response, fail_send=failure))
    assert not snapshot.exists()
    assert original.read_bytes() == ORIGINAL


def test_cache_validators_and_if_range_are_stable_across_snapshots(image_route):
    original, _, route = image_route
    first = asyncio.run(_deliver(route("api")))
    second = asyncio.run(_deliver(route("api")))
    first_headers, second_headers = dict(first[0]["headers"]), dict(second[0]["headers"])
    for name in (b"etag", b"last-modified", b"content-length"):
        assert first_headers[name] == second_headers[name]
    assert first_headers[b"etag"] == f'"{hashlib.sha256(ORIGINAL).hexdigest()}"'.encode()
    assert first_headers[b"last-modified"] == formatdate(original.stat().st_mtime, usegmt=True).encode()
    ranged = asyncio.run(_deliver(route("api"), headers=[
        (b"range", b"bytes=0-3"), (b"if-range", first_headers[b"etag"]),
    ]))
    assert ranged[0]["status"] == 206
    assert b"".join(message.get("body", b"") for message in ranged) == ORIGINAL[:4]


def test_actual_http_route_keeps_auth_error_and_binary_contract(image_route):
    original, row, _ = image_route
    app = FastAPI()
    app.include_router(expenses.router)
    add_exception_handlers(app)
    app.dependency_overrides[get_db] = object
    with TestClient(app) as client:
        unauthenticated = client.get("/api/expenses/1/image")
        assert unauthenticated.status_code == 401
        app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="owner")
        accepted = client.get("/api/expenses/1/image", headers={"Range": "bytes=0-3", "Accept-Encoding": "gzip"})
        assert accepted.status_code == 206
        assert accepted.content == ORIGINAL[:4]
        assert "content-encoding" not in accepted.headers
        original.write_bytes(b"corrupt file at the saved path")
        rejected = client.get("/api/expenses/1/image")
        assert rejected.status_code == 409
        assert rejected.json()["error"] == "image_integrity_mismatch"
    assert row.image_hash == hashlib.sha256(ORIGINAL).hexdigest()
