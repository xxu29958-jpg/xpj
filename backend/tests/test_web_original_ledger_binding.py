"""Original planning forms cannot follow a browser session into another ledger."""

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.params import Form
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from starlette.requests import Request

from app.database import get_db
from app.middleware import csrf
from app.routes import (
    web_common,
    web_debt_create,
    web_expense_offsets,
    web_goal_edit,
    web_goals,
    web_income_edit,
    web_income_plans,
    web_recurring,
    web_recurring_occurrences,
    web_rule_edit,
    web_rules,
)
from app.routes._web_expense_return_context import ExpenseReturnContext
from app.routes._web_session_common import LedgerOption
from tests._web_native_form_support import hidden_post_forms

CASES = [
    (web_goals, "web_goals_create", "/web/goals/create"),
    (web_goal_edit, "web_goal_save", "/web/goals/original-goal/edit"),
    (web_rules, "web_rules_create", "/web/rules/create"),
    (web_rule_edit, "web_rule_save", "/web/rules/17/edit"),
    (web_rules, "web_rules_toggle", "/web/rules/17/toggle"),
    (web_recurring, "web_recurring_create", "/web/recurring/create"),
    (web_recurring, "web_recurring_edit", "/web/recurring/original-item/edit"),
    (web_recurring, "web_recurring_confirm_candidate", "/web/recurring/confirm-candidate"),
    (web_recurring_occurrences, "web_set_recurring_occurrence", "/web/recurring/original-item/occurrence"),
    (web_income_plans, "post_create", "/web/income-plans/create"),
    (web_income_edit, "web_income_save", "/web/income-plans/original-income/edit"),
    (web_income_plans, "post_archive", "/web/income-plans/original-income/archive"),
    (web_income_plans, "post_restore", "/web/income-plans/original-income/restore"),
]


def _request(path, role="owner"):
    request = Request({"type": "http", "method": "POST", "path": path, "headers": [],
        "scheme": "https", "server": ("example.test", 443), "client": ("127.0.0.1", 50100), "query_string": b""})
    request.state.web_session_auth = SimpleNamespace(account_id=None, ledger_id="new-ledger", ledger_name="New", role=role)
    return request


