"""Protocol rejection precedes validation of the new month-bearing commands."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_writer_context
from app.database import get_db
from app.errors import AppError, add_exception_handlers
from app.routes import income_plans, recycle_bin
from app.runtime_compatibility_contract import (
    CURRENT_API_VERSION,
    RUNTIME_COMPATIBILITY_SESSION_KEY,
    RuntimeCompatibilityRequest,
)

MONTHLESS_API_VERSION = "2026-08-02"
COMMANDS = (
    ("POST", "/api/income-plans", {"label": "plan", "amount_cents": 100, "pay_day": 1}),
    ("PATCH", "/api/income-plans/plan", {"expected_row_version": 1, "amount_cents": 200}),
    ("DELETE", "/api/income-plans/plan", {"expected_row_version": 1}),
    ("POST", "/api/income-plans/plan/restore", {"expected_row_version": 1}),
    ("POST", "/api/recycle-bin/restore", {"kind": "income_plan", "resource_id": "plan", "expected_row_version": 1}),
    ("POST", "/api/recycle-bin/restore", {"kind": " income_plan ", "resource_id": "plan", "expected_row_version": 1}),
)


def test_month_bearing_protocol_has_a_distinct_version() -> None:
    assert CURRENT_API_VERSION != MONTHLESS_API_VERSION


def test_protocol_schema_requires_one_header_for_each_guarded_income_command() -> None:
    from app.main import app

    schema = app.openapi()
    components = schema["components"]["parameters"]
    for method, path, _ in COMMANDS[:4]:
        route = path.replace("/plan", "/{public_id}")
        parameters = schema["paths"][route][method.lower()]["parameters"]
        resolved = [components[p["$ref"].rsplit("/", 1)[-1]] if "$ref" in p else p for p in parameters]
        version_headers = [p for p in resolved if p.get("name") == "Ticketbox-Api-Version"]
        assert len(version_headers) == 1, (method, route, version_headers)
        assert version_headers[0]["required"] is True, (method, route)
    # Other recycle kinds do not require the income epoch. Document that
    # conditional guard without imposing a new protocol on every restore.
    parameters = schema["paths"]["/api/recycle-bin/restore"]["post"]["parameters"]
    resolved = [components[p["$ref"].rsplit("/", 1)[-1]] if "$ref" in p else p for p in parameters]
    version_headers = [p for p in resolved if p.get("name") == "Ticketbox-Api-Version"]
    assert len(version_headers) == 1
    assert version_headers[0]["required"] is False
    assert "income_plan" in version_headers[0]["description"]


def test_recycle_income_display_and_restore_share_one_accounting_month(monkeypatch) -> None:
    from app.services import recycle_bin_service

    clock = Mock(side_effect=["2026-09", "2026-10", "2026-10", "2026-10"])
    monkeypatch.setattr(recycle_bin_service, "current_accounting_month", clock)
    monkeypatch.setattr(recycle_bin_service, "_income_detail", lambda _item, _currency: "计划")
    db = Mock()
    db.scalars.return_value = [
        SimpleNamespace(public_id=key, label=key, archived_at=None, row_version=2)
        for key in ("plan-a", "plan-b")
    ]

    rows = recycle_bin_service._archived_income_rows(db, "owner", "CNY")
    responses = [recycle_bin._to_response(row) for row in rows]

    assert len(responses) == 2
    for row in responses:
        assert row.restore_intent_month == "2026-09"
        assert row.detail.endswith("恢复从 2026-09 生效")
    clock.assert_called_once_with()


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


@pytest.mark.parametrize("case", [
    ("ADOPTION_REQUIRED", CURRENT_API_VERSION, None, "http_client", None, "currency_adoption_required"),
    ("ACTIVE", CURRENT_API_VERSION, None, "http_client", None, "client_upgrade_required"),
    ("EMPTY", CURRENT_API_VERSION, None, "http_client", None, "currency_adoption_required"),
    ("ADOPTION_REQUIRED", MONTHLESS_API_VERSION, None, "http_client", None, "client_upgrade_required"),
    ("ADOPTION_REQUIRED", None, None, "http_client", None, "currency_adoption_required"),
    ("ADOPTION_REQUIRED", None, None, "server_runtime", None, "currency_adoption_required"),
    ("ADOPTION_REQUIRED", CURRENT_API_VERSION, None, "http_client", 0, "client_upgrade_required"),
    ("ADOPTION_REQUIRED", CURRENT_API_VERSION, "invalid", "http_client", None, "client_upgrade_required"),
    ("ADOPTION_REQUIRED", CURRENT_API_VERSION, "1:0:CNY", "http_client", None, "currency_adoption_required"),
    ("ACTIVE", CURRENT_API_VERSION, "1:7:CNY", "http_client", None, "currency_binding_revision_conflict"),
])
def test_currency_owner_keeps_adoption_refusal_without_inventing_proof(
    monkeypatch, case,
) -> None:
    from app.services import currency_binding_service as currency_owner

    state, version, binding, origin, revision, error = case
    db = Mock(info={RUNTIME_COMPATIBILITY_SESSION_KEY: RuntimeCompatibilityRequest(version, binding, origin)})
    stored_binding = SimpleNamespace(state=state, home_currency_code="JPY", currency_contract_version=1, binding_revision=7)
    monkeypatch.setattr(currency_owner, "_load_binding", lambda _db, **_: stored_binding)
    proof = Mock(side_effect=AssertionError("Refused command must not gain writer proof"))
    monkeypatch.setattr(currency_owner, "_set_writer_proof", proof)

    with pytest.raises(AppError) as raised:
        currency_owner.resolve_write_capability(
            db, expected_contract_version=1 if revision is not None else None, expected_revision=revision,
        )

    assert raised.value.error == error
    assert raised.value.status_code == 409
    proof.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_called()
