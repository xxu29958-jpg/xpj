"""Issue #263: the mock advisor never forwards an out-of-range suggested amount.

A category's monthly total is a read projection bounded by the aggregate
range, so individually valid expenses can sum past ``MONEY_MINOR_MAX``. The
mock provider must apply the same suggested-amount bound as the live parser:
drop the suggestion line, keep the summary, never fail DTO construction.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.money_contract_types import MONEY_MINOR_MAX
from app.services.budget_advisor_service import BudgetInputs, MockBudgetAdvisor
from app.services.budget_advisor_service._models import CategorySnapshot
from app.services.budget_advisor_service._providers import (
    MAX_SUGGESTED_AMOUNT_MINOR,
    _budget_suggestion_from_json,
)
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.time_service import now_utc
from tests._infra.budget_advise_fixtures import current_month


def _seed_category_expenses(amounts: list[int]) -> None:
    now = now_utc()
    year_text, month_text = current_month().split("-")
    anchor = datetime(int(year_text), int(month_text), 15, 12, tzinfo=now.tzinfo)
    with SessionLocal() as db:
        for amount in amounts:
            expense = Expense(tenant_id="owner", status="confirmed", amount_cents=amount,
                home_currency_code="CNY", original_currency_code="CNY", original_amount_minor=amount,
                merchant="大额餐饮", category="餐饮", expense_time=anchor, confirmed_at=anchor,
                created_at=anchor, updated_at=anchor)
            refresh_legacy_expense_time(db, expense)
            db.add(expense)
        db.commit()


def test_mock_advice_drops_category_total_beyond_money_bound(client: TestClient, *, identity) -> None:
    near_cap = MONEY_MINOR_MAX - 1
    _seed_category_expenses([near_cap, near_cap])
    with patch("app.services.budget_advisor_service._runner.get_budget_advisor",
            return_value=MockBudgetAdvisor()):
        response = client.post("/api/budget/advise", headers=identity.app_headers,
            json={"month": current_month()})

    assert response.status_code == 200, response.text
    advice = response.json()["advice"]
    assert "餐饮" in advice["summary"]
    assert advice["suggestions"] == []


@pytest.mark.parametrize("amount", [-1, 0, MAX_SUGGESTED_AMOUNT_MINOR, MAX_SUGGESTED_AMOUNT_MINOR + 1,
    MONEY_MINOR_MAX + 1])
def test_mock_and_live_parser_accept_the_same_suggested_amounts(amount: int) -> None:
    inputs = BudgetInputs(month="2026-10", home_currency="CNY",
        category_breakdown=[CategorySnapshot(category="餐饮", amount_cents=amount, count=1)])
    mock_amounts = [row.suggested_amount_cents for row in MockBudgetAdvisor().advise(inputs).suggestions]
    live = _budget_suggestion_from_json({"category": "餐饮", "suggested_amount_cents": amount},
        accepted_categories={"餐饮"})
    assert mock_amounts == ([] if live is None else [live.suggested_amount_cents])
