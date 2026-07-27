"""Refresh-rotation × desktop switch/revoke lineage interactions (218-E).

Four contracts: switch activation atomically closes the source refresh
family; the lineage teardown covers promoted replacements' whole refresh
family; the default switch-cleanup scope never touches the successor family;
and when a racing refresh kills the presented row first, the lineage
teardown still closes that row's live refresh family (the default scope
stays a 401 no-op).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import AuthToken, DesktopActivationAttempt, SessionRefreshAttempt
from app.services.desktop_switch_service import revoke_desktop_app_session
from app.services.identity_service import (
    authenticate_desktop_session_token,
    hash_secret,
    new_session_token,
)
from app.services.time_service import now_utc
from tests.desktop_activation_support import token_row as _token_row
from tests.pairing_test_support import session_refresh_payload
from tests.test_desktop_ledger_switch_prepare import (
    _activate_attempt,
    _create_ledger,
    _desktop_session,
    _prepare_payload,
)
from tests.test_desktop_session_revoke import (
    LOOPBACK_BASE_URL,
    REVOKE_PATH,
    _bridge_headers,
)


@pytest.fixture()
def loopback_client(identity) -> Iterator[TestClient]:
    del identity
    with TestClient(
        app,
        base_url=LOOPBACK_BASE_URL,
        client=("127.0.0.1", 51011),
    ) as test_client:
        yield test_client


def test_activate_after_source_refresh_closes_the_source_family(
    identity,
    client: TestClient,
) -> None:
    """Prepare with A live, rotate A→A2 via /api/auth/refresh, then activate:
    the promoted B goes live on the target ledger AND the source family
    (A, A2) is closed atomically — never two authorized families."""

    _, headers = _desktop_session(client, identity.pairing_code)
    source_value = headers["Authorization"].removeprefix("Bearer ")
    target = _create_ledger(client, headers)
    payload = _prepare_payload()
    assert (
        client.post(
            f"/api/ledgers/{target}/switch/prepare",
            headers=headers,
            json=payload,
        ).status_code
        == 200
    )

    # The legitimate client rotates A → A2 between prepare and activation.
    refreshed = client.post(
        "/api/auth/refresh",
        headers=headers,
        json=session_refresh_payload(),
    )
    assert refreshed.status_code == 200, refreshed.text
    rotated_value = refreshed.json()["session_token"]
    assert rotated_value != source_value

    activated = _activate_attempt(client, payload)
    assert activated.status_code == 200, activated.text
    successor_value = activated.json()["session_token"]

    # B is the live session on the target ledger; A's whole refresh family
    # (A and its replacement A2) is closed atomically at activation.
    check = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {successor_value}"},
    )
    assert check.status_code == 200, check.text
    assert check.json()["ledger_id"] == target
    rotated_row = _token_row(rotated_value)
    assert rotated_row.revoked_at is not None
    source_row = _token_row(source_value)
    assert source_row.revoked_at is not None


def _seed_promoted_lineage(db, source_row, fabricated_ledger: str) -> tuple[str, str]:
    """Fabricate a promoted replacement (B) rotated onward via refresh (B2)."""
    promoted_value = new_session_token()
    promoted = AuthToken(
        token_hash=hash_secret(promoted_value),
        account_id=source_row.account_id,
        device_id=source_row.device_id,
        ledger_id=fabricated_ledger,
        scope="app",
    )
    db.add(promoted)
    db.flush()
    promoted.revoked_at = now_utc()
    db.add(
        DesktopActivationAttempt(
            public_id=str(uuid4()),
            token_id=promoted.id,
            previous_token_id=source_row.id,
            account_id=source_row.account_id,
            device_id=source_row.device_id,
            ledger_id=fabricated_ledger,
            secret_hash="x" * 64,
            activated_at=now_utc(),
            expires_at=now_utc() + timedelta(seconds=300),
            last_issued_at=None,
            created_at=now_utc(),
        )
    )
    descendant_value = new_session_token()
    descendant = AuthToken(
        token_hash=hash_secret(descendant_value),
        account_id=source_row.account_id,
        device_id=source_row.device_id,
        ledger_id=fabricated_ledger,
        scope="app",
    )
    db.add(descendant)
    db.flush()
    db.add(
        SessionRefreshAttempt(
            public_id=str(uuid4()),
            source_token_id=promoted.id,
            replacement_token_id=descendant.id,
            secret_hash="x" * 64,
            expires_at=now_utc() + timedelta(days=90),
            last_issued_at=now_utc(),
            created_at=now_utc(),
        )
    )
    db.flush()
    return promoted_value, descendant_value


def test_lineage_revoke_covers_the_promoted_tokens_refresh_family(
    identity,
    client: TestClient,
) -> None:
    """Service-level pin for the lineage kill set: a promoted replacement
    rotated onward through refresh (B → B2) dies with its whole family when
    the predecessor's lineage is torn down."""

    _, headers = _desktop_session(client, identity.pairing_code)
    source_value = headers["Authorization"].removeprefix("Bearer ")
    fabricated_ledger = _create_ledger(client, headers, name="血缘账本")
    with SessionLocal() as db:
        source_row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(source_value))
        )
        promoted_value, descendant_value = _seed_promoted_lineage(
            db,
            source_row,
            fabricated_ledger,
        )
        db.commit()
        auth = authenticate_desktop_session_token(db, source_value)
        revoke_desktop_app_session(db, auth=auth, token_value=source_value, lineage=True)

    with SessionLocal() as db:
        for value in (source_value, promoted_value, descendant_value):
            row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(value)))
            assert row.revoked_at is not None, value


