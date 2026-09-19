"""Native financial exports remain events when admitted to a saved import task.

These are bounded producer/parser/staging counterexamples. Real batch replay,
human confirmation, permissions and financial effects require the HTTP/PG lane.
"""

import csv
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest

from app.models import CsvImportBatch, ExpenseOffsetFact
from app.money_contract import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX
from app.services import stats_service
from app.services.csv_import_batch_service import _queries
from app.services.csv_import_batch_service._csv_io import _row_from_parsed, build_csv_import_errors_csv
from app.services.expense_service._query import _offset_stream_projection
from app.services.import_service import parse_csv_preview

ROOT_ID = "94794f1d-9445-436f-bb03-62bc6e23e438"
OFFSET_ID = "e7d7f226-3364-432e-951e-61712f932f76"


def _export_offset(monkeypatch, kind: str) -> str:
    reversal = kind == "reversal"
    fact = ExpenseOffsetFact(
        public_id=OFFSET_ID,
        kind=kind,
        category="购物",
        original_currency_code="USD",
        original_amount_minor=2500,
        home_currency_code="JPY",
        amount_cents=3728,
        exchange_rate_to_cny=Decimal("149.12345678"),
        exchange_rate_date=date(2026, 5, 4 if reversal else 5),
        exchange_rate_source="manual",
    )
    entry = SimpleNamespace(
        entry_kind="offset",
        offset=_offset_stream_projection(fact),
        root=SimpleNamespace(id=41, public_id=ROOT_ID, merchant="Synthetic purchase"),
        stream_date=date(2026, 5, 9),
        stream_amount_cents=0 if reversal else -3728,
        lineage_status="reversed" if reversal else "partially_refunded",
        lineage_home_net_cents=0 if reversal else 10000,
    )
    monkeypatch.setattr(stats_service, "filtered_confirmed_stream", lambda *args, **kwargs: [entry])
    return stats_service.export_confirmed_csv(object(), tenant_id="target-ledger")


@pytest.mark.parametrize("kind", ["refund", "chargeback", "reversal"])
def test_native_offset_keeps_its_kind_root_date_and_frozen_money_on_preview(monkeypatch, kind):
    preview = parse_csv_preview(_export_offset(monkeypatch, kind), home_currency="JPY")
    assert preview.valid_count == 1, [row.error for row in preview.rows]
    row, = preview.rows

    # A valid positive Expense would silently reverse this event's meaning.
    assert getattr(row, "entry_kind", "expense") == "offset"
    assert row.offset_kind == kind
    assert row.source_event_public_id == OFFSET_ID
    assert row.source_root_public_id == ROOT_ID
    assert row.accounting_date == date(2026, 5, 9)
    assert row.stream_amount_cents == (0 if kind == "reversal" else -3728)
    assert row.home_currency_code == "JPY"
    assert row.amount_cents == 3728
    assert row.original_currency_code == "USD"
    assert row.original_amount_minor == 2500
    assert row.exchange_rate_to_cny == Decimal("149.12345678")
    assert row.exchange_rate_date == date(2026, 5, 4 if kind == "reversal" else 5)
    assert row.exchange_rate_source == "manual"


def test_saved_import_row_does_not_lose_the_offset_before_later_review(monkeypatch):
    parsed, = parse_csv_preview(_export_offset(monkeypatch, "refund"), home_currency="JPY").rows
    batch = CsvImportBatch(id=7, public_id="saved-batch", tenant_id="target-ledger", file_name="own.csv")

    row = _row_from_parsed(batch, parsed)

    assert row.status == "valid"
    assert getattr(row, "entry_kind", "expense") == "offset"
    assert row.offset_kind == "refund"
    assert row.source_event_public_id == OFFSET_ID
    assert row.source_root_public_id == ROOT_ID
    assert row.accounting_date == date(2026, 5, 9)
    assert row.stream_amount_cents == -3728
    assert row.exchange_rate_to_cny == Decimal("149.12345678")
    assert row.expense_id is None


@pytest.mark.parametrize("kind", ["unknown", "adjustment", "payment"])
def test_unknown_native_event_never_falls_through_as_an_ordinary_expense(kind):
    content = (
        "amount_cents,home_currency_code,entry_kind,public_id,root_expense_public_id,stream_date\n"
        f"2000,CNY,{kind},{OFFSET_ID},{ROOT_ID},2026-05-09\n"
    )

    preview = parse_csv_preview(content, home_currency="CNY")

    assert preview.error_count == 1
    assert preview.valid_count == 0
    assert preview.rows[0].error


