"""The real report router preserves task currency, nullable money and viewer reads."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_period_report_projection import StreamRows, entry

from app.auth import get_current_app_context
from app.database import get_db
from app.routes import reports
from app.services import money_projection_service as money
from app.services.reports_service import _ranking


def test_report_api_and_csv_expose_same_original_home_and_missing_rate(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    monkeypatch.setattr(_ranking, "enabled_merchant_display_map", lambda *a, **kw: {})
    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="owner", role="viewer")
    app.dependency_overrides[get_db] = lambda: StreamRows([entry(2000, "CNY"), entry(1000)])
    client = TestClient(app)
    query = "?month=2026-09&timezone=UTC&home_currency_code=JPY&granularity=week&ranking_metric=count"
    response = client.get("/api/reports/overview" + query)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["month"], body["home_currency_code"], body["granularity"], body["count"]) == ("2026-09", "JPY", "week", 2)
    assert body["total_amount_cents"] is None
    assert body["merchant_ranking"][0]["amount_cents"] is None
    assert body["missing_rates"] == [{"source_currency_code": "CNY", "home_currency_code": "JPY", "rate_date": "2026-09-07"}]
    exported = client.get("/api/reports/overview.csv" + query)
    assert exported.status_code == 200, exported.text
    assert "summary,home_currency_code,JPY" in exported.text
    assert "summary,total_amount_cents,\n" in exported.text
    assert "missing_rates,CNY,JPY,2026-09-07" in exported.text


def test_explicit_invalid_report_home_is_rejected_before_read():
    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="owner")
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    for home in ("", "jpy", "JP"):
        response = client.get("/api/reports/overview?month=2026-09&home_currency_code=" + home)
        assert response.status_code == 422