def test_switch_cleanup_default_scope_never_touches_the_successor_family(
    identity,
    loopback_client: TestClient,
    client: TestClient,
) -> None:
    """Contract from the P0 fix: the switch cleanup retires the predecessor
    only — the promoted successor AND its refreshed descendants stay alive."""

    _, headers = _desktop_session(client, identity.pairing_code)
    source_token = headers["Authorization"].removeprefix("Bearer ")
    target = _create_ledger(client, headers)
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

    rotated = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {activated.json()['session_token']}"},
        json=session_refresh_payload(),
    )
    assert rotated.status_code == 200, rotated.text
    descendant_value = rotated.json()["session_token"]

    response = loopback_client.post(REVOKE_PATH, headers=_bridge_headers(source_token))

    # A's family was already closed at activation, so the default cleanup is a
    # no-op 401 — and it must never touch the successor's refresh family.
    assert response.status_code == 401
    successor = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {descendant_value}"},
    )
    assert successor.status_code == 200, successor.text
    assert successor.json()["ledger_id"] == target


def test_lineage_revoke_with_race_dead_presented_row_closes_its_refresh_family(
    identity,
    client: TestClient,
) -> None:
    """Unpair-vs-refresh race: authentication saw A live, then a refresh
    A → A2 committed before the teardown's lock. The lineage intent is not
    exempt: it still closes A's live refresh family (hard) and returns
    normally (204 semantics) instead of reporting a bare 401."""

    _, headers = _desktop_session(client, identity.pairing_code)
    source_value = headers["Authorization"].removeprefix("Bearer ")
    with SessionLocal() as db:
        auth = authenticate_desktop_session_token(db, source_value)

    rotated = client.post(
        "/api/auth/refresh",
        headers=headers,
        json=session_refresh_payload(),
    )
    assert rotated.status_code == 200, rotated.text
    rotated_value = rotated.json()["session_token"]

    with SessionLocal() as db:
        revoke_desktop_app_session(db, auth=auth, token_value=source_value, lineage=True)

    source_row = _token_row(source_value)
    assert source_row.revoked_at is not None
    rotated_row = _token_row(rotated_value)
    assert rotated_row.revoked_at is not None
    assert rotated_row.grace_until is None  # hard teardown, not a grace window


def test_default_revoke_with_race_dead_presented_row_stays_a_401_noop(
    identity,
    client: TestClient,
) -> None:
    """Same race under the default (switch-cleanup) scope: an already-dead
    presented row stays a 401 no-op and the rotated successor is untouched."""

    _, headers = _desktop_session(client, identity.pairing_code)
    source_value = headers["Authorization"].removeprefix("Bearer ")
    with SessionLocal() as db:
        auth = authenticate_desktop_session_token(db, source_value)

    rotated = client.post(
        "/api/auth/refresh",
        headers=headers,
        json=session_refresh_payload(),
    )
    assert rotated.status_code == 200, rotated.text
    rotated_value = rotated.json()["session_token"]

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        revoke_desktop_app_session(db, auth=auth, token_value=source_value)
    assert exc.value.error == "invalid_token"
    assert exc.value.status_code == 401

    rotated_row = _token_row(rotated_value)
    assert rotated_row.revoked_at is None
