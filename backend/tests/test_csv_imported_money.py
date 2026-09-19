"""Imported facts retain reviewed money without changing shared daily quotes."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.models import CsvImportRow, Expense
from app.schemas import CsvImportReviewRequest, ExpenseOffsetCreateRequest
from app.services import exchange_rate_service
from app.services.csv_import_batch_service import _review
from app.services.csv_import_batch_service._events import _matches_fact, _same_source_row
from app.services.expense_offset_money import resolve_offset_money


def _snapshot(**changes):
    values = {"home_currency_code": "JPY", "original_currency_code": "USD",
        "original_amount_minor": 2500, "amount_cents": 3728,
        "exchange_rate_to_cny": Decimal("149.12345678"),
        "exchange_rate_date": date(2026, 5, 5), "exchange_rate_source": "manual"}
    return SimpleNamespace(**(values | changes))


def _root():
    return Expense(home_currency_code="JPY", original_currency_code="USD",
        original_amount_minor=10000, amount_cents=15000,
        exchange_rate_to_cny=Decimal("150"), exchange_rate_date=date(2026, 5, 1),
        exchange_rate_source="imported", fx_status="ready", status="confirmed")


def _payload(kind="refund"):
    return ExpenseOffsetCreateRequest(kind=kind,
        original_amount_minor=None if kind == "reversal" else 2500,
        accounting_date=date(2026, 5, 9), reason="Reviewed file event", expected_row_version=1)


@pytest.mark.parametrize("kind", ["refund", "chargeback"])
def test_offset_uses_reviewed_file_money_and_quote_day_without_a_database_rate(kind):
    money = resolve_offset_money(object(), tenant_id="target", expense=_root(),
        offsets=[], payload=_payload(kind), imported_snapshot=_snapshot())
    assert (money.original_amount_minor, money.amount_cents) == (2500, 3728)
    assert money.exchange_rate_to_cny == Decimal("149.12345678")
    assert money.exchange_rate_date == date(2026, 5, 5)
    assert money.exchange_rate_source == "imported"


@pytest.mark.parametrize("changes", [
    {"amount_cents": 3729}, {"home_currency_code": "CNY"},
    {"original_currency_code": "EUR"}, {"exchange_rate_to_cny": Decimal("NaN")},
    {"exchange_rate_to_cny": Decimal("0")}, {"exchange_rate_date": None},
])
def test_inconsistent_imported_money_is_not_admitted(changes):
    with pytest.raises(AppError) as error:
        resolve_offset_money(object(), tenant_id="target", expense=_root(), offsets=[],
            payload=_payload(), imported_snapshot=_snapshot(**changes))
    assert error.value.error == "currency_snapshot_invalid"


def test_reversal_uses_the_real_roots_gross_snapshot_not_zero_stream_contribution():
    root = _root()
    snapshot = _snapshot(original_amount_minor=10000, amount_cents=15000,
        exchange_rate_to_cny=Decimal("150"), exchange_rate_date=date(2026, 5, 1))
    money = resolve_offset_money(object(), tenant_id="target", expense=root,
        offsets=[], payload=_payload("reversal"), imported_snapshot=snapshot)
    assert (money.original_amount_minor, money.amount_cents) == (10000, 15000)
    with pytest.raises(AppError) as error:
        resolve_offset_money(object(), tenant_id="target", expense=root,
            offsets=[], payload=_payload("reversal"), imported_snapshot=_snapshot(amount_cents=0))
    assert error.value.error == "currency_snapshot_invalid"


def test_purchase_draft_freezes_imported_evidence_without_asserting_provider_authority():
    apply_snapshot = getattr(exchange_rate_service, "apply_imported_currency_snapshot", None)
    assert callable(apply_snapshot), "native import has no money-owner admission yet"
    expense = Expense(status="pending")
    apply_snapshot(expense, _snapshot())
    assert expense.status == "pending"
    assert (expense.original_amount_minor, expense.amount_cents) == (2500, 3728)
    assert expense.home_currency_code == "JPY"
    assert expense.exchange_rate_to_cny == Decimal("149.12345678")
    assert expense.exchange_rate_date == date(2026, 5, 5)
    assert expense.exchange_rate_source == "imported"
    assert expense.fx_status == "ready"


def _legacy_import_row(missing=("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source")):
    values = vars(_snapshot(**dict.fromkeys(missing)))
    return CsvImportRow(**values, entry_kind="expense", category="其他", source="manual",
        event_input={field: "" if values[field] is None else str(values[field])
            for field in ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source")})


@pytest.mark.parametrize("missing", [
    ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source"),
    ("exchange_rate_to_cny",), ("exchange_rate_date",), ("exchange_rate_source",),
])
def test_legacy_file_quote_can_be_reviewed_without_rewriting_the_source_evidence(missing):
    row = _legacy_import_row(missing)
    original_input = dict(row.event_input)
    payload = CsvImportReviewRequest(reason="根据原单补录", manual_exchange_rate="149.12345678",
        exchange_rate_date="2026-05-05")
    complete = getattr(_review, "_complete_reviewed_quote", None)
    assert callable(complete), "legacy native files have no quote continuation"
    complete(row, payload)
    expense = Expense(status="pending")
    exchange_rate_service.apply_imported_currency_snapshot(expense, row)
    assert (expense.amount_cents, expense.exchange_rate_date) == (3728, date(2026, 5, 5))
    assert row.event_input == original_input
    assert row.exchange_rate_source == "manual"
    assert _same_source_row(row, _legacy_import_row(missing)), "review evidence must not make the same file conflict"


@pytest.mark.parametrize("missing", [("exchange_rate_date",), ("exchange_rate_to_cny",)])
def test_review_cannot_overwrite_the_known_part_of_a_historical_quote(missing):
    row = _legacy_import_row(missing)
    with pytest.raises(AppError) as error:
        _review._complete_reviewed_quote(row, CsvImportReviewRequest(reason="不能改写已有依据",
            manual_exchange_rate="150", exchange_rate_date="2026-05-06"))
    assert error.value.error == "currency_snapshot_invalid"
    assert getattr(row, missing[0]) is None


def test_review_cannot_replace_a_quote_recorded_in_the_file():
    row = CsvImportRow(**vars(_snapshot()))
    complete = getattr(_review, "_complete_reviewed_quote", None)
    assert callable(complete)
    with pytest.raises(AppError) as error:
        complete(row, CsvImportReviewRequest(reason="重新报价", manual_exchange_rate="150",
            exchange_rate_date="2026-05-06"))
    assert error.value.error == "currency_snapshot_invalid"
    assert row.exchange_rate_to_cny == Decimal("149.12345678")


def test_native_identity_matches_the_exported_effective_time_at_its_serialized_precision():
    moment = datetime(2026, 5, 5, 12, 30, 15, 654321, tzinfo=UTC)
    row = CsvImportRow(**vars(_snapshot()), entry_kind="expense", merchant="shop", category="其他",
        source="manual", expense_time=moment.replace(microsecond=0))
    fact = Expense(**vars(_snapshot()), status="confirmed", merchant="shop", category="其他",
        source="manual", expense_time=None, confirmed_at=moment)
    assert _matches_fact(row, fact), "the actual export carries the shared effective accounting instant"
    fact.expense_time = moment.replace(day=6)
    assert not _matches_fact(row, fact), "a changed accounting instant remains a real conflict"
