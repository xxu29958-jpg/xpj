"""Expense child amounts and symbols come from the same recorded currency."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from _web_native_form_support import hidden_post_forms
from jinja2 import ChoiceLoader, DictLoader
from starlette.requests import Request

from app.middleware import csrf
from app.models import Expense
from app.routes import _web_bill_split_context as invites
from app.routes import _web_correction_page as correction
from app.routes import _web_expense_fact as fact
from app.routes import _web_expense_fx as fx
from app.routes import _web_expense_helpers as helpers
from app.routes import _web_expense_split_presenter as splits
from app.routes import _web_money_views as money_views
from app.routes import web_expense_edit as edit
from app.routes._web_expense_edit_form import WebExpenseEditForm
from app.routes._web_expense_return_context import ExpenseReturnContext
from app.routes.web_common import templates
from app.schemas import ExpenseRevisionListResponse


@pytest.fixture()
def record_context(monkeypatch):
    now = datetime(2026, 9, 1, 4, tzinfo=UTC)
    expense = Expense(id=41, tenant_id="owner", home_currency_code="CNY", amount_cents=1200,
        original_currency_code="JPY", original_amount_minor=240, exchange_rate_to_cny=Decimal("0.05"),
        exchange_rate_source="manual", exchange_rate_date=now.date(), fx_status="ready",
        merchant="车票", category="交通", status="confirmed", fact_revision=1, row_version=1,
        expense_time=now, created_at=now, confirmed_at=now, updated_at=now, duplicate_status="none")
    monkeypatch.setattr(helpers, "get_expense", lambda *_a: expense)
    monkeypatch.setattr(fact, "get_expense", lambda *_a: expense)
    monkeypatch.setattr(helpers, "_base_ctx", lambda request, **_k: {
        "request": request, "home_currency_code": "USD", "home_currency_symbol": "$",
        "can_write": True, "csrf_token": "csrf", "selected_ledger_id": "owner"})
    monkeypatch.setattr(helpers, "manual_draft_ack", lambda *_a: None)
    task_query = Mock(return_value={})
    monkeypatch.setattr(money_views, "current_pending_expense_fx_tasks", task_query)
    monkeypatch.setattr(helpers, "web_split_members", lambda *_a: [])
    monkeypatch.setattr(helpers, "list_ledger_category_options", lambda *_a, **_k: [])
    item_response = SimpleNamespace(items_sum_status="mismatch_known", mismatch_cents=200, items=[
        SimpleNamespace(public_id="item", kind="product", name="车票", quantity_text="1",
            unit_price_cents=1000, amount_cents=1000, category="交通", is_ocr_draft=False)])
    monkeypatch.setattr(helpers, "list_expense_items", lambda *_a: item_response)
    monkeypatch.setattr(splits, "list_expense_splits", lambda *_a: SimpleNamespace(
        parent_amount_cents=1200, splits_total_amount_cents=1000, mismatch_cents=200, splits=[
            SimpleNamespace(public_id="split", member_id=7, account_name="我", role="member",
                amount_cents=1000, note="", disabled_at=None)]))
    monkeypatch.setattr(correction, "require_runtime_home_currency_code", lambda _db: "USD")
    monkeypatch.setattr(fact, "build_split_invite_context", lambda *_a, **_k: None)
    monkeypatch.setattr(fact, "expense_offset_fact_view", lambda *_a: {})
    monkeypatch.setattr(fact.invitation_members, "list_members", lambda *_a, **_k: [])
    monkeypatch.setattr(fact, "list_expense_revisions", lambda *_a, **_k: ExpenseRevisionListResponse(
        items=[], page=1, page_size=50, total=0, snapshot_revision=1))

    def read(mode, status="mismatch_known"):
        item_response.items_sum_status = status
        expense.status = "pending" if mode == "pending" else "confirmed"
        request = Request({"type": "http", "method": "GET", "headers": [],
            "path": "/web/expenses/41/edit", "query_string": b""})
        factory = {"fact": fact.web_fact_context, "correction": correction.web_correction_context,
            "pending": helpers.web_edit_context}[mode]
        before = task_query.call_count
        context = factory(object(), request, [], "owner", 41)
        assert task_query.call_count == before + (mode == "pending")
        if mode != "pending":
            assert context["expense_fx"] is None
        return context

    return read


def _render(name, context):
    # Keep the actual child template; the unrelated navigation shell needs no DB fixtures.
    env = templates.env.overlay(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), templates.env.loader]))
    return env.get_template(name).render(context)


@pytest.mark.parametrize("mode,item_template,split_template", [
    ("fact", "_fact_items_readonly.html", "_fact_splits_readonly.html"),
    ("correction", "_correction_items.html", "_correction_splits.html"),
])
@pytest.mark.parametrize("status", ["mismatch_known", "mismatch_acknowledged"])
def test_record_child_templates_keep_home_symbol_separate_from_payment_and_default(
    record_context, mode, item_template, split_template, status,
):
    context = record_context(mode, status)
    assert context["home_currency_symbol"] == "$"
    assert context["expense"]["original_currency_code"] == "JPY"
    assert context["currency_input"]["currency_code"] == "CNY"
    assert context["receipt_items"]["mismatch_yuan"] == "2.00"
    assert context["split_rows"]["parent_amount_yuan"] == "12.00"
    items_html = _render(item_template, context)
    splits_html = _render(split_template, context)
    assert "¥2.00" in items_html and "$2.00" not in items_html
    assert "账单 ¥12.00 · 已拆 ¥10.00" in splits_html
    assert "还差 ¥2.00 未分配" in splits_html and "$" not in splits_html


def test_pending_record_uses_the_same_record_basis_for_child_summaries(record_context):
    html = _render("edit.html", record_context("pending"))
    assert "金额差 ¥2.00" in html and "金额差 $2.00" not in html
    assert "账单 ¥12.00 · 已拆 ¥10.00" in html
    assert "还差 ¥2.00 未分配" in html


def test_fx_status_keeps_original_form_and_offers_review_when_current_bill_no_longer_needs_fx(
    record_context, monkeypatch,
):
    expense = helpers.get_expense(None, 41, "owner")
    expense.amount_cents = None
    expense.fx_status = "pending"
    assert record_context("pending")["expense_fx"]["current"]["fx_pending"]
    # Another client corrected the pending original input to CNY. The recorded
    # home basis stays CNY; the unsaved JPY form still belongs to the prior revision.
    expense.original_currency_code = "CNY"
    expense.original_amount_minor = 240
    expense.amount_cents = 240
    expense.fx_status = "ready"
    expense.exchange_rate_to_cny = Decimal(1)
    expense.exchange_rate_source = "base"
    expense.row_version += 1
    monkeypatch.setattr(fx, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(fx, "_resolve_selected_ledger_id", lambda *_a, **_k: "owner")
    monkeypatch.setattr(fx, "preserve_original_ledger_form", lambda *_a, **_k: None)
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"synthetic-presenter-csrf-signing-key")
    monkeypatch.setattr(templates.env, "loader", ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), templates.env.loader]))
    db = Mock()
    for fragment in (0, 1):
        request = Request({"type": "http", "method": "POST", "headers": [],
            "path": "/web/expenses/41/fx-status", "query_string": b""})
        form = WebExpenseEditForm(ledger_id="owner", expected_row_version="1",
            idempotency_key="original-edit-key", save_before_confirm=True, amount_yuan="999",
            original_currency="JPY", manual_exchange_rate="", merchant="Unsent merchant",
            category="交通", note="Unsent note", tags="trip", expense_time="2026-09-01T12:00",
            fragment=fragment, return_context=ExpenseReturnContext(return_to="pending"))
        response = edit.web_refresh_expense_fx(41, request, form, db=db)
        assert response.status_code == 200
        assert response.context["expense_fx"] is None
        assert response.context["conflict_current"] is None
        body = response.body.decode()
        retained = hidden_post_forms(body)["/web/expenses/41/save"]
        assert (retained["expected_row_version"], retained["idempotency_key"],
            retained["ledger_id"], retained["original_currency"]) == (
                "1", "original-edit-key", "owner", "JPY")
        assert 'value="999"' in body and 'value="Unsent merchant"' in body and "Unsent note" in body
        assert (expense.home_currency_code, expense.original_currency_code, expense.row_version,
            expense.original_amount_minor, expense.amount_cents) == ("CNY", "CNY", 2, 240, 240)
        assert "载入最新账单（替换未保存填写）" in body
        assert f'href="{escape(response.context["edit_current_href"])}" data-drawer-reload' in body
        assert 'formaction="/web/expenses/41/confirm"' not in body
    db.commit.assert_not_called()


def test_source_invitation_uses_parent_basis_for_input_and_each_agreement_for_sent_rows(
    record_context, monkeypatch,
):
    context = record_context("fact")
    now = datetime(2026, 9, 1, tzinfo=UTC)
    monkeypatch.setattr(invites, "resolve_web_actor_account_id", lambda *_a: 1)
    monkeypatch.setattr(invites, "list_members", lambda *_a, **_k: [SimpleNamespace(
        account_id=2, account_name="家人", role="member", is_self=False, disabled_at=None)])
    monkeypatch.setattr(invites, "require_runtime_home_currency_code", lambda _db: "USD")
    monkeypatch.setattr(invites, "now_utc", lambda: now)
    # Cancelled historical agreements are displayed independently of the current remaining capacity.
    monkeypatch.setattr(invites.bsplit, "list_sent_for_expense", lambda *_a, **_k: [
        SimpleNamespace(public_id=code, status="cancelled", amount_cents=amount, home_currency_code=code,
            receiver_display_name_snapshot="家人", expires_at=now + timedelta(days=1))
        for code, amount in (("CNY", 500), ("JPY", 12))])
    context["split_invite"] = invites.build_split_invite_context(object(), context["request"],
        selected_ledger_id="owner", expense=context["expense"], can_write=True)
    html = _render("_fact_split_invite.html", context)
    assert "分摊金额（¥）" in html and "本张账单还可分摊 ¥12.00" in html
    assert '<td class="amount">¥5.00</td>' in html
    assert '<td class="amount">¥12</td>' in html
    assert "$" not in html
