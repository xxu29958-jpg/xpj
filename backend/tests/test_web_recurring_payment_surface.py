"""Existing Web entry and return adapters must expose one period's payment task."""

import re
from datetime import UTC, datetime
from html import unescape
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import Request

SERIES_ID = "6dce3575-fb65-4df5-bb93-7bb270e8df9b"


@pytest.fixture(autouse=True)
def synthetic_render_signing_key(monkeypatch):
    from app.middleware import csrf

    # Rendering still runs the real context processor and HMAC. This pure
    # fixture supplies its own signing material without relying on app startup.
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"synthetic-recurring-render-signing-key")


def _form(html, action):
    for form in re.findall(r"<form\b[^>]*>.*?</form>", html, re.S):
        if f'action="{action}"' in form:
            return form
    raise AssertionError(f"native form missing: {action}")


def _fields(form):
    values = {}
    for tag in re.findall(r"<input\b[^>]*>", form):
        attrs = {key: unescape(value) for key, value in re.findall(r'([\w-]+)="([^"]*)"', tag)}
        if attrs.get("name") and "disabled" not in tag:
            values[attrs["name"]] = attrs.get("value", "")
    for attrs, content in re.findall(r"<textarea\b([^>]*)>(.*?)</textarea>", form, re.S):
        name = re.search(r'name="([^"]+)"', attrs)
        if name:
            values[name.group(1)] = unescape(content)
    for attrs, content in re.findall(r"<select\b([^>]*)>(.*?)</select>", form, re.S):
        name = re.search(r'name="([^"]+)"', attrs)
        options = re.findall(r'<option\b([^>]*)value="([^"]*)"([^>]*)>', content)
        selected = next((value for before, value, after in options if "selected" in before + after), None)
        if name and options:
            values[name.group(1)] = unescape(selected if selected is not None else options[0][1])
    return values


def _currency_selector(form):
    selector = re.search(r'<select\b[^>]*name="home_currency_code"[^>]*>.*?</select>', form, re.S)
    assert selector is not None, "A user cannot choose an overseas subscription's currency in the hidden home field"
    assert "disabled" not in selector.group(0).split(">", 1)[0]
    return selector.group(0)


def _payment_link(html):
    for href in re.findall(r'href="([^"]+)"', html):
        href = unescape(href)
        if urlsplit(href).path == "/web/expenses/new":
            return href
    raise AssertionError("An unpaid period with no existing bill has no usable record-payment entry")


def _request(path):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []})


def test_actual_recurring_create_form_lets_user_choose_foreign_commitment_currency(monkeypatch):
    from app.routes import web_recurring as web

    monkeypatch.setattr(web, "list_recurring_items", lambda *a, **kw: [])
    monkeypatch.setattr(web, "recurring_amount_anomalies", lambda *a, **kw: {})
    monkeypatch.setattr(web, "next_due_dates", lambda *a, **kw: {})
    monkeypatch.setattr(web, "_load_candidate_rows", lambda *a, **kw: ([], False))
    monkeypatch.setattr(web, "_recurring_hero", lambda *a, **kw: None)
    monkeypatch.setattr(web, "_base_ctx", lambda request, **kw: {
        "request": request, "home_currency_code": "CNY", "home_currency_symbol": "¥",
        "selected_ledger_id": "family", "can_write": True, "csrf_field": ""})
    page = web._render_recurring(request=_request("/web/recurring"), db=object(), selected_id="family", options=[])
    form = _form(page.body.decode(), "/web/recurring/create")
    selector = _currency_selector(form)
    assert 'value="USD"' in selector and 'value="JPY"' in selector
    assert _fields(form)["ledger_id"] == "family"


