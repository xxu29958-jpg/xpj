"""Income history must be reachable from the actual active and archived rows."""

from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape


@pytest.mark.parametrize(("can_write", "archived"), [(True, False), (False, False), (False, True)])
def test_income_rows_offer_readable_history_without_requiring_edit_permission(can_write, archived):
    templates = Path(__file__).resolve().parents[1] / "app/templates/web"
    environment = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), FileSystemLoader(templates),
    ]), autoescape=select_autoescape(["html"]))
    plan = {"public_id": "income-original", "label": "工资预测", "source_type": "salary", "frequency": "monthly",
        "home_currency_code": "JPY", "amount_cents": 1200, "pay_day": 31, "row_version": 7}
    body = environment.get_template("income_plans.html").render(
        selected_ledger_id="household", can_write=can_write, plans_active=[] if archived else [plan],
        plans_archived=[plan] if archived else [], intent_month="2026-09", total_yuan="1200", scheduled_yuan="0",
        home_currency_symbol="¥", missing_currency_codes=[], reference_rates=[], minor_label=lambda _: "1200",
        income_form_values={"intent_month": "2026-09", "home_currency_code": "JPY", "frequency": "monthly",
            "income_month_year": "2026", "income_month_number": "9"},
        income_form_currency={"currency_code": "JPY"}, income_month_years=[2026],
    )
    assert "工资预测" in body and "JPY 1200" in body
    assert '/web/income-plans/income-original/history?ledger_id=household' in body, \
        "A saved income plan has no reachable revision history for this reader"
    if not can_write:
        assert 'action="/web/income-plans/income-original/archive"' not in body
        assert 'action="/web/income-plans/income-original/restore"' not in body


@pytest.mark.parametrize("currency", ["JPY", None])
def test_history_renders_original_definition_and_unknown_months_without_mutation_controls(currency):
    templates = Path(__file__).resolve().parents[1] / "app/templates/web"
    environment = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), FileSystemLoader(templates),
    ]), autoescape=select_autoescape(["html"]))
    environment.filters["to_iso"] = str
    snapshot = {"label": "<原工资预测>", "source_type": "salary", "frequency": "one_time",
        "income_month": "2026-11", "amount_cents": 1200, "home_currency_code": currency, "pay_day": 31, "status": "archived"}
    history = SimpleNamespace(public_id="original", next_before_version=3, items=[{
        "row_version": 3, "change_kind": "baseline", "recorded_at": "2026-09-28T10:00:00Z",
        "intent_month": None, "effective_month": None, "snapshot": snapshot,
    }])
    body = environment.get_template("income_history.html").render(history=history, selected_ledger_id="household",
        limit=2, before_version=4, minor_amount_value=lambda amount, code: str(amount))
    text = []
    parser = HTMLParser()
    parser.handle_data = text.append
    parser.feed(body)
    readable = " ".join(" ".join(text).split())
    assert "&lt;原工资预测&gt;" in body and "单次预计 2026-11" in body
    assert "更早的修改及发生时间未知" in readable and "变更所用月份 未知" in readable
    assert "预测重算起月 未知" in readable
    assert ("JPY 1200" if currency else "1200 最小单位（原币种未记录）") in body
    assert "before_version=3" in body and "最近的记录" in body
    assert 'method="post"' not in body
