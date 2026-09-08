"""A manual exchange rate belongs to a currency pair, never to a later setting."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.services.exchange_rate_service import resolve_payload_rate


def _put_rate(client, identity, home, rate):
    return client.put(
        "/api/exchange-rates/USD/2026-09-08",
        headers=identity.app_headers,
        json={
            "currency_code": "USD", "home_currency_code": home,
            "rate_date": "2026-09-08", "rate_to_cny": rate,
        },
    )


@pytest.mark.currency_binding_unbound
def test_unadopted_rates_require_owner_choice_before_the_list_can_label_them(client: TestClient, identity):
    response = client.get("/api/exchange-rates", headers=identity.app_headers)
    assert response.status_code == 409
    assert response.json()["error"] == "currency_adoption_required"


def test_manual_rate_requires_the_target_currency(client: TestClient, identity):
    response = client.put(
        "/api/exchange-rates/USD/2026-09-08",
        headers=identity.app_headers,
        json={"currency_code": "USD", "rate_date": "2026-09-08", "rate_to_cny": "7"},
    )
    assert response.status_code == 422
    rates = client.get("/api/exchange-rates", headers=identity.app_headers)
    assert rates.json()["items"] == []


def test_manual_rate_pairs_coexist_and_updates_do_not_rewrite_the_other_pair(client: TestClient, identity):
    yuan = _put_rate(client, identity, "CNY", "7")
    assert yuan.status_code == 200, yuan.json()
    yen = _put_rate(client, identity, "JPY", "150")
    assert yen.status_code == 200, yen.json()
    assert yuan.json()["home_currency_code"] == "CNY"
    assert yen.json()["home_currency_code"] == "JPY"
    assert yuan.json()["public_id"] != yen.json()["public_id"]

    updated = _put_rate(client, identity, "CNY", "7.2")
    assert updated.status_code == 200, updated.json()
    assert updated.json()["public_id"] == yuan.json()["public_id"]
    rates = client.get("/api/exchange-rates?currency_code=USD", headers=identity.app_headers)
    assert rates.status_code == 200, rates.json()
    assert {row["home_currency_code"]: Decimal(row["rate_to_cny"]) for row in rates.json()["items"]} == {
        "CNY": Decimal("7.2"), "JPY": Decimal("150"),
    }
    filtered = client.get("/api/exchange-rates?home_currency_code=JPY", headers=identity.app_headers)
    assert [row["public_id"] for row in filtered.json()["items"]] == [yen.json()["public_id"]]
    other_ledger = client.get("/api/exchange-rates?home_currency_code=JPY", headers=identity.gray_app_headers)
    assert other_ledger.json()["items"] == []

    with SessionLocal() as db:
        for home, expected in (("CNY", "7.2"), ("JPY", "150")):
            rate, source, status, effective = resolve_payload_rate(
                db, tenant_id="owner", currency_code="USD", home_currency_code=home,
                rate_date=date(2026, 9, 8),
            )
            assert (rate, source, status, effective) == (Decimal(expected), "manual", "ready", date(2026, 9, 8))


def test_a_rate_for_another_target_leaves_the_conversion_pending(client: TestClient, identity):
    response = _put_rate(client, identity, "CNY", "7")
    assert response.status_code == 200, response.json()
    with SessionLocal() as db:
        rate, source, status, effective = resolve_payload_rate(
            db, tenant_id="owner", currency_code="USD", home_currency_code="JPY",
            rate_date=date(2026, 9, 8),
        )
        assert (rate, source, status, effective) == (None, None, "pending", date(2026, 9, 8))
