"""Desktop bridge self-revoke: the kill set depends on the scope intent.

``POST /desktop/session/revoke`` (router: :mod:`app.routes.desktop`) is a
loopback-only bridge route (explicit ``X-Ticketbox-Desktop-Bridge: v1``
marker + a live ``platform=desktop`` app bearer). Three contracts are pinned
here:

- Default scope (the ledger-switch cleanup intent): retires exactly the
  presented credential plus its still-staged ``desktop_pending`` rows — the
  already-promoted successor stays alive by design, so switching ledgers
  never suicides the session it just created. (After a switch activation the
  presented predecessor is typically already dead — activation closed the
  source family — and the cleanup is a no-op 401.)
- ``?scope=lineage`` (the unpair/teardown intent): additionally hard-revokes
  every promoted replacement whose activation receipt names the presented
  credential as predecessor, together with that replacement's whole refresh
  family; unrelated lineages (independently-paired devices) and the device
  itself stay untouched.
- Unknown scope values are rejected with 400.
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
    attempt_row as _attempt_row,
)
from tests.desktop_activation_support import (
    new_desktop_pairing_code,
)
from tests.desktop_activation_support import (
    pair_desktop as _pair_desktop,
)
from tests.desktop_activation_support import (
    token_row as _token_row,
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


def test_switch_activation_closes_source_family_and_cleanup_keeps_successor(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    """Switch activation atomically retires the source family (recorded
    predecessor + its refresh descendants) with rotation grace; the promoted
    successor becomes the session, and the default cleanup revoke afterwards
    is a no-op 401 (predecessor already dead) that never touches it."""
    from tests.test_desktop_ledger_switch_prepare import _create_ledger

    _, headers = _desktop_session(client, identity.pairing_code)
    source_token = headers["Authorization"].removeprefix("Bearer ")
    target = _create_ledger(client, headers, name="目标账本")
    payload = _prepare_payload()
    assert (
        client.post(
            f"/api/ledgers/{target}/switch/prepare",
            headers=headers,
            json=payload,
        ).status_code
        == 200
    )
    activated = _activate_attempt(client, payload)
    assert activated.status_code == 200, activated.text
    successor_token = activated.json()["session_token"]

    attempt = _attempt_row(payload["activation_attempt_id"])
    source_row = _token_row(source_token)
    assert attempt.previous_token_id == source_row.id
    # The atomic family close: A is already retired when activation commits.
    assert source_row.revoked_at is not None

    response = loopback_client.post(REVOKE_PATH, headers=_bridge_headers(source_token))

    # A is dead, so the route rejects it — the cleanup intent is already
    # fulfilled; crucially the promoted successor is untouched either way.
    assert response.status_code == 401
    successor = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {successor_token}"},
    )
    assert successor.status_code == 200, successor.text
    assert successor.json()["ledger_id"] == target


def test_unpair_lineage_scope_kills_promoted_replacements_but_not_unrelated_lineages(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    """The teardown intent (``?scope=lineage``) end-to-end: the presented
    (current, post-switch) session dies and an independently-paired desktop
    device's session survives. The promoted-replacement kill set itself —
    including a promoted token's refresh descendants — is pinned at service
    level in :mod:`tests.test_desktop_session_revoke_refresh_lineage`."""
    from tests.test_desktop_ledger_switch_prepare import _create_ledger

    # Pair + activate a desktop session, then switch it to the second ledger.
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers, name="替换账本")
    payload = _prepare_payload()
    source_token = headers["Authorization"].removeprefix("Bearer ")
    assert (
        client.post(
            f"/api/ledgers/{target}/switch/prepare",
            headers=headers,
            json=payload,
        ).status_code
        == 200
    )
    activated = _activate_attempt(client, payload)
    assert activated.status_code == 200, activated.text
    sibling_token = activated.json()["session_token"]

    attempt = _attempt_row(payload["activation_attempt_id"])
    source_row = _token_row(source_token)
    assert attempt.previous_token_id == source_row.id

    other_payload, other_body = _pair_desktop(
        client,
        new_desktop_pairing_code(client, headers),
    )
    assert _activate(client, other_payload).status_code == 200

    # The desktop unpair presents the CURRENT (promoted) session.
    response = loopback_client.post(
        f"{REVOKE_PATH}?scope=lineage",
        headers=_bridge_headers(sibling_token),
    )

    assert response.status_code == 204, response.text
    sibling = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {sibling_token}"},
    )
    assert sibling.status_code == 401
    assert source_row.revoked_at is not None
    unrelated = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {other_body['session_token']}"},
    )
    assert unrelated.status_code == 200, unrelated.text


def test_revoke_rejects_unknown_scope(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")

    response = loopback_client.post(
        f"{REVOKE_PATH}?scope=everything",
        headers=_bridge_headers(token),
    )

    assert response.status_code == 400


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


def test_revoke_cancels_outstanding_staged_replacements(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    """Unpair must not leave a staged desktop_pending replacement live: the
    unauthenticated activate endpoint would otherwise restore a full session
    from the retained attempt proof after the session was revoked."""
    from tests.test_desktop_ledger_switch_prepare import _create_ledger

    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    payload = _prepare_payload()
    prepared = client.post(
        f"/api/ledgers/{target}/switch/prepare",
        headers=headers,
        json=payload,
    )
    assert prepared.status_code == 200, prepared.text
    staged_value = prepared.json()["session_token"]

    token = headers["Authorization"].removeprefix("Bearer ")
    assert loopback_client.post(REVOKE_PATH, headers=_bridge_headers(token)).status_code == 204

    # The staged attempt can no longer activate: its pending row was revoked
    # inside the same revocation transaction.
    activated = _activate_attempt(client, payload)
    assert activated.status_code == 401
    staged_row = _token_row(staged_value)
    assert staged_row.revoked_at is not None
    assert staged_row.grace_until is None

