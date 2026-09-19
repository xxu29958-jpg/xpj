"""Pure metadata checks; these do not connect to a database."""

from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models import (
    BillSplitInvitation,
    CsvImportBatch,
    CsvImportRow,
    Expense,
    ExpenseOffsetFact,
    Ledger,
    LedgerCalendarRevision,
)


def test_calendar_rules_and_fact_references_are_ledger_scoped():
    rules = LedgerCalendarRevision.__table__
    assert tuple(rules.primary_key.columns.keys()) == ("ledger_id", "revision")
    assert Ledger.__table__.c.calendar_revision.nullable
    for model, ledger_column in ((Ledger, "ledger_id"), (Expense, "tenant_id"), (ExpenseOffsetFact, "tenant_id"),
                                 (CsvImportBatch, "tenant_id")):
        assert any(
            isinstance(item, ForeignKeyConstraint)
            and tuple(item.column_keys) == (ledger_column, "calendar_revision")
            and item.referred_table.name == "ledger_calendar_revisions"
            for item in model.__table__.constraints
        )


def test_calendar_expansion_does_not_invent_historical_evidence():
    fields = ("calendar_revision", "user_local_date", "time_precision", "source_timezone",
              "source_utc_offset_seconds", "accounting_date_basis")
    for model in (Expense, ExpenseOffsetFact):
        for field in fields:
            column = model.__table__.c[field]
            assert column.nullable and column.default is None and column.server_default is None
    assert Expense.__table__.c.accounting_date.nullable
    assert not ExpenseOffsetFact.__table__.c.accounting_date.nullable
    invitation = BillSplitInvitation.__table__.c.accounting_time_snapshot
    assert invitation.nullable and invitation.default is None and invitation.server_default is None
    assert isinstance(invitation.type, JSONB)
    assert isinstance(CsvImportRow.__table__.c.time_input.type, JSONB)
    for column in (CsvImportBatch.__table__.c.calendar_revision, CsvImportRow.__table__.c.time_input,
                   CsvImportRow.__table__.c.expense_time_input):
        assert column.nullable and column.default is None and column.server_default is None
