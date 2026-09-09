"""Real monthly report views and template with query owners isolated from DB."""

import re
from datetime import date
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader, StrictUndefined


@pytest.fixture()
def monthly_page(monkeypatch):
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from sqlalchemy.engine import Engine

    from app.database import get_db
    from app.routes import web_reports
    from app.services.money_projection_service import ProjectionGap
    from app.services.monthly_report_service import BudgetExplanation, CategoryRollup, MonthlyReport

    def no_database(*_args, **_kwargs):
        pytest.fail("Monthly Web projection checks must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    report = MonthlyReport("2026-05", "JPY", 1200, 1, [CategoryRollup("餐饮", 1200, 1)], 200, 20.0)
    explanation = BudgetExplanation("餐饮", "2026-05", "JPY", 1200, 1000, 1500, -300, "on_track")
    state = SimpleNamespace(module=web_reports, report=report, explanation=explanation, calls=[], gap=ProjectionGap)

    def monthly(_db, **kwargs):
        state.calls.append(("monthly", kwargs))
        return state.report

    def budget(_db, **kwargs):
        state.calls.append(("budget", kwargs))
        return state.explanation

    monkeypatch.setattr(web_reports, "compose_monthly_report", monthly)
    monkeypatch.setattr(web_reports, "compose_budget_explanation", budget)
    monkeypatch.setattr(web_reports, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(web_reports, "_resolve_selected_ledger_id", lambda *_a, **_k: "family")
    monkeypatch.setattr(web_reports, "require_runtime_home_currency_code", lambda _db: "JPY")
    monkeypatch.setattr(web_reports, "_sidebar_counts", lambda *_a: {})
    monkeypatch.setattr(web_reports, "six_month_summary", lambda *_a, **_k: [])
    monkeypatch.setattr(web_reports, "_top_expenses_view", lambda *_a, **_k: [])
    monkeypatch.setattr(web_reports, "_base_ctx", lambda _request, **kw: {
        "selected_ledger_id": kw["selected_ledger_id"], "home_currency_symbol": "CN¥",
    })
    monkeypatch.setattr(web_reports, "reports_overview", lambda _db, **kw: kw)
    monkeypatch.setattr(web_reports, "_view_model", lambda payload, **_k: {
        **payload, "merchant_category": "", "total_amount_yuan": "0.00", "year_over_year_delta_amount_yuan": "0.00",
        "count": 0, "previous_count": 0, "trend": [], "category_comparison": [], "merchant_ranking": [],
    })
    root = Path(__file__).resolve().parents[1] / "app/templates/web"
    monkeypatch.setattr(web_reports.templates.env, "loader", ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), FileSystemLoader(root),
    ]))
    monkeypatch.setattr(web_reports.templates.env, "undefined", StrictUndefined)
    web_reports.templates.env.cache.clear()
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[web_reports.LocalOnly.dependency] = lambda: None
    app.include_router(web_reports.router)
    with TestClient(app) as client:
        state.client = client
        yield state
    web_reports.templates.env.cache.clear()


def _sections(page):
    response = page.client.get("/web/reports?ledger_id=family&month=2026-05")
    assert response.status_code == 200
    sections = re.findall(r"<section\b[^>]*>(.*?)</section>", response.text, re.DOTALL)
    selected = [section for section in sections if "月报摘要" in section or "预算解释" in section]
    assert len(selected) == 2
    return "\n".join(selected)


def _rate_queries(html):
    return [parse_qs(urlsplit(unescape(href)).query) for href in re.findall(r'href="([^"]+)"', html)
        if urlsplit(unescape(href)).path == "/web/budget-advise/rates"]


def test_real_route_captures_home_for_both_query_owners(monthly_page):
    html = _sections(monthly_page)
    assert len(monthly_page.calls) == 2
    for _name, arguments in monthly_page.calls:
        assert arguments["tenant_id"] == "family"
        assert arguments["year_month"] == "2026-05"
        assert arguments["home_currency_code"] == "JPY"
    assert "JPY" in html and "1200" in html
    assert "CN¥" not in html and "12.00" not in html


