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

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.main import app
from app.middleware import web_session as web_session_middleware
from app.models import AuthToken
from app.routes.web_auth import (
    SESSION_COOKIE_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
)
from app.services.identity_service import hash_secret
from app.services.time_service import ensure_utc, now_utc

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
        base_url=f"https://{PUBLIC_HOST}",
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
    before = now_utc()
    code = _request_pairing_code(client, identity=identity)
    # Login goes through the public-host TestClient too — login itself is
    # NOT session-gated (see web_auth router). Origin matches the public
    # host so CSRF middleware accepts the form POST as same-site.
    login = _public_client()
    login_form = login.get("/web/auth/login")
    assert login_form.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', login_form.text)
    assert match is not None, login_form.text
    resp = login.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "pytest browser", "csrf_token": match.group(1)},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    after = now_utc()
    assert resp.status_code == 303, resp.text
    set_cookie = resp.headers["set-cookie"]
    token = set_cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        expires_at = ensure_utc(row.expires_at)
        assert expires_at is not None
        assert expires_at >= before + timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS)
        assert expires_at <= after + timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS)
    return token


def test_public_host_without_cookie_redirects_to_login(client: TestClient) -> None:
    pub = _public_client()
    resp = pub.get("/web/pending", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")
    # next= must carry the original destination
    assert "next=%2Fweb%2Fpending" in resp.headers["location"]


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
    assert SESSION_COOKIE_NAME not in resp.headers.get("set-cookie", "")


def test_public_host_cookie_does_not_refresh_last_used_or_cookie(client: TestClient, *, identity) -> None:
    token = _mint_session(client, identity=identity)
    old_last_used = now_utc() - timedelta(hours=2)
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        row.last_used_at = old_last_used
        db.commit()

    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
    )
    assert resp.status_code == 200, resp.text
    assert SESSION_COOKIE_NAME not in resp.headers.get("set-cookie", "")

    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        assert ensure_utc(row.last_used_at) == ensure_utc(old_last_used)


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


def test_public_host_android_app_token_cookie_redirects_clears_and_does_not_revoke(
    client: TestClient, *, identity
) -> None:
    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={identity.app_token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "Max-Age=0" in set_cookie or set_cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].startswith(";")

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token))
        )
        assert row is not None
        assert row.revoked_at is None


def test_public_host_session_db_error_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_session() -> None:
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(web_session_middleware, "SessionLocal", _raise_session)
    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}=tbx_fake"},
        follow_redirects=False,
    )
    assert resp.status_code == 503
    assert resp.json()["error"] == "server_error"


def test_public_host_server_side_expired_cookie_redirects_clears_and_revokes(
    client: TestClient, *, identity
) -> None:
    token = _mint_session(client, identity=identity)
    old = now_utc() - timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS + 1)
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        row.created_at = old
        row.expires_at = old
        row.last_used_at = old
        db.commit()

    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "Max-Age=0" in set_cookie or set_cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].startswith(";")

    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        assert row.revoked_at is not None


def test_public_host_fixed_ttl_uses_expires_at_not_last_used(client: TestClient, *, identity) -> None:
    token = _mint_session(client, identity=identity)
    now = now_utc()
    created_at = now - timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS + 60)
    expires_at = now + timedelta(minutes=5)
    stale_last_used = now - timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS + 60)
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        row.created_at = created_at
        row.expires_at = expires_at
        row.last_used_at = stale_last_used
        db.commit()

    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
    )
    assert resp.status_code == 200, resp.text
    assert SESSION_COOKIE_NAME not in resp.headers.get("set-cookie", "")

    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        assert ensure_utc(row.last_used_at) == ensure_utc(stale_last_used)
        assert ensure_utc(row.expires_at) == ensure_utc(expires_at)


def test_public_host_legacy_null_expires_at_falls_back_to_created_at(
    client: TestClient, *, identity
) -> None:
    token = _mint_session(client, identity=identity)
    old = now_utc() - timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS + 1)
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        row.created_at = old
        row.expires_at = None
        db.commit()

    pub = _public_client()
    resp = pub.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")

    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        assert row.revoked_at is not None


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
