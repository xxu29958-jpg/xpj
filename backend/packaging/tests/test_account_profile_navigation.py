"""Small real route checks; database consequences run in the PostgreSQL lane."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_app_principal
from app.database import get_db
from app.routes import settings
from app.tenants import SessionPrincipal


def test_connected_account_can_read_its_profile_without_selecting_a_ledger():
    principal = SessionPrincipal(1, "account-public", "小王", 2, "device-public", "手机", "app", 3, "test-hash")
    account = SimpleNamespace(id=1, public_id="account-public", display_name="小王", disabled_at=None)
    app = FastAPI()
    app.include_router(settings.router)
    app.dependency_overrides[get_current_app_principal] = lambda: principal
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(get=lambda *args, **kwargs: account)
    with TestClient(app) as client:
        result = client.get("/api/settings/account")
    assert result.status_code == 200
    assert result.json() == {"account_public_id": "account-public", "display_name": "小王"}
