"""The complete browser report keeps one currency and recoverable unknown projections."""

import csv
import json
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


def _overview(gap, **changes):
    category = {"category": "餐饮", "amount_cents": None, "count": 2,
        "previous_amount_cents": 1200, "previous_count": 1, "delta_amount_cents": None, "delta_count": 1,
        "year_over_year_amount_cents": None, "year_over_year_count": 1,
        "year_over_year_delta_amount_cents": None, "year_over_year_delta_count": 1}
    return {"month": "2026-05", "timezone": "Asia/Shanghai", "home_currency_code": "JPY", "missing_rates": (gap,),
        "granularity": "week", "ranking_metric": "amount", "merchant_category": "餐饮", "total_amount_cents": None,
        "count": 2, "previous_month": "2026-04", "previous_total_amount_cents": 1200, "previous_count": 1,
        "year_over_year_month": "2025-05", "year_over_year_total_amount_cents": None, "year_over_year_count": 1,
        "year_over_year_delta_amount_cents": None, "year_over_year_delta_count": 1,
        "trend": [{"bucket": "w1", "label": "第一周", "amount_cents": None, "count": 2},
            {"bucket": "w2", "label": "第二周", "amount_cents": 0, "count": 0}],
        "merchant_ranking": [], "category_comparison": [category], **changes}


