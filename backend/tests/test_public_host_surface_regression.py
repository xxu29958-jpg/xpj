"""Public-host surface regression bundle (v1.0 PR-5).

After PR-1 .. PR-4 wired the Web session cookie flow, this file is the
single integration check that the public-host attack surface is exactly
what the runbook (\\docs/runbook/CLOUDFLARE_TUNNEL.md§\"公网路由分层\") says
it is: only the documented allowlist responds successfully, everything
else stays denied.

Each test simulates a request *as if it had been forwarded by Cloudflare
Tunnel* — peer is a routable IP and Host is a public DNS name — so the
middleware (\\app/middleware/web_session.py) treats it as public mode
instead of taking the loopback / TestClient carve-out.

If any of these regress, the public Host attack surface widened.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import app
from app.network_boundary import require_admin_network_boundary
from app.routes.web_auth import SESSION_COOKIE_NAME

PUBLIC_HOST = "api.example.com"


def _public_client() -> TestClient:
    return TestClient(
        app,
        base_url=f"http://{PUBLIC_HOST}",
        client=("203.0.113.10", 50001),
    )


@contextmanager
def _real_admin_boundary() -> Iterator[None]:
    """The default conftest TestClient overrides ``require_admin_network_boundary``
    with a no-op so admin-tagged business tests can run. Public-host
    regression tests need the REAL boundary to fire — temporarily lift
    the override, restore on exit."""

    override = app.dependency_overrides.pop(require_admin_network_boundary, None)
    try:
        yield
    finally:
        if override is not None:
            app.dependency_overrides[require_admin_network_boundary] = override


# ── /owner is loopback only forever ─────────────────────────────────────────


def test_public_host_owner_console_403(client: TestClient) -> None:
    pub = _public_client()
    for path in ("/owner", "/owner/devices", "/owner/upload-links", "/owner/backups", "/owner/settings"):
        resp = pub.get(path)
        assert resp.status_code == 403, f"{path} should refuse public host, got {resp.status_code}"


# ── /api/admin requires loopback unless ALLOW_PUBLIC_ADMIN_API ──────────────


def test_public_host_admin_api_403(client: TestClient, *, identity) -> None:
    pub = _public_client()
    # Even with a valid admin token in the header, the network boundary
    # refuses public Host requests by default.
    with _real_admin_boundary():
        resp = pub.get("/api/admin/devices", headers=identity.admin_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "admin_api_local_only"


# ── /api/bootstrap defaults to disabled (404 bootstrap_disabled) ────────────


def test_public_host_bootstrap_owner_disabled_by_default(client: TestClient) -> None:
    pub = _public_client()
    resp = pub.post("/api/bootstrap/owner", json={})
    assert resp.status_code == 404
    assert resp.json()["error"] == "bootstrap_disabled"


def test_public_host_bootstrap_pairing_codes_blocked_without_loopback(
    client: TestClient, *, identity,
) -> None:
    # PR #50 (P1-A) attached require_admin_network_boundary to
    # /api/bootstrap/pairing-codes; this regression-checks that admin
    # token alone, from a public Host, cannot mint a pairing code.
    pub = _public_client()
    with _real_admin_boundary():
        resp = pub.post(
            "/api/bootstrap/pairing-codes",
            headers=identity.admin_headers,
            json={"ttl_minutes": 15},
        )
    assert resp.status_code == 403
    assert resp.json()["error"] == "admin_api_local_only"


# ── /api/maintenance requires loopback ──────────────────────────────────────


def test_public_host_maintenance_403(client: TestClient, *, identity) -> None:
    pub = _public_client()
    with _real_admin_boundary():
        resp = pub.post(
            "/api/maintenance/cleanup-images",
            headers=identity.admin_headers,
        )
    assert resp.status_code == 403


# ── /api/health is the one public endpoint that returns 200 anonymously ─────


def test_public_host_health_is_publicly_reachable(client: TestClient) -> None:
    pub = _public_client()
    resp = pub.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── /docs / /openapi.json closed by default ─────────────────────────────────


def test_public_host_openapi_docs_404_by_default(client: TestClient) -> None:
    pub = _public_client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = pub.get(path)
        assert resp.status_code == 404, f"{path} should be hidden by default, got {resp.status_code}"


# ── /web/* (non-auth) requires a valid cookie ───────────────────────────────


def test_public_host_web_root_redirects_to_login(client: TestClient) -> None:
    pub = _public_client()
    resp = pub.get("/web", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")


def test_public_host_web_pending_post_without_cookie_redirects(client: TestClient) -> None:
    # POST too — gate runs before CSRF / endpoint dependency.
    pub = _public_client()
    resp = pub.post(
        "/web/pending/batch-reject",
        data={"expense_ids": "[1]"},
        headers={"Origin": f"http://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")


# ── /web/auth/* is reachable without cookie (only place that should be) ─────


def test_public_host_login_form_is_reachable(client: TestClient) -> None:
    pub = _public_client()
    resp = pub.get("/web/auth/login")
    assert resp.status_code == 200
    assert "绑定码" in resp.text


# ── No path should return 200 for raw uploads/ ──────────────────────────────


def test_public_host_uploads_directory_not_publicly_served(client: TestClient) -> None:
    pub = _public_client()
    # The uploads dir is intentionally NOT mounted as static. Any direct
    # path under /uploads/ should 404. If this ever returns 200 we have
    # accidentally exposed receipt images on the open internet.
    for path in (
        "/uploads/owner/2026/05/anyfile.png",
        "/static/uploads/x.png",  # static is mounted, uploads under it is not
    ):
        resp = pub.get(path)
        assert resp.status_code in {403, 404}, (
            f"{path} returned {resp.status_code} — uploads dir is NEVER public"
        )


# ── End-to-end: cookie session round trip from public host ──────────────────


def _request_pairing_code(client: TestClient, *, identity) -> str:
    resp = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["pairing_code"]


def test_public_host_full_login_to_dashboard_flow(client: TestClient, *, identity) -> None:
    code = _request_pairing_code(client, identity=identity)
    pub = _public_client()
    login = pub.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "regression bundle"},
        headers={"Origin": f"http://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    token = login.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]

    cookie_header = {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}

    # /web dashboard renders
    dashboard = pub.get("/web", headers=cookie_header)
    assert dashboard.status_code == 200

    # /web/pending renders
    pending = pub.get("/web/pending", headers=cookie_header)
    assert pending.status_code == 200

    # /api/auth/check with the same token (Bearer in header) works
    bearer = pub.get(
        "/api/auth/check",
        headers={**cookie_header, "Authorization": f"Bearer {token}"},
    )
    assert bearer.status_code == 200

    # /owner is still 403 even with the cookie (cookie alone doesn't unlock /owner)
    owner = pub.get("/owner", headers=cookie_header)
    assert owner.status_code == 403
