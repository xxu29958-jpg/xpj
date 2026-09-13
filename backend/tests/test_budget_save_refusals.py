"""An old budget form cannot overwrite a later amount or reinterpret its units."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.models import Budget
from app.schemas import BudgetMonthlyUpdateRequest
from app.services import budget_command_service as command
from app.services.idempotency import IdempotencyOutcomeKind


@pytest.mark.parametrize("currency,version", [("CNY", 1), ("JPY", 3), ("CNY", None)])
def test_existing_budget_refuses_a_different_currency_or_observed_version(monkeypatch, currency, version):
    db = Mock()
    budget = Budget(id=7, tenant_id="owner", month="2026-09", home_currency_code="CNY",
        total_amount_cents=100, row_version=3)
    monkeypatch.setattr(command, "resolve_write_capability", lambda _: None)
    monkeypatch.setattr(command, "_get_any_budget", lambda *args, **kwargs: budget)
    monkeypatch.setattr(command, "_list_category_budgets", lambda *args, **kwargs: [])
    monkeypatch.setattr(command, "_budget_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(command, "claim_idempotency_key", lambda *args, **kwargs: SimpleNamespace(
        kind=IdempotencyOutcomeKind.PROCEED, row=object(),
    ))
    with pytest.raises(AppError):
        command.save_monthly_budget(db, tenant_id="owner", month="2026-09", actor_account_id=1,
            idempotency_key="original-key", payload=BudgetMonthlyUpdateRequest(
            home_currency_code=currency, expected_row_version=version, total_amount_cents=999,
        ))
    assert budget.total_amount_cents == 100
    db.commit.assert_not_called()
    db.rollback.assert_called_once_with()
