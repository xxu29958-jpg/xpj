"""Local governance stays local even with the retired public opt-in present.

The real app, router, network guard and scope checks run here. Only database
identity reads and final business services are substituted. Request tests do
not run lifespan; the startup test stops before database readiness. The PG
suite separately owns persisted identity checks.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app import auth
from app.config import reset_settings_cache
from app.database import get_db
from app.errors import AppError
from app.main import app
from app.network_boundary import require_admin_network_boundary
from app.routes import admin, bootstrap, maintenance
from app.schemas import MaintenanceCleanupResponse, PairingCodeResponse
from app.services import admin_scope_service, route_inspector_service
from app.tenants import AuthContext

_ROUTES = (
    ("GET", "/api/admin/devices", None),
    ("POST", "/api/maintenance/cleanup-images", None),
    ("POST", "/api/bootstrap/pairing-codes", {"ttl_minutes": 15}),
)


@pytest.fixture()
def old_public_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_TEAM_DOMAIN", "https://family.cloudflareaccess.com")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_AUD", "test-access-audience")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.mark.parametrize(
    ("peer", "host"),
    (("127.0.0.1", "api.example.com"), ("203.0.113.8", "127.0.0.1:8000")),
)
def test_retired_opt_in_cannot_open_admin_boundary(old_public_configuration, peer, host):
    request = Request({
        "type": "http", "method": "GET", "path": "/api/admin/devices",
        "headers": [(b"host", host.encode())], "client": (peer, 50001),
        "query_string": b"",
    })
    with pytest.raises(AppError) as error:
        require_admin_network_boundary(request)
    assert (error.value.status_code, error.value.error) == (403, "admin_api_local_only")


@pytest.fixture()
def governance_services(monkeypatch: pytest.MonkeyPatch):
    from app.middleware import cloudflare_access

    calls = []
    context = AuthContext(
        account_id=11, account_public_id="account-a", account_name="Owner",
        ledger_id="ledger-a", ledger_name="Household", device_id=21,
        device_public_id="device-a", device_name="Local maintenance",
        role="owner", scope="admin",
    )

    def authenticate(_db, token, _scopes):
        if token == "boundary-admin-session":
            return context
        if token == "boundary-app-session":
            return replace(context, scope="app")
        raise AppError("invalid_token", status_code=401)

    def list_devices(_db, *, account_id):
        calls.append(("devices", account_id))
        return []

    def cleanup_images(_db, tenant_id):
        calls.append(("cleanup", tenant_id))
        return MaintenanceCleanupResponse(
            enabled=True, delete_after_days=30, scanned=0,
            deleted_images=0, deleted_thumbnails=0,
        )

    def create_pairing(_db, **values):
        calls.append(("pairing", values["ledger_id"], values["account_id"]))
        return PairingCodeResponse(
            pairing_code="12345678", ledger_name="Household",
            expires_at="2026-09-06T12:15:00Z",
        )

    saved_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.pop(require_admin_network_boundary, None)
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(auth, "authenticate_session_token", authenticate)
    monkeypatch.setattr(admin.admin_service, "list_devices", list_devices)
    monkeypatch.setattr(maintenance, "cleanup_confirmed_images", cleanup_images)
    monkeypatch.setattr(bootstrap, "create_pairing_code", create_pairing)
    monkeypatch.setattr(
        admin_scope_service, "managed_ledger_ids_for_account",
        lambda _db, *, account_id: {"ledger-a"} if account_id == 11 else set(),
    )
    monkeypatch.setattr(
        cloudflare_access, "verify_cloudflare_access_jwt",
        lambda *_args, **_kwargs: {"sub": "owner@example.com"},
    )
    yield calls
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved_overrides)


@pytest.mark.parametrize(("method", "path", "body"), _ROUTES)
def test_public_governance_refuses_valid_admin_before_service(
    old_public_configuration, governance_services, method, path, body,
):
    client = TestClient(app, base_url="https://api.example.com", client=("127.0.0.1", 50001))
    try:
        response = client.request(method, path, json=body, headers={
            "Authorization": "Bearer boundary-admin-session",
            "cf-access-jwt-assertion": "valid-access-jwt",
        })
    finally:
        client.close()
    assert response.status_code == 403
    assert response.json()["error"] == "admin_api_local_only"
    assert governance_services == []


@pytest.mark.parametrize(("method", "path", "body"), _ROUTES)
@pytest.mark.parametrize(("token", "status"), (
    ("boundary-admin-session", 200), ("boundary-app-session", 403), ("invalid-session", 401),
))
def test_local_governance_keeps_admin_auth_and_original_scope(
    old_public_configuration, governance_services, method, path, body, token, status,
):
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50001))
    try:
        response = client.request(method, path, json=body, headers={"Authorization": f"Bearer {token}"})
    finally:
        client.close()
    assert response.status_code == status
    if status == 200:
        expected = {
            "/api/admin/devices": ("devices", 11),
            "/api/maintenance/cleanup-images": ("cleanup", "ledger-a"),
            "/api/bootstrap/pairing-codes": ("pairing", "ledger-a", 11),
        }
        assert governance_services == [expected[path]]
    else:
        assert governance_services == []


def test_route_inventory_groups_all_shared_guard_consumers_as_local_governance():
    groups = route_inspector_service.list_route_groups(app)
    local_admin = next(group for group in groups if group.surface == "admin")
    paths = {row.path for row in local_admin.rows}
    assert {"/api/admin/devices", "/api/maintenance/cleanup-images", "/api/bootstrap/pairing-codes"} <= paths
    assert "仅本机" in local_admin.label


def test_retired_opt_in_without_access_does_not_block_local_startup(
    old_public_configuration, monkeypatch: pytest.MonkeyPatch,
):
    from app import main

    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "false")
    monkeypatch.delenv("CLOUDFLARE_ACCESS_TEAM_DOMAIN")
    monkeypatch.delenv("CLOUDFLARE_ACCESS_AUD")
    reset_settings_cache()

    class DatabaseReadinessReachedError(Exception):
        pass

    def stop_before_database():
        raise DatabaseReadinessReachedError

    monkeypatch.setattr(main, "wait_for_db", stop_before_database)

    async def enter_startup():
        async with main.lifespan(app):
            pytest.fail("The database fence must stop startup before services run")

    with pytest.raises(DatabaseReadinessReachedError):
        asyncio.run(enter_startup())
