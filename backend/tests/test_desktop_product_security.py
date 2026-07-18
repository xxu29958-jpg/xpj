"""Authentication and authorization contracts for Desktop workspaces."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from _desktop_product_test_support import (
    BRIDGE_HEADERS,
    allow_testclient_loopback,
    command,
    mint_desktop_token_from,
    principal_headers,
    seed_expenses,
    workspace,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import AuthToken, Device, Expense, LedgerMember, PairingCode
from app.schemas._desktop_product import DesktopInboxCommandRequest
from app.services.desktop_product_command_service import (
    execute_desktop_inbox_command,
)
from app.services.identity_service import (
    authenticate_desktop_session_token,
    hash_secret,
    new_session_token,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import hash_pairing_code
from app.services.time_service import now_utc
from app.tenants import AuthContext


def _mint_platform_principal(*, platform: str, revoked_with_grace: bool = False) -> str:
    token_value = new_session_token()
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.role == "owner")
        )
        assert membership is not None
        device = Device(
            account_id=membership.account_id,
            device_name=f"pytest-{platform}",
            platform=platform,
        )
        db.add(device)
        db.flush()
        revoked_at = now_utc() if revoked_with_grace else None
        db.add(
            AuthToken(
                token_hash=hash_secret(token_value),
                account_id=membership.account_id,
                device_id=device.id,
                ledger_id="owner",
                scope="app",
                revoked_at=revoked_at,
                grace_until=(
                    revoked_at + timedelta(minutes=5)
                    if revoked_at is not None
                    else None
                ),
            )
        )
        db.commit()
    return token_value


@pytest.mark.parametrize("platform", ["android", "web"])
def test_desktop_adapter_rejects_non_desktop_app_principals(
    client: TestClient,
    monkeypatch,
    identity,
    platform: str,
) -> None:
    del identity
    allow_testclient_loopback(monkeypatch)
    token = _mint_platform_principal(platform=platform)

    response = workspace(client, "inbox", token=token)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_desktop_adapter_rejects_revoked_token_inside_rotation_grace(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    del identity
    allow_testclient_loopback(monkeypatch)
    token = _mint_platform_principal(
        platform="desktop",
        revoked_with_grace=True,
    )

    response = workspace(client, "inbox", token=token)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def _run_stale_desktop_command(
    *,
    auth: AuthContext,
    public_id: str,
    idempotency_key: str,
) -> str:
    try:
        with SessionLocal() as db:
            execute_desktop_inbox_command(
                db,
                auth=auth,
                public_id=public_id,
                payload=DesktopInboxCommandRequest(
                    action="ignore",
                    expected_row_version=1,
                ),
                idempotency_key=idempotency_key,
            )
    except AppError as exc:
        return exc.error
    return "succeeded"


def _stage_principal_change(db, *, auth: AuthContext, mutation: str) -> None:
    if mutation == "token":
        token = db.scalar(
            select(AuthToken).where(AuthToken.id == auth.credential_id)
        )
        assert token is not None
        token.revoked_at = now_utc()
        token.grace_until = None
    elif mutation == "device":
        device = db.scalar(select(Device).where(Device.id == auth.device_id))
        assert device is not None
        device.revoked_at = now_utc()
    else:
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == auth.ledger_id)
            .where(LedgerMember.account_id == auth.account_id)
        )
        assert membership is not None
        membership.role = "viewer"
    db.flush()


@pytest.mark.real_db
@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("token", "invalid_token"),
        ("device", "invalid_token"),
        ("membership", "permission_denied"),
    ],
)
def test_desktop_command_serializes_with_principal_lifecycle_change(
    identity,
    mutation: str,
    expected_error: str,
) -> None:
    del identity
    token = _mint_platform_principal(platform="desktop")
    pending_id, _ = seed_expenses()
    with SessionLocal() as db:
        stale_auth = authenticate_desktop_session_token(db, token)

    with SessionLocal() as blocker:
        lock_bootstrap_owner_transaction(blocker)
        _stage_principal_change(
            blocker,
            auth=stale_auth,
            mutation=mutation,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                _run_stale_desktop_command,
                auth=stale_auth,
                public_id=pending_id,
                idempotency_key=f"desktop-principal-race-{mutation}",
            )
            try:
                time.sleep(0.2)
                assert not future.done()
            finally:
                blocker.commit()
            assert future.result(timeout=5) == expected_error

    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense).where(Expense.public_id == pending_id)
        )
        assert expense is not None
        assert expense.status == "pending"


def test_desktop_projection_requires_bridge_and_app_principal(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    allow_testclient_loopback(monkeypatch)
    seed_expenses()
    desktop_token = mint_desktop_token_from(identity.app_token)

    no_headers = client.get("/desktop/workspaces/inbox")
    bridge_only = client.get(
        "/desktop/workspaces/inbox",
        headers=BRIDGE_HEADERS,
    )
    token_only = client.get(
        "/desktop/workspaces/inbox",
        headers={"Authorization": f"Bearer {desktop_token}"},
    )
    invalid = client.get(
        "/desktop/workspaces/inbox",
        headers=principal_headers("tbx-invalid"),
    )
    mismatch = workspace(
        client,
        "inbox",
        token=desktop_token,
        ledger_id="tester_1",
    )

    assert no_headers.status_code == 401
    assert no_headers.json()["error"] == "invalid_token"
    assert bridge_only.status_code == 401
    assert bridge_only.json()["error"] == "invalid_token"
    assert token_only.status_code == 401
    assert token_only.json()["error"] == "desktop_bridge_required"
    assert invalid.status_code == 401
    assert invalid.json()["error"] == "invalid_token"
    assert mismatch.status_code == 404
    assert mismatch.json()["error"] == "ledger_not_found"


def test_desktop_inbox_command_enforces_selected_ledger_write_permission(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    allow_testclient_loopback(monkeypatch)
    pending_id, _ = seed_expenses(tenant_id="tester_1")
    desktop_token = mint_desktop_token_from(identity.tenant_app_token)
    with SessionLocal() as db:
        membership = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "tester_1"))
        assert membership is not None
        membership.role = "viewer"
        db.commit()

    projection = workspace(
        client,
        "inbox",
        token=desktop_token,
        ledger_id="tester_1",
    )
    denied = command(
        client,
        pending_id,
        ledger_id="tester_1",
        key="desktop-viewer-denied",
        token=desktop_token,
        body={"action": "ignore", "expected_row_version": 1},
    )

    assert projection.status_code == 200
    assert projection.json()["role"] == "viewer"
    pending = next(row for row in projection.json()["rows"] if row["key"] == f"expense:{pending_id}")
    assert pending["capabilities"] == []
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"


def test_desktop_command_service_rechecks_write_permission(identity) -> None:
    del identity
    token = _mint_platform_principal(platform="desktop")
    with SessionLocal() as db:
        stale_auth = authenticate_desktop_session_token(db, token)
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == stale_auth.ledger_id)
            .where(LedgerMember.account_id == stale_auth.account_id)
        )
        assert membership is not None
        membership.role = "viewer"
        db.commit()

    with SessionLocal() as db, pytest.raises(AppError) as error:
        execute_desktop_inbox_command(
            db,
            auth=stale_auth,
            public_id="not-reached",
            payload=DesktopInboxCommandRequest(
                action="ignore",
                expected_row_version=1,
            ),
            idempotency_key="not-reached",
        )
    assert error.value.error == "permission_denied"


def test_desktop_pairing_rejects_expired_code(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    allow_testclient_loopback(monkeypatch)
    with SessionLocal() as db:
        pairing = db.scalar(
            select(PairingCode).where(PairingCode.code_hash == hash_pairing_code(identity.pairing_code))
        )
        assert pairing is not None
        pairing.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()

    response = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": identity.pairing_code,
            "device_name": "pytest-desktop",
            "platform": "desktop",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_pairing_code"


def test_desktop_explicit_revoke_invalidates_the_exact_app_session(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    allow_testclient_loopback(monkeypatch)
    desktop_token = mint_desktop_token_from(identity.app_token)

    bridge_only = client.post(
        "/desktop/session/revoke",
        headers=BRIDGE_HEADERS,
    )
    revoked = client.post(
        "/desktop/session/revoke",
        headers=principal_headers(desktop_token),
    )
    after_revoke = workspace(
        client,
        "inbox",
        token=desktop_token,
    )

    assert bridge_only.status_code == 401
    assert bridge_only.json()["error"] == "invalid_token"
    assert revoked.status_code == 204
    assert revoked.content == b""
    assert after_revoke.status_code == 401
    assert after_revoke.json()["error"] == "invalid_token"
