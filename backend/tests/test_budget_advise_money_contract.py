"""C07 home-currency binding at the budget-advice endpoint boundary."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.models import Expense
from app.services.budget_advisor_service import (
    BudgetAdvice,
    BudgetInputs,
    BudgetSuggestion,
)
from app.services.time_service import now_utc
from tests._infra.budget_advise_fixtures import current_month


@pytest.mark.parametrize("currency", ["JPY", "KRW"])
def test_advise_binds_outbound_and_returned_minor_units_to_runtime_home(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
    currency: str,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency)
    get_settings.cache_clear()
    captured: dict[str, BudgetInputs] = {}

    class _EchoAdvisor:
        last_error_code: str | None = None

        def advise(self, inputs: BudgetInputs) -> BudgetAdvice:
            captured["inputs"] = inputs
            return BudgetAdvice(
                summary="本位币绑定回传",
                suggestions=[
                    BudgetSuggestion(
                        category="餐饮",
                        suggested_amount_cents=300_000,
                        rationale="保持输入的最小货币单位",
                    )
                ],
                confidence=1.0,
            )

    now = now_utc()
    year_text, month_text = current_month().split("-")
    month_anchor = datetime(
        int(year_text),
        int(month_text),
        15,
        12,
        tzinfo=now.tzinfo,
    )
    try:
        with SessionLocal() as db:
            db.add(
                Expense(
                    tenant_id="owner",
                    status="confirmed",
                    amount_cents=120_000,
                    home_currency_code=currency,
                    original_currency_code=currency,
                    original_amount_minor=120_000,
                    merchant="Home Currency Merchant",
                    category="餐饮",
                    expense_time=month_anchor,
                    confirmed_at=month_anchor,
                    created_at=month_anchor,
                    updated_at=month_anchor,
                )
            )
            db.commit()
        with patch(
            "app.services.budget_advisor_service._runner.get_budget_advisor",
            return_value=_EchoAdvisor(),
        ):
            response = client.post(
                "/api/budget/advise",
                headers=identity.app_headers,
                json={"month": current_month()},
            )

        assert response.status_code == 200, response.text
        assert response.json()["home_currency_code"] == currency
        outbound = captured["inputs"]
        assert outbound.home_currency == currency
        assert [row.amount_cents for row in outbound.category_breakdown] == [
            120_000
        ]
        assert response.json()["advice"]["suggestions"][0][
            "suggested_amount_cents"
        ] == 300_000
    finally:
        get_settings.cache_clear()
