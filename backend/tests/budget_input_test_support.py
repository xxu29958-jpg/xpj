"""Declared projection inputs shared by budget consumers; no business rules."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.budget_advisor_service import _inputs_builder as builder
from app.services.monthly_report_service import CategoryRollup, MonthlyReport


def seed_reads(monkeypatch, *, gap=None, references=()):
    report = MonthlyReport("2026-08", "JPY", 300, 1, [CategoryRollup("餐饮", 300, 1)])
    monkeypatch.setattr(builder, "compose_monthly_report", lambda *args, **kwargs: report)
    monkeypatch.setattr(builder, "compose_budget_explanation", lambda *args, **kwargs: SimpleNamespace(
        undated_expense_count=0, p50_cents=None if gap else 200, p75_cents=None if gap else 400, missing_rates=(gap,) if gap else (),
    ))
    plan = SimpleNamespace(source_type="private employer", pay_day=15)
    monkeypatch.setattr(builder, "income_forecast", lambda *args, **kwargs: SimpleNamespace(
        expected_amount_cents=2000, projected_entries=((plan, 2000),), reference_rates=references,
    ))
    monkeypatch.setattr(builder, "_active_recurring_items", lambda *args, **kwargs: [])
    monkeypatch.setattr(builder, "recurring_monthly_total", lambda *args, **kwargs: 500)
    monkeypatch.setattr(builder, "total_outstanding_recurring_cents", lambda *args, **kwargs: 100, raising=False)
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(builder, "read_monthly_budget_definition", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(builder, "now_utc", lambda: datetime(2026, 10, 11, 4, 0, tzinfo=UTC))
