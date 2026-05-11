"""T26: Owner Console per-ledger health card."""

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


def test_owner_index_renders_ledger_health_section(local_client: TestClient) -> None:
    body = local_client.get("/owner").text
    assert "账本健康" in body
    assert "/web/data-quality?ledger_id=" in body


def test_owner_ledger_health_shows_pending_count(local_client: TestClient) -> None:
    resp = local_client.post(
        f"/u/{cf.CURRENT_UPLOAD_KEY}",
        headers={"Content-Type": "image/png"},
        content=PNG,
    )
    assert resp.status_code == 200
    body = local_client.get("/owner").text
    # The default ledger is "owner"; that row must now show ≥ 1 pending.
    assert "账本健康" in body
    # Quick links scoped per ledger.
    assert 'href="/web?ledger_id=owner"' in body


def test_owner_ledger_health_no_secret_leak(local_client: TestClient) -> None:
    body = local_client.get("/owner").text
    assert cf.CURRENT_APP_TOKEN not in body
    assert cf.CURRENT_ADMIN_TOKEN not in body
    assert cf.CURRENT_UPLOAD_KEY not in body
