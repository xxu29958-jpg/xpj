"""Bounded CSV reference reads and DTO projection, without a database connection."""

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportEvent, CsvImportRow, Expense, ExpenseOffsetFact
from app.services.csv_import_batch_service._queries import build_csv_row_responses, csv_row_status_filter


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.setattr(Engine, "connect", lambda *_a, **_k: pytest.fail("projection opened a database"))


class ReferenceReads:
    def __init__(self, *, events=(), expenses=(), offsets=()):
        self.records = {CsvImportEvent: events, Expense: expenses, ExpenseOffsetFact: offsets}
        self.reads = []

    def scalars(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert f"{entity.__tablename__}.tenant_id = 'family'" in sql
        self.reads.append((entity, sql))
        return self.records[entity]


def source_row(**changes):
    values = {"line_number": 2, "status": "review", "entry_kind": "offset", "offset_kind": "refund",
        "category": "餐饮", "source": "csv", "source_event_public_id": "source-refund",
        "source_root_public_id": "source-purchase", "expense_id": None}
    return CsvImportRow(**{**values, **changes})


def test_completed_alias_projects_current_root_and_offset_without_rewriting_saved_row():
    row = source_row()
    event = CsvImportEvent(entry_kind="offset", source_event_public_id="source-refund", expense_id=42, offset_id=9)
    root = Expense(id=42, public_id="target-purchase", status="confirmed", row_version=8)
    offset = ExpenseOffsetFact(id=9, public_id="target-refund")
    db = ReferenceReads(events=[event], expenses=[root], offsets=[offset])

    result, = build_csv_row_responses(db, tenant_id="family", rows=[row])

    assert result.status == "matched" and row.status == "review"
    assert result.expense_id is None and row.expense_id is None
    assert (result.resolved_expense_id, result.resolved_root_status, result.resolved_root_row_version) == (42, "confirmed", 8)
    assert result.resolved_offset_public_id == "target-refund"
    assert result.source_event_public_id == "source-refund"
    assert [entity for entity, _ in db.reads] == [CsvImportEvent, Expense, ExpenseOffsetFact]
    assert "expenses.id IN (42)" in db.reads[1][1]
    assert "expense_offset_facts.id IN (9)" in db.reads[2][1]


def test_resolved_root_alone_does_not_mark_an_unreviewed_refund_as_matched():
    row = source_row()
    mapping = CsvImportEvent(entry_kind="expense", source_event_public_id="source-purchase", expense_id=42)
    root = Expense(id=42, public_id="target-purchase", status="pending", row_version=3)
    db = ReferenceReads(events=[mapping], expenses=[root])

    result, = build_csv_row_responses(db, tenant_id="family", rows=[row])

    assert result.status == "review" and result.resolved_expense_id == 42
    assert result.resolved_root_status == "pending" and result.resolved_root_row_version == 3
    assert result.resolved_offset_public_id is None
    assert [entity for entity, _ in db.reads] == [CsvImportEvent, Expense]


@pytest.mark.parametrize(("row_id", "event_id", "root_id", "expected"), [
    (11, 12, 13, 11), (None, 12, 13, 12), (None, None, 13, 13), (None, None, None, 14),
])
def test_root_navigation_keeps_persisted_mapping_precedence(row_id, event_id, root_id, expected):
    row = source_row(expense_id=row_id, status="conflict")
    events = [
        CsvImportEvent(entry_kind="offset", source_event_public_id="source-refund", expense_id=event_id),
        CsvImportEvent(entry_kind="expense", source_event_public_id="source-purchase", expense_id=root_id),
    ]
    roots = [Expense(id=value, public_id="source-purchase" if value == 14 else f"target-{value}",
                     status="confirmed", row_version=value) for value in (11, 12, 13, 14)]
    result, = build_csv_row_responses(ReferenceReads(events=events, expenses=roots), tenant_id="family", rows=[row])

    assert result.resolved_expense_id == expected
    assert result.resolved_root_row_version == expected
    assert result.status == "conflict"


def test_empty_and_ordinary_rows_do_not_add_source_or_offset_queries():
    empty_db = ReferenceReads()
    assert build_csv_row_responses(empty_db, tenant_id="family", rows=[]) == []
    assert empty_db.reads == []
    row = source_row(entry_kind="expense", offset_kind=None, source_event_public_id=None,
                     source_root_public_id=None, expense_id=42, status="applied")
    root = Expense(id=42, public_id="ordinary", status="pending", row_version=1)
    db = ReferenceReads(expenses=[root])
    result, = build_csv_row_responses(db, tenant_id="family", rows=[row])
    assert result.status == "applied" and result.expense_id == result.resolved_expense_id == 42
    assert [entity for entity, _ in db.reads] == [Expense]


@pytest.mark.parametrize("status", ["review", "matched", "conflict"])
def test_effective_status_sql_keeps_ledger_and_event_kind_correlation(status):
    statement = ledger_scoped_select(CsvImportRow, "family").where(
        csv_row_status_filter(tenant_id="family", status=status))
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "csv_import_rows.tenant_id = 'family'" in sql
    if status == "conflict":
        assert "csv_import_rows.status = 'conflict'" in sql and "EXISTS" not in sql
        return
    assert "csv_import_events.tenant_id = 'family'" in sql
    assert "csv_import_events.entry_kind = csv_import_rows.entry_kind" in sql
    assert "csv_import_events.source_event_public_id = csv_import_rows.source_event_public_id" in sql
    assert "csv_import_events.offset_id IS NOT NULL" in sql
    assert "csv_import_events.expense_id IS NOT NULL" in sql
    assert ("NOT (" in sql) == (status == "review")
