"""Existing Web entry and return adapters must expose one period's payment task."""

import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from fastapi import Request

SERIES_ID = "6dce3575-fb65-4df5-bb93-7bb270e8df9b"


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
