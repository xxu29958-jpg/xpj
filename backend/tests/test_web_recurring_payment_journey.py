"""An overseas commitment becomes paid only after an explicitly reviewed bill is linked."""

import re
from datetime import date
from html import unescape
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Expense, RecurringItem, RecurringOccurrenceRevision
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.schemas import ExchangeRateRequest
from app.services.budget_advisor_service import read_budget_inputs
from app.services.exchange_rate_service import set_exchange_rate_idempotently
from app.services.recurring_occurrence_query import occurrence_response
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests.test_web_recurring_payment_surface import _currency_selector, _fields, _form, _payment_link

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web(monkeypatch):
    # Exercise saved pending bills without an unrelated executor racing this review.
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *a, **kw: None)
    yield from installed_web_setup()


def _period_link(html, series_id):
    path = f"/web/recurring/{series_id}/occurrence"
    for href in re.findall(r'href="([^"]+)"', html):
        if urlsplit(unescape(href)).path == path:
            return unescape(href)
    raise AssertionError("The saved bill lost its original recurring payment task")


def _assert_period(target, *, ledger, series_id, expense_id):
    parsed = urlsplit(target)
    assert not parsed.netloc and parsed.path == f"/web/recurring/{series_id}/occurrence"
    query = parse_qs(parsed.query)
    assert query["ledger_id"] == [ledger] and query["month"] == ["2026-08"]
    assert query["payment_id"] == [str(expense_id)]


def _state(ledger, series_id):
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.tenant_id == ledger, RecurringItem.public_id == series_id))
        occurrence = occurrence_response(db, item=item, period=date(2026, 8, 1))
        august = read_budget_inputs(db, tenant_id=ledger, month="2026-08", home_currency_code="CNY").breakdown
        september = read_budget_inputs(db, tenant_id=ledger, month="2026-09", home_currency_code="CNY").breakdown
        return occurrence, august, september


def _seed_commitment_valuation_rates(installed_web):
    # A closed month's commitment uses month-end valuation; the current month uses today.
    # Neither quote grants coverage to the separate September 5 payment.
    today = now_utc().astimezone(accounting_zone()).date()
    with SessionLocal() as db:
        for day in (min(today, date(2026, 8, 31)), min(today, date(2026, 9, 30))):
            set_exchange_rate_idempotently(db, tenant_id=installed_web.shared_ledger_id,
                actor_account_id=installed_web.installation_account_id, idempotency_key=str(uuid4()),
                payload=ExchangeRateRequest(currency_code="USD", home_currency_code="CNY", rate_date=day,
                    rate_to_cny="7", expected_row_version=0))


