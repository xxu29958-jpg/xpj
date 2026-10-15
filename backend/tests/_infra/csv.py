"""Use the saved-import parser for existing CSV row and round-trip checks."""

from io import BytesIO
from types import SimpleNamespace

from app.config import get_settings
from app.services.csv_import_batch_service._lifecycle import _csv_import_limits, _parse_csv_import_rows


def parse_uploaded_csv(content: str, timezone_name: str | None = None, *, home_currency: str):
    max_bytes, max_cell_bytes, max_data_rows, _ = _csv_import_limits()
    rows, _, valid_count, error_count = _parse_csv_import_rows(
        BytesIO(content.encode("utf-8")),
        max_bytes=max_bytes,
        max_cell_bytes=max_cell_bytes,
        max_data_rows=max_data_rows,
        timezone_name=timezone_name or get_settings().ocr_default_timezone,
        home_currency=home_currency,
        calendar_revision=1,
    )
    return SimpleNamespace(rows=rows, valid_count=valid_count, error_count=error_count)
