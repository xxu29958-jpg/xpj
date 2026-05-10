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


# ── v0.3-rc1-preflight: Host-header hardening ───────────────────────────────

class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in for Starlette ``Request`` used to exercise the
    network boundary helper. We avoid spinning up the full ASGI stack so we
    can vary the TCP peer address (which Starlette's TestClient pins to
    ``testclient``)."""

    def __init__(self, peer: str | None, host_header: str) -> None:
        self.client = _FakeClient(peer) if peer is not None else None
        self.headers = {"host": host_header}


def test_owner_console_local_peer_local_host_allowed() -> None:
    from app.network_boundary import require_owner_console_local

    require_owner_console_local(_FakeRequest("127.0.0.1", "127.0.0.1:8000"))
    require_owner_console_local(_FakeRequest("127.0.0.1", "localhost:8000"))
    require_owner_console_local(_FakeRequest("::1", "[::1]:8000"))


def test_owner_console_local_peer_public_host_rejected() -> None:
    """Cloudflare Tunnel forwards public traffic to 127.0.0.1, so loopback
    peer alone must not grant access. The Host header has to also look
    local, otherwise the boundary rejects with 403."""
    from app.errors import AppError
    from app.network_boundary import require_owner_console_local

    with pytest.raises(AppError) as excinfo:
        require_owner_console_local(_FakeRequest("127.0.0.1", "api.zen70.cn"))
    assert excinfo.value.status_code == 403


def test_owner_console_remote_peer_rejected() -> None:
    from app.errors import AppError
    from app.network_boundary import require_owner_console_local

    with pytest.raises(AppError):
        require_owner_console_local(_FakeRequest("203.0.113.5", "127.0.0.1:8000"))
    with pytest.raises(AppError):
        require_owner_console_local(_FakeRequest("testclient", "testserver"))


def test_admin_boundary_local_allowed() -> None:
    from app.network_boundary import require_admin_network_boundary

    require_admin_network_boundary(_FakeRequest("127.0.0.1", "127.0.0.1:8000"))


def test_admin_boundary_public_host_rejected_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.errors import AppError
    from app import network_boundary

    # Defensive: ensure the public-allow flag is not enabled by env leakage.
    monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "false")
    network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        with pytest.raises(AppError) as excinfo:
            network_boundary.require_admin_network_boundary(
                _FakeRequest("127.0.0.1", "api.zen70.cn")
            )
        assert excinfo.value.status_code == 403
    finally:
        network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]


def test_admin_boundary_public_host_allowed_when_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import network_boundary

    monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "true")
    network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        network_boundary.require_admin_network_boundary(
            _FakeRequest("127.0.0.1", "api.zen70.cn")
        )
    finally:
        monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "false")
        network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]
