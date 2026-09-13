"""Pure Insights-to-Facts counterexamples; no client, database, or lifespan."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined


@pytest.fixture(scope="module")
def web_modules() -> SimpleNamespace:
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()  # Safe import defaults only; does not start the app or its database.
    from app.routes import _web_expense_return_context, web_reports

    return SimpleNamespace(reports=web_reports, returns=_web_expense_return_context)


def test_report_top_rows_link_to_exact_facts_even_when_display_fields_match(
    monkeypatch: pytest.MonkeyPatch, web_modules: SimpleNamespace,
) -> None:
    expenses = [
        SimpleNamespace(
            id=expense_id, merchant="同一家商店", category="餐饮", amount_cents=12_300,
            home_currency_code="CNY", expense_time=datetime(2026, 5, 18, 10, tzinfo=UTC),
        )
        for expense_id in (41, 42)
    ]
    db = object()

    def query_rows(actual_db, **kwargs):
        assert actual_db is db
        assert kwargs == {"tenant_id": "family", "month": "2026-05", "timezone_name": "Asia/Shanghai",
            "home_currency_code": "JPY"}
        return SimpleNamespace(home_currency_code="JPY", missing_rates=(), items=[
            SimpleNamespace(expense=expense, amount_cents=2700) for expense in expenses])

    monkeypatch.setattr(web_modules.reports, "top_expenses_for_month", query_rows)
    rows = web_modules.reports._top_expenses_view(
        db, tenant_id="family", month="2026-05", timezone_name="Asia/Shanghai",
        presentation_currency_code="JPY", return_context=web_modules.returns.ExpenseReturnContext(
            return_to="reports", return_month="2026-05", return_home_currency_code="JPY",
            return_granularity="week", return_ranking_metric="count", return_merchant_category="餐饮"),
    )["top_expenses"]

    assert len(rows) == 2
    for expense, row in zip(expenses, rows, strict=True):
        target = urlsplit(row["edit_href"])
        assert target.path == f"/web/expenses/{expense.id}/edit"
        assert row["amount_yuan"] == "2700"
        assert parse_qs(target.query) == {"ledger_id": ["family"], "return_to": ["reports"],
            "return_month": ["2026-05"], "return_home_currency_code": ["JPY"], "return_granularity": ["week"],
            "return_ranking_metric": ["count"], "return_merchant_category": ["餐饮"]}


def test_report_month_survives_fact_correction_and_return(web_modules: SimpleNamespace) -> None:
    helpers = web_modules.returns
    origin = {"return_to": "reports", "return_month": "2026-05"}
    retained = helpers.return_context_params(**origin)
    correction = helpers.flow_href("/web/expenses/41/correct", ledger_id="family", **origin)
    carried = {"return_to": "", **{key: values[0] for key, values in parse_qs(urlsplit(correction).query).items()}}
    corrected_fact = helpers.flow_href("/web/expenses/41/edit", **carried)
    back = helpers.return_href(default_path="/web/confirmed", **carried)

    assert (retained, correction, corrected_fact, back) == (
        {"month": "2026-05"},
        "/web/expenses/41/correct?ledger_id=family&return_to=reports&return_month=2026-05",
        "/web/expenses/41/edit?ledger_id=family&return_to=reports&return_month=2026-05",
        "/web/reports?ledger_id=family&month=2026-05",
    )


@pytest.mark.parametrize("origin", ["https://outside.example/report", "//outside.example/report", "reports/../owner"])
def test_fact_return_still_rejects_non_allowlisted_origins(web_modules: SimpleNamespace, origin: str) -> None:
    helpers = web_modules.returns
    context = {"return_to": origin, "return_month": "2026-05"}

    assert helpers.return_context_params(**context) == {}
    assert helpers.flow_href("/web/expenses/41/correct", ledger_id="family", **context) == (
        "/web/expenses/41/correct?ledger_id=family"
    )
    assert helpers.return_href(ledger_id="family", default_path="/web/confirmed", **context) == (
        "/web/confirmed?ledger_id=family"
    )


def test_data_quality_routes_each_uncategorized_count_to_its_records() -> None:
    templates = Path(__file__).resolve().parents[1] / "app" / "templates" / "web"
    environment = Environment(
        loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(templates),
        ]),
        autoescape=True,
        undefined=StrictUndefined,
    )
    summary = {
        "pending_total": 2, "missing_amount": 0, "missing_merchant": 0,
        "suspected_duplicates": 0, "ready_to_confirm_categorized": 0,
        "missing_category": 5, "missing_category_pending": 2, "missing_category_confirmed": 3,
        "confirmed_without_image": 0, "oldest_pending_age_days": None,
    }
    body = environment.get_template("data_quality.html").render(
        summary=summary, selected_ledger_id="family", selected_ledger_name="家庭账本",
        can_write=True, generated_at_local="2026-05-31 12:00",
    )
    actions = {
        unescape(href): re.sub(r"<[^>]+>", " ", content)
        for href, content in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.DOTALL)
    }
    expected = {
        "/web/pending?ledger_id=family&filter=missing_category": "2",
        "/web/confirmed?ledger_id=family&filter=missing_category": "3",
    }

    assert set(actions) == set(expected)
    for href, count in expected.items():
        assert re.search(rf"(?<!\d){count}(?!\d)", actions[href])


def test_uncategorized_pagination_and_fact_return_keep_the_all_month_scope(monkeypatch, web_modules):
    from app.routes import web_app

    captured = {}

    def rows(_db, **kwargs):
        captured.update(kwargs)
        return [], 51

    monkeypatch.setattr(web_app, "list_confirmed", rows)
    monkeypatch.setattr(web_app, "require_runtime_home_currency_code", lambda _db: "CNY")
    monkeypatch.setattr(web_app, "accounting_timezone_key", lambda: "UTC")
    page = web_app._confirmed_page_rows(
        object(), selected_id="family", page=2, month="2026-05", tag=None,
        filter="missing_category",
    )
    assert captured == {
        "tenant_id": "family", "page": 2, "page_size": 50, "month": None,
        "tag": None, "timezone_name": "UTC", "missing_category": True,
    }
    assert page == ("", "CNY", [], 51, 2, "ledger_id=family&filter=missing_category&home_currency_code=CNY", 2)
    context = web_app._confirmed_edit_query(
        "family", effective_month="", page=2, tag=None, filter="missing_category",
    )
    fields = {key: values[0] for key, values in parse_qs(context).items()}
    assert web_modules.returns.return_href(default_path="/web/pending", **fields) == (
        "/web/confirmed?ledger_id=family&filter=missing_category&page=2"
    )


def test_shrunk_last_page_still_exposes_remaining_uncategorized_work(monkeypatch, web_modules):
    from app.routes import web_app

    requested_pages = []

    def rows(_db, **kwargs):
        requested_pages.append(kwargs["page"])
        assert kwargs["month"] is None
        assert kwargs["missing_category"] is True
        return [], 50

    monkeypatch.setattr(web_app, "list_confirmed", rows)
    monkeypatch.setattr(web_app, "require_runtime_home_currency_code", lambda _db: "CNY")
    monkeypatch.setattr(web_app, "accounting_timezone_key", lambda: "UTC")
    page = web_app._confirmed_page_rows(
        object(), selected_id="family", page=2, month=None, tag=None,
        filter="missing_category",
    )
    assert requested_pages == [2, 1]
    assert page[-1] == 1


@pytest.mark.parametrize("filter,month,scope", [
    ("", "2026-05", {"month": ["2026-05"]}),
    ("missing_category", "", {"filter": ["missing_category"]}),
])
def test_clear_tag_links_keep_only_the_current_month_or_all_month_scope(filter, month, scope):
    templates = Path(__file__).resolve().parents[1] / "app" / "templates" / "web"
    environment = Environment(
        loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(templates),
        ]), autoescape=True, undefined=StrictUndefined,
    )
    body = environment.get_template("confirmed.html").render(
        filter=filter, month=month, selected_month=month, selected_ledger_id="family",
        tag="Shared", can_write=False, total=0, expenses=[], flash_message=None,
        home_currency_symbol="¥", month_total_amount_yuan="0.00", month_total_count=0,
        by_day=[], source_breakdown=[], calendar_max=0, home_currency_code="JPY", missing_rates=[],
        money_task={"ledger_id": "family", "month": month, "home_currency_code": "JPY", "return_to": "confirmed"},
    )
    hrefs = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>清除[^<]*</a>', body)
    assert len(hrefs) == 2  # Both the active-filter bar and the empty-state exit.
    for href in hrefs:
        target = urlsplit(unescape(href))
        assert target.path == "/web/confirmed"
        assert parse_qs(target.query, keep_blank_values=True) == {"ledger_id": ["family"], "home_currency_code": ["JPY"], **scope}
