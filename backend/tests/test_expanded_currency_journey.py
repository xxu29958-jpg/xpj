"""New currency selection reaches recorded money and real quote projection."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.services.currency_common import currency_input_metadata, minor_amount_value
from app.services.money_projection_service import project_recorded_amount


@pytest.mark.parametrize(("code", "major", "minor", "rate", "home"), [
    ("TWD", "120.50", 12050, "0.22", 2651),
    ("VND", "120000", 120000, "0.00028", 3360),
    ("KWD", "1.234", 1234, "23.4", 2888),
])
def test_record_foreign_money_with_original_units_then_project_without_rewriting(client, identity, code, major, minor, rate, home):
    from app.services import fx_rate_provider as provider

    day = date(2026, 5, 29)
    body = {"home_currency_code": code, "original_currency": code, "original_amount": major,
        "client_ref": str(uuid4()), "category": "旅行", "expense_time": f"{day}T12:00:00Z"}
    created = client.post("/api/expenses/manual", json=body, headers=identity.app_headers)
    assert created.status_code == 200, created.text
    fact = created.json()
    assert (fact["home_currency"], fact["amount_cents"], fact["original_amount_minor"]) == (code, minor, minor)
    assert minor_amount_value(minor, code) == major
    with SessionLocal() as db:
        provider.upsert_fx_rate(db, home_currency_code="CNY", currency_code=code, rate_date=day, rate_to_home=Decimal(rate))
        assert project_recorded_amount(db, tenant_id="owner", amount_minor=minor,
            source_currency=code, home_currency="CNY", rate_date=day) == home
    reread = client.get(f"/api/expenses/{fact['id']}", headers=identity.app_headers).json()
    assert (reread["amount_cents"], reread["home_currency"]) == (minor, code)
    assert client.post("/api/expenses/manual", json=body, headers=identity.app_headers).json()["id"] == fact["id"]
    if code == "KWD":
        assert currency_input_metadata(code)["amount_step"] == "0.001"
        invalid = client.post("/api/expenses/manual", headers=identity.app_headers,
            json={**body, "client_ref": str(uuid4()), "original_amount": "1.2345"})
        assert invalid.status_code == 422