@pytest.mark.parametrize(
    ("content", "currency", "minor"),
    [
        ("amount_yuan,merchant\n12.34,Cafe\n", "CNY", 1234),
        ("amount_cents,home_currency_code,amount_home_major\n1200,JPY,1200\n", "JPY", 1200),
    ],
)
def test_plain_expense_csv_keeps_its_existing_currency_aware_admission(content, currency, minor):
    preview = parse_csv_preview(content, home_currency=currency)
    assert preview.valid_count == 1
    assert preview.error_count == 0
    assert preview.rows[0].amount_cents == minor
    assert preview.rows[0].home_currency_code == currency


def _replace_cells(content: str, **changes: str) -> str:
    reader = csv.DictReader(StringIO(content))
    rows = list(reader)
    rows[0].update(changes)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_native_quote_precision_cannot_be_silently_rounded(monkeypatch):
    content = _replace_cells(_export_offset(monkeypatch, "refund"),
        exchange_rate_to_cny="149.123456789")
    preview = parse_csv_preview(content, home_currency="JPY")
    assert preview.error_count == 1
    assert preview.rows[0].event_input["exchange_rate_to_cny"] == "149.123456789"


@pytest.mark.parametrize("reversed_root", [False, True])
def test_native_root_retains_gross_money_even_when_its_stream_contribution_is_zero(monkeypatch, reversed_root):
    root = SimpleNamespace(
        id=41, public_id=ROOT_ID, amount_cents=3728, home_currency="JPY",
        original_currency_code="USD", original_amount_minor=2500,
        exchange_rate_to_cny=Decimal("149.12345678"), exchange_rate_date=date(2026, 5, 4),
        exchange_rate_source="manual", merchant="Synthetic purchase", category="购物", note="",
        source="CSV导入", expense_time=datetime(2026, 5, 9, 12, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 10, 12, tzinfo=UTC), tags="", value_score=None, regret_score=None,
        accounting_time=None,
    )
    entry = SimpleNamespace(
        entry_kind="expense", root=root, stream_date=date(2026, 5, 9),
        stream_amount_cents=0 if reversed_root else 3728,
        lineage_status="reversed" if reversed_root else "confirmed",
        lineage_home_net_cents=0 if reversed_root else 3728,
    )
    monkeypatch.setattr(stats_service, "filtered_confirmed_stream", lambda *args, **kwargs: [entry])

    row, = parse_csv_preview(stats_service.export_confirmed_csv(object(), tenant_id="source"), home_currency="CNY").rows

    assert row.is_valid, row.error
    assert row.source_event_public_id == row.source_root_public_id == ROOT_ID
    assert row.amount_cents == 3728
    assert row.original_amount_minor == 2500
    assert row.stream_amount_cents == (0 if reversed_root else 3728)
    assert row.exchange_rate_date == date(2026, 5, 4)
    assert row.accounting_date == date(2026, 5, 9)
    assert row.home_currency_code == "JPY"


@pytest.mark.parametrize("changes", [
    {"entry_kind": ""},
    {"offset_kind": ""},
    {"offset_kind": "unknown"},
    {"public_id": ""},
    {"public_id": "not-a-uuid" * 10},
    {"public_id": ROOT_ID},
    {"root_expense_public_id": ""},
    {"stream_date": "2026-02-30"},
    {"stream_amount_cents": "3728"},
    {"stream_amount_cents": "-3727"},
    {"stream_amount_cents": "-9223372036854775809"},
    {"lineage_status": "confirmed"},
    {"lineage_home_net_cents": "not-a-number"},
    {"home_currency_code": ""},
    {"original_currency_code": ""},
    {"original_amount_minor": ""},
    {"exchange_rate_source": "unknown-provider-" * 5},
])
def test_native_missing_or_contradictory_cells_remain_repairable_errors(monkeypatch, changes):
    content = _replace_cells(_export_offset(monkeypatch, "refund"), **changes)

    row, = parse_csv_preview(content, home_currency="JPY").rows
    staged = _row_from_parsed(CsvImportBatch(id=7, tenant_id="target", public_id="batch"), row)

    assert not row.is_valid
    assert staged.status == "error"
    assert staged.event_input is not None
    for name, value in changes.items():
        assert staged.event_input[name] == value
    assert staged.source_event_public_id is None or len(staged.source_event_public_id) == 36


def test_native_lineage_net_preserves_the_projection_range_not_the_single_fact_limit(monkeypatch):
    net = -(MONEY_MINOR_MAX + 1)
    content = _replace_cells(_export_offset(monkeypatch, "refund"), lineage_home_net_cents=str(net))

    row, = parse_csv_preview(content, home_currency="JPY").rows

    assert row.is_valid, row.error
    assert row.lineage_home_net_cents == net
    invalid, = parse_csv_preview(
        _replace_cells(content, lineage_home_net_cents=str(-MONEY_AGGREGATE_MAX - 1)), home_currency="JPY",
    ).rows
    assert not invalid.is_valid


