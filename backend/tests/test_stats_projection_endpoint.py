"""Actual stats routers preserve task currency and distinguish missing from zero."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_stats_currency_projection import StatsRows, entry

from app.auth import get_current_app_context
from app.database import get_db
from app.routes import stats as routes
from app.services import money_projection_service as money
from app.services import stats_service as stats


def client_for(monkeypatch, rows):
    monkeypatch.setattr(stats, "require_runtime_home_currency_code", lambda db: "CNY")
    monkeypatch.setattr(stats, "enabled_merchant_display_map", lambda *a, **kw: {})
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="owner", role="viewer")
    app.dependency_overrides[get_db] = lambda: StatsRows(rows)
    return TestClient(app, raise_server_exceptions=False)


def test_stats_api_preserves_explicit_home_nullable_money_and_original_month(monkeypatch):
    client = client_for(monkeypatch, [entry(-2000, "CNY", kind="offset")])
    query = {"month": "2026-09", "timezone": "UTC", "home_currency_code": "JPY"}
    for route in ("monthly", "lifestyle"):
        response = client.get("/api/stats/" + route, params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["month"], body["home_currency_code"]) == ("2026-09", "JPY")
        assert body["missing_rates"] == [{"source_currency_code": "CNY", "home_currency_code": "JPY", "rate_date": "2026-09-09"}]
        if route == "monthly":
            assert (body["total_amount_cents"], body["count"]) == (None, 1)
            assert body["by_category"] == [{"category": "数码", "amount_cents": None, "count": 1}]
        else:
            assert body["digital_amount_cents"] is None
            assert body["max_expense"] is None


def test_explicit_invalid_stats_home_cannot_fall_back_to_runtime(monkeypatch):
    client = client_for(monkeypatch, [])
    for route in ("monthly", "lifestyle"):
        for home in ("", "jpy", "JP"):
            response = client.get("/api/stats/" + route, params={"month": "2026-09", "home_currency_code": home})
            assert response.status_code == 422, (route, home, response.text)
