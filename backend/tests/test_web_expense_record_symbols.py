"""Expense child amounts and symbols come from the same recorded currency."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from _web_native_form_support import hidden_post_forms
from jinja2 import ChoiceLoader, DictLoader
from starlette.requests import Request

from app.errors import AppError
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
from app.routes._web_pending_enrichment_watch import (
    PendingEnrichmentWatch,
    pending_enrichment_presentation,
)
from app.routes.web_common import templates
from app.schemas import ExpenseRevisionListResponse


@pytest.fixture()
def record_context(monkeypatch):
    now = datetime(2026, 9, 1, 4, tzinfo=UTC)
    expense = Expense(id=41, tenant_id="owner", home_currency_code="CNY", amount_cents=1200,
        original_currency_code="JPY", original_amount_minor=240, exchange_rate_to_cny=Decimal("0.05"),
        exchange_rate_source="manual", exchange_rate_date=now.date(), fx_status="ready",
        merchant="车票", category="交通", status="confirmed", fact_revision=1, row_version=1,
        expense_time=now, created_at=now, confirmed_at=now, updated_at=now, duplicate_status="none",
        accounting_date=now.date(), calendar_revision=1, time_precision="instant",
        user_local_date=now.date(), source_timezone="Asia/Shanghai", source_utc_offset_seconds=28800,
        accounting_date_basis="instant_calendar")
    monkeypatch.setattr(helpers, "calendar_revision", lambda *_a, **_k: SimpleNamespace(
        revision=1, timezone_name="Asia/Shanghai"))
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

    def read(mode, status="mismatch_known", *, source_unknown=False):
        item_response.items_sum_status = status
        expense.status = "pending" if mode == "pending" else "confirmed"
        if source_unknown:
            expense.source_timezone = expense.source_utc_offset_seconds = expense.user_local_date = None
            expense.time_precision = "unknown"
            expense.accounting_date_basis = "legacy_expense_time"
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


@pytest.mark.parametrize("mode", ["pending", "correction"])
def test_legacy_editor_uses_recorded_calendar_without_inventing_source(record_context, mode):
    context = record_context(mode, source_unknown=True)
    assert context["time_form"]["calendar_revision"] == "1"
    assert context["time_form"]["source_timezone"] == "Asia/Shanghai"
    assert context["time_form"]["wall_time"] == "2026-09-01T12:00:00"
    assert context["expense"]["expense_time"] == "2026-09-01 04:00:00+00:00"


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


def _ocr_retry_targets(html: str) -> list[str]:
    """Read visible retry links/buttons and their actual native destinations."""
    targets = []
    for match in re.finditer(r'<(a|button)\b([^>]*)>(.*?)</\1>', html, re.S):
        tag, attrs, body = match.groups()
        if not any(label in body for label in ("重试识别", "重新识别")) or "disabled" in attrs:
            continue
        target = re.search(r'(?:href|formaction)="([^"]+)"', attrs)
        if target is None and tag == "button":
            preceding = html[:match.start()].rsplit("<form", 1)[-1]
            if "</form>" not in preceding:
                target = re.search(r'action="([^"]+)"', preceding)
        if target is not None:
            targets.append(target.group(1))
    return targets


@pytest.mark.parametrize("template", ["edit.html", "_edit_drawer.html"])
@pytest.mark.parametrize("outcome", ["failed", "no_result"])
def test_ocr_failure_next_step_reaches_retry_on_the_original_bill(record_context, template, outcome):
    context = record_context("pending")
    context["expense"].update(has_image=True, image_state="available")
    feedback = pending_enrichment_presentation(
        PendingEnrichmentWatch("00000000-0000-0000-0000-000000000001", outcome, 30000),
        flash_message="", flash_type="",
    )
    assert "打开账单重试识别" in feedback.flash_message
    targets = _ocr_retry_targets(_render(template, context))
    assert targets, "失败/无结果后，真实账单页面必须有可操作的原单识别重试入口"
    assert all("/expenses/41/" in target for target in targets)
    assert all(not target.split("?", 1)[0].endswith(("/save", "/confirm", "/reject")) for target in targets)


@pytest.mark.parametrize("template", ["edit.html", "_edit_drawer.html"])
def test_ocr_retry_does_not_consume_original_edit_currency_date_or_command(record_context, template):
    original = record_context("pending")
    submitted = {"amount_yuan": "00999", "original_currency": "JPY", "merchant": "未保存商家",
        "category": "交通", "note": "未保存备注", "tags": "trip", "expense_time": "",
        "expected_row_version": "1", "idempotency_key": "original-edit-key",
        "reject_idempotency_key": "original-reject-key", "time_precision": "date_only",
        "calendar_revision": "1", "user_local_date": "2026-08-31",
        "source_timezone": "Asia/Tokyo", "source_utc_offset_seconds": "32400",
        "accounting_date": "2026-09-01"}
    context = helpers.web_edit_context(object(), original["request"], [], "owner", 41, form_values=submitted)
    context["expense"].update(has_image=True, image_state="available")
    html = _render(template, context)
    retained = hidden_post_forms(html)["/web/expenses/41/save"]
    for name in ("original_currency", "expected_row_version", "idempotency_key", "reject_idempotency_key",
        "time_precision", "calendar_revision", "user_local_date", "source_timezone",
        "source_utc_offset_seconds", "accounting_date"):
        assert retained[name] == submitted[name]
    assert retained["csrf_token"] == "csrf" and retained["ledger_id"] == "owner"
    assert 'value="00999"' in html and 'value="未保存商家"' in html and "未保存备注" in html
    assert _ocr_retry_targets(html), "保留原填写时也必须能显式选择原单识别重试"
    retry = hidden_post_forms(html)["/web/expenses/41/ocr/retry"]
    assert retry["idempotency_key"] not in {retained["idempotency_key"], retained["reject_idempotency_key"]}
    assert retry["expected_row_version"] == retained["expected_row_version"]
    assert retry["csrf_token"] == retained["csrf_token"] and retry["ledger_id"] == retained["ledger_id"]
    assert not {"amount_yuan", "merchant", "note", "original_currency", "time_precision"} & retry.keys()
    tag = re.search(r'<form\b[^>]*action="/web/expenses/41/ocr/retry"[^>]*>', html).group()
    assert 'target="_blank"' in tag and 'rel="noopener"' in tag and "data-drawer-form" not in tag


@pytest.mark.parametrize("template", ["edit.html", "_edit_drawer.html"])
def test_ocr_retry_is_not_a_viewer_write_action(record_context, template):
    context = record_context("pending")
    context["expense"].update(has_image=True, image_state="available")
    context["can_write"] = False
    assert not _ocr_retry_targets(_render(template, context))


@pytest.mark.parametrize("template", ["edit.html", "_edit_drawer.html"])
def test_ocr_retry_missing_original_has_an_explicit_safe_next_step(record_context, template):
    context = record_context("pending")
    context["expense"].update(has_image=False, image_state="missing")
    html = _render(template, context)
    assert not _ocr_retry_targets(html), "原件缺失不能提供看似可识别的提交"
    assert 'href="/web/expenses/41/original?ledger_id=owner"' in html
    assert re.search(r"(?:无法|不能|不可|需要)[^<>。]*识别|识别[^<>。]*(?:原件|原图)", html), (
        "原件缺失应说明识别为何不可执行，并保留原单原件补回/手动补全入口")


@pytest.mark.parametrize("code,status,retryable", [
    ("ocr_not_configured", 503, True), ("idempotency_key_in_progress", 409, True),
    ("state_conflict", 409, False), ("image_not_found", 404, False),
])
def test_original_ocr_failure_page_preserves_intent_or_guides_review(
    record_context, monkeypatch, code, status, retryable,
):
    record_context("pending")
    monkeypatch.setattr(edit, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(edit, "_resolve_selected_ledger_id", lambda *_a, **_k: "owner")
    monkeypatch.setattr(edit, "_require_selected_ledger_write", lambda *_a: None)
    monkeypatch.setattr(edit, "resolve_web_actor", lambda *_a: (1, None))
    monkeypatch.setattr(edit, "_base_ctx", helpers._base_ctx)
    monkeypatch.setattr(edit, "submit_expense_ocr_retry", Mock(side_effect=AppError(code, status_code=status)))
    env = templates.env.overlay(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), templates.env.loader]))
    monkeypatch.setattr(templates, "env", env)
    request = Request({"type": "http", "method": "POST", "headers": [],
        "path": "/web/expenses/41/ocr/retry", "query_string": b""})
    response = edit.web_retry_expense_ocr(41, request, "owner", "1", "original-ocr-key",
        ExpenseReturnContext(return_to="pending"), None, Mock())
    body = response.body.decode()
    assert response.status_code == status and AppError(code).message in body
    assert "原窗口的填写仍保留" in body
    assert '/web/expenses/41/edit?ledger_id=owner&amp;return_to=pending' in body
    assert '/web/expenses/41/original?ledger_id=owner' in body
    forms = hidden_post_forms(body)
    action = "/web/expenses/41/ocr/retry"
    assert (action in forms) == retryable
    if retryable:
        for name, value in {"ledger_id": "owner", "expected_row_version": "1",
            "idempotency_key": "original-ocr-key", "return_to": "pending"}.items():
            assert forms[action][name] == value


@pytest.mark.parametrize("time_fields", [None, {"time_precision": "instant", "calendar_revision": "1",
    "user_local_date": "2026-09-01", "source_timezone": "Asia/Shanghai",
    "source_utc_offset_seconds": "28800", "accounting_date": ""}])
def test_fx_status_keeps_original_form_and_offers_review_when_current_bill_no_longer_needs_fx(
    record_context, monkeypatch, time_fields,
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
            fragment=fragment, return_context=ExpenseReturnContext(return_to="pending"), time_fields=time_fields)
        response = edit.web_refresh_expense_fx(41, request, form, db=db)
        assert response.status_code == 200
        assert response.context["expense_fx"] is None
        assert response.context["conflict_current"] is None
        body = response.body.decode()
        retained = hidden_post_forms(body)["/web/expenses/41/save"]
        if time_fields is not None:
            assert all(retained[name] == value for name, value in time_fields.items())
        else:
            assert "calendar_revision" not in retained
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
