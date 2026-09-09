"""Confirmed list, calendar and recovery retain the same projected task."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from sqlalchemy.engine import Engine

    monkeypatch.setattr(Engine, "connect", lambda *_a, **_k: pytest.fail("pure confirmed check opened a database"))


def test_calendar_uses_shared_projection_and_preserves_unknown_day(monkeypatch):
    from app.services import web_stats_service as service
    from app.services.money_projection_service import ProjectionGap

    gap = ProjectionGap("CNY", "JPY", date(2026, 8, 5))
    entries = [SimpleNamespace(stream_date=date(2026, 8, 4), amount_cents=120, gap=None),
        SimpleNamespace(stream_date=date(2026, 8, 4), amount_cents=-20, gap=None),
        SimpleNamespace(stream_date=date(2026, 8, 5), amount_cents=None, gap=gap)]
    calls = []
    monkeypatch.setattr(service, "read_projected_entries", lambda _db, **kw: calls.append(kw) or entries)
    rows = service.confirmed_by_day(object(), "family", "2026-08", currency_code="JPY", tag="旅行")
    assert [(row["amount_cents"], row["count"]) for row in rows] == [(100, 2), (None, 1)]
    assert rows[0]["amount_yuan"] == 100 and rows[1]["amount_yuan"] is None
    assert rows[1]["missing_rates"] == (gap,)
    assert calls[0]["home"] == "JPY" and calls[0]["tag"] == "旅行" and calls[0]["tenant_id"] == "family"


def test_confirmed_unknown_month_and_day_keep_counts_and_unavailable_peak(monkeypatch):
    from app.routes import web_app as web
    from app.services.money_projection_service import ProjectionGap

    gap = ProjectionGap("CNY", "JPY", date(2026, 8, 5))
    calls = []
    monkeypatch.setattr(web, "monthly_stats", lambda _db, *a, **kw: calls.append(kw) or {
        "home_currency_code": "JPY", "total_amount_cents": None, "count": 3, "missing_rates": (gap,)})
    monkeypatch.setattr(web, "_confirmed_by_day", lambda *a, **kw: [
        {"date": "2026-08-04", "amount_cents": 100, "count": 2},
        {"date": "2026-08-05", "amount_cents": None, "count": 1}])
    monkeypatch.setattr(web, "_confirmed_source_breakdown", lambda *a, **kw: [{"count": 2}])
    context = web._confirmed_month_context(object(), selected_id="family", effective_month="2026-08",
        currency_code="JPY", tag="旅行")
    assert context["month_total_amount_yuan"] is None and context["month_average_amount_yuan"] is None
    assert context["month_peak_amount_yuan"] is None and context["month_total_count"] == 3
    assert context["missing_rates"] == (gap,) and calls[0]["home_currency_code"] == "JPY"


def test_confirmed_fact_origin_keeps_display_home_and_filters():
    from app.routes._web_expense_return_context import ExpenseReturnContext, return_context_params
    from app.routes.web_app import _confirmed_edit_query

    query = parse_qs(_confirmed_edit_query("family", effective_month="2026-08", page=3, tag="旅行",
        home_currency_code="JPY"))
    context = ExpenseReturnContext(**{key: value[0] for key, value in query.items() if key != "ledger_id"})
    assert return_context_params(**context.as_kwargs()) == {
        "month": "2026-08", "page": "3", "tag": "旅行", "home_currency_code": "JPY"}


def test_real_confirmed_dto_keeps_original_label_while_projecting_page_total(monkeypatch):
    from app.routes import web_app as web
    from app.schemas import ConfirmedExpenseStreamItem, ExpenseResponse
    from app.services import money_projection_service

    when = datetime(2026, 8, 5, 12, tzinfo=UTC)
    roots = []
    for index, home in enumerate(("CNY", "JPY"), 1):
        fields = dict.fromkeys(ExpenseResponse.model_fields)
        fields.update(id=index, amount_cents=100, home_currency=home, original_currency_code=home,
            original_amount_minor=100, merchant=f"原账单{index}", category="餐饮", status="confirmed",
            created_at=when, confirmed_at=when, expense_time=when, image_path=None, image_deleted_at=None,
            fx_status="none", row_version=1)
        roots.append(ExpenseResponse.model_construct(**fields))
    entries = [ConfirmedExpenseStreamItem.model_construct(root=root, offset=None, entry_kind="expense",
        stream_date=when.date(), stream_sort_id=root.id, stream_amount_cents=100, lineage_status="active") for root in roots]
    monkeypatch.setattr(money_projection_service, "resolve_payload_rate", lambda *a, **kw: (Decimal("0.05"), None, None, None))
    items = web._confirmed_items(entries, "CNY", db=object(), ledger_id="family")
    assert [item["projected_amount_cents"] for item in items] == [100, 500]
    assert [item["amount_label"] for item in items] == ["¥1.00", "¥100"]
    context = web._confirmed_money_context(object(), selected_id="family", month="", home="CNY", tag=None, items=items)
    assert context["page_day_totals"] == {"2026-08-05": 600}
    assert context["missing_rates"] == () and context["money_incomplete"] is False


def test_actual_confirmed_template_distinguishes_unknown_calendar_and_page_sum():
    from app.routes._web_money_views import projected_money_context

    env = Environment(autoescape=True, undefined=StrictUndefined, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web"),
    ]))
    entry = {"entry_kind": "expense", "id": 3, "stream_date": "2026-08-05", "stream_amount_cents": 100,
        "merchant": "原账单", "category": "餐饮", "stat_time": "", "lineage_chip_label": "", "amount_label": "CN¥1.00",
        "fx_meta": None}
    html = env.get_template("confirmed.html").render(filter="", tag="", total=1, selected_ledger_id="family",
        selected_month="2026-08", month="2026-08", month_total_amount_yuan=None, month_total_count=1,
        can_write=False, expenses=[entry], page_day_totals={"2026-08-05": None},
        by_day=[{"date": "2026-08-05", "amount_cents": None, "count": 1}], calendar_max=None,
        source_breakdown=[], total_pages=1, page=1, confirmed_edit_query="ledger_id=family", pager_query="",
        flash_message="", flash_type="", missing_rates=[],
        money_task={"ledger_id": "family", "month": "2026-08", "home_currency_code": "JPY", "return_to": "confirmed"},
        **projected_money_context("JPY"))
    assert 'title="2026-08-05 · 待补齐换算信息"' in html
    assert html.count("待补齐换算信息") >= 3 and "CN¥1.00" in re.sub(r"<[^>]+>", "", html)
    assert "None" not in html and "¥100" not in html


@pytest.mark.parametrize("failed", [True, False])
def test_actual_batch_post_preserves_projection_home_on_error_and_success(monkeypatch, failed):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.routes import web_confirmed_batch as web

    monkeypatch.setattr(web, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(web, "_resolve_selected_ledger_id", lambda *a, **kw: "family")
    monkeypatch.setattr(web, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(web, "resolve_web_actor", lambda *a: (7, None))
    outcome = web._ConfirmedBatchOutcome([3], result=SimpleNamespace(updated_count=1, skipped_not_found=0,
        skipped_not_confirmed=0), error_message="原输入已保留" if failed else "")
    monkeypatch.setattr(web, "_execute_confirmed_batch", lambda *a, **kw: outcome)
    monkeypatch.setattr(web, "_render_confirmed_page", lambda *a, **kw: JSONResponse(kw, status_code=kw["status_code"]))
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[web.LocalOnly.dependency] = lambda: None
    with TestClient(app) as client:
        response = client.post("/web/confirmed/batch-update", data={"action": "set_category",
            "ledger_id": "family", "home_currency_code": "JPY", "month": "2026-08", "tag": "旅行",
            "page": "3", "idempotency_key": "original-batch-key"}, follow_redirects=False)
    if failed:
        assert response.status_code == 422
        values = response.json()
        assert values["home_currency_code"] == "JPY" and values["batch_idempotency_key"] == "original-batch-key"
        assert values["month"] == "2026-08" and values["tag"] == "旅行" and values["page"] == 3
    else:
        assert response.status_code == 303
        values = parse_qs(response.headers["location"].split("?", 1)[1])
        assert values["home_currency_code"] == ["JPY"] and values["month"] == ["2026-08"]
        assert values["tag"] == ["旅行"] and values["page"] == ["3"]
