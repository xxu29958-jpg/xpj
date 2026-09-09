"""Old goal clients must be refused before validating the new monetary body."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.auth import get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.routes.goals import router
from app.runtime_compatibility_contract import CURRENT_API_VERSION


@pytest.mark.parametrize(("method", "path", "body"), [
    ("POST", "/api/goals", {"name": "旧客户端目标", "month": "2026-09", "target_amount_cents": 1200}),
    ("PATCH", "/api/goals/original-goal", {"expected_row_version": 1, "target_amount_cents": 1200}),
])
@pytest.mark.parametrize(("headers", "expected_status"), [
    ({}, 409), ({"Ticketbox-Api-Version": "2026-09-07"}, 409),
    ({"Ticketbox-Api-Version": CURRENT_API_VERSION}, 422),
])
def test_original_goal_body_gets_upgrade_instruction_before_new_schema(method, path, body, headers, expected_status):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_writer_context] = lambda: SimpleNamespace(tenant_id="owner", role="owner")
    app.dependency_overrides[get_db] = lambda: None

    @app.exception_handler(AppError)
    async def app_error(_request, error):
        return JSONResponse({"error": error.error}, status_code=error.status_code)

    response = TestClient(app).request(method, path, json=body, headers=headers)
    assert response.status_code == expected_status, response.text
    if expected_status == 409:
        assert response.json()["error"] == "client_upgrade_required"
    else:
        assert "home_currency_code" in response.text
