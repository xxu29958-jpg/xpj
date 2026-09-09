"""Native correction forms keep the original command across a separate FX save."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ExchangeRate, Expense, ExpenseRevision, LedgerMember
from app.services.currency_binding_service import require_runtime_home_currency_code
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._runtime_protocol import current_protocol_headers
from tests._web_native_form_support import hidden_post_forms

OLD_DATE = "2025-12-02"
NEW_DATE = "2025-12-03"
RETURN = {"return_to": "reports", "return_month": "2025-12", "return_home_currency_code": "USD",
    "return_granularity": "week", "return_ranking_metric": "count", "return_merchant_category": "餐饮"}


class _NativeForm(HTMLParser):
    """Successful controls, including repeated rows and the clicked submit button."""

    def __init__(self, html, action):
        super().__init__()
        self.action = action
        self.fields = {}
        self.buttons = []
        self.active = False
        self.textarea = None
        self.select = None
        self.options = []
        self.feed(html)
        assert self.fields, f"Missing native form: {action}"
        # Reuse the shared hidden-field reader for the original command identity.
        hidden = hidden_post_forms(html)[action]
        for name in ("csrf_token", "expected_row_version", "idempotency_key"):
            assert self.one(name) == hidden[name]

    def one(self, name):
        values = self.fields[name]
        assert len(values) == 1, (name, values)
        return values[0]

    def set(self, name, value):
        assert name in self.fields, f"The actual form does not expose {name}"
        self.fields[name] = [value] if isinstance(value, str) else value

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.active = attrs.get("action") == self.action and attrs.get("method", "").lower() == "post"
        if not self.active or "disabled" in attrs:
            return
        name = attrs.get("name")
        if tag == "input" and name:
            self._record_input(name, attrs)
            return
        if tag == "textarea" and name:
            self.textarea = name
            self.fields.setdefault(name, []).append("")
            return
        if tag == "select" and name:
            self.select, self.options = name, []
            return
        if tag == "option" and self.select:
            self.options.append((attrs.get("value", ""), "selected" in attrs))
            return
        if tag == "button" and attrs.get("type", "submit") == "submit":
            self.buttons.append(attrs)

    def _record_input(self, name, attrs):
        kind = attrs.get("type", "text")
        if kind in {"submit", "button", "reset"} or (kind in {"checkbox", "radio"} and "checked" not in attrs):
            return
        self.fields.setdefault(name, []).append(attrs.get("value", ""))

    def handle_data(self, data):
        if self.active and self.textarea:
            self.fields[self.textarea][-1] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False
        elif tag == "textarea":
            self.textarea = None
        elif tag == "select" and self.select:
            selected = [value for value, chosen in self.options if chosen]
            self.fields.setdefault(self.select, []).append(selected[-1] if selected else self.options[0][0])
            self.select, self.options = None, []

    def post(self, client, *, rate=False, review=False):
        fields = deepcopy(self.fields)
        action = self.action
        if rate:
            candidates = [button for button in self.buttons
                if button.get("formaction", "").endswith("/correction-rate")
                and (button.get("name") == "fx_review_latest") == review]
            assert len(candidates) == 1, self.buttons
            button = candidates[0]
            action = button["formaction"]
            if button.get("name"):
                fields[button["name"]] = [button["value"]]
        return client.post(action, data=fields, headers={"Origin": str(client.base_url).rstrip("/")},
            follow_redirects=False)


def _read_form(response, expense_id):
    return _NativeForm(response.text, f"/web/expenses/{expense_id}/corrections")


def _put_rate(client, headers, rate_date, value, version=0):
    response = client.put(f"/api/exchange-rates/JPY/{rate_date}",
        headers={**headers, "Idempotency-Key": str(uuid4())}, json={
            "currency_code": "JPY", "home_currency_code": "USD", "rate_date": rate_date,
            "rate_to_cny": value, "source": "manual", "expected_row_version": version})
    assert response.status_code == 200, response.text
    return response.json()


def _historical_expense(client, headers, ledger="owner"):
    _put_rate(client, headers, OLD_DATE, "0.05")
    response = client.post("/api/expenses/manual", headers=headers, json={
        "client_ref": str(uuid4()), "home_currency_code": "USD", "original_currency": "JPY",
        "original_amount": "12", "expense_time": f"{OLD_DATE}T12:00:00Z",
        "merchant": "历史日元账单", "category": "餐饮"})
    assert response.status_code == 200, response.text
    fact = response.json()
    assert (fact["status"], fact["home_currency"], fact["original_currency_code"],
        fact["original_amount_minor"], fact["amount_cents"]) == ("confirmed", "USD", "JPY", 12, 60)
    with SessionLocal() as db:
        assert require_runtime_home_currency_code(db) == "CNY"
    page = client.get(f"/web/expenses/{fact['id']}/correct", params={"ledger_id": ledger, **RETURN})
    assert page.status_code == 200, page.text
    form = _read_form(page, fact["id"])
    assert form.one("original_currency") == "JPY"
    form.set("reason", "  核对旅行小票日期  ")
    form.set("expense_time", f"{NEW_DATE}T12:00")
    form.set("note", "原始备注 & <保留>\n第二行")
    return fact, form


def _snapshot(expense_id):
    with SessionLocal() as db:
        fact = db.get(Expense, expense_id)
        return (fact.row_version, fact.fact_revision, fact.home_currency_code,
            fact.original_currency_code, fact.original_amount_minor, fact.amount_cents,
            fact.expense_time, fact.note, fact.exchange_rate_date,
            db.scalar(select(func.count()).select_from(ExpenseRevision).where(ExpenseRevision.expense_id == expense_id)))


def _assert_original(form, original):
    expected = {key: values for key, values in original.fields.items()
        if key != "csrf_token" and not key.startswith("fx_")}
    actual = {key: values for key, values in form.fields.items()
        if key != "csrf_token" and not key.startswith("fx_")}
    assert actual == expected


def _missing_rate(client, fact, original):
    before = _snapshot(fact["id"])
    refused = original.post(client)
    assert refused.status_code == 409, refused.text
    recovery = _read_form(refused, fact["id"])
    _assert_original(recovery, original)
    assert tuple(recovery.one(f"fx_{name}") for name in (
        "currency_code", "home_currency_code", "rate_date", "expected_row_version")) == (
        "JPY", "USD", NEW_DATE, "0")
    assert recovery.one("fx_idempotency_key") != original.one("idempotency_key")
    assert _snapshot(fact["id"]) == before
    return recovery


def test_native_rate_save_preserves_complete_correction_then_explicit_save_updates_fact(web_client, identity):
    fact, original = _historical_expense(web_client, identity.app_headers)
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember.id).where(LedgerMember.ledger_id == "owner",
            LedgerMember.disabled_at.is_(None)).limit(1))
        assert member is not None
    original.fields["item_name"][:2] = ["车票", "午餐"]
    original.fields["item_amount_yuan"][:2] = ["0.30", "0.66"]
    original.fields["split_member_id"][0] = str(member)
    original.fields["split_amount_yuan"][0] = "0.20"
    original.fields["split_note"][0] = "原拆账意图"
    recovery = _missing_rate(web_client, fact, original)
    before = _snapshot(fact["id"])
    recovery.set("fx_rate_to_cny", "0.08")
    accepted = recovery.post(web_client, rate=True)
    assert accepted.status_code == 200, accepted.text
    returned = _read_form(accepted, fact["id"])
    _assert_original(returned, original)
    assert _snapshot(fact["id"]) == before  # A rate command cannot commit the correction.
    replay = recovery.post(web_client, rate=True)
    assert replay.status_code == 200, replay.text
    with SessionLocal() as db:
        rate = db.scalar(select(ExchangeRate).where(ExchangeRate.rate_date == date.fromisoformat(NEW_DATE)))
        assert (rate.home_currency_code, rate.rate_to_cny, rate.row_version) == ("USD", Decimal("0.08"), 1)
    saved = returned.post(web_client)
    assert saved.status_code == 303, saved.text
    assert parse_qs(urlparse(saved.headers["location"]).query).items() >= {
        key: [value] for key, value in RETURN.items()}.items()
    current = web_client.get(f"/api/expenses/{fact['id']}", headers=identity.app_headers).json()
    assert (current["original_amount_minor"], current["original_currency_code"],
        current["home_currency"], current["amount_cents"], current["exchange_rate_date"]) == (
        12, "JPY", "USD", 96, NEW_DATE)
    items = web_client.get(f"/api/expenses/{fact['id']}/items", headers=identity.app_headers).json()["items"]
    splits = web_client.get(f"/api/expenses/{fact['id']}/splits", headers=identity.app_headers).json()["splits"]
    assert [(row["name"], row["amount_cents"]) for row in items] == [("车票", 30), ("午餐", 66)]
    assert [(row["amount_cents"], row["note"]) for row in splits] == [(20, "原拆账意图")]


def test_rate_conflict_review_only_replaces_rate_baseline_and_peer_expense_still_conflicts(web_client, identity):
    fact, original = _historical_expense(web_client, identity.app_headers)
    recovery = _missing_rate(web_client, fact, original)
    recovery.set("fx_rate_to_cny", "0.08")
    _put_rate(web_client, identity.app_headers, NEW_DATE, "0.07")
    peer = web_client.post(f"/api/expenses/{fact['id']}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
            "expected_row_version": fact["row_version"], "reason": "另一端已核对", "note": "另一端的新事实"})
    assert peer.status_code == 201, peer.text
    current = _snapshot(fact["id"])
    refused = recovery.post(web_client, rate=True)
    assert refused.status_code == 409, refused.text
    blocked = _read_form(refused, fact["id"])
    _assert_original(blocked, original)
    assert blocked.one("fx_expected_row_version") == "0"
    assert blocked.one("fx_idempotency_key") == recovery.one("fx_idempotency_key")
    reviewed_response = blocked.post(web_client, rate=True, review=True)
    assert reviewed_response.status_code == 200, reviewed_response.text
    reviewed = _read_form(reviewed_response, fact["id"])
    _assert_original(reviewed, original)
    assert reviewed.one("fx_rate_to_cny") == "0.08"
    assert reviewed.one("fx_expected_row_version") == "1"
    assert reviewed.one("fx_idempotency_key") != blocked.one("fx_idempotency_key")
    assert _snapshot(fact["id"]) == current
    rate_saved = reviewed.post(web_client, rate=True)
    assert rate_saved.status_code == 200, rate_saved.text
    returned = _read_form(rate_saved, fact["id"])
    _assert_original(returned, original)
    assert _snapshot(fact["id"]) == current
    conflict = returned.post(web_client)
    assert conflict.status_code == 409, conflict.text
    assert "另一端的新事实" in conflict.text
    assert _snapshot(fact["id"]) == current


def test_rate_validation_preserves_raw_child_rows_return_fields_and_both_original_tokens(web_client, identity):
    fact, original = _historical_expense(web_client, identity.app_headers)
    recovery = _missing_rate(web_client, fact, original)
    recovery.fields["item_name"][:2] = ["  待核对 A  ", "B & <C>"]
    recovery.fields["item_amount_yuan"][:2] = ["1..2", "not-an-amount"]
    recovery.fields["split_member_id"][:2] = ["unknown-member", "another-unknown"]
    recovery.fields["split_amount_yuan"][:2] = [" 00x ", "--1"]
    recovery.fields["split_note"][:2] = ["第一行原稿", "第二行原稿"]
    recovery.set("expected_row_version", f"000{original.one('expected_row_version')}")
    recovery.set("fx_rate_to_cny", " 0..08 ")
    before = _snapshot(fact["id"])
    invalid = recovery.post(web_client, rate=True)
    assert invalid.status_code == 422, invalid.text
    retained = _read_form(invalid, fact["id"])
    _assert_original(retained, recovery)
    assert {name: values for name, values in retained.fields.items() if name.startswith("fx_")} == {
        name: values for name, values in recovery.fields.items() if name.startswith("fx_")}
    retained.set("fx_rate_to_cny", "0.08")
    accepted = retained.post(web_client, rate=True)
    assert accepted.status_code == 200, accepted.text
    _assert_original(_read_form(accepted, fact["id"]), recovery)
    assert _snapshot(fact["id"]) == before


@pytest.mark.parametrize("missing_field", ["idempotency_key", "expected_row_version"])
@pytest.mark.parametrize("absent", [False, True], ids=["blank", "omitted"])
def test_rate_save_cannot_supply_missing_original_correction_identity(web_client, identity, missing_field, absent):
    fact, original = _historical_expense(web_client, identity.app_headers)
    recovery = _missing_rate(web_client, fact, original)
    recovery.set("fx_rate_to_cny", "0.08")
    recovery.set(missing_field, "")
    before = _snapshot(fact["id"])
    # The recovery page must explicitly retain an unknown identity, not mint one.
    expected = deepcopy(recovery)
    if absent:
        recovery.fields.pop(missing_field)
    saved_rate = recovery.post(web_client, rate=True)
    assert saved_rate.status_code == 200, saved_rate.text
    returned = _read_form(saved_rate, fact["id"])
    _assert_original(returned, expected)
    assert returned.one(missing_field) == ""
    assert _snapshot(fact["id"]) == before
    with SessionLocal() as db:
        rate = db.scalar(select(ExchangeRate).where(ExchangeRate.rate_date == date.fromisoformat(NEW_DATE)))
        assert (rate.rate_to_cny, rate.row_version) == (Decimal("0.08"), 1)
    for _ in range(2):
        refused = returned.post(web_client)
        assert refused.status_code == 422, refused.text
        returned = _read_form(refused, fact["id"])
        _assert_original(returned, expected)
        assert returned.one(missing_field) == ""
        assert _snapshot(fact["id"]) == before


@pytest.fixture
def installed_browser():
    yield from installed_web_setup()


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_native_ledger_switch_preserves_both_forms_without_retargeting_or_writing(installed_browser):
    installed = installed_browser
    token = _connect_local_session(installed)
    headers = current_protocol_headers({"Authorization": f"Bearer {token}"})
    client = installed.browser
    fact, original = _historical_expense(client, headers, installed.shared_ledger_id)
    recovery = _missing_rate(client, fact, original)
    recovery.set("fx_rate_to_cny", "0.08")
    recovery.fields["item_name"][:2] = ["第一行原稿", "第二行原稿"]
    before = _snapshot(fact["id"])
    switched = client.post("/web/auth/ledgers", data={
        "csrf_token": recovery.one("csrf_token"), "ledger_id": "owner"},
        headers={"Origin": str(client.base_url).rstrip("/")}, follow_redirects=False)
    assert switched.status_code == 303, switched.text
    for rate in (True, False):
        refused = recovery.post(client, rate=rate)
        assert refused.status_code == 409, refused.text
        assert "切回原账本" in refused.text
        action = f"/web/expenses/{fact['id']}/correction-rate" if rate else original.action
        retained = _NativeForm(refused.text, action)
        _assert_original(retained, recovery)
        assert {key: values for key, values in retained.fields.items() if key.startswith("fx_")} == {
            key: values for key, values in recovery.fields.items() if key.startswith("fx_")}
        assert retained.one("ledger_id") == installed.shared_ledger_id
        assert _snapshot(fact["id"]) == before
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExchangeRate).where(
            ExchangeRate.rate_date == date.fromisoformat(NEW_DATE))) == 0
        assert db.scalar(select(func.count()).select_from(Expense).where(Expense.tenant_id == "owner")) == 0
