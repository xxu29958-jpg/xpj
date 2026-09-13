"""Old rule clients receive an upgrade result before required money validation."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.auth import get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.routes.rules import router
from app.runtime_compatibility_contract import CURRENT_API_VERSION


@pytest.mark.parametrize(("method", "path", "body"), [
    ("POST", "/api/rules/categories", {"keyword": "Travel", "category": "交通", "amount_min_cents": 1200}),
    ("PATCH", "/api/rules/categories/17", {"expected_row_version": 3, "amount_min_cents": 1200}),
])
@pytest.mark.parametrize("version", [None, "2026-09-07", CURRENT_API_VERSION])
def test_old_protocol_is_refused_before_amount_currency_schema(method, path, body, version):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_writer_context] = lambda: SimpleNamespace(tenant_id="owner", role="owner")
    app.dependency_overrides[get_db] = lambda: None

    @app.exception_handler(AppError)
    async def app_error(_request, error):
        return JSONResponse({"error": error.error}, status_code=error.status_code)

    headers = {} if version is None else {"Ticketbox-Api-Version": version}
    response = TestClient(app).request(method, path, json=body, headers=headers)
    if version == CURRENT_API_VERSION:
        assert response.status_code == 422, response.text
        assert "home_currency_code" in response.text
    else:
        assert response.status_code == 409, response.text
        assert response.json()["error"] == "client_upgrade_required"
