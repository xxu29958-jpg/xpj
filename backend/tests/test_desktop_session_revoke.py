"""Desktop bridge self-revoke: only the presented app credential dies.

``POST /desktop/session/revoke`` (router: :mod:`app.routes.desktop`) is a
loopback-only bridge route (explicit ``X-Ticketbox-Desktop-Bridge: v1``
marker + a live ``platform=desktop`` app bearer). It revokes exactly the
credential that authenticated the call — sibling sessions, other ledgers of
the same device, and staged pending credentials are all untouched.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.web_session import DESKTOP_BRIDGE_HEADER, DESKTOP_BRIDGE_VERSION
from tests.desktop_activation_support import (
    activate as _activate,
)
from tests.desktop_activation_support import (
    pair_desktop as _pair_desktop,
)
from tests.test_desktop_ledger_switch_prepare import (
    _activate_attempt,
    _desktop_session,
    _prepare_payload,
)

LOOPBACK_BASE_URL = "http://127.0.0.1:8000"
PUBLIC_BASE_URL = "https://api.example.com"
REVOKE_PATH = "/desktop/session/revoke"


@pytest.fixture()
def loopback_client(identity) -> Iterator[TestClient]:
    del identity
    with TestClient(
        app,
        base_url=LOOPBACK_BASE_URL,
        client=("127.0.0.1", 51011),
    ) as test_client:
        yield test_client


def _bridge_headers(token: str, *, marker: str = DESKTOP_BRIDGE_VERSION) -> dict[str, str]:
    return {
        DESKTOP_BRIDGE_HEADER: marker,
        "Authorization": f"Bearer {token}",
    }


def test_revoke_exact_presented_credential(identity, loopback_client: TestClient, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")

    response = loopback_client.post(REVOKE_PATH, headers=_bridge_headers(token))

    assert response.status_code == 204, response.text
    check = client.get("/api/auth/check", headers=headers)
    assert check.status_code == 401


def test_revoke_is_not_idempotent_for_the_same_credential(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")

    assert loopback_client.post(REVOKE_PATH, headers=_bridge_headers(token)).status_code == 204
    # The dead credential can no longer authenticate the route at all.
    replay = loopback_client.post(REVOKE_PATH, headers=_bridge_headers(token))
    assert replay.status_code == 401
    assert replay.json()["error"] == "invalid_token"


def test_revoke_never_touches_sibling_credentials(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    source_token = headers["Authorization"].removeprefix("Bearer ")

    # Stage + activate a second app credential for the SAME device on another
    # ledger: two live sibling slots, one per ledger.
    created = client.post("/api/ledgers", headers=headers, json={"name": "撤销隔离账本"})
    assert created.status_code == 201, created.text
    target = created.json()["ledger_id"]
    payload = _prepare_payload()
    prepared = client.post(
        f"/api/ledgers/{target}/switch/prepare",
        headers=headers,
        json=payload,
    )
    assert prepared.status_code == 200, prepared.text
    activated = _activate_attempt(client, payload)
    assert activated.status_code == 200, activated.text
    sibling_token = activated.json()["session_token"]

    response = loopback_client.post(REVOKE_PATH, headers=_bridge_headers(source_token))

    assert response.status_code == 204, response.text
    assert client.get("/api/auth/check", headers=headers).status_code == 401
    sibling = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {sibling_token}"},
    )
    assert sibling.status_code == 200, sibling.text
    assert sibling.json()["ledger_id"] == target


def test_revoke_requires_bridge_marker(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")

    missing = loopback_client.post(REVOKE_PATH, headers={"Authorization": f"Bearer {token}"})
    assert missing.status_code == 401
    assert missing.json()["error"] == "desktop_bridge_required"

    wrong = loopback_client.post(REVOKE_PATH, headers=_bridge_headers(token, marker="v2"))
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "desktop_bridge_required"

    # Guard failures never revoke the credential.
    assert client.get("/api/auth/check", headers=headers).status_code == 200


def test_revoke_rejects_non_loopback(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")

    with TestClient(
        app,
        base_url=PUBLIC_BASE_URL,
        client=("203.0.113.10", 51012),
    ) as public_client:
        response = public_client.post(REVOKE_PATH, headers=_bridge_headers(token))

    assert response.status_code == 403
    # Guard failures never revoke the credential.
    assert client.get("/api/auth/check", headers=headers).status_code == 200


def test_revoke_rejects_non_desktop_platform(
    identity,
    loopback_client: TestClient,
) -> None:
    # The seeded owner app token is an Android credential; it must never cross
    # into the Desktop session surface (the bridge gate pins the web-platform
    # variant of the same authenticator restriction).
    token = identity.app_token

    response = loopback_client.post(REVOKE_PATH, headers=_bridge_headers(token))

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_revoke_rejects_pending_and_missing_credentials(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    # A staged desktop_pending value is not an app credential: 401, and the
    # staging itself stays alive for activation.
    payload, body = _pair_desktop(client, identity.pairing_code)
    pending_headers = _bridge_headers(body["session_token"])
    response = loopback_client.post(REVOKE_PATH, headers=pending_headers)
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert _activate(client, payload).status_code == 200

    missing = loopback_client.post(
        REVOKE_PATH,
        headers={DESKTOP_BRIDGE_HEADER: DESKTOP_BRIDGE_VERSION},
    )
    assert missing.status_code == 401
    assert missing.json()["error"] == "invalid_token"
