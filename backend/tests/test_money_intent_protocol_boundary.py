"""Currency-bearing commands reject old clients before body validation."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_writer_context
from app.database import get_db
from app.errors import add_exception_handlers
from app.routes import debts, exchange_rates
from app.runtime_compatibility_contract import CURRENT_API_VERSION
from app.services import runtime_compatibility_service
from app.services.currency_binding_service import CurrencyCapability


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/debts", {"direction": "i_owe", "counterparty_type": "external", "principal_amount_cents": 1200}),
    ("PUT", "/api/exchange-rates/USD/2026-09-08", {"currency_code": "USD", "rate_date": "2026-09-08", "rate_to_cny": "7"}),
])
@pytest.mark.parametrize("version", [None, "2026-09-07", "current"])
def test_currency_intent_protocol_rejection_precedes_missing_money_context(version, method, path, body):
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(debts.router)
    app.include_router(exchange_rates.router)
    app.dependency_overrides[get_current_writer_context] = lambda: SimpleNamespace(tenant_id="probe", account_id=1)
    app.dependency_overrides[get_db] = lambda: None
    headers = {} if version is None else {"Ticketbox-Api-Version": CURRENT_API_VERSION if version == "current" else version}
    with TestClient(app) as client:
        response = client.request(method, path, json=body, headers=headers)
    assert response.status_code == (422 if version == "current" else 409)
    assert response.json()["error"] == ("invalid_request" if version == "current" else "client_upgrade_required")


def test_cny_revision_one_no_longer_claims_the_unversioned_write_protocol_is_compatible(monkeypatch):
    capability = CurrencyCapability(state="ACTIVE", home_currency_code="CNY", minor_unit_exponent=2,
        rounding_mode="ROUND_HALF_UP", currency_contract_version=1, binding_revision=1,
        minimum_writable_currency_contract=1, health="active_match", initialization_offer=None)
    monkeypatch.setattr(runtime_compatibility_service, "get_capability", lambda _db: capability)
    snapshot = runtime_compatibility_service.runtime_compatibility_snapshot(None)
    assert snapshot.write_compatibility == "compatible"
    assert snapshot.legacy_write_compatibility == "client_upgrade_required"
