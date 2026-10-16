"""Shared preparation for the existing income plan consumers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.database import SessionLocal
from app.main import app
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.routes import income_plans, web_income_edit, web_income_plans
from app.routes.web_app import _require_local as _web_require_local
from app.services import income_plan_service


def _seed_undated_single_month_plan(when: datetime) -> tuple[int, str, int]:
    from app.services.currency_binding_service import resolve_write_capability

    with SessionLocal() as db:
        resolve_write_capability(db)
        plan = MonthlyIncomePlan(
            home_currency_code="CNY", tenant_id="owner", label="旧名称", source_type="salary", frequency="one_time",
            income_month="2026-08", amount_cents=10000, pay_day=1, status="active",
            row_version=1, created_at=when, updated_at=when,
        )
        db.add(plan)
        db.flush()
        db.add(IncomePlanRevision(
            home_currency_code="CNY", tenant_id="owner", plan_id=plan.id, revision_number=1, change_kind="baseline",
            effective_month=None, intent_month=None, label=plan.label, source_type=plan.source_type,
            frequency=plan.frequency, income_month=plan.income_month, amount_cents=plan.amount_cents,
            pay_day=plan.pay_day, status=plan.status, recorded_at=when,
        ))
        db.commit()
        return plan.id, plan.public_id, plan.row_version


@pytest.fixture()
def web_income(client, monkeypatch):
    clock = {"month": "2026-09", "now": datetime(2026, 9, 5, tzinfo=UTC)}
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: clock["now"])
    for routes in (income_plans, web_income_edit, web_income_plans):
        monkeypatch.setattr(routes, "current_ledger_month", lambda _db, *, ledger_id: clock["month"])
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client, clock
    app.dependency_overrides.pop(_web_require_local, None)