def test_actual_unpaid_period_offers_manual_payment_with_original_ledger_series_and_period(monkeypatch):
    from app.models import RecurringItem
    from app.routes import web_recurring_occurrences as web
    from app.schemas._recurring_occurrence import RecurringOccurrenceResponse

    item = RecurringItem(id=7, public_id=SERIES_ID, tenant_id="family", merchant_name="Cloud subscription",
        home_currency_code="USD", baseline_amount_cents=2000, row_version=3, status="active")
    occurrence = RecurringOccurrenceResponse(series_public_id=SERIES_ID, period="2026-09", series_row_version=3,
        row_version=0, state="unfulfilled", home_currency_code="USD", planned_amount_cents=2000,
        reserved_amount_cents=2000, expense_public_id=None, expense_id=None, expense_row_version=None,
        paid_amount_cents=None, next_due_date=None)
    monkeypatch.setattr(web, "_list_ledger_options", lambda *a: [])
    monkeypatch.setattr(web, "_resolve_selected_ledger_id", lambda *a, **kw: "family")
    monkeypatch.setattr(web, "get_recurring_item", lambda *a, **kw: item)
    monkeypatch.setattr(web, "occurrence_response", lambda *a, **kw: occurrence)
    monkeypatch.setattr(web, "find_recurring_payments", lambda *a, **kw: [])
    monkeypatch.setattr(web, "_base_ctx", lambda request, **kw: {
        "request": request, "selected_ledger_id": "family", "can_write": True, "csrf_field": ""})
    page = web._page(_request(f"/web/recurring/{SERIES_ID}/occurrence"), object(),
        public_id=SERIES_ID, ledger_id="family", month="2026-09")
    href = _payment_link(page.body.decode())
    assert parse_qs(urlsplit(href).query) == {"ledger_id": ["family"], "return_to": ["recurring_occurrence"],
        "return_recurring_public_id": [SERIES_ID], "return_month": ["2026-09"]}
    from app.models import Expense

    rejected = Expense(id=41, public_id="rejected-payment", tenant_id="family", status="rejected", row_version=9,
        home_currency_code="CNY", original_currency_code="USD", original_amount_minor=2200,
        merchant="Saved subscription", expense_time=datetime(2026, 9, 5, tzinfo=UTC))
    monkeypatch.setattr(web, "resolve_expense", lambda *a: rejected)
    recovery = web._page(_request(f"/web/recurring/{SERIES_ID}/occurrence"), object(),
        public_id=SERIES_ID, ledger_id="family", month="2026-09", payment_id="41")
    undo = _fields(_form(recovery.body.decode(), "/web/expenses/41/undo"))
    assert (undo["expected_row_version"], undo["return_month"], undo["return_payment_expense_id"]) == ("9", "2026-09", "41")
    assert 'name="action" value="link"' not in recovery.body.decode()


def test_existing_expense_return_adapter_retains_exact_period_without_accepting_external_paths():
    from app.routes._web_expense_return_context import edit_context_params, return_href

    origin = {"return_to": "recurring_occurrence", "return_recurring_public_id": SERIES_ID,
        "return_month": "2026-09"}
    assert edit_context_params(**origin) == origin
    target = urlsplit(return_href(ledger_id="family", default_path="/web/pending", **origin))
    assert target.path == f"/web/recurring/{SERIES_ID}/occurrence"
    assert parse_qs(target.query) == {"ledger_id": ["family"], "month": ["2026-09"]}
    unsafe = return_href(ledger_id="family", default_path="/web/pending",
        **{**origin, "return_recurring_public_id": "//outside.invalid/escape"})
    assert urlsplit(unsafe).path == "/web/pending" and not urlsplit(unsafe).netloc
    invalid_month = return_href(ledger_id="family", default_path="/web/pending",
        **{**origin, "return_month": "2026-13"})
    assert urlsplit(invalid_month).path == "/web/pending"


