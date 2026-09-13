"""The actual read endpoint admits viewers and exposes gaps without AI side effects."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_app_context
from app.database import get_db
from app.routes import budget_advisor
from app.services.budget_advisor_service._inputs_builder import BudgetInputProjection
from app.services.budget_baseline_service import compute_monthly_discretionary
from app.services.money_projection_service import ProjectionGap


def test_viewer_can_read_original_month_currency_and_nullable_inputs(monkeypatch):
    projection = BudgetInputProjection("2026-08", "JPY", compute_monthly_discretionary(
        monthly_income_cents=2000, fixed_expenses_cents=100, spent_amount_cents=None,
        savings_target_cents=20, reserved_buffer_cents=30),
        (ProjectionGap("CNY", "JPY", date(2026, 7, 2)), ProjectionGap(None, "JPY", None)), None)
    read = Mock(return_value=projection)
    monkeypatch.setattr(budget_advisor, "read_budget_inputs", read, raising=False)
    forbidden = Mock(side_effect=AssertionError("GET must not invoke advisor"))
    monkeypatch.setattr(budget_advisor, "run_budget_advisor", forbidden)
    app = FastAPI()
    app.include_router(budget_advisor.router)
    app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="ledger-a", role="viewer")
    app.dependency_overrides[get_db] = lambda: None
    response = TestClient(app).get("/api/budget/advisor/inputs?month=2026-08&home_currency_code=JPY"
        "&timezone=UTC&savings_target_cents=20&reserved_buffer_cents=30")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["month"], body["home_currency_code"]) == ("2026-08", "JPY")
    assert body["breakdown"]["spent_amount_cents"] is body["breakdown"]["discretionary_cents"] is None
    assert body["missing_rates"] == [
        {"source_currency_code": "CNY", "home_currency_code": "JPY", "rate_date": "2026-07-02"},
        {"source_currency_code": None, "home_currency_code": "JPY", "rate_date": None},
    ]
    assert "provider_inputs" not in body
    assert body["inputs_fingerprint"] is None
    assert read.call_args.kwargs == {"tenant_id": "ledger-a", "month": "2026-08", "home_currency_code": "JPY",
        "timezone_name": "UTC", "savings_target_cents": 20, "reserved_buffer_cents": 30}
    forbidden.assert_not_called()


def test_generation_http_carries_the_input_currency_to_the_same_owner(monkeypatch):
    run = Mock(return_value=SimpleNamespace(advice=None, home_currency_code="JPY", provider_name="empty", reason_code=None))
    monkeypatch.setattr(budget_advisor, "run_budget_advisor", run)
    app = FastAPI()
    app.include_router(budget_advisor.router)
    app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="ledger-a", role="owner", account_id=1)
    app.dependency_overrides[get_db] = lambda: None
    response = TestClient(app).post("/api/budget/advise", json={
        "month": "2026-08", "timezone": "UTC", "home_currency_code": "JPY",
    })
    assert response.status_code == 200, response.text
    assert response.json()["home_currency_code"] == "JPY"
    assert run.call_args.kwargs == {"tenant_id": "ledger-a", "actor_role": "owner", "actor_account_id": 1,
        "month": "2026-08", "timezone_name": "UTC", "home_currency_code": "JPY"}
