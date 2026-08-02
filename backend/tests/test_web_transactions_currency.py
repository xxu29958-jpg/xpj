"""Currency-specific S-TX Web edit contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.models import Expense
from tests._infra.currency import activate_test_currency_authority


@pytest.fixture
def jpy_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
    get_settings.cache_clear()


@pytest.mark.currency_binding_unbound
def test_web_edit_rejects_fraction_for_frozen_zero_decimal_currency(
    jpy_env,
    web_client: TestClient,
    *,
    identity,
) -> None:
    with SessionLocal() as db:
        activate_test_currency_authority(db, "JPY")
        now = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
        expense = Expense(
            tenant_id="owner",
            amount_cents=1200,
            home_currency_code="JPY",
            original_currency_code="JPY",
            original_amount_minor=1200,
            exchange_rate_to_cny=Decimal("1"),
            exchange_rate_date=date(2026, 5, 4),
            exchange_rate_source="base",
            fx_status="ready",
            merchant="JPY Cafe",
            category="餐饮",
            source="pytest",
            status="pending",
            expense_time=now,
            created_at=now,
            updated_at=now,
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id
        row_version = expense.row_version

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(row_version),
            "original_currency": "JPY",
            "amount_yuan": "12.5",
            "merchant": "JPY Cafe",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422, response.text
    assert "JPY 只支持整数金额" in response.text
    with SessionLocal() as db:
        persisted = db.get(Expense, expense_id)
        assert persisted is not None
        assert persisted.original_amount_minor == 1200
        assert persisted.row_version == row_version