def test_manual_entry_reads_original_series_money_and_preserves_origin_on_validation(monkeypatch):
    from app.models import RecurringItem
    from app.routes import web_expense_create as web
    from app.routes._web_expense_return_context import ExpenseReturnContext
    from app.services.currency_common import currency_input_metadata

    monkeypatch.setattr(web, "_list_ledger_options", lambda *a: [])
    monkeypatch.setattr(web, "_resolve_selected_ledger_id", lambda *a, **kw: "family")
    monkeypatch.setattr(web, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(web, "_sidebar_counts", lambda *a: (0, 0))
    monkeypatch.setattr(web, "list_ledger_category_options", lambda *a, **kw: [])
    monkeypatch.setattr(web, "manual_draft_scope", lambda *a: {"ledgerId": "family"})
    monkeypatch.setattr(web, "_session_writer_auth", lambda *a: SimpleNamespace(ledger_id="family", device_public_id="browser"))
    monkeypatch.setattr(web, "_base_ctx", lambda request, **kw: {
        "request": request, "home_currency_code": "CNY", "currency_input": currency_input_metadata("CNY"),
        "selected_ledger_id": "family", "can_write": True, "csrf_field": ""})
    reads = []
    item = RecurringItem(merchant_name="Cloud subscription", home_currency_code="JPY", baseline_amount_cents=1250)

    def series(db, **kw):
        reads.append(kw)
        return item

    monkeypatch.setattr(web, "get_recurring_item", series)
    origin = ExpenseReturnContext(return_to="recurring_occurrence", return_recurring_public_id=SERIES_ID, return_month="2026-08")
    db = SimpleNamespace(rollback=lambda: None)
    request = _request("/web/expenses/new")
    page = web.web_manual_expense_new(request, ledger_id="family", return_context=origin, db=db)
    form = _fields(_form(page.body.decode(), "/web/expenses/new"))
    assert reads == [{"tenant_id": "family", "public_id": SERIES_ID}]
    assert (form["currency_code"], form["amount_major"], form["home_currency_code"]) == ("JPY", "1250", "CNY")
    failed = web.web_manual_expense_create(request, ledger_id="family", expected_device_public_id="browser",
        client_ref=form["client_ref"], amount_major="bad", currency_code="JPY", home_currency_code="CNY",
        merchant="My subscription", category="其他", spent_at="2026-09-05T12:00", note="original",
        return_context=origin, db=db)
    assert failed.status_code == 422
    retained = _fields(_form(failed.body.decode(), "/web/expenses/new"))
    assert (retained["client_ref"], retained["currency_code"], retained["amount_major"], retained["return_month"]) == (
        form["client_ref"], "JPY", "bad", "2026-08")
    ordinary = web.web_manual_expense_new(request, ledger_id="family", return_context=ExpenseReturnContext(), db=db)
    assert len(reads) == 1 and 'name="return_to" value=""' in ordinary.body.decode()
    refused_currency = web.web_manual_expense_create(request, ledger_id="family", expected_device_public_id="browser",
        client_ref=form["client_ref"], amount_major="1250", currency_code="", home_currency_code="CNY",
        merchant="My subscription", category="", spent_at="", note="original", return_context=origin, db=db)
    original_fields = _fields(_form(refused_currency.body.decode(), "/web/expenses/new"))
    assert (original_fields["currency_code"], original_fields["spent_at"], original_fields["category"]) == ("", "", "")
    # Unknown legacy currency never interprets its old minor amount as today's home currency.
    item.home_currency_code = None
    needs_currency = web.web_manual_expense_new(request, ledger_id="family", return_context=origin, db=db)
    unknown = _fields(_form(needs_currency.body.decode(), "/web/expenses/new"))
    assert (unknown["merchant"], unknown["currency_code"], unknown["amount_major"], unknown["home_currency_code"]) == (
        "Cloud subscription", "", "", "CNY")
    assert unknown["return_month"] == "2026-08"


def test_cross_month_focus_uses_exact_saved_bill_and_existing_link_eligibility(monkeypatch):
    from app.models import Expense
    from app.routes import web_recurring_occurrences as web

    payment = Expense(id=41, public_id="saved-payment", tenant_id="family", status="pending", row_version=8,
        home_currency_code="CNY", original_currency_code="USD", original_amount_minor=2200,
        merchant="Saved subscription", expense_time=datetime(2026, 9, 5, tzinfo=UTC))
    reads = []

    def resolve(db, ledger_id, expense_id):
        reads.append((ledger_id, expense_id))
        return payment if ledger_id == "family" and expense_id == 41 else None

    eligible_queries = []

    def eligible(db, **kw):
        eligible_queries.append(kw)
        return [payment] if payment.status == "confirmed" else []

    monkeypatch.setattr(web, "resolve_expense", resolve)
    monkeypatch.setattr(web, "find_recurring_payments", eligible)
    origin = {"return_to": "recurring_occurrence", "return_recurring_public_id": SERIES_ID, "return_month": "2026-08"}
    focused = web._focused_payment(object(), ledger_id="family", payment_id="41", origin=origin)
    assert focused["amount"] == "22.00" and not focused["eligible"]
    assert parse_qs(urlsplit(focused["href"]).query)["return_month"] == ["2026-08"]
    assert eligible_queries == [{"tenant_id": "family", "month": None, "query": "", "expense_id": 41}]
    payment.status = "confirmed"
    assert web._focused_payment(object(), ledger_id="family", payment_id="41", origin=origin)["eligible"]
    assert web._focused_payment(object(), ledger_id="another", payment_id="41", origin=origin) is None
    assert web._focused_payment(object(), ledger_id="family", payment_id="999999999999", origin=origin) is None
    assert reads[-1] == ("another", 41)


def test_rejected_payment_and_undo_return_to_original_period_with_original_revision(monkeypatch):
    from app.routes import web_expense_lifecycle as web
    from app.routes._web_expense_return_context import ExpenseReturnContext

    origin = ExpenseReturnContext(return_to="recurring_occurrence", return_recurring_public_id=SERIES_ID,
        return_month="2026-08", return_payment_expense_id="41")
    monkeypatch.setattr(web, "_list_ledger_options", lambda *a: [])
    monkeypatch.setattr(web, "_resolve_selected_ledger_id", lambda *a, **kw: "family")
    monkeypatch.setattr(web, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(web, "confirmed_write_guard_response", lambda *a, **kw: None)
    calls = []
    monkeypatch.setattr(web, "reject_expense", lambda *a, **kw: calls.append(("reject", a[1:], kw)))
    monkeypatch.setattr(web, "undo_reject_expense", lambda *a, **kw: calls.append(("undo", a[1:], kw)))
    request, db = _request("/web/expenses/41/reject"), SimpleNamespace(rollback=lambda: None)
    rejected = web.web_reject(request, 41, ledger_id="family", expected_row_version="8",
        return_context=origin, fragment=0, db=db)
    target = urlsplit(rejected.headers["location"])
    assert target.path == f"/web/recurring/{SERIES_ID}/occurrence"
    assert parse_qs(target.query)["month"] == ["2026-08"]
    assert parse_qs(target.query)["payment_id"] == ["41"]
    restored = web.web_expense_undo(request, 41, ledger_id="family", expected_row_version="9",
        return_context=origin, db=db)
    restored_target = urlsplit(restored.headers["location"])
    assert restored_target.path == target.path and parse_qs(restored_target.query)["month"] == ["2026-08"]
    assert calls == [("reject", (41, "family"), {"expected_row_version": 8}), ("undo", (41, "family", 9), {})]