@pytest.fixture
def retained_form_context(monkeypatch):
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"synthetic-csrf-signing-secret")
    template = Jinja2Templates(directory=Path(__file__).parents[1] / "app/templates/web", context_processors=[csrf.csrf_context])
    template.env.loader = ChoiceLoader([DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web")])
    monkeypatch.setattr(web_common, "templates", template)
    monkeypatch.setattr(web_common, "_base_ctx", lambda *_a, **_k: {})


@pytest.mark.parametrize("current_role", ["owner", "viewer"])
@pytest.mark.parametrize("module,function,path", CASES, ids=[case[1] for case in CASES])
def test_switched_session_keeps_original_form_before_any_object_read_or_command(monkeypatch, retained_form_context,
    module, function, path, current_role):
    monkeypatch.setattr(module, "_list_ledger_options", lambda _db: [LedgerOption("new-ledger", "New", current_role, False, 0, 0)])
    stopped = []
    for name in ("get_goal", "get_income_plan", "find_rule_for_tenant", "create_spending_goal_idempotently",
        "update_goal_idempotently", "create_rule_idempotently", "update_rule_idempotently",
        "create_manual_recurring_item", "update_recurring_item", "confirm_recurring_candidate",
        "set_occurrence_payment", "create_income_plan_idempotently", "update_income_plan_idempotently",
        "archive_income_plan", "restore_income_plan"):
        if hasattr(module, name):
            spy = Mock(side_effect=AssertionError("Original submission reached current-ledger reader/writer"))
            monkeypatch.setattr(module, name, spy)
            stopped.append(spy)
    handler = getattr(module, function)
    values = {name: parameter.default.default for name, parameter in inspect.signature(handler).parameters.items()
        if isinstance(parameter.default, Form)}
    supplied = {"ledger_id": "old-ledger", "name": "原目标", "label": "原收入", "merchant": "原固定支出",
        "keyword": "原规则", "category": "transport", "source_type": "salary", "frequency": "monthly",
        "home_currency_code": "JPY", "month": "2026-09", "intent_month": "2026-09", "amount_yuan": "1200",
        "target_amount_yuan": "1200", "baseline_amount_yuan": "1200", "amount_min_yuan": "1200",
        "pay_day": "10", "expected_row_version": "3", "idempotency_key": "original-key",
        "public_id": "original-object", "rule_id": 17, "enabled": False, "action": "clear", "amount_cents": "1200"}
    values.update({key: value for key, value in supplied.items() if key in inspect.signature(handler).parameters})
    response = handler(_request(path, current_role), **values, db=Mock(), _local=None)
    assert response.status_code == 409
    html = response.body.decode()
    assert 'name="ledger_id" value="old-ledger"' in html
    assert f'action="{path}"' in html
    for field in ("idempotency_key", "expected_row_version", "amount_yuan", "baseline_amount_yuan", "target_amount_yuan"):
        if field in values:
            assert f'name="{field}" value="{values[field]}"' in html
    assert "切回原账本" in html
    assert all(not spy.called for spy in stopped)


def test_missing_original_ledger_keeps_raw_fields_without_offering_ambiguous_retry(retained_form_context):
    response = web_common.preserve_original_ledger_form(_request("/web/income-plans/create"), Mock(), options=[],
        selected="new-ledger", fields={"ledger_id": "", "label": "待核对收入", "amount_yuan": " 001200 ",
            "idempotency_key": "original-key", "expected_row_version": "3"}, task="添加收入计划")
    html = response.body.decode()
    assert response.status_code == 409 and 'name="amount_yuan" value=" 001200 "' in html
    assert 'name="idempotency_key" value="original-key"' in html
    assert 'name="expected_row_version" value="3"' in html
    assert "原账本无法确认" in html and '<button' not in html
    assert '<dd>original-key</dd>' not in html and '<dt>expected_row_version</dt>' not in html


def test_original_ledger_match_continues_to_the_existing_owner_without_reading_or_rekeying():
    db = Mock()
    fields = {"ledger_id": "owner", "idempotency_key": "original-key", "expected_row_version": "3"}
    assert web_common.preserve_original_ledger_form(_request("/web/goals/create"), db,
        options=[], selected="owner", fields=fields, task="添加支出目标") is None
    assert not db.mock_calls
    assert fields == {"ledger_id": "owner", "idempotency_key": "original-key", "expected_row_version": "3"}


def test_final_debt_submit_after_rate_recovery_cannot_follow_a_switched_session(
    monkeypatch, retained_form_context,
):
    monkeypatch.setattr(web_debt_create, "_list_ledger_options",
        lambda _db: [LedgerOption("new-ledger", "New", "owner", False, 0, 0)])
    monkeypatch.setattr(web_debt_create, "_actor_account_id", lambda *_: 7)
    writer = Mock(return_value=SimpleNamespace(public_id="wrong-ledger-debt"))
    monkeypatch.setattr(web_debt_create, "create_debt_idempotently", writer)
    original = {"ledger_id": "old-ledger", "home_currency_code": "CNY", "currency_code": "USD",
        "amount_major": "12.50", "event_time": "2026-05-06", "direction": "i_owe",
        "counterparty_label": "Original debt", "note": "Keep original intent", "debt_kind": "unspecified",
        "installment_count": "", "installment_period_months": "", "idempotency_key": "original-debt-key"}
    response = web_debt_create.web_create_debt(_request("/web/debts"), **original, csrf_token="", db=Mock(), _local=None)
    assert response.status_code == 409
    saved = hidden_post_forms(response.body.decode())["/web/debts"]
    assert all(saved[key] == value for key, value in original.items())
    writer.assert_not_called()


def test_final_refund_after_rate_recovery_preserves_original_before_new_ledger_lookup(
    monkeypatch, retained_form_context,
):
    monkeypatch.setattr(web_expense_offsets, "_list_ledger_options",
        lambda _db: [LedgerOption("new-ledger", "New", "owner", False, 0, 0)])
    reader = Mock(side_effect=AssertionError("Original refund reached a different ledger"))
    monkeypatch.setattr(web_expense_offsets, "get_expense", reader)
    original = {"ledger_id": "old-ledger", "kind": "refund", "original_amount": "25.00",
        "accounting_date": "2026-05-06", "reason": "Original refund",
        "expected_row_version": "7", "idempotency_key": "original-refund-key"}
    response = web_expense_offsets.web_create_expense_offset(17, _request("/web/expenses/17/offsets"),
        **original, return_context=ExpenseReturnContext(return_to="reports", return_month="2026-05"), db=Mock(), _local=None)
    assert response.status_code == 409
    saved = hidden_post_forms(response.body.decode())["/web/expenses/17/offsets"]
    assert all(saved[key] == value for key, value in original.items())
    assert saved["return_month"] == "2026-05" and saved["return_to"] == "reports"
    reader.assert_not_called()


def test_native_retained_form_can_retry_unchanged_after_switching_back(monkeypatch, retained_form_context):
    current = {"ledger": "new-ledger"}
    writer = Mock()
    monkeypatch.setattr(web_income_plans, "_list_ledger_options", lambda _db: [
        LedgerOption(current["ledger"], "Current", "owner", False, 0, 0)])
    monkeypatch.setattr(web_income_plans, "create_income_plan_idempotently", writer)
    monkeypatch.setattr(web_income_plans, "resolve_web_actor_account_id", lambda *_a: 1)
    app = FastAPI()
    app.include_router(web_income_plans.router)
    app.dependency_overrides[get_db] = lambda: Mock()
    app.dependency_overrides[web_common._require_local] = lambda: None
    app.middleware("http")(csrf.csrf_loopback_form_guard)

    @app.middleware("http")
    async def authenticated_session(request, call_next):
        request.state.web_session_auth = SimpleNamespace(account_id=None, ledger_id=current["ledger"],
            ledger_name="Current", role="owner")
        return await call_next(request)

    original = {"ledger_id": "old-ledger", "home_currency_code": "JPY", "amount_yuan": "1200", "label": "原日元收入",
        "source_type": "salary", "frequency": "monthly", "pay_day": "10", "intent_month": "2026-09",
        "idempotency_key": "original-key", "csrf_token": csrf._csrf_token_for_seed("synthetic-browser-seed")}
    with TestClient(app, base_url="https://example.test", client=("127.0.0.1", 50100)) as client:
        client.cookies.set(csrf.CSRF_COOKIE_NAME, "synthetic-browser-seed")
        retained = client.post("/web/income-plans/create", data=original, headers={"Origin": "https://example.test"})
        assert retained.status_code == 409 and not writer.called
        saved = hidden_post_forms(retained.text)["/web/income-plans/create"]
        assert all(saved[key] == value for key, value in original.items())
        current["ledger"] = "old-ledger"
        retried = client.post("/web/income-plans/create", data=saved,
            headers={"Origin": "https://example.test"}, follow_redirects=False)
        assert retried.status_code == 303
    assert writer.call_count == 1 and writer.call_args.kwargs["tenant_id"] == "old-ledger"
    assert writer.call_args.kwargs["idempotency_key"] == "original-key"
    payload = writer.call_args.kwargs["payload"]
    assert (payload.amount_cents, payload.home_currency_code, payload.intent_month) == (1200, "JPY", "2026-09")