@pytest.mark.parametrize("missing", [
    ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source"),
    ("exchange_rate_to_cny",), ("exchange_rate_date",), ("exchange_rate_source",),
])
def test_native_legacy_null_quote_remains_missing_evidence_instead_of_an_invented_rate(monkeypatch, missing):
    content = _replace_cells(_export_offset(monkeypatch, "refund"),
        **dict.fromkeys(missing, ""))

    row, = parse_csv_preview(content, home_currency="JPY").rows

    assert row.is_valid, row.error
    expected = {"exchange_rate_to_cny": Decimal("149.12345678"),
        "exchange_rate_date": date(2026, 5, 5), "exchange_rate_source": "manual"}
    for field, value in expected.items():
        assert getattr(row, field) == (None if field in missing else value)
    assert all(row.event_input[field] == "" for field in missing)
    assert row.amount_cents == 3728
    assert row.accounting_date == date(2026, 5, 9)


def _error_download(monkeypatch, rows) -> str:
    monkeypatch.setattr(_queries, "get_csv_import_batch", lambda *args, **kwargs: SimpleNamespace(id=7))
    db = SimpleNamespace(scalars=lambda statement: rows)
    return build_csv_import_errors_csv(db, tenant_id="target", public_id="batch")


def test_error_csv_repairs_native_identity_without_losing_signed_money_or_quote(monkeypatch):
    original = _replace_cells(_export_offset(monkeypatch, "refund"), public_id="broken-source-id")
    parsed, = parse_csv_preview(original, home_currency="JPY").rows
    saved = _row_from_parsed(CsvImportBatch(id=7, tenant_id="target", public_id="batch"), parsed)
    assert saved.source_event_public_id is None

    downloaded = _error_download(monkeypatch, [saved])
    exported, = list(csv.DictReader(StringIO(downloaded)))
    assert exported["public_id"] == "broken-source-id"
    assert exported["stream_amount_cents"] == "-3728"
    assert exported["exchange_rate_date"] == "2026-05-05"
    repaired, = parse_csv_preview(_replace_cells(downloaded, public_id=OFFSET_ID), home_currency="CNY").rows

    assert repaired.is_valid, repaired.error
    assert repaired.entry_kind == "offset"
    assert repaired.source_event_public_id == OFFSET_ID
    assert repaired.source_root_public_id == ROOT_ID
    assert repaired.home_currency_code == "JPY"
    assert repaired.exchange_rate_to_cny == Decimal("149.12345678")
    assert repaired.exchange_rate_source == "manual"
    assert repaired.stream_amount_cents == -3728


def test_mixed_error_download_keeps_plain_rows_plain_and_native_rows_native(monkeypatch):
    ordinary, = parse_csv_preview("amount_yuan,merchant\n12.34,Cafe\n", home_currency="CNY").rows
    native, = parse_csv_preview(_export_offset(monkeypatch, "reversal"), home_currency="JPY").rows
    batch = CsvImportBatch(id=7, tenant_id="target", public_id="batch")
    rows = [_row_from_parsed(batch, parsed) for parsed in (ordinary, native)]
    for row in rows:
        row.status = "insert_failed"

    restored = parse_csv_preview(_error_download(monkeypatch, rows), home_currency="CNY")

    assert restored.valid_count == 2, [row.error for row in restored.rows]
    plain, reversal = restored.rows
    assert plain.event_input is None
    assert plain.entry_kind == "expense"
    assert plain.source_event_public_id is None
    assert plain.amount_cents == 1234
    assert reversal.entry_kind == "offset"
    assert reversal.offset_kind == "reversal"
    assert reversal.amount_cents == 3728
    assert reversal.stream_amount_cents == 0


def test_ordinary_legacy_foreign_csv_keeps_its_released_fx_resolution_path():
    content = (
        "amount_cents,original_currency_code,exchange_rate_to_cny,exchange_rate_date,expense_time\n"
        "12345,USD,7.1234,2026-05-01,2026-05-04T16:30:00Z\n"
    )

    row, = parse_csv_preview(content, timezone_name="Asia/Shanghai", home_currency="CNY").rows

    assert row.is_valid, row.error
    assert row.event_input is None
    assert row.amount_cents is None
    assert row.original_amount_minor == 12345
    assert row.exchange_rate_to_cny is None
    assert row.exchange_rate_date == date(2026, 5, 5)
