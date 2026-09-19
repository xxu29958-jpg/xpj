"""Native calendar evidence through the installed browser's real HTTP commands."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Expense
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web():
    yield from installed_web_setup()


def open_manual(installed):
    token = _connect_local_session(installed, next_url="/web/expenses/new")
    cookie = f"{SESSION_COOKIE_NAME}={token}"
    page = installed.browser.get("/web/expenses/new", headers={"Cookie": cookie})
    assert page.status_code == 200, page.text
    fields = hidden_post_forms(page.text)["/web/expenses/new"]
    fields.update(amount_major="23.45", currency_code="CNY", merchant="时间证据", category="餐饮", note="")
    headers = {"Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000"}
    return fields, headers


def test_native_date_only_create_replay_has_one_fact_and_original_ack(installed_web):
    fields, headers = open_manual(installed_web)
    fields.update(time_precision="date_only", spent_at="", user_local_date="2026-08-31",
        source_timezone="Asia/Shanghai", source_utc_offset_seconds="", accounting_date="2026-08-31")
    first = installed_web.browser.post("/web/expenses/new", data=fields, headers=headers, follow_redirects=False)
    assert first.status_code == 303, first.text
    replay = installed_web.browser.post("/web/expenses/new", data=fields, headers=headers, follow_redirects=False)
    assert replay.status_code == 303 and replay.headers["location"] == first.headers["location"]
    with SessionLocal() as db:
        query = select(Expense).where(Expense.tenant_id == installed_web.shared_ledger_id,
            Expense.merchant == "时间证据")
        expense = db.scalar(query)
        assert expense.expense_time is None and expense.time_precision == "date_only"
        assert expense.accounting_date == expense.user_local_date == date(2026, 8, 31)
        assert expense.amount_cents == 2345 and expense.status == "confirmed"
        assert db.scalar(select(func.count()).select_from(query.subquery())) == 1
    detail = installed_web.browser.get(first.headers["location"], headers=headers)
    assert detail.status_code == 200, detail.text
    assert "账务日期 2026-08-31" in detail.text and "发生时刻 未记录" in detail.text
    assert "data-manual-draft-ack=" in detail.text


def test_native_gap_then_fold_keeps_key_and_only_explicit_choice_creates(installed_web):
    fields, headers = open_manual(installed_web)
    fields.update(time_precision="instant", spent_at="2026-03-08T02:30",
        source_timezone="America/New_York", source_utc_offset_seconds="", accounting_date="")
    gap = installed_web.browser.post("/web/expenses/new", data=fields, headers=headers, follow_redirects=False)
    assert gap.status_code == 422 and "不存在" in gap.text
    retained = hidden_post_forms(gap.text)["/web/expenses/new"]
    assert retained["client_ref"] == fields["client_ref"]
    assert retained["spent_at"] == fields["spent_at"]
    fields["spent_at"] = "2026-11-01T01:30"
    fold = installed_web.browser.post("/web/expenses/new", data=fields, headers=headers, follow_redirects=False)
    assert fold.status_code == 422 and 'value="-18000"' in fold.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense).where(
            Expense.tenant_id == installed_web.shared_ledger_id, Expense.merchant == "时间证据")) == 0
    fields["source_utc_offset_seconds"] = "-18000"
    saved = installed_web.browser.post("/web/expenses/new", data=fields, headers=headers, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.tenant_id == installed_web.shared_ledger_id,
            Expense.merchant == "时间证据"))
        assert expense.expense_time == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
        assert expense.source_timezone == "America/New_York" and expense.source_utc_offset_seconds == -18000


def test_native_correction_date_only_replays_original_intent_without_new_revision(installed_web):
    fields, headers = open_manual(installed_web)
    fields.update(spent_at="2026-09-01T12:00", source_timezone="Asia/Shanghai",
        source_utc_offset_seconds="28800", accounting_date="")
    saved = installed_web.browser.post("/web/expenses/new", data=fields, headers=headers, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.tenant_id == installed_web.shared_ledger_id,
            Expense.merchant == "时间证据"))
        expense_id, initial_revision = expense.id, expense.fact_revision
    page = installed_web.browser.get(f"/web/expenses/{expense_id}/correct", headers=headers)
    assert page.status_code == 200, page.text
    action = f"/web/expenses/{expense_id}/corrections"
    correction = hidden_post_forms(page.text)[action]
    correction.update(time_precision="date_only", expense_time="", user_local_date="2026-08-31",
        accounting_date="2026-08-31", source_utc_offset_seconds="", reason="原凭证仅记日期")
    first = installed_web.browser.post(action, data=correction, headers=headers, follow_redirects=False)
    assert first.status_code == 303, first.text
    replay = installed_web.browser.post(action, data=correction, headers=headers, follow_redirects=False)
    assert replay.status_code == 303, replay.text
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.fact_revision == initial_revision + 1
        assert expense.time_precision == "date_only" and expense.expense_time is None
        assert expense.user_local_date == expense.accounting_date == date(2026, 8, 31)
        assert expense.amount_cents == 2345
    latest = installed_web.browser.get(saved.headers["location"], headers=headers)
    assert "账务日期与发生时间" in latest.text and "只有日期" in latest.text
