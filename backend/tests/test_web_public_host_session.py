"""/web public-host dual mode (PR-4).

PR-3 added the cookie session minting flow. PR-4 wires the
:mod:`app.middleware.web_session` middleware so that requests from a
public Host header (Cloudflare Tunnel hostname, attacker-set Host,
anything that's not loopback) get redirected to /web/auth/login unless
they carry a valid __Host-session cookie. Loopback Owner Console flow
is unchanged.

These tests exercise the middleware end to end:
- public Host + no cookie → 303 to /web/auth/login?next=
- public Host + valid cookie → 200, ledger forced to session ledger
- public Host + cookie + cross-ledger ?ledger_id= → 403 ledger_forbidden
- public Host + dead cookie → 303 + cookie cleared
- /web/auth/* itself remains reachable without cookie (login can't redirect to itself)
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_auth import SESSION_COOKIE_NAME

# A public host header that the test injects to simulate a Cloudflare
# Tunnel request reaching the backend.
PUBLIC_HOST = "api.example.com"


def _public_client() -> TestClient:
    """Return a TestClient that looks like a public-host caller: client
    peer is a routable IP and Host header is a non-loopback DNS name.

    Required because the default TestClient (peer=testclient,
    host=testserver) is excluded from web_session_gate explicitly so
    pre-PR-3 tests still see LocalOnly 403 instead of 303 redirect.
    See app/middleware/web_session.py::_is_session_required.
    """
    return TestClient(
        app,
        base_url=f"http://{PUBLIC_HOST}",
        client=("203.0.113.10", 50001),
    )


def _request_pairing_code(client: TestClient, *, identity) -> str:
    resp = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["pairing_code"]


def _mint_session(client: TestClient, *, identity) -> str:
    code = _request_pairing_code(client, identity=identity)
    # Login goes through the public-host TestClient too — login itself is
    # NOT session-gated (see web_auth router). Origin matches the public
    # host so CSRF middleware accepts the form POST as same-site.
    login = _public_client()
    resp = login.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "pytest browser"},
        headers={"Origin": f"http://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    set_cookie = resp.headers["set-cookie"]
    return set_cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]


def test_public_host_without_cookie_redirects_to_login(client: TestClient) -> None:
    pub = _public_client()
    resp = pub.get("/web/pending", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")
    # next= must carry the original destination
    assert "next=/web/pending" in resp.headers["location"]


def test_public_host_login_page_itself_does_not_redirect(client: TestClient) -> None:
    # If /web/auth/login bounced to itself, public users could never log in.
    pub = _public_client()
    resp = pub.get("/web/auth/login")
    assert resp.status_code == 200
    assert "绑定码" in resp.text


def test_public_host_with_valid_cookie_renders_dashboard(client: TestClient, *, identity) -> None:
    token = _mint_session(client, identity=identity)
    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
    )
    assert resp.status_code == 200, resp.text
    # Lands on the owner ledger (the test identity uses the owner ledger)
    assert "待确认" in resp.text


def test_public_host_cross_ledger_query_rejected(client: TestClient, *, identity) -> None:
    # The cookie is bound to ledger "owner"; the URL claims "tester_1".
    # Middleware must refuse rather than silently serve either signal.
    token = _mint_session(client, identity=identity)
    pub = _public_client()
    resp = pub.get(
        "/web/pending?ledger_id=tester_1",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "ledger_forbidden"


def test_public_host_dead_cookie_redirects_and_clears(client: TestClient, *, identity) -> None:
    # A token that doesn't exist server-side (or has been revoked).
    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}=tbx_not_a_real_token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")
    # Middleware also clears the dead cookie so the browser stops sending it.
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    # Set-Cookie with an empty value (or expires in the past) is the
    # browser-honoured deletion form. Starlette's delete_cookie emits
    # an empty value + Max-Age=0.
    assert "Max-Age=0" in set_cookie or set_cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].startswith(";")


def test_loopback_host_still_works_without_cookie(client: TestClient) -> None:
    # Existing Owner Console loopback flow is left intact: TestClient default
    # (peer=testclient, host=testserver) is excluded from the public-mode gate
    # so the legacy LocalOnly dependency path is what reports the result.
    # This is a regression guard — if someone accidentally removes the
    # testclient/testserver carve-out the suite will tell us.
    resp = client.get("/web/pending")
    # LocalOnly still rejects because the testclient peer is NOT one of the
    # loopback peers (127.0.0.1 / ::1 / localhost). Same response as before PR-4.
    assert resp.status_code == 403
