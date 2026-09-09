"""Native fact split forms retain their report origin through failure and cancellation."""

import re
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader, StrictUndefined

from tests._web_native_form_support import hidden_post_forms


@pytest.fixture()
def split_page(monkeypatch):
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from sqlalchemy.engine import Engine

    from app.database import get_db
    from app.errors import AppError
    from app.routes import _web_expense_fact
    from app.routes import web_bill_split as route
    from app.routes._web_expense_return_context import ExpenseReturnContext, edit_navigation_view
    from app.services.currency_common import currency_input_metadata

    def no_database(*_a, **_k):
        pytest.fail("Split return checks must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    origin = ExpenseReturnContext(return_to="reports", return_month="2026-05", return_home_currency_code="JPY",
        return_granularity="week", return_ranking_metric="count", return_merchant_category="咖啡 & 茶")
    state = SimpleNamespace(origin=origin, fail=True, calls=[])

    def fact_view(*_a, return_context=ExpenseReturnContext(), **_k):
        return {"selected_ledger_id": "family", "expense": {"id": 41}, "home_currency_symbol": "¥",
            "currency_input": currency_input_metadata("CNY"),
            **edit_navigation_view(return_context, expense_id=41, ledger_id="family"),
            "split_invite": {"members": [{"account_id": 9, "account_name": "家人", "role": "member"}],
                "receiver_account_id": 9, "remaining_yuan": "30.00", "requires_review": True,
                "idempotency_key": "original-key", "expected_row_version": 7,
                "sent_rows": [{"public_id": "invitation-1", "receiver_display_name": "家人", "amount_label": "¥10.00",
                    "status": "invited", "expires_at": "2026-05-31", "is_cancellable": True}]}}

    def command(*_a, **kwargs):
        state.calls.append(kwargs)
        if state.fail:
            raise AppError("state_conflict", status_code=409)

    monkeypatch.setattr(_web_expense_fact, "web_fact_context", fact_view)
    monkeypatch.setattr(route, "_list_ledger_options", lambda *_a: [])
    monkeypatch.setattr(route, "_resolve_selected_ledger_id", lambda *_a, **_k: "family")
    monkeypatch.setattr(route, "_require_selected_ledger_write", lambda *_a: None)
    monkeypatch.setattr(route, "resolve_web_actor_account_id", lambda *_a: 3)
    monkeypatch.setattr(route, "require_runtime_home_currency_code", lambda *_a: "CNY")
    monkeypatch.setattr(route.bsplit, "create_invitation", command)
    monkeypatch.setattr(route.bsplit, "cancel_invitation", command)
    root = Path(__file__).resolve().parents[1] / "app/templates/web"
    monkeypatch.setattr(route.templates.env, "loader", ChoiceLoader([
        DictLoader({"expense_fact.html": '{% include "_fact_split_invite.html" %}'}), FileSystemLoader(root)]))
    monkeypatch.setattr(route.templates.env, "undefined", StrictUndefined)
    route.templates.env.cache.clear()
    state.html = lambda: route.templates.get_template("_fact_split_invite.html").render(fact_view(return_context=origin))
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(rollback=lambda: None)
    app.dependency_overrides[route.LocalOnly.dependency] = lambda: None
    app.include_router(route.router)
    with TestClient(app) as client:
        state.client = client
        yield state
    route.templates.env.cache.clear()


def _assert_origin(fields, page):
    expected = {key: value for key, value in page.origin.as_kwargs().items() if value}
    assert {key: fields.get(key) for key in expected} == expected


def test_native_invite_cancel_and_review_link_keep_same_origin(split_page):
    body = split_page.html()
    forms = hidden_post_forms(body)
    assert len(forms) == 2
    for fields in forms.values():
        _assert_origin(fields, split_page)
    href = re.search(r'href="([^"]+)"[^>]*>重新核对账单后发起', body).group(1)
    target = urlsplit(unescape(href))
    assert target.path == "/web/expenses/41/edit"
    _assert_origin({key: values[0] for key, values in parse_qs(target.query).items()}, split_page)


def test_invite_error_preserves_native_origin_and_original_command(split_page):
    action = "/web/expenses/41/split-invite"
    data = {**hidden_post_forms(split_page.html())[action], "receiver_account_id": "9", "amount_yuan": "12.00",
        **split_page.origin.as_kwargs()}
    response = split_page.client.post(action, data=data, follow_redirects=False)
    assert response.status_code == 409
    fields = hidden_post_forms(response.text)[action]
    _assert_origin(fields, split_page)
    assert fields["idempotency_key"] == "original-key" and fields["expected_row_version"] == "7"
    assert 'value="12.00"' in response.text
    assert split_page.calls == [{"sender_account_id": 3, "sender_ledger_id": "family", "expense_id": 41,
        "receiver_account_id": 9, "amount_cents": 1200, "idempotency_key": "original-key", "expected_row_version": 7}]


@pytest.mark.parametrize("failure", [False, True])
def test_cancel_returns_to_fact_with_original_context_on_success_or_failure(split_page, failure):
    split_page.fail = failure
    response = split_page.client.post("/web/bill-splits/invitation-1/cancel", data={
        "ledger_id": "family", "return_expense_id": "41", **split_page.origin.as_kwargs()}, follow_redirects=False)
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.path == "/web/expenses/41/edit"
    query = {key: values[0] for key, values in parse_qs(target.query).items()}
    _assert_origin(query, split_page)
    assert query["ledger_id"] == "family" and query["flash_type"] == ("error" if failure else "success")


def test_invite_success_still_opens_sent_invitations(split_page):
    split_page.fail = False
    response = split_page.client.post("/web/expenses/41/split-invite", data={"ledger_id": "family",
        "receiver_account_id": "9", "amount_yuan": "12.00", "expected_row_version": "7",
        "idempotency_key": "original-key", **split_page.origin.as_kwargs()}, follow_redirects=False)
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.path == "/web/bill-splits/sent"
    query = parse_qs(target.query)
    assert query["ledger_id"] == ["family"] and query["flash_type"] == ["success"]
    assert not any(key.startswith("return_") for key in query)


def test_invite_error_when_fact_disappears_returns_to_original_report(monkeypatch, split_page):
    from app.errors import AppError
    from app.routes import _web_expense_fact
    from app.routes._web_expense_return_context import return_context_params

    def missing(*_a, **_k):
        raise AppError("expense_not_found", status_code=404)

    monkeypatch.setattr(_web_expense_fact, "web_fact_context", missing)
    response = split_page.client.post("/web/expenses/41/split-invite", data={"ledger_id": "family",
        "receiver_account_id": "9", "amount_yuan": "12.00", "expected_row_version": "7",
        "idempotency_key": "original-key", **split_page.origin.as_kwargs()}, follow_redirects=False)
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.path == "/web/reports"
    query = parse_qs(target.query)
    assert query.pop("ledger_id") == ["family"] and query.pop("flash_type") == ["error"]
    assert query.pop("msg")
    assert query == {key: [value] for key, value in return_context_params(**split_page.origin.as_kwargs()).items()}


def test_sent_list_cancel_stays_in_sent_list(split_page):
    split_page.fail = False
    response = split_page.client.post("/web/bill-splits/invitation-1/cancel", data={
        "ledger_id": "family", **split_page.origin.as_kwargs()}, follow_redirects=False)
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.path == "/web/bill-splits/sent"
    assert not any(key.startswith("return_") for key in parse_qs(target.query))
