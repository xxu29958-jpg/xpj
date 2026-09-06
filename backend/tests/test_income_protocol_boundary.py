"""Protocol rejection precedes validation of the new month-bearing commands."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_writer_context
from app.database import get_db
from app.errors import add_exception_handlers
from app.routes import income_plans, recycle_bin
from app.runtime_compatibility_contract import CURRENT_API_VERSION

MONTHLESS_API_VERSION = "2026-08-02"
COMMANDS = (
    ("POST", "/api/income-plans", {"label": "plan", "amount_cents": 100, "pay_day": 1}),
    ("PATCH", "/api/income-plans/plan", {"expected_row_version": 1, "amount_cents": 200}),
    ("DELETE", "/api/income-plans/plan", {"expected_row_version": 1}),
    ("POST", "/api/income-plans/plan/restore", {"expected_row_version": 1}),
    ("POST", "/api/recycle-bin/restore", {"kind": "income_plan", "resource_id": "plan", "expected_row_version": 1}),
)


def test_month_bearing_protocol_has_a_distinct_version() -> None:
    assert CURRENT_API_VERSION != MONTHLESS_API_VERSION


@pytest.mark.parametrize("version", [None, MONTHLESS_API_VERSION, "current"])
@pytest.mark.parametrize("method,path,body", COMMANDS)
def test_income_protocol_rejection_precedes_month_validation(version, method, path, body) -> None:
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(income_plans.router)
    app.include_router(recycle_bin.router)
    app.dependency_overrides[get_current_writer_context] = lambda: SimpleNamespace(tenant_id="probe", account_id=1)
    # No database or command owner is needed to reject an unsupported protocol.
    app.dependency_overrides[get_db] = lambda: None
    headers = {} if version is None else {
        "Ticketbox-Api-Version": CURRENT_API_VERSION if version == "current" else version,
        "Ticketbox-Currency-Binding": "1:1:CNY",
    }
    response = TestClient(app).request(method, path, json=body, headers=headers)
    assert response.status_code == (422 if version == "current" else 409)
    assert response.json()["error"] == ("invalid_request" if version == "current" else "client_upgrade_required")
