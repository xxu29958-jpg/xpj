"""Income estimates keep their declared month and never assert receipt."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader


def test_income_page_does_not_turn_a_due_plan_into_received_money() -> None:
    templates = Path(__file__).resolve().parents[1] / "app" / "templates" / "web"
    environment = Environment(
        loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(templates),
        ]),
        autoescape=True,
    )
    plan = SimpleNamespace(
        public_id="synthetic-income-plan", label="尚未收到的计划", source_type="salary",
        frequency="monthly", pay_day=1, amount_cents=100_00, row_version=1,
    )
    html = environment.get_template("income_plans.html").render(
        can_write=False, plans_active=[plan], plans_archived=[], total_yuan="100.00", scheduled_yuan="100.00",
        intent_month="2026-09",
        home_currency_symbol="¥", minor_label=lambda _: "100.00",
    )
    assert "尚未收到的计划" in html
    assert "截至今日已到账收入" not in html
    assert "不代表实际到账" in html


def test_monthly_revision_preserves_previous_months(identity) -> None:
    from app.database import SessionLocal
    from app.services.income_plan_service import (
        archive_income_plan,
        create_income_plan,
        restore_income_plan,
        total_monthly_income_cents,
        update_income_plan,
    )

    def at(month: int) -> datetime:
        return datetime(2026, month, 2, tzinfo=UTC)

    with SessionLocal() as db:
        plan = create_income_plan(
            db, tenant_id="owner", label="revision estimate", source_type="salary",
            amount_cents=100_00, pay_day=1, now=at(8),
        )
        plan = update_income_plan(
            db, tenant_id="owner", public_id=plan.public_id,
            expected_row_version=plan.row_version, amount_cents=120_00, now=at(9),
        )
        plan = archive_income_plan(
            db, tenant_id="owner", public_id=plan.public_id,
            expected_row_version=plan.row_version, now=at(10),
        )
        restore_income_plan(
            db, tenant_id="owner", public_id=plan.public_id,
            expected_row_version=plan.row_version, now=at(11),
        )
        totals = [total_monthly_income_cents(
            db, tenant_id="owner", month=f"2026-{month:02d}", as_of=at(12),
        ) for month in range(7, 12)]
    assert totals == [0, 100_00, 120_00, 0, 120_00]
