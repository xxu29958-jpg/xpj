"""Real ledger history consumers keep stored instants independent of installation settings."""

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.database import SessionLocal
from app.models import (
    BillSplitInvitation,
    CsvImportBatch,
    Debt,
    Expense,
    ExpenseOffsetRevision,
    ExpenseRevision,
    Invitation,
    LedgerAuditLog,
    LedgerMember,
    Repayment,
)
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services import spending_contract_service
from tests._web_public_session_support import mint_session, public_client
from tests.bill_split_test_support import _seed_web_receiver
from tests.debt_repayment_goal_helpers import _create_external_debt, _repay_debt
from tests.test_web_app_search import _seed_pending_with_amount
from tests.test_web_expense_offsets import _fact_bundle
from tests.test_web_family import _create_invitation
from tests.web_expense_fact_test_support import create_confirmed, row_version

INSTANT = datetime(2026, 10, 19, 23, 46, 37, tzinfo=UTC)


@pytest.fixture
def history_clock():
    models = (Expense, ExpenseRevision, ExpenseOffsetRevision, CsvImportBatch,
              Invitation, LedgerAuditLog, Debt, Repayment, BillSplitInvitation)

    def stamp(_mapper, _connection, row):
        row.created_at = INSTANT
        if isinstance(row, (Invitation, BillSplitInvitation)):
            row.expires_at = INSTANT + timedelta(days=7)

    for model in models:
        event.listen(model, "before_insert", stamp)
    try:
        yield
    finally:
        for model in models:
            event.remove(model, "before_insert", stamp)


def _create_history(client, identity):
    expense_id = create_confirmed(client, identity=identity)
    pending_id = _seed_pending_with_amount(client, merchant="HistorySearch", identity=identity)
    refunded = client.post(f"/web/expenses/{expense_id}/offsets", data={
        "ledger_id": "owner", "kind": "refund", "original_amount": "3.00",
        "accounting_date": "2026-09-03", "reason": "退回差价",
        "expected_row_version": str(row_version(client, expense_id, identity)),
        "idempotency_key": str(uuid4()),
    }, follow_redirects=False)
    assert refunded.status_code == 303, refunded.text
    imported = client.post("/api/imports/csv", headers=identity.app_headers,
        files={"csv_file": ("history.csv", b"amount_yuan,merchant\n19.90,History\n", "text/csv")})
    assert imported.status_code == 201, imported.text
    _create_invitation(client)
    with SessionLocal() as db:
        for row in db.scalars(select(LedgerMember).where(LedgerMember.ledger_id == "owner")):
            row.created_at = INSTANT
        db.get(Expense, expense_id).confirmed_at = INSTANT
        db.get(Expense, pending_id).expense_time = None
        db.commit()
    return expense_id, pending_id


@pytest.mark.parametrize(("zone", "expected", "expires"), [
    ("Asia/Shanghai", "2026-10-20 07:46", "2026-10-27 07:46"),
    ("America/Los_Angeles", "2026-10-19 16:46", "2026-10-26 16:46"),
])
def test_fact_import_and_family_history_use_the_persisted_ledger_calendar(
    web_client, identity, monkeypatch, history_clock, zone, expected, expires,
):
    path = "/api/ledgers/owner/calendar"
    rule = web_client.get(path, headers=identity.app_headers).json()
    changed = web_client.post(path, headers={**identity.app_headers, "Idempotency-Key": "history-followup"},
        json={"expected_revision": rule["revision"], "timezone_name": zone})
    assert changed.status_code == 200, changed.text
    expense_id, pending_id = _create_history(web_client, identity)
    before = _fact_bundle(web_client, expense_id, identity)
    stamp = f'<time datetime="2026-10-19T23:46:37Z" title="2026-10-19T23:46:37Z">{expected}</time>'
    for installation_zone in ("UTC", "Pacific/Honolulu"):
        monkeypatch.setattr(spending_contract_service, "get_settings",
            lambda zone=installation_zone: SimpleNamespace(ocr_default_timezone=zone))
        fact = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
        assert fact.status_code == 200, fact.text
        for start, count in (
            ('<section class="fact-recent"', 2),
            ('<section class="fact-task fact-timeline"', 2),
            ('<section aria-label="更多事实"', 2),
            ('<div class="offset-history"', 1),
        ):
            end = "div" if start.startswith("<div") else "section"
            section = re.search(re.escape(start) + rf".*?</{end}>", fact.text, re.S)
            assert section is not None
            assert section.group(0).count(stamp) == count, section.group(0)
        imported = web_client.get("/web/import?ledger_id=owner")
        family = web_client.get("/web/family?ledger_id=owner")
        assert imported.status_code == family.status_code == 200
        assert stamp in imported.text
        assert family.text.count(stamp) >= 3
        assert f'>{expires}</time> 到期' in family.text
        search = web_client.get("/web/search?ledger_id=owner&q=HistorySearch")
        assert search.status_code == 200
        assert f"录入于 {expected}" in search.text
        drawer = web_client.get(f"/web/expenses/{pending_id}/edit?ledger_id=owner&fragment=1")
        assert drawer.status_code == 200
        assert re.search(r"上传于\s+" + re.escape(stamp), drawer.text)
        after = _fact_bundle(web_client, expense_id, identity)
        for key in ("root", "financial_summary", "active_offsets", "recent_history"):
            assert after[key] == before[key]


