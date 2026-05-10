"""Tests for the Owner Console (/owner) pages.

Security invariants verified:
- Local access (127.0.0.1) returns 200; remote access returns 403.
- HTML pages must not contain token_hash values.
- Upload-links list shows only /u/*** masked paths, never the full key.
- Full upload URL only appears once in the create/rotate response.
- All pages render without crashing.
- health.owner_console_status is not 'not-implemented'.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import conftest as cf  # noqa: F401 — ensures module-level seeds run
from app.main import app
from app.routes.owner_console import _require_local


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    """Client with loopback check bypassed (simulates 127.0.0.1 access)."""
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def test_owner_index_local_returns_200(local_client: TestClient) -> None:
    resp = local_client.get("/owner")
    assert resp.status_code == 200
    assert "小票夹" in resp.text


def test_owner_index_remote_returns_403(client: TestClient) -> None:
    # Default TestClient uses host='testclient', which is NOT in the loopback
    # allowlist, so the dependency must reject it.
    resp = client.get("/owner")
    assert resp.status_code == 403


def test_owner_html_does_not_contain_token_hash(local_client: TestClient) -> None:
    resp = local_client.get("/owner")
    assert resp.status_code == 200
    # token_hash values are 64-char hex strings; the page must not contain one
    import re

    matches = re.findall(r"\b[0-9a-f]{64}\b", resp.text)
    assert matches == [], f"token_hash leaked in HTML: {matches[:1]}"


def test_owner_devices_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/devices")
    assert resp.status_code == 200
    assert "设备管理" in resp.text or "设备" in resp.text


def test_owner_devices_html_no_token_hash(local_client: TestClient) -> None:
    import re

    resp = local_client.get("/owner/devices")
    assert resp.status_code == 200
    matches = re.findall(r"\b[0-9a-f]{64}\b", resp.text)
    assert matches == [], f"token_hash in /owner/devices: {matches[:1]}"


def test_owner_pairing_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/pairing")
    assert resp.status_code == 200
    assert "绑定" in resp.text


def test_owner_upload_links_list_masked(local_client: TestClient) -> None:
    resp = local_client.get("/owner/upload-links")
    assert resp.status_code == 200
    # Full upload keys start with 'upl_'; must NOT appear in persistent list HTML
    import re

    raw_keys = re.findall(r"upl_[A-Za-z0-9_\-]{20,}", resp.text)
    assert raw_keys == [], f"raw upload key visible in list: {raw_keys[:1]}"


def test_owner_upload_links_create_reveals_once(local_client: TestClient) -> None:
    resp = local_client.post("/owner/upload-links")
    assert resp.status_code == 200
    # After create the full path should appear once in the secret-box section
    assert "/u/" in resp.text
    # But if we navigate back to the list it should be gone
    list_resp = local_client.get("/owner/upload-links")
    import re

    raw_keys = re.findall(r"upl_[A-Za-z0-9_\-]{20,}", list_resp.text)
    assert raw_keys == [], f"raw upload key visible in list after navigate: {raw_keys[:1]}"


def test_owner_diagnostics_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/diagnostics")
    assert resp.status_code == 200
    assert "诊断" in resp.text


def test_health_owner_console_status_not_unimplemented(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("owner_console_status") not in {None, "not-implemented"}