@pytest.fixture()
def period_page(monkeypatch):
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from sqlalchemy.engine import Engine

    from app.database import get_db
    from app.routes import web_reports
    from app.services.money_projection_service import ProjectionGap, ProjectionReference

    def no_database(*_args, **_kwargs):
        pytest.fail("Browser projection checks must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    gap = ProjectionGap("USD", "JPY", date(2026, 5, 2))
    rows = [{"month": month, "home_currency_code": "JPY", "amount_cents": amount, "amount_yuan": amount,
        "amount_major_text": None if amount is None else str(amount), "count": 2, "undated_expense_count": 0,
        "budget_cents": budget, "budget_yuan": budget, "budget_major_text": None if budget is None else str(budget),
        "missing_rates": (gap,) if amount is None else (),
        "reference_rates": () if budget is None else (ProjectionReference("USD", "JPY", date(2026, 4, 15)),)}
        for month, amount, budget in [("2026-04", 1200, 1500), ("2026-05", None, None)]]
    state = SimpleNamespace(module=web_reports, gap=gap, payload=_overview(gap), rows=rows, calls=[])

    def overview(_db, **kwargs):
        state.calls.append(("overview", kwargs))
        return {**state.payload, "ranking_metric": kwargs["ranking_metric"]}

    def history(_db, **kwargs):
        state.calls.append(("history", kwargs))
        return state.rows

    def largest(_db, **kwargs):
        state.calls.append(("largest", kwargs))
        return SimpleNamespace(home_currency_code="JPY", missing_rates=(gap,), items=[])

    def export(_db, **kwargs):
        state.calls.append(("export", kwargs))
        return "section,field,value\nsummary,home_currency_code,JPY\n"

    monkeypatch.setattr(web_reports, "reports_overview", overview)
    monkeypatch.setattr(web_reports, "six_month_summary", history)
    monkeypatch.setattr(web_reports, "top_expenses_for_month", largest)
    monkeypatch.setattr(web_reports, "export_reports_overview_csv", export)
    monkeypatch.setattr(web_reports, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(web_reports, "_resolve_selected_ledger_id", lambda *_a, **_k: "family")
    monkeypatch.setattr(web_reports, "require_runtime_home_currency_code", lambda _db: "CNY")
    monkeypatch.setattr(web_reports, "_sidebar_counts", lambda *_a: {})
    monkeypatch.setattr(web_reports, "_monthly_report_sections", lambda *_a, **_k: (None, []))
    monkeypatch.setattr(web_reports, "_base_ctx", lambda _request, **kw: {
        "selected_ledger_id": kw["selected_ledger_id"], "home_currency_code": "CNY",
        "home_currency_symbol": "CN¥", "home_currency_minor_digits": 2,
    })
    root = Path(__file__).resolve().parents[1] / "app/templates/web"
    monkeypatch.setattr(web_reports.templates.env, "loader", ChoiceLoader([
        DictLoader({"base.html": '<html data-home-currency="{{ home_currency_code }}" '
            'data-home-currency-minor-digits="{{ home_currency_minor_digits }}">{% block content %}{% endblock %}</html>'}),
        FileSystemLoader(root),
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


def _report_response(page, **changes):
    response = page.client.get("/web/reports", params={"ledger_id": "family", "month": "2026-05",
        "home_currency_code": "JPY", "granularity": "week", "ranking_metric": "amount", "merchant_category": "餐饮", **changes})
    assert response.status_code == 200, response.text
    return response


def test_period_views_preserve_none_and_real_zero(period_page):
    vm = period_page.module._view_model(period_page.payload)
    assert vm["home_currency_code"] == "JPY"
    assert vm["total_amount_yuan"] is None and vm["year_over_year_delta_amount_cents"] is None
    assert vm["trend"][0]["amount_cents"] is None and vm["trend"][0]["amount_yuan"] is None
    assert vm["trend"][1]["amount_cents"] == 0 and vm["trend"][1]["amount_yuan"] == "0"
    assert vm["category_comparison"][0]["previous_amount_yuan"] == "1200"
    assert vm["category_comparison"][0]["delta_amount_cents"] is None
    json.dumps(vm)


@pytest.mark.parametrize("category, unavailable", [("餐饮", True), ("交通", False), ("", True)])
def test_merchant_empty_state_uses_only_the_selected_category_projection(period_page, category, unavailable):
    period_page.payload["merchant_category"] = category
    html = _report_response(period_page, merchant_category=category).text
    assert ("补齐汇率后继续，也可切换笔数排行" in html) is unavailable


def test_full_page_preserves_currency_unknown_metrics_and_unavailable_rankings(period_page):
    response = _report_response(period_page)
    assert 'data-home-currency="JPY"' in response.text and 'data-home-currency-minor-digits="0"' in response.text
    assert "CN¥" not in response.text and "None" not in response.text
    assert "待补" in response.text and "金额排行暂不可用" in response.text
    assert "本月还没有已确认账单可统计" not in response.text
    assert "上月无数据" not in response.text and "前 5 笔" not in response.text and "前 8 名" not in response.text
    payload = json.loads(re.search(r'id="reports-overview-data">(.*?)</script>', response.text, re.DOTALL).group(1))
    assert payload["total_amount_cents"] is None and payload["count"] == 2
    data = _report_response(period_page, view="data")
    assert "参考汇率日期：USD → JPY · 2026-04-15" in data.text
    assert "待补信息" in data.text and "None" not in data.text
    history = json.loads(unescape(re.search(r"id=\"chart-trend\"[^>]*data-series='([^']+)'", response.text, re.S).group(1)))
    assert history[0]["reference_rates"] == [{"source_currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-04-15"}]
    for name, kwargs in period_page.calls:
        assert kwargs["tenant_id"] == "family"
        assert kwargs.get("home_currency_code", kwargs.get("currency_code")) == "JPY", name


def test_count_ranking_remains_usable_when_amount_is_unknown(period_page):
    period_page.payload["merchant_ranking"] = [{"merchant": "原商家", "amount_cents": None, "count": 2}]
    response = _report_response(period_page, ranking_metric="count")
    assert "原商家" in response.text and "按本月笔数降序" in response.text
    payload = json.loads(re.search(r'id="reports-overview-data">(.*?)</script>', response.text, re.DOTALL).group(1))
    assert payload["merchant_ranking"][0]["amount_cents"] is None
    assert payload["merchant_ranking"][0]["count"] == 2


def test_history_reader_and_csv_share_month_currency_unknowns_and_return_context(period_page, monkeypatch):
    from app.services.reports_service import _history

    def history(_db, **kwargs):
        period_page.calls.append(("history_export", kwargs))
        return period_page.rows

    monkeypatch.setattr(_history, "six_month_summary", history)
    overview = _report_response(period_page)
    href = next(unescape(href) for href in re.findall(r'href="([^"]+)"', overview.text) if "view=data" in href)
    reader = period_page.client.get(href)
    assert reader.status_code == 200
    assert "2026-04" in reader.text and "2026-05" in reader.text and "待补信息" in reader.text
    download = next(unescape(href) for href in re.findall(r'href="([^"]+)"', reader.text) if "scope=six_month" in href)
    query = parse_qs(urlsplit(download).query)
    assert {key: query[key] for key in ("ledger_id", "month", "home_currency_code", "merchant_category", "granularity", "ranking_metric")} == {
        "ledger_id": ["family"], "month": ["2026-05"], "home_currency_code": ["JPY"],
        "merchant_category": ["餐饮"], "granularity": ["week"], "ranking_metric": ["amount"]}
    result = period_page.client.get(download)
    assert result.status_code == 200
    assert '2026-05-six-month.csv' in result.headers['content-disposition']
    rows = list(csv.reader(result.text.lstrip('\ufeff').splitlines()))
    assert rows[1][0:7] == ['monthly_history', '2026-04', 'JPY', '1200', '1200', '1500', '1500']
    assert rows[2][0:7] == ['monthly_history', '2026-05', 'JPY', '', '', '', '']
    assert ['missing_rates', '2026-05', 'USD', 'JPY', '2026-05-02'] in rows
    assert ['reference_rates', '2026-04', 'USD', 'JPY', '2026-04-15'] in rows
    assert period_page.calls[-1] == ('history_export', {
        'anchor_month': '2026-05', 'tenant_id': 'family', 'timezone_name': 'Asia/Shanghai', 'currency_code': 'JPY'})


def test_history_total_does_not_block_representable_months_and_average():
    from app.money_contract_types import MONEY_AGGREGATE_MAX
    from app.routes.web_reports import _six_month_history_view

    rows = [{'amount_cents': MONEY_AGGREGATE_MAX, 'budget_cents': 0, 'missing_rates': [], 'reference_rates': []}] * 2
    view = _six_month_history_view(rows, currency_code='JPY')
    assert view['six_month_total_label'] == '合计超出显示范围'
    assert view['six_month_average_amount_yuan'] == str(MONEY_AGGREGATE_MAX)
    assert [row['amount_cents'] for row in view['six_month_trend']] == [MONEY_AGGREGATE_MAX] * 2


def test_navigation_export_and_rate_recovery_keep_original_report_task(period_page):
    response = _report_response(period_page)
    links = [urlsplit(unescape(href)) for href in re.findall(r'href="([^"]+)"', response.text)]
    followed = [link for link in links if link.path in {"/web/reports", "/web/reports/export.csv", "/web/budget-advise/rates"}]
    assert {link.path for link in followed} == {"/web/reports", "/web/reports/export.csv", "/web/budget-advise/rates"}
    for link in followed:
        query = parse_qs(link.query)
        assert (query["ledger_id"], query["month"], query["home_currency_code"], query["merchant_category"]) == (
            ["family"], ["2026-05"], ["JPY"], ["餐饮"])
        assert {"granularity", "ranking_metric"} <= query.keys()
        if link.path.endswith("/rates"):
            assert query["return_to"] == ["reports"]
    csv_link = next(link for link in followed if link.path.endswith(".csv"))
    exported = period_page.client.get(csv_link.geturl())
    assert exported.status_code == 200
    args = next(kwargs for name, kwargs in period_page.calls if name == "export")
    assert (args["home_currency_code"], args["month"], args["merchant_category"],
        args["ranking_metric"], args["granularity"]) == ("JPY", "2026-05", "餐饮", "amount", "week")


def test_month_navigation_encodes_filters_and_keeps_captured_currency(period_page):
    from starlette.requests import Request

    context = {"selected_month": "2026-05", "month_picker_query": {"ledger_id": "family",
        "home_currency_code": "JPY", "granularity": "week", "ranking_metric": "count",
        "merchant_category": "咖啡 & 茶"},
        "request": Request({"type": "http", "path": "/web/reports", "headers": [], "query_string": b"month=2026-05"})}
    html = period_page.module.templates.get_template("_month_picker.html").render(context)
    links = re.findall(r'href="([^"]+)"', html)
    assert len(links) == 2
    for link, month in zip(links, ("2026-04", "2026-06"), strict=True):
        assert parse_qs(urlsplit(unescape(link)).query) == {
            **{key: [value] for key, value in context["month_picker_query"].items()}, "month": [month]}
