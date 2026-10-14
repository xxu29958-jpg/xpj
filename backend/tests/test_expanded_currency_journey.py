"""New currency selection reaches recorded money and real quote projection."""

import re
from datetime import date
from decimal import Decimal
from html import unescape
from uuid import uuid4

import pytest
from api_contract_helpers import patch_expense, upload_png

from app.database import SessionLocal
from app.services.money_projection_service import project_recorded_amount


@pytest.mark.parametrize(("code", "major", "minor", "rate", "home"), [
    ("TWD", "120.50", 12050, "0.22", 2651),
    ("VND", "120000", 120000, "0.00028", 3360),
    ("KWD", "12.345", 12345, "23.4", 28887),
])
def test_record_foreign_money_with_original_units_then_project_without_rewriting(client, web_client, identity, code, major, minor, rate, home):
    from app.services import fx_rate_provider as provider

    day = date(2026, 5, 29)
    body = {"home_currency_code": code, "original_currency": code, "original_amount": major,
        "client_ref": str(uuid4()), "category": "旅行", "expense_time": f"{day}T12:00:00Z"}
    created = client.post("/api/expenses/manual", json=body, headers=identity.app_headers)
    assert created.status_code == 200, created.text
    fact = created.json()
    assert (fact["home_currency"], fact["amount_cents"], fact["original_amount_minor"]) == (code, minor, minor)
    assert Decimal(fact["original_amount"]) == Decimal(major)
    with SessionLocal() as db:
        provider.upsert_fx_rate(db, home_currency_code="CNY", currency_code=code, rate_date=day, rate_to_home=Decimal(rate))
        assert project_recorded_amount(db, tenant_id="owner", amount_minor=minor,
            source_currency=code, home_currency="CNY", rate_date=day) == home
    reread = client.get(f"/api/expenses/{fact['id']}", headers=identity.app_headers).json()
    assert (reread["amount_cents"], reread["home_currency"]) == (minor, code)
    assert Decimal(reread["original_amount"]) == Decimal(major)
    assert client.post("/api/expenses/manual", json=body, headers=identity.app_headers).json()["id"] == fact["id"]
    overview = web_client.get(f"/web/overview?ledger_id=owner&month=2026-05&home_currency_code={code}")
    assert overview.status_code == 200, overview.text
    hero = re.search(r'<div class="insight-hero-value[^\"]*">(.*?)</div>', overview.text, re.S)
    assert hero is not None
    displayed_amount = re.sub(r"<small>.*?</small>", "", hero[1], count=1, flags=re.S)
    displayed_amount = unescape(re.sub(r"<[^>]+>", "", displayed_amount)).strip().replace(",", "")
    assert Decimal(displayed_amount) == Decimal(major)
    if code == "KWD":
        invalid = client.post("/api/expenses/manual", headers=identity.app_headers,
            json={**body, "client_ref": str(uuid4()), "original_amount": "1.2345"})
        assert invalid.status_code == 422
        pending_id = upload_png(client, identity=identity)
        for fields, expected in [
            ({"original_currency": "KWD", "original_amount": "12.345"}, 12345),
            ({"note": "仅改备注"}, 12345),
            ({"original_amount": "12.346"}, 12346),
        ]:
            edited = patch_expense(client, pending_id, headers=identity.app_headers, fields=fields)
            assert edited.status_code == 200, edited.text
            stored = client.get(f"/api/expenses/{pending_id}", headers=identity.app_headers).json()
            assert stored["original_amount_minor"] == expected
            assert Decimal(stored["original_amount"]) == Decimal(expected) / 1000
