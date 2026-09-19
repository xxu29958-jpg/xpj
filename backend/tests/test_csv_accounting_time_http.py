"""PostgreSQL coverage for staged calendar evidence and native replay."""

from datetime import date

import pytest
from api_contract_helpers import confirm_expense_api
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CsvImportBatch, CsvImportRow, Expense, Ledger, LedgerCalendarRevision
from app.services.ledger_calendar_service import adopt_ledger_calendar, current_calendar
from tests.test_csv_financial_events_http import _apply, _batch, _export

pytestmark = pytest.mark.real_db


def _change_calendar(zone):
    with SessionLocal.begin() as db:
        adopt_ledger_calendar(db, ledger_id="owner", timezone_name="Asia/Shanghai")
        previous = current_calendar(db, ledger_id="owner")
        rule = LedgerCalendarRevision(ledger_id="owner", revision=previous.revision + 1,
            timezone_name=zone, basis="owner_selected")
        db.add(rule)
        db.flush()
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        ledger.calendar_revision = rule.revision
        return rule.revision


def test_saved_csv_rule_survives_calendar_change_confirm_and_native_reupload(client, identity):
    captured_revision = _change_calendar("Asia/Shanghai")
    batch_id = _batch(client, identity.app_headers,
        b"amount_cents,merchant,expense_time\n100,Exact original,2026-04-30T16:30:00Z\n200,Date only,2026-04-30\n")
    _change_calendar("America/New_York")
    assert _apply(client, identity.app_headers, batch_id)["inserted_count"] == 2
    with SessionLocal() as db:
        batch = db.scalar(select(CsvImportBatch).where(CsvImportBatch.public_id == batch_id))
        assert batch.calendar_revision == captured_revision
        rows = list(db.scalars(select(CsvImportRow).where(CsvImportRow.batch_id == batch.id).order_by(CsvImportRow.line_number)))
        assert [row.expense_time_input for row in rows] == ["2026-04-30T16:30:00Z", "2026-04-30"]
        roots = [db.get(Expense, row.expense_id) for row in rows]
        assert [root.accounting_date for root in roots] == [date(2026, 5, 1), date(2026, 4, 30)]
        assert all(root.calendar_revision == captured_revision for root in roots)
        assert all(root.user_local_date == date(2026, 4, 30) for root in roots)
        assert all(root.exchange_rate_date == date(2026, 4, 30) for root in roots)
        assert roots[1].expense_time is None and roots[1].time_precision == "date_only"
        expense_ids = [root.id for root in roots]
    for expense_id in expense_ids:
        result = confirm_expense_api(client, expense_id, headers=identity.app_headers)
        assert result.status_code == 200, result.text
        assert result.json()["accounting_time"]["calendar_revision"] == captured_revision
    replay = _batch(client, identity.app_headers, _export(client, identity.app_headers))
    _apply(client, identity.app_headers, replay)
    with SessionLocal() as db:
        batch = db.scalar(select(CsvImportBatch).where(CsvImportBatch.public_id == replay))
        rows = list(db.scalars(select(CsvImportRow).where(CsvImportRow.batch_id == batch.id)))
        assert [row.status for row in rows] == ["matched", "matched"]
        assert sorted(db.scalars(select(Expense.id).where(Expense.tenant_id == "owner"))) == sorted(expense_ids)
