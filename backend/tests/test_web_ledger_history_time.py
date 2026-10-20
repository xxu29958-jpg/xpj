"""Real ledger history consumers keep stored instants independent of installation settings."""

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.database import SessionLocal
from app.models import (
    CsvImportBatch,
    Expense,
    ExpenseOffsetRevision,
    ExpenseRevision,
    Invitation,
    LedgerAuditLog,
    LedgerMember,
)
from app.services import spending_contract_service
from tests.test_web_app_search import _seed_pending_with_amount
from tests.test_web_expense_offsets import _fact_bundle
from tests.test_web_family import _create_invitation
from tests.web_expense_fact_test_support import create_confirmed, row_version

INSTANT = datetime(2026, 10, 19, 23, 46, 37, tzinfo=UTC)


@pytest.fixture
def history_clock():
    models = (Expense, ExpenseRevision, ExpenseOffsetRevision, CsvImportBatch,
              Invitation, LedgerAuditLog)

    def stamp(_mapper, _connection, row):
        row.created_at = INSTANT
        if isinstance(row, Invitation):
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
    return expense_id


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
    expense_id = _create_history(web_client, identity)
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
        after = _fact_bundle(web_client, expense_id, identity)
        for key in ("root", "financial_summary", "active_offsets", "recent_history"):
            assert after[key] == before[key]