def test_view_models_use_each_returned_currency_and_preserve_unknown_amounts(monthly_page):
    from dataclasses import replace

    report = replace(monthly_page.report, home_currency_code="USD", total_cents=1234, delta_vs_previous_cents=None)
    item = replace(monthly_page.explanation, actual_cents=None, p50_cents=None, p75_cents=None,
        delta_vs_p75_cents=None, verdict="projection_unavailable")
    monthly = monthly_page.module._monthly_report_view_model(report)
    budget = monthly_page.module._budget_explanation_view_model(item)
    assert monthly["home_currency_code"] == "USD" and monthly["total_amount_yuan"] == "12.34"
    assert monthly["delta_vs_previous_yuan"] is None
    assert budget["home_currency_code"] == "JPY" and budget["actual_yuan"] is None
    assert budget["p75_yuan"] is None and budget["verdict_label"] == "待补信息"


def test_missing_rate_keeps_unknown_summary_and_history_visible_with_exact_recovery(monthly_page):
    from dataclasses import replace

    gap = monthly_page.gap("USD", "JPY", date(2026, 4, 17))
    monthly_page.report = replace(monthly_page.report, total_cents=None, delta_vs_previous_cents=None,
        delta_pct=None, top_categories=[replace(monthly_page.report.top_categories[0], amount_cents=None)], missing_rates=(gap,))
    monthly_page.explanation = replace(monthly_page.explanation, actual_cents=None, p50_cents=None, p75_cents=None,
        delta_vs_p75_cents=None, verdict="projection_unavailable", missing_rates=(gap,))
    html = _sections(monthly_page)
    assert "待补汇率" in html and "USD → JPY" in html and "2026-04-17" in html
    assert "无历史" not in html and "历史不足" not in html and "0.00" not in html and "None" not in html
    queries = _rate_queries(html)
    assert queries and all(query == {"ledger_id": ["family"], "month": ["2026-05"],
        "home_currency_code": ["JPY"], "currency_code": ["USD"], "rate_date": ["2026-04-17"]} for query in queries)


@pytest.mark.parametrize("source,day", [(None, date(2026, 4, 17)), ("USD", None)])
def test_incomplete_gap_does_not_invent_a_currency_or_date(monthly_page, source, day):
    from dataclasses import replace

    gap = monthly_page.gap(source, "JPY", day)
    monthly_page.report = replace(monthly_page.report, total_cents=None, delta_vs_previous_cents=None,
        delta_pct=None, missing_rates=(gap,))
    html = _sections(monthly_page)
    assert "待补信息" in html and "核对原记录" in html
    assert "补录汇率" not in html
    queries = _rate_queries(html)
    assert queries and all(query == {"ledger_id": ["family"], "month": ["2026-05"],
        "home_currency_code": ["JPY"]} for query in queries)


def test_missing_previous_rate_does_not_hide_the_known_current_total(monthly_page):
    from dataclasses import replace

    monthly_page.report = replace(monthly_page.report, delta_vs_previous_cents=None, delta_pct=None,
        missing_rates=(monthly_page.gap("USD", "JPY", date(2026, 4, 17)),))
    html = _sections(monthly_page)
    assert "1200" in html and "待补汇率" in html
    assert "上月无数据" not in html


def test_real_zero_and_missing_history_remain_distinct_from_missing_fx(monthly_page):
    from dataclasses import replace

    monthly_page.report = replace(monthly_page.report, total_cents=0,
        top_categories=[replace(monthly_page.report.top_categories[0], amount_cents=0)])
    monthly_page.explanation = replace(monthly_page.explanation, actual_cents=0, p50_cents=None, p75_cents=None,
        delta_vs_p75_cents=None, verdict="no_history")
    html = _sections(monthly_page)
    assert "历史不足" in html and "无历史" in html
    assert "待补信息" not in html and "待补汇率" not in html and not _rate_queries(html)
