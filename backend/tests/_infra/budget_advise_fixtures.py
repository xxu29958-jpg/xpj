"""Shared fixtures for budget-advisor endpoint and money-contract tests."""

from __future__ import annotations

from datetime import datetime

from app.database import SessionLocal
from app.models import Expense, MonthlyIncomePlan, RecurringItem
from app.services.spending_contract_service import current_accounting_month
from app.services.time_service import now_utc


def current_month() -> str:
    """Return the current month in the configured accounting timezone."""
    return current_accounting_month()


def seed_minimal_data() -> None:
    """Seed the smallest useful income, expense, and recurring-item snapshot."""
    now = now_utc()
    # Anchor to the accounting timezone's current month. A UTC-derived month
    # can disagree with the accounting window around month boundaries.
    year_str, month_str = current_month().split("-")
    month_anchor = datetime(
        int(year_str),
        int(month_str),
        15,
        12,
        tzinfo=now.tzinfo,
    )
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
