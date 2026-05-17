from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.services.fx_rate_provider import cross_rate_to_home, parse_ecb_daily_rates, upsert_fx_rate
from conftest import app_headers, gray_app_headers


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        members = db.scalars(select(LedgerMember).where(LedgerMember.ledger_id == "owner")).all()
        assert members
        for member in members:
            member.role = "viewer"
        db.commit()


def test_exchange_rate_crud_is_ledger_scoped_and_viewer_read_only(client: TestClient) -> None:
    created = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=app_headers(),
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7.1234",
            "source": "manual",
        },
    )
    assert created.status_code == 200, created.json()
    assert created.json()["currency_code"] == "USD"
    assert Decimal(created.json()["rate_to_cny"]) == Decimal("7.12340000")

    owner_rates = client.get("/api/exchange-rates?currency_code=USD", headers=app_headers())
    assert owner_rates.status_code == 200, owner_rates.json()
    assert [row["rate_date"] for row in owner_rates.json()["items"]] == ["2026-05-04"]

    gray_rates = client.get("/api/exchange-rates?currency_code=USD", headers=gray_app_headers())
    assert gray_rates.status_code == 200, gray_rates.json()
    assert gray_rates.json()["items"] == []

    _demote_owner_ledger_to_viewer()
    viewer_read = client.get("/api/exchange-rates?currency_code=USD", headers=app_headers())
    assert viewer_read.status_code == 200, viewer_read.json()
    assert viewer_read.json()["items"][0]["rate_date"] == "2026-05-04"

    viewer_write = client.put(
        "/api/exchange-rates/USD/2026-05-05",
        headers=app_headers(),
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-05",
            "rate_to_cny": "7.2",
        },
    )
    assert viewer_write.status_code == 403
    assert viewer_write.json()["error"] == "permission_denied"


def test_manual_foreign_expense_uses_stored_daily_rate_and_stats_stay_cny(client: TestClient) -> None:
    rate = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=app_headers(),
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7.1234",
            "source": "manual",
        },
    )
    assert rate.status_code == 200, rate.json()

    response = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 12345,
            "merchant": "海外咖啡",
            "category": "餐饮",
            "expense_time": "2026-05-04T02:00:00Z",
        },
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["amount_cents"] == 87938
    assert payload["home_amount_cents"] == 87938
    assert payload["home_currency"] == "CNY"
    assert payload["original_currency_code"] == "USD"
    assert payload["original_currency"] == "USD"
    assert payload["original_amount_minor"] == 12345
    assert Decimal(payload["original_amount"]) == Decimal("123.45")
    assert Decimal(payload["exchange_rate_to_cny"]) == Decimal("7.12340000")
    assert Decimal(payload["fx_rate"]) == Decimal("7.12340000")
    assert payload["exchange_rate_date"] == "2026-05-04"
    assert payload["fx_rate_date"] == "2026-05-04"
    assert payload["fx_source"] == "manual"
    assert payload["fx_status"] == "ready"

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 87938

    exported = client.get("/api/expenses/export.csv?month=2026-05", headers=app_headers())
    assert exported.status_code == 200, exported.text
    header = exported.text.splitlines()[0]
    assert "original_currency_code" in header
    assert "original_amount_minor" in header
    assert "exchange_rate_to_cny" in header
    assert "USD" in exported.text
    assert "12345" in exported.text
    assert "7.12340000" in exported.text


