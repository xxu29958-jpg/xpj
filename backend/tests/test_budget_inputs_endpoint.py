"""The actual read endpoint admits viewers and exposes gaps without AI side effects."""

from datetime import UTC, date, datetime
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


def test_cross_currency_http_trial_and_ai_share_repaired_report_basis(monkeypatch):
    from app.schemas._monthly_arrangement import MonthlyArrangementDto
    from app.services.budget_advisor_service import _inputs_builder as builder
    from app.services.budget_advisor_service import _runner
    from tests.test_budget_inputs_projection import seed_reads

    seed_reads(monkeypatch)
    saved = MonthlyArrangementDto(ledger_id="ledger-a", month="2026-08", home_currency_code="JPY",
        savings_target_cents=500, reserved_buffer_cents=100, row_version=3, updated_at=datetime(2026, 9, 27, tzinfo=UTC))
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *a, **kw: saved)
    monkeypatch.setattr(builder, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="UTC"))
    monkeypatch.setattr(builder, "now_utc", lambda: datetime(2026, 9, 27, tzinfo=UTC))
    missing = True

    def project(db, **kw):
        assert (kw["source_currency"], kw["home_currency"]) == ("JPY", "USD")
        if missing:
            kw["missing_rates"].add(ProjectionGap("JPY", "USD", date(2026, 8, 31)))
            return None
        return kw["amount_minor"] * 2

    monkeypatch.setattr(builder, "project_recorded_amount", project)
    monkeypatch.setattr(_runner, "get_advisor_readiness", lambda: SimpleNamespace(
        provider="empty", is_live=False, blocked_reason=lambda _: None))
    provider = Mock()
    provider.advise.return_value = None
    monkeypatch.setattr(_runner, "get_budget_advisor", lambda: provider)
    app = FastAPI()
    from app.errors import add_exception_handlers
    add_exception_handlers(app)
    app.include_router(budget_advisor.router)
    app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="ledger-a", role="owner", account_id=1)
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    body = {"month": "2026-08", "timezone": "UTC", "home_currency_code": "USD",
        "arrangement_currency_code": "JPY", "savings_target_cents": 1200, "reserved_buffer_cents": 30}
    before = client.get("/api/budget/advisor/inputs", params=body).json()
    assert before["home_currency_code"] == "USD"
    assert before.get("arrangement_currency_code") == "JPY"
    saved_read = client.get("/api/budget/advisor/inputs", params={"month": "2026-08",
        "home_currency_code": "USD", "arrangement_currency_code": "USD"}).json()
    assert saved_read["arrangement_currency_code"] == "JPY" and not saved_read["is_trial"]
    assert before["breakdown"]["savings_target_cents"] is None
    assert before["inputs_fingerprint"] is None
    blocked = client.post("/api/budget/advise", json=body)
    assert blocked.status_code == 409 and blocked.json()["error"] == "money_projection_unavailable"
    provider.advise.assert_not_called()
    missing = False
    read = client.get("/api/budget/advisor/inputs", params=body).json()
    generated = client.post("/api/budget/advise", json=body)
    assert generated.status_code == 200, generated.text
    assert generated.json()["inputs"] == read
    assert read["arrangement_currency_code"] == "JPY"
    assert generated.json()["home_currency_code"] == "USD"
    basis = provider.advise.call_args.args[0]
    assert (basis.home_currency, basis.savings_target_cents, basis.reserved_buffer_cents) == ("USD", 2400, 60)
    assert read["breakdown"]["savings_target_cents"] == 2400 and read["inputs_fingerprint"]
    assert saved.home_currency_code == "JPY" and saved.savings_target_cents == 500


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
        "arrangement_currency_code": None, "timezone_name": "UTC", "savings_target_cents": 20, "reserved_buffer_cents": 30}
    forbidden.assert_not_called()


def test_generation_http_carries_the_input_currency_to_the_same_owner(monkeypatch):
    projection = BudgetInputProjection("2026-08", "JPY", compute_monthly_discretionary(
        monthly_income_cents=2000, savings_target_cents=2100, reserved_buffer_cents=30), (), None, is_trial=True)
    run = Mock(return_value=SimpleNamespace(advice=None, home_currency_code="JPY", provider_name="empty", reason_code=None,
        inputs=projection))
    monkeypatch.setattr(budget_advisor, "run_budget_advisor", run)
    app = FastAPI()
    app.include_router(budget_advisor.router)
    app.dependency_overrides[get_current_app_context] = lambda: SimpleNamespace(tenant_id="ledger-a", role="owner", account_id=1)
    app.dependency_overrides[get_db] = lambda: None
    response = TestClient(app).post("/api/budget/advise", json={
        "month": "2026-08", "timezone": "UTC", "home_currency_code": "JPY",
        "savings_target_cents": 2100, "reserved_buffer_cents": 30,
    })
    assert response.status_code == 200, response.text
    assert response.json()["home_currency_code"] == "JPY"
    assert response.json()["inputs"]["breakdown"]["shortfall_cents"] == 130
    assert response.json()["inputs"]["is_trial"] is True
    assert run.call_args.kwargs == {"tenant_id": "ledger-a", "actor_role": "owner", "actor_account_id": 1,
        "month": "2026-08", "timezone_name": "UTC", "home_currency_code": "JPY",
        "arrangement_currency_code": None, "savings_target_cents": 2100, "reserved_buffer_cents": 30}