def _credit_history(client, identity):
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    debt = _repay_debt(client, identity.app_headers, debt, amount_cents=3000)
    choice = client.get("/api/funds/accounts/existing-debts/list", headers=identity.app_headers).json()[0]
    account = client.post("/api/funds/accounts",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
            "name": "历史信用账户", "kind": "credit", "currency_code": "CNY",
            "opening_amount_minor": 7000, "opening_date": choice["earliest_opening_date"],
            "opening_source": "原欠款核对", "visibility": "ledger",
            "existing_debt": {"public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
        })
    assert account.status_code == 200, account.text
    return debt["public_id"], account.json()["public_id"]


@pytest.mark.parametrize(("zone", "expected"), [
    ("Asia/Shanghai", "2026-10-20 07:46"), ("America/Los_Angeles", "2026-10-19 16:46"),
])
def test_credit_and_split_history_keep_the_selected_ledger_day(
    web_client, identity, monkeypatch, history_clock, request, zone, expected,
):
    path = "/api/ledgers/owner/calendar"
    rule = web_client.get(path, headers=identity.app_headers).json()
    changed = web_client.post(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": rule["revision"], "timezone_name": zone})
    assert changed.status_code == 200, changed.text
    debt_id, account_id = _credit_history(web_client, identity)
    token = mint_session(web_client, identity=identity)
    browser = public_client()
    request.addfinalizer(browser.close)
    receiver_id, _ = _seed_web_receiver("receiver_history")
    expense_id = create_confirmed(web_client, identity=identity)
    invited = web_client.post(f"/api/expenses/{expense_id}/split-invite",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": row_version(web_client, expense_id, identity),
              "receiver_account_id": receiver_id, "amount_cents": 300})
    assert invited.status_code == 200, invited.text
    api_path = f"/api/funds/accounts/{account_id}"
    before = web_client.get(api_path, headers=identity.app_headers).json()
    for installation_zone in ("UTC", "Pacific/Honolulu"):
        monkeypatch.setattr(spending_contract_service, "get_settings",
            lambda zone=installation_zone: SimpleNamespace(ocr_default_timezone=zone))
        debt = web_client.get(f"/web/debts/{debt_id}?ledger_id=owner")
        funds = browser.get(f"/web/funds?ledger_id=owner&account_id={account_id}",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
        sent = web_client.get("/web/bill-splits/sent?ledger_id=owner")
        for name, response in (("debt", debt), ("funds", funds), ("sent", sent)):
            assert response.status_code == 200, (name, response.status_code, response.text[:400])
        assert f"记录于 {expected}" in debt.text
        stamp = f'<time datetime="2026-10-19T23:46:37Z" title="2026-10-19T23:46:37Z">{expected}</time>'
        assert re.search(r"录入于\s+" + re.escape(stamp), funds.text)
        assert stamp in sent.text
        assert web_client.get(api_path, headers=identity.app_headers).json() == before
