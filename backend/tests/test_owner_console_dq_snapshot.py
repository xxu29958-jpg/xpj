"""Tests for the PR19 Owner Console data-quality snapshot card."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import conftest as cf
from app.main import app
from app.routes.owner_console import _require_local


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _upload(client: TestClient) -> int:
    resp = client.post(
        f"/u/{cf.CURRENT_UPLOAD_KEY}",
        headers={"Content-Type": "image/png"},
        content=PNG,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_owner_index_renders_dq_snapshot(local_client: TestClient) -> None:
    body = local_client.get("/owner").text
    assert "运营快照" in body
    assert "可一键入账" in body
    assert "疑似重复" in body


def test_owner_index_dq_counts_update_after_upload(local_client: TestClient) -> None:
    # Two uploads with the same image hash → second is flagged suspected.
    _upload(local_client)
    _upload(local_client)
    body = local_client.get("/owner").text
    assert "运营快照" in body
    # Quick link to the new /web pages is rendered.
    assert "/web/duplicates" in body
    assert "/web/data-quality" in body
    assert "/web/categories/uncategorized" in body
    assert "/web/import" in body
    assert "/web/export.csv" in body


def test_owner_index_dq_no_secret_leak(local_client: TestClient) -> None:
    _upload(local_client)
    body = local_client.get("/owner").text
    assert cf.CURRENT_APP_TOKEN not in body
    assert cf.CURRENT_ADMIN_TOKEN not in body
    assert cf.CURRENT_UPLOAD_KEY not in body
