"""Report origin survives native fact commands without a database connection."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request


@pytest.fixture()
def origin(monkeypatch):
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from sqlalchemy.engine import Engine

    from app.routes._web_expense_return_context import ExpenseReturnContext

    def no_database(*_args, **_kwargs):
        pytest.fail("Report origin tests must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    return ExpenseReturnContext(return_to="reports", return_month="2026-05", return_home_currency_code="JPY",
        return_granularity="week", return_ranking_metric="count", return_merchant_category="咖啡 & 茶")


def test_fact_acknowledgement_returns_original_context_and_keeps_command_identity(monkeypatch, origin):
    from app.database import get_db
    from app.routes import web_expense_items as route
    from app.routes._web_expense_return_context import edit_context_params

    calls = []
    monkeypatch.setattr(route, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(route, "_resolve_selected_ledger_id", lambda *_a, **_k: "family")
    monkeypatch.setattr(route, "_require_selected_ledger_write", lambda *_a: None)
    monkeypatch.setattr(route, "_acknowledge_web_items_mismatch", lambda _db, _request, **kw: calls.append(kw))
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[route.LocalOnly.dependency] = lambda: None
    app.include_router(route.router)
    with TestClient(app) as client:
        response = client.post("/web/expenses/41/items/acknowledge-mismatch", data={
            "ledger_id": "family", "expected_row_version": "7", "idempotency_key": "original-key",
            **origin.as_kwargs()}, follow_redirects=False)
    assert response.status_code == 303
    assert calls == [{"expense_id": 41, "selected_id": "family", "expected_row_version": 7,
        "idempotency_key": "original-key"}]
    target = urlsplit(response.headers["location"])
    assert target.path == "/web/expenses/41/edit"
    query = parse_qs(target.query)
    assert query.pop("ledger_id") == ["family"]
    assert query.pop("msg")
    assert query == {key: [value] for key, value in edit_context_params(**origin.as_kwargs()).items()}


def test_revision_pager_retains_validated_report_origin(origin):
    from app.routes._web_expense_fact_pager import timeline_page_url
    from app.routes._web_expense_return_context import edit_context_params

    target = urlsplit(timeline_page_url(origin, expense_id=41, selected_ledger_id="family", page=2, snapshot=14))
    assert target.path == "/web/expenses/41/edit" and target.fragment == "fact-timeline"
    assert parse_qs(target.query) == {"ledger_id": ["family"], "rev_page": ["2"], "rev_snapshot": ["14"],
        **{key: [value] for key, value in edit_context_params(**origin.as_kwargs()).items()}}


@pytest.mark.parametrize("return_to", ["reports", "confirmed", "search", "https://outside.example"])
def test_report_fields_have_one_allowlisted_consumer(origin, return_to):
    from dataclasses import replace

    from app.routes._web_expense_return_context import return_context_params

    context = replace(origin, return_to=return_to, return_query="咖啡", return_filter="missing_category")
    params = return_context_params(**context.as_kwargs())
    expected = {"reports": {"month": "2026-05", "home_currency_code": "JPY", "granularity": "week",
        "ranking_metric": "count", "merchant_category": "咖啡 & 茶"},
        "confirmed": {"filter": "missing_category"}, "search": {"q": "咖啡"}}
    assert params == expected.get(return_to, {})


def test_fact_error_uses_same_origin_for_missing_row(monkeypatch, origin):
    from app.errors import AppError
    from app.routes import _web_expense_fact as route
    from app.routes._web_expense_return_context import return_context_params

    def missing(*_args, **kwargs):
        assert kwargs["return_context"] is origin
        raise AppError("expense_not_found", status_code=404)

    monkeypatch.setattr(route, "web_fact_context", missing)
    response = route.web_fact_error_response(object(), SimpleNamespace(), [], "family", 41,
        "无法保存", return_context=origin)
    target = urlsplit(response.headers["location"])
    assert target.path == "/web/reports"
    query = parse_qs(target.query)
    assert query.pop("ledger_id") == ["family"] and query.pop("flash_type") == ["error"]
    assert query.pop("msg")
    assert query == {key: [value] for key, value in return_context_params(**origin.as_kwargs()).items()}


def test_post_error_fact_projection_keeps_form_origin_on_both_timeline_links(monkeypatch, origin):
    from app.routes import _web_expense_fact as route
    from app.routes._web_expense_return_context import edit_context_params

    monkeypatch.setattr(route, "web_edit_context", lambda *_a, **_k: {
        "expense": {}, "can_write": True, "home_currency_code": "JPY"})
    monkeypatch.setattr(route, "get_expense", lambda *_a: SimpleNamespace(fact_revision=120, confirmed_at=None))
    monkeypatch.setattr(route, "build_split_invite_context", lambda *_a, **_k: {})
    monkeypatch.setattr(route, "expense_offset_fact_view", lambda *_a: {})
    monkeypatch.setattr(route.invitation_members, "list_members", lambda *_a, **_k: [])
    monkeypatch.setattr(route, "build_fact_timeline", lambda *_a, **_k: {
        "entries": [], "page": 2, "page_size": 50, "total": 120, "snapshot_revision": 120,
        "has_newer": True, "has_older": True})
    request = Request({"type": "http", "method": "POST", "headers": [],
        "path": "/web/expenses/41/items/acknowledge-mismatch", "query_string": b""})

    context = route.web_fact_context(object(), request, [], "family", 41,
        revision_page=2, revision_snapshot=120, error="账单已在其它端被修改", return_context=origin)

    assert context["error"] == "账单已在其它端被修改"
    for direction, page in (("newer", "1"), ("older", "3")):
        target = urlsplit(context["fact_timeline_page"][f"{direction}_url"])
        assert target.path == "/web/expenses/41/edit" and target.fragment == "fact-timeline"
        assert parse_qs(target.query) == {"ledger_id": ["family"], "rev_page": [page], "rev_snapshot": ["120"],
            **{key: [value] for key, value in edit_context_params(**origin.as_kwargs()).items()}}
