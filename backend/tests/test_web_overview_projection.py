"""Browser overview preserves the projection owner's currency and unknown amounts."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from sqlalchemy.engine import Engine

    monkeypatch.setattr(Engine, "connect", lambda *_a, **_k: pytest.fail("pure browser check opened a database"))


def test_missing_month_projection_does_not_become_zero_or_monthly_change():
    from app.routes._web_dashboard_calculations import dashboard_month_delta

    assert dashboard_month_delta({"total_amount_cents": None}, {"total_amount_cents": 100}) == (
        None, 100, None, "unavailable", None)
    assert dashboard_month_delta({"total_amount_cents": 100}, {"total_amount_cents": None}) == (
        100, None, None, "unavailable", None)


def test_known_month_comparison_preserves_zero_and_refund_values():
    from app.routes._web_dashboard_calculations import dashboard_month_delta

    assert dashboard_month_delta({"total_amount_cents": 0}, {"total_amount_cents": 100}) == (0, 100, -100, "down", 100)
    assert dashboard_month_delta({"total_amount_cents": -50}, {"total_amount_cents": 100}) == (-50, 100, -150, "down", 150)


def test_overview_category_projection_never_publishes_partial_percentages(monkeypatch):
    from app.routes import web_common as web

    calls = []
    rows = [{"category": f"类别{i}", "amount_cents": 100 - i, "count": 1} for i in range(7)]
    rows[-1]["amount_cents"] = None

    def stats(_db, month, ledger, **kwargs):
        calls.append((month, ledger, kwargs))
        return {"home_currency_code": "JPY", "by_category": rows}

    monkeypatch.setattr(web, "monthly_stats", stats)
    result = web._dashboard_category_share(object(), "family", currency_code="JPY", month="2026-08")
    assert len(result) == 7
    assert result[-1]["amount_cents"] is None and result[-1]["amount_label"] == "待补齐换算信息"
    assert result[0]["amount_major"] == 100
    assert calls == [("2026-08", "family", {"timezone_name": "Asia/Shanghai", "home_currency_code": "JPY"})]


def test_overview_amount_view_uses_owner_currency_and_preserves_unknown():
    from app.routes.web_dashboard import _overview_amount_views

    cards = {"home_currency_code": "JPY", "total_amount_cents": None, "delta_amount_cents": None,
        "previous_total_amount_cents": 1200, "budget_top": [], "budget_remaining_cents": None,
        "budget_home_currency_code": "CNY"}
    view = _overview_amount_views(cards)
    assert view["hero_amount"] is None
    assert view["previous_total_label"] == "¥1,200"
    assert view["delta_amount_label"] == "待补齐换算信息"


def test_overview_assembles_original_month_and_one_display_home(monkeypatch):
    from app.routes import web_common as web

    calls = []
    def stats(_db, month, ledger, **kwargs):
        calls.append((month, ledger, kwargs))
        return {"month": month, "home_currency_code": "JPY", "total_amount_cents": 1200,
            "count": 1, "missing_rates": ()}

    monkeypatch.setattr(web, "monthly_stats", stats)
    monkeypatch.setattr(web, "current_month", lambda _tz: "2026-10")
    monkeypatch.setattr(web.web_stats_service, "pending_quality_counts", lambda *a: {})
    monkeypatch.setattr(web, "recurring_status_counts", lambda *a: (0, 0))
    monkeypatch.setattr(web, "get_monthly_budget", lambda *a, **kw: None)
    monkeypatch.setattr(web, "list_goals", lambda *a, **kw: [])
    monkeypatch.setattr(web, "list_dashboard_cards", lambda *a, **kw: SimpleNamespace(items=[]))
    monkeypatch.setattr(web, "_dashboard_budget_goals_block", lambda *a: {})
    monkeypatch.setattr(web, "_dashboard_status_counts_block", lambda *a: {})
    cards = web._dashboard_cards(object(), "family", currency_code="JPY", month="2026-08")
    assert cards["month"] == "2026-08" and cards["home_currency_code"] == "JPY"
    assert cards["total_amount_yuan"] == "1200" and cards["total_amount_segments"]["int"] == "1,200"
    assert [call[0] for call in calls] == ["2026-08", "2026-07"]
    assert all(call[1] == "family" and call[2]["home_currency_code"] == "JPY" for call in calls)


def test_actual_overview_template_exposes_unknown_and_original_recovery():
    from app.routes.web_dashboard import _overview_amount_views, _overview_lanes
    from app.services.money_projection_service import ProjectionGap

    cards = {"home_currency_code": "JPY", "month": "2026-08", "total_amount_cents": None,
        "delta_amount_cents": None, "delta_direction": "unavailable", "previous_total_amount_cents": 1200,
        "confirmed_count": 2, "pending_count": 0, "budget_top": [], "budget_remaining_cents": None,
        "budget_home_currency_code": "CNY"}
    env = Environment(autoescape=True, undefined=StrictUndefined, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web"),
    ]))
    html = env.get_template("overview.html").render(cards=cards, selected_ledger_id="family", q="?ledger_id=family",
        can_write=True, has_any_expense=True, overview_load_charts=False, category_chart_available=False,
        category_share=[{"name": "餐饮", "amount_label": "待补齐换算信息", "amount_cents": None}],
        overview_lanes=_overview_lanes([{"key": "monthly_spend"}, {"key": "reports"}]),
        money_task={"ledger_id": "family", "month": "2026-08", "home_currency_code": "JPY", "return_to": "overview"},
        missing_rates=[ProjectionGap("CNY", "JPY", date(2026, 8, 4))], flash_message="",
        **_overview_amount_views(cards))
    assert "待补齐换算信息" in html
    assert 'id="chart-category"' not in html and "还没有分类结构" not in html
    assert "与上月持平" not in html and "None" not in html
    assert "return_to=overview" in html and "home_currency_code=JPY" in html
    assert "month=2026-08" in html and "rate_date=2026-08-04" in html
