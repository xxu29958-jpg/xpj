"""Security contract for the Desktop principal on the shared ``/web`` surface.

A paired ``platform=desktop`` app bearer plus the explicit bridge marker
becomes the application principal for proxied ``/web`` requests. The gate
runs before the loopback-owner bypass, so marker/credential failures can
never inherit the legacy local owner projection.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.main import app
from app.middleware import web_session as web_session_middleware
from app.middleware.web_session import (
    DESKTOP_BRIDGE_HEADER,
    DESKTOP_BRIDGE_VERSION,
)
from app.models import (
    Account,
    AuthToken,
    Device,
    Ledger,
    LedgerMember,
)
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret, new_session_token
from app.services.time_service import now_utc

LOOPBACK_BASE_URL = "http://127.0.0.1:8000"
PUBLIC_BASE_URL = "https://api.example.com"


@dataclass(frozen=True)
class _Principal:
    token: str
    account_id: int
    device_id: int
    ledger_id: str


@pytest.fixture()
def desktop_bridge_client(identity) -> Iterator[TestClient]:
    del identity  # fixture seeds the canonical owner + two ledgers
    with TestClient(
        app,
        base_url=LOOPBACK_BASE_URL,
        client=("127.0.0.1", 51001),
    ) as test_client:
        yield test_client


def _principal_headers(
    token: str | None,
    *,
    marker: str = DESKTOP_BRIDGE_VERSION,
) -> dict[str, str]:
    headers = {DESKTOP_BRIDGE_HEADER: marker}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mint_principal(
    *,
    ledger_id: str = "owner",
    role: str = "owner",
    platform: str = "desktop",
    scope: str = "app",
    expires_at: datetime | None = None,
) -> _Principal:
    token = new_session_token()
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id))
        assert ledger is not None
        if role == "owner":
            membership = db.scalar(
                select(LedgerMember)
                .where(LedgerMember.ledger_id == ledger_id)
                .where(LedgerMember.role == "owner")
                .where(LedgerMember.disabled_at.is_(None))
                .limit(1)
            )
            assert membership is not None
            account_id = membership.account_id
        else:
            account = Account(display_name=f"bridge-{role}-{uuid4()}")
            db.add(account)
            db.flush()
            account_id = account.id
            db.add(
                LedgerMember(
                    ledger_id=ledger_id,
                    account_id=account_id,
                    role=role,
                )
            )

        device = Device(
            account_id=account_id,
            device_name=f"pytest-{platform}-bridge",
            platform=platform,
        )
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account_id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope=scope,
                expires_at=expires_at,
            )
        )
        db.commit()
        return _Principal(
            token=token,
            account_id=account_id,
            device_id=device.id,
            ledger_id=ledger_id,
        )


def _auth_token(token: str) -> AuthToken:
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        db.expunge(row)
        return row


def test_valid_desktop_bridge_projects_bound_viewer_and_its_ledger(
    desktop_bridge_client: TestClient,
) -> None:
    principal = _mint_principal(role="viewer")
    with SessionLocal() as db:
        bound = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        assert bound is not None
        bound.name = "Desktop 绑定账本"
        db.commit()

    response = desktop_bridge_client.get(
        "/web/pending",
        headers=_principal_headers(principal.token),
    )

    assert response.status_code == 200, response.text
    # The bound ledger renders as the selected ledger with the session's role
    # stamped on it — a viewer principal stays read-only.
    assert "Desktop 绑定账本" in response.text
    assert 'name="ledger_id" value="owner"' in response.text
    assert "ledger-role-viewer" in response.text
    # The bridge never mints a browser cookie session.
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")

    theme_write = desktop_bridge_client.put(
        "/api/me/ui-preferences",
        headers=_principal_headers(principal.token),
        json={"theme": "midnight"},
    )
    assert theme_write.status_code == 403, theme_write.text


def test_loopback_without_marker_preserves_legacy_owner_mode(
    desktop_bridge_client: TestClient,
) -> None:
    principal = _mint_principal(role="viewer")
    with SessionLocal() as db:
        private = db.scalar(select(Ledger).where(Ledger.ledger_id == "tester_1"))
        assert private is not None
        private.name = "无 marker 时仍可见的本机账本"
        db.commit()

    response = desktop_bridge_client.get(
        "/web/pending",
        headers={"Authorization": f"Bearer {principal.token}"},
    )

    assert response.status_code == 200, response.text
    assert "无 marker 时仍可见的本机账本" in response.text
    assert "ledger-role-viewer" not in response.text


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic not-a-bearer",
        "Bearer ",
        "Bearer not-a-real-token",
    ],
)
def test_explicit_bridge_with_missing_or_bad_bearer_never_falls_back_to_owner(
    desktop_bridge_client: TestClient,
    authorization: str | None,
) -> None:
    headers = {DESKTOP_BRIDGE_HEADER: DESKTOP_BRIDGE_VERSION}
    if authorization is not None:
        headers["Authorization"] = authorization

    response = desktop_bridge_client.get(
        "/web/pending",
        headers=headers,
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


@pytest.mark.parametrize("marker", ["", "V1", "v2", " v1 "])
def test_invalid_explicit_bridge_marker_never_falls_back_to_owner(
    desktop_bridge_client: TestClient,
    marker: str,
) -> None:
    principal = _mint_principal()
    response = desktop_bridge_client.get(
        "/web/pending",
        headers=_principal_headers(principal.token, marker=marker),
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "desktop_bridge_required"


@pytest.mark.parametrize(
    ("platform", "scope"),
    [
        ("android", "app"),
        ("web", "app"),
        ("desktop", "admin"),
    ],
)
def test_wrong_platform_or_scope_is_rejected_without_revoking_token(
    desktop_bridge_client: TestClient,
    platform: str,
    scope: str,
) -> None:
    principal = _mint_principal(platform=platform, scope=scope)
    response = desktop_bridge_client.get(
        "/web/pending",
        headers=_principal_headers(principal.token),
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert _auth_token(principal.token).revoked_at is None


def test_revoked_desktop_token_is_rejected_even_inside_app_refresh_grace(
    desktop_bridge_client: TestClient,
) -> None:
    principal = _mint_principal()
    revoked_at = now_utc()
    with SessionLocal() as db:
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(principal.token)))
        assert token is not None
        token.revoked_at = revoked_at
        token.grace_until = revoked_at + timedelta(minutes=5)
        db.commit()

    response = desktop_bridge_client.get(
        "/web/pending",
        headers=_principal_headers(principal.token),
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_revoked_desktop_device_is_rejected(
    desktop_bridge_client: TestClient,
) -> None:
    principal = _mint_principal()
    with SessionLocal() as db:
        device = db.get(Device, principal.device_id)
        assert device is not None
        device.revoked_at = now_utc()
        db.commit()

    response = desktop_bridge_client.get(
        "/web/pending",
        headers=_principal_headers(principal.token),
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_expired_desktop_token_is_revoked_and_rejected(
    desktop_bridge_client: TestClient,
) -> None:
    principal = _mint_principal(expires_at=now_utc() - timedelta(seconds=1))
    response = desktop_bridge_client.get(
        "/web/pending",
        headers=_principal_headers(principal.token),
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    stored = _auth_token(principal.token)
    assert stored.revoked_at is not None
    assert stored.grace_until is None


def test_desktop_bridge_cross_ledger_query_is_forbidden(
    desktop_bridge_client: TestClient,
) -> None:
    principal = _mint_principal(ledger_id="owner")
    response = desktop_bridge_client.get(
        "/web/pending?ledger_id=tester_1",
        headers=_principal_headers(principal.token),
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["error"] == "ledger_forbidden"


def test_public_host_cannot_forge_desktop_bridge_even_from_loopback_connector(
    identity,
) -> None:
    del identity
    principal = _mint_principal()
    with TestClient(
        app,
        base_url=PUBLIC_BASE_URL,
        client=("127.0.0.1", 51002),
    ) as public_client:
        response = public_client.get(
            "/web/pending",
            headers=_principal_headers(principal.token),
            follow_redirects=False,
        )

    assert response.status_code == 403
    assert response.json()["error"] == "desktop_bridge_required"


def test_public_web_without_bridge_marker_keeps_cookie_session_flow(identity) -> None:
    del identity
    with TestClient(
        app,
        base_url=PUBLIC_BASE_URL,
        client=("203.0.113.10", 51003),
    ) as public_client:
        response = public_client.get("/web/pending", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/web/auth/login")


def test_explicit_bridge_marker_on_web_auth_path_is_still_fail_closed(
    desktop_bridge_client: TestClient,
) -> None:
    response = desktop_bridge_client.get(
        "/web/auth/login",
        headers={DESKTOP_BRIDGE_HEADER: DESKTOP_BRIDGE_VERSION},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_desktop_bridge_database_error_returns_503(
    desktop_bridge_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_session() -> None:
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(web_session_middleware, "SessionLocal", _raise_session)
    response = desktop_bridge_client.get(
        "/web/pending",
        headers=_principal_headers("tbx_fake"),
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["error"] == "server_error"
