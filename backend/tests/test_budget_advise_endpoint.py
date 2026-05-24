"""v1.1 PR-8: POST /api/budget/advise — builder + provider integration.

Locks in:

- Default empty provider returns advice=null (clean "AI not configured" UX).
- Mock provider returns deterministic advice derived from inputs.
- Builder honours the P3 boundary: advisor inputs are assembled from
  monthly_report-style aggregates, not raw merchant/member rows.
- Endpoint requires auth.
- Payload validation (month format).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense, MonthlyIncomePlan, RecurringItem
from app.services.budget_advisor_service import (
    BudgetInputs,
    MockBudgetAdvisor,
    build_budget_inputs,
)
from app.services.time_service import now_utc


def _seed_minimal_data() -> None:
    """One income plan + one confirmed expense + one recurring item for
    the owner tenant. Just enough to exercise the builder paths."""

    now = now_utc()
    month_anchor = datetime(now.year, now.month, 15, tzinfo=now.tzinfo)
    with SessionLocal() as db:
        db.add(
            MonthlyIncomePlan(
                tenant_id="owner",
                label="工资",
                source_type="salary",
                amount_cents=1_000_000,
                pay_day=10,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            Expense(
                tenant_id="owner",
                status="confirmed",
                amount_cents=120_000,
                home_currency_code="CNY",
                original_currency_code="CNY",
                original_amount_minor=120_000,
                merchant="麦当劳",
                category="餐饮",
                expense_time=month_anchor,
                confirmed_at=month_anchor,
                created_at=month_anchor,
                updated_at=month_anchor,
            )
        )
        db.add(
            RecurringItem(
                tenant_id="owner",
                merchant_key="netflix",
                merchant_name="Netflix",
                baseline_amount_cents=2_000,
                last_amount_cents=2_000,
                frequency="monthly",
                status="active",
                source="declared",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def _current_month() -> str:
    now = now_utc()
    return f"{now.year:04d}-{now.month:02d}"


# ---------------------------------------------------------------------------
# Default empty provider
# ---------------------------------------------------------------------------


def test_advise_with_default_empty_provider_returns_null_advice(
    client: TestClient, *, identity
) -> None:
    resp = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": _current_month()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["advice"] is None
    assert body["provider_name"] == "empty"


def test_advise_requires_auth(client: TestClient, *, identity) -> None:  # noqa: ARG001
    resp = client.post(
        "/api/budget/advise", json={"month": _current_month()}
    )
    assert resp.status_code == 401


@pytest.mark.parametrize("bad_month", ["2026-1", "2026-13-01", "26-05", "", "abc"])
def test_advise_rejects_bad_month_format(
    client: TestClient, *, identity, bad_month
) -> None:
    resp = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": bad_month},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Mock provider — advice round-trip
# ---------------------------------------------------------------------------


def test_advise_with_mock_provider_returns_anonymised_advice(
    client: TestClient, *, identity
) -> None:
    _seed_minimal_data()
    with patch(
        "app.routes.budget_advisor.get_budget_advisor",
        return_value=MockBudgetAdvisor(),
    ):
        resp = client.post(
            "/api/budget/advise",
            headers=identity.app_headers,
            json={"month": _current_month()},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["advice"] is not None
    assert "餐饮" in body["advice"]["summary"]
    assert len(body["advice"]["suggestions"]) == 1
    assert body["advice"]["confidence"] == 0.5


def test_advise_handles_provider_returning_none_gracefully(
    client: TestClient, *, identity
) -> None:
    class _NullAdvisor:
        def advise(self, inputs):  # noqa: ARG002
            return None

    with patch(
        "app.routes.budget_advisor.get_budget_advisor",
        return_value=_NullAdvisor(),
    ):
        resp = client.post(
            "/api/budget/advise",
            headers=identity.app_headers,
            json={"month": _current_month()},
        )
    assert resp.status_code == 200
    assert resp.json()["advice"] is None


# ---------------------------------------------------------------------------
# Builder service — anonymisation contract
# ---------------------------------------------------------------------------


def test_builder_anonymises_merchant_canonical(identity) -> None:  # noqa: ARG001
    _seed_minimal_data()
    with SessionLocal() as db:
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    assert inputs.merchant_summary == []
    assert inputs.fixed_expenses == []
    assert "麦当劳" not in repr(inputs)
    assert "Netflix" not in repr(inputs)


def test_builder_anonymises_member_account_id(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    assert inputs.members == []


def test_builder_does_not_send_income_plan(identity) -> None:  # noqa: ARG001
    _seed_minimal_data()
    with SessionLocal() as db:
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    assert inputs.income_plan == []


def test_builder_does_not_send_recurring_merchants(identity) -> None:  # noqa: ARG001
    _seed_minimal_data()
    with SessionLocal() as db:
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    assert inputs.fixed_expenses == []


def test_builder_pulls_current_month_category_breakdown(identity) -> None:  # noqa: ARG001
    _seed_minimal_data()
    with SessionLocal() as db:
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    by_cat = {row.category: row for row in inputs.category_breakdown}
    assert "餐饮" in by_cat
    assert by_cat["餐饮"].amount_cents == 120_000
    assert by_cat["餐饮"].count == 1


def test_builder_excludes_previous_month_expenses(identity) -> None:  # noqa: ARG001
    now = now_utc()
    prev_month = (datetime(now.year, now.month, 1, tzinfo=now.tzinfo)
                  - timedelta(days=10))
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                status="confirmed",
                amount_cents=999_999,
                home_currency_code="CNY",
                original_currency_code="CNY",
                original_amount_minor=999_999,
                merchant="LastMonthMart",
                category="购物",
                expense_time=prev_month,
                confirmed_at=prev_month,
                created_at=prev_month,
                updated_at=prev_month,
            )
        )
        db.commit()
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    by_cat = {row.category: row for row in inputs.category_breakdown}
    assert by_cat.get("购物") is None or by_cat["购物"].amount_cents != 999_999


def test_builder_excludes_pending_and_rejected(identity) -> None:  # noqa: ARG001
    now = now_utc()
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                status="pending",
                amount_cents=888_888,
                home_currency_code="CNY",
                original_currency_code="CNY",
                original_amount_minor=888_888,
                merchant="PendingShop",
                category="购物",
                expense_time=now,
                confirmed_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    by_cat = {row.category: row for row in inputs.category_breakdown}
    assert by_cat.get("购物") is None or by_cat["购物"].amount_cents != 888_888


def test_builder_returns_valid_budget_inputs_when_empty(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        inputs = build_budget_inputs(
            db, tenant_id="owner", month=_current_month()
        )
    assert isinstance(inputs, BudgetInputs)
    assert inputs.month == _current_month()
    assert inputs.home_currency == "CNY"
    assert inputs.members == []
    assert inputs.merchant_summary == []
