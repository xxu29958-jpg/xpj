"""New recurring monetary bodies negotiate before rejecting a legacy payload."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.auth import get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.routes.recurring import router
from app.runtime_compatibility_contract import CURRENT_API_VERSION


@pytest.mark.parametrize(("method", "path", "body"), [
    ("POST", "/api/recurring/items", {"merchant": "旧客户端计划", "baseline_amount_cents": 1200}),
    ("POST", "/api/recurring/from-candidate", {"merchant": "旧候选", "amount_cents": 1200}),
    ("PATCH", "/api/recurring/items/original-item", {"expected_row_version": 1, "baseline_amount_cents": 1200}),
])
@pytest.mark.parametrize(("headers", "status"), [
    ({}, 409),
    ({"Ticketbox-Api-Version": "2026-09-07"}, 409),
    ({"Ticketbox-Api-Version": CURRENT_API_VERSION}, 422),
])
def test_recurring_original_body_gets_protocol_admission_before_schema(method, path, body, headers, status):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_writer_context] = lambda: SimpleNamespace(tenant_id="owner", role="owner")
    app.dependency_overrides[get_db] = lambda: None

    @app.exception_handler(AppError)
    async def app_error(_request, error):
        return JSONResponse({"error": error.error}, status_code=error.status_code)

    response = TestClient(app).request(method, path, json=body, headers=headers)
    assert response.status_code == status, response.text
    if status == 409:
        assert response.json()["error"] == "client_upgrade_required"
    else:
        assert response.json()["detail"][0]["loc"] == ["body", "home_currency_code"]
        assert response.json()["detail"][0]["type"] == "missing"
