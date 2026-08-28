from __future__ import annotations

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import AuthToken
from app.routes.web_auth import SESSION_COOKIE_MAX_AGE_SECONDS, SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret
from app.services.time_service import ensure_utc, now_utc

PUBLIC_HOST = "api.example.com"


def public_client() -> TestClient:
    """Return a routable-peer TestClient using the public Web host."""
    return TestClient(
        app,
        base_url=f"https://{PUBLIC_HOST}",
        client=("203.0.113.10", 50001),
    )


def _request_pairing_code(client: TestClient, *, identity) -> str:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 200, response.text
    return response.json()["pairing_code"]


def mint_session(client: TestClient, *, identity) -> str:
    before = now_utc()
    code = _request_pairing_code(client, identity=identity)
    login = public_client()
    login_form = login.get("/web/auth/login")
    assert login_form.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', login_form.text)
    assert match is not None, login_form.text
    response = login.post(
        "/web/auth/login",
        data={
            "pairing_code": code,
            "device_name": "pytest browser",
            "csrf_token": match.group(1),
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    after = now_utc()
    assert response.status_code == 303, response.text
    token = response.headers["set-cookie"].split(
        f"{SESSION_COOKIE_NAME}=", 1
    )[1].split(";", 1)[0]
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        expires_at = ensure_utc(row.expires_at)
        assert expires_at is not None
        assert expires_at >= before + timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS)
        assert expires_at <= after + timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS)
    return token


__all__ = ["PUBLIC_HOST", "mint_session", "public_client"]
