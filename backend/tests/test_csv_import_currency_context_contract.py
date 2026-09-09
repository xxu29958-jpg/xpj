"""The file's declared money survives parsing and durable import staging."""

import pytest

from app.models import CsvImportBatch
from app.services.csv_import_batch_service._csv_io import _row_from_parsed
from app.services.import_service import parse_csv_preview


@pytest.mark.parametrize("current,declared", [("CNY", "JPY"), ("JPY", "CNY")])
def test_an_explicit_file_currency_is_preserved_under_another_default(current, declared):
    preview = parse_csv_preview(f"home_currency_code,amount_cents,merchant\n{declared},1200,Train\n", home_currency=current)
    row = preview.rows[0]
    assert row.is_valid, row.error
    assert row.home_currency_code == row.original_currency_code == declared
    assert row.amount_cents == row.original_amount_minor == 1200


def test_staging_carries_the_currency_that_gave_the_parsed_amount_its_meaning():
    row = parse_csv_preview("home_currency_code,amount_cents,merchant\nJPY,1200,Train\n", home_currency="JPY").rows[0]
    stored = _row_from_parsed(CsvImportBatch(id=7, tenant_id="owner"), row)
    assert stored.home_currency_code == "JPY"
    assert stored.amount_cents == stored.original_amount_minor == 1200
    assert stored.original_currency_code == "JPY"


def test_an_invalid_declared_currency_remains_an_error_instead_of_using_the_default():
    row = parse_csv_preview("home_currency_code,amount_cents\nZZZ,1200\n", home_currency="CNY").rows[0]
    assert not row.is_valid
    assert row.error_code == "currency_not_supported"
    assert row.amount_cents is None
