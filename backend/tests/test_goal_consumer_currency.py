"""Secondary goal consumers keep recorded currency and unavailable progress."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.routes.web_common import _goals_top_rows
from app.services.currency_common import currency_input_metadata, minor_amount_label
from app.services.recycle_bin_service import _goal_detail
from app.services.web_search_service import WebSearchGroup, _search_goals


def _goal(*, currency="JPY", spent=300, percent=25):
    return SimpleNamespace(name="日元目标", public_id="test-goal", month="2026-09", category=None,
        status="active", goal_type="spending_limit", home_currency_code=currency,
        target_amount_cents=1200, spent_amount_cents=spent, progress_percent=percent,
        progress_state="unavailable" if percent is None else "on_track")


def _render(template, **context):
    loader = ChoiceLoader([DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app" / "templates" / "web")])
    return Environment(loader=loader, autoescape=True).get_template(template).render(**context)


def test_overview_goal_uses_captured_currency_and_keeps_unknown_progress():
    known = _goal()
    unavailable = _goal(spent=None, percent=None)
    rows = _goals_top_rows([known, unavailable])
    assert rows[0]["percent"] is None
    assert rows[0]["spent_yuan"] is None
    assert rows[0]["target_yuan"] == "1200"
    assert rows[1]["percent"] == 25 and rows[1]["spent_yuan"] == "300"
    assert rows[1]["home_currency_code"] == "JPY"


def test_overview_template_has_no_fake_percent_or_bar_for_unknown_goal():
    html = _render("overview.html", cards={"goals_count": 1, "goals_top": [
        {"name": "待汇率目标", "percent": None, "state": "unavailable"}]},
        overview_lanes=[{"cards": [{"key": "goals"}]}], selected_ledger_id="owner",
        currency_input=currency_input_metadata("CNY"))
    assert "暂不可计算" in html
    assert "None%" not in html
    assert 'aria-label="待汇率目标已使用' not in html


@pytest.mark.parametrize("currency", ["JPY", None])
def test_recycle_goal_label_preserves_its_recorded_currency(currency):
    label = _goal_detail(_goal(currency=currency))
    if currency:
        assert "JPY" in label and "1,200" in label
    else:
        assert "1200" in label and "币种待确认" in label
    assert "12.00" not in label


@pytest.mark.parametrize("currency", ["JPY", None])
def test_goal_search_carries_currency_through_the_real_template(currency):
    db = Mock()
    db.scalars.return_value.all.return_value = [_goal(currency=currency)]
    results = _search_goals(db, "owner", "目标", 6)
    assert results[0].currency_code == currency
    html = _render("search.html", search_query="目标", search_total=1,
        search_groups=[WebSearchGroup("goals", "目标", results)], selected_ledger_id="owner",
        home_currency_code="CNY", search_amount_label=minor_amount_label)
    if currency:
        assert "JPY" in html and "1,200" in html
    else:
        assert "1200" in html and "币种待确认" in html
    assert "12.00" not in html