def test_native_foreign_commitment_records_later_payment_and_returns_for_explicit_original_period_link(installed_web):
    browser, ledger = installed_web.browser, installed_web.shared_ledger_id
    session = _connect_local_session(installed_web, next_url="/web/recurring")

    def get(path):
        response = browser.get(path, headers={"Cookie": f"{SESSION_COOKIE_NAME}={session}"}, follow_redirects=False)
        assert response.status_code == 200, response.text
        return response

    def post(path, fields):
        cookie = f"{SESSION_COOKIE_NAME}={session}; {CSRF_COOKIE_NAME}={browser.cookies.get(CSRF_COOKIE_NAME)}"
        return browser.post(path, data=fields, headers={"Cookie": cookie, "Origin": "http://127.0.0.1:8000"},
            follow_redirects=False)

    _seed_commitment_valuation_rates(installed_web)
    create_form = _form(get(f"/web/recurring?ledger_id={ledger}").text, "/web/recurring/create")
    assert 'value="USD"' in _currency_selector(create_form)
    fields = {**_fields(create_form), "home_currency_code": "USD", "merchant": "Overseas subscription",
        "baseline_amount_yuan": "20.00", "next_expected_date": "2026-08-05"}
    created = post("/web/recurring/create", fields)
    assert created.status_code == 303, created.text
    assert post("/web/recurring/create", fields).status_code == 303
    with SessionLocal() as db:
        series = db.scalars(select(RecurringItem).where(RecurringItem.tenant_id == ledger)).one()
        assert (series.home_currency_code, series.baseline_amount_cents) == ("USD", 2000)
        series_id = series.public_id
    occurrence, august, september = _state(ledger, series_id)
    assert occurrence.state == "unfulfilled" and august.fixed_expenses_cents == 14000
    assert september.spent_amount_cents == 0
    occurrence_path = f"/web/recurring/{series_id}/occurrence"
    entry = _payment_link(get(f"{occurrence_path}?ledger_id={ledger}&month=2026-08").text)
    raw = _fields(_form(get(entry).text, "/web/expenses/new"))
    origin = {"return_to": "recurring_occurrence", "return_recurring_public_id": series_id, "return_month": "2026-08"}
    assert all(raw[key] == value for key, value in origin.items())
    assert (raw["ledger_id"], raw["currency_code"], raw["amount_major"], raw["merchant"]) == (
        ledger, "USD", "20.00", "Overseas subscription")
    proposed = {**raw, "amount_major": "invalid", "spent_at": "2026-09-05T12:00",
        "category": "订阅", "note": "August obligation paid in September"}
    refused = post("/web/expenses/new", proposed)
    assert refused.status_code == 422, refused.text
    retained = _fields(_form(refused.text, "/web/expenses/new"))
    assert all(retained[key] == proposed[key] for key in (*origin, "ledger_id", "client_ref", "spent_at", "note"))
    submitted = {**retained, "amount_major": "22.00"}
    accepted = post("/web/expenses/new", submitted)
    assert accepted.status_code == 303, accepted.text
    replay = post("/web/expenses/new", submitted)
    assert replay.status_code == 303 and replay.headers["location"] == accepted.headers["location"]
    with SessionLocal() as db:
        bill = db.scalars(select(Expense).where(Expense.tenant_id == ledger)).one()
        assert (bill.status, bill.original_currency_code, bill.original_amount_minor, bill.amount_cents) == ("pending", "USD", 2200, None)
        expense_id, version = bill.id, bill.row_version
    page = get(accepted.headers["location"])
    pending_return = _period_link(page.text, series_id)
    _assert_period(pending_return, ledger=ledger, series_id=series_id, expense_id=expense_id)
    pending_period = get(pending_return)
    assert f"/web/expenses/{expense_id}/edit" in pending_period.text
    assert 'name="action" value="link"' not in pending_period.text
    save_path = f"/web/expenses/{expense_id}/save"
    draft = _fields(_form(page.text, save_path))
    assert all(draft[key] == value for key, value in origin.items())
    assert draft["return_payment_expense_id"] == str(expense_id)
    rejected = post(f"/web/expenses/{expense_id}/reject", {**draft, "expected_row_version": str(version)})
    assert rejected.status_code == 303, rejected.text
    _assert_period(rejected.headers["location"], ledger=ledger, series_id=series_id, expense_id=expense_id)
    rejected_page = get(rejected.headers["location"])
    undo_path = f"/web/expenses/{expense_id}/undo"
    undo_fields = _fields(_form(rejected_page.text, undo_path))
    assert int(undo_fields["expected_row_version"]) > version
    assert _state(ledger, series_id)[0].state == "unfulfilled"
    restored = post(undo_path, undo_fields)
    assert restored.status_code == 303, restored.text
    _assert_period(restored.headers["location"], ledger=ledger, series_id=series_id, expense_id=expense_id)
    review_return = get(restored.headers["location"])
    review_href = next(unescape(href) for href in re.findall(r'href="([^"]+)"', review_return.text)
        if urlsplit(unescape(href)).path == f"/web/expenses/{expense_id}/edit")
    page = get(review_href)
    draft = _fields(_form(page.text, save_path))
    assert int(draft["expected_row_version"]) > int(undo_fields["expected_row_version"])
    status_page = post(f"/web/expenses/{expense_id}/fx-status", draft)
    assert status_page.status_code == 200, status_page.text
    status_fields = _fields(_form(status_page.text, save_path))
    assert all(status_fields[key] == draft[key] for key in (*origin, "return_payment_expense_id", "idempotency_key", "expected_row_version"))
    saved = post(save_path, {**status_fields, "manual_exchange_rate": "8"})
    assert saved.status_code == 303, saved.text
    review = get(saved.headers["location"])
    review_fields = _fields(_form(review.text, save_path))
    assert int(review_fields["expected_row_version"]) > version
    assert all(review_fields[key] == value for key, value in origin.items())
    assert _state(ledger, series_id)[0].state == "unfulfilled"
    confirm_path = f"/web/expenses/{expense_id}/confirm"
    assert f'formaction="{confirm_path}"' in review.text
    confirmed = post(confirm_path, review_fields)
    assert confirmed.status_code == 303, confirmed.text
    _assert_period(confirmed.headers["location"], ledger=ledger, series_id=series_id, expense_id=expense_id)
    current_period = get(confirmed.headers["location"])
    assert _state(ledger, series_id)[0].state == "unfulfilled"
    choice = _fields(_form(current_period.text, occurrence_path))
    assert choice["action"] == "link" and choice["month"] == "2026-08"
    linked = post(occurrence_path, choice)
    assert linked.status_code == 303, linked.text
    assert post(occurrence_path, choice).status_code == 303
    occurrence, august, september = _state(ledger, series_id)
    assert occurrence.state == "fulfilled" and occurrence.expense_id == expense_id
    assert august.fixed_expenses_cents == 0 and august.spent_amount_cents == 0
    assert september.spent_amount_cents == 17600
    fulfilled_page = get(linked.headers["location"])
    fact_link = next(unescape(href) for href in re.findall(r'href="([^"]+)"', fulfilled_page.text)
        if urlsplit(unescape(href)).path == f"/web/expenses/{expense_id}/edit")
    fact_page = get(fact_link)
    _assert_period(_period_link(fact_page.text, series_id), ledger=ledger, series_id=series_id, expense_id=expense_id)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RecurringOccurrenceRevision).where(
            RecurringOccurrenceRevision.tenant_id == ledger)) == 1
        assert db.scalar(select(func.count()).select_from(Expense).where(Expense.tenant_id == ledger)) == 1