def test_jpy_expense_uses_zero_fraction_minor_units_and_missing_rate_stays_pending(client: TestClient) -> None:
    missing_rate = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "original_currency_code": "JPY",
            "original_amount_minor": 1200,
            "spent_at": "2026-05-04T02:00:00Z",
            "merchant": "东京交通",
        },
    )
    assert missing_rate.status_code == 200, missing_rate.json()
    pending_payload = missing_rate.json()
    assert pending_payload["status"] == "pending"
    assert pending_payload["amount_cents"] is None
    assert pending_payload["home_amount_cents"] is None
    assert pending_payload["fx_rate"] is None
    assert pending_payload["fx_status"] == "pending"
    pending_id = int(pending_payload["id"])

    with SessionLocal() as db:
        upsert_fx_rate(
            db,
            currency_code="JPY",
            rate_date=date(2026, 5, 4),
            rate_to_home=Decimal("0.048"),
        )
        db.commit()

    confirmed_pending = client.post(
        f"/api/expenses/{pending_id}/confirm",
        headers=app_headers(),
    )
    assert confirmed_pending.status_code == 200, confirmed_pending.json()
    assert confirmed_pending.json()["status"] == "confirmed"
    assert confirmed_pending.json()["amount_cents"] == 5760
    assert confirmed_pending.json()["fx_status"] == "ready"

    response = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "original_currency_code": "JPY",
            "original_amount_minor": 1200,
            "merchant": "东京交通",
            "category": "交通",
            "expense_time": "2026-05-04T04:00:00Z",
        },
    )
    assert response.status_code == 200, response.json()
    assert response.json()["amount_cents"] == 5760
    assert response.json()["home_amount_cents"] == 5760
    assert response.json()["original_currency_code"] == "JPY"
    assert response.json()["original_amount_minor"] == 1200
    assert Decimal(response.json()["fx_rate"]) == Decimal("0.04800000")
    assert response.json()["fx_source"] == "ecb"
    assert response.json()["fx_status"] == "ready"


def test_legacy_amount_payload_defaults_to_cny_rate_one(client: TestClient) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "amount_cents": 1280,
            "merchant": "手动早餐",
            "category": "餐饮",
            "expense_time": "2026-05-04T00:30:00Z",
        },
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["amount_cents"] == 1280
    assert payload["original_currency_code"] == "CNY"
    assert payload["original_amount_minor"] == 1280
    assert Decimal(payload["exchange_rate_to_cny"]) == Decimal("1.00000000")
    assert payload["exchange_rate_source"] == "base"
    assert payload["home_amount_cents"] == 1280
    assert payload["home_currency"] == "CNY"
    assert payload["fx_status"] == "ready"


def test_expense_write_rejects_client_submitted_exchange_rate(client: TestClient) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "original_currency": "USD",
            "original_amount": "12.34",
            "spent_at": "2026-05-15T02:00:00Z",
            "exchange_rate_to_cny": "7.1234",
            "merchant": "客户端汇率",
        },
    )

    assert response.status_code == 422


def test_ecb_daily_xml_cross_rate_can_be_stored_as_home_rate(client: TestClient) -> None:
    xml = """
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
        xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube>
        <Cube time="2026-05-15">
          <Cube currency="USD" rate="1.1628"/>
          <Cube currency="CNY" rate="7.9194"/>
        </Cube>
      </Cube>
    </gesmes:Envelope>
    """
    daily = parse_ecb_daily_rates(xml)
    expected = (Decimal("7.9194") / Decimal("1.1628")).quantize(Decimal("0.00000001"))
    assert daily.rate_date == date(2026, 5, 15)
    assert cross_rate_to_home(daily.rates_per_eur, currency_code="USD") == expected

    with SessionLocal() as db:
        upsert_fx_rate(
            db,
            currency_code="USD",
            rate_date=daily.rate_date,
            rate_to_home=expected,
            provider_rate=daily.rates_per_eur["USD"],
        )
        db.commit()

    response = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "original_currency": "USD",
            "original_amount": "12.34",
            "spent_at": "2026-05-15T02:00:00Z",
            "merchant": "ECB 测试",
        },
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["amount_cents"] == 8404
    assert payload["original_currency"] == "USD"
    assert Decimal(payload["original_amount"]) == Decimal("12.34")
    assert Decimal(payload["fx_rate"]) == expected
    assert payload["fx_source"] == "ecb"
