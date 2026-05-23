"""ADR-0028 P2 boundary: /static/owner/* must refuse public Host requests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _public_client() -> TestClient:
    """A TestClient that looks like a public-host caller (routable IP +
    non-loopback Host) so static_owner_guard sees it as public."""
    return TestClient(
        app,
        base_url="http://api.example.com",
        client=("203.0.113.10", 50001),
    )


def test_public_static_owner_css_blocked() -> None:
    public = _public_client()
    response = public.get("/static/owner/owner.css", follow_redirects=False)
    assert response.status_code == 403, response.text[:200]


def test_loopback_static_owner_css_allowed(client: TestClient) -> None:
    """Default TestClient is treated as loopback (testclient/testserver)
    by network_boundary.is_loopback_request. The middleware shouldn't
    block this — but the actual file may not exist in tests, so accept
    200 (asset present) or 404 (asset missing) — what we care about is
    that the guard didn't 403."""
    response = client.get("/static/owner/owner.css")
    assert response.status_code != 403, "loopback access must not be blocked"


def test_public_static_web_still_allowed() -> None:
    """``/static/web/*`` is the shared family-member surface (cookie
    session) and must remain reachable to the public — the guard only
    targets the ``/owner/`` subpath."""
    public = _public_client()
    response = public.get("/static/web/web.css", follow_redirects=False)
    # 200 if asset exists, 404 if missing — either is fine; we only
    # need to assert the guard didn't 403 it.
    assert response.status_code != 403


def test_public_other_static_path_not_affected() -> None:
    """The guard only matches ``/static/owner/*``; other static paths
    don't touch it."""
    public = _public_client()
    response = public.get("/static/shared/tokens.css", follow_redirects=False)
    assert response.status_code != 403
