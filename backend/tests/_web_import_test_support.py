"""Shared preparation for the existing  web import consumers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

BATCH = "eed35556-b580-468c-9406-6087538829a4"


EVENT = "a28bc45d-9fda-44b5-9f67-3b70b0819909"


ROOT = "4a21eb10-8be3-42dc-b3fe-434ce6680d88"


def row(**changes):
    from app.schemas import CsvImportRowResponse

    return CsvImportRowResponse(
        line_number=3, status="review", error_code=None, error_message=None,
        amount_cents=710, home_currency_code="CNY", original_currency_code="USD", original_amount_minor=100,
        exchange_rate_to_cny=Decimal("7.10"), exchange_rate_date=date(2026, 5, 3), exchange_rate_source="receipt",
        merchant="Coffee", category="餐饮", note="原退款", expense_time=datetime(2026, 5, 2, tzinfo=UTC),
        tags=None, source="csv", expense_id=None, entry_kind="offset", offset_kind="refund",
        source_event_public_id=EVENT, source_root_public_id=ROOT, accounting_date=date(2026, 5, 4),
        stream_amount_cents=-710, lineage_status="partially_refunded", lineage_home_net_cents=1420,
        event_input={"entry_kind": "offset"},
    ).model_copy(update=changes)


def root(**changes):
    values = {
        "id": 42, "row_version": 9, "status": "confirmed", "merchant": "Coffee", "category": "餐饮",
        "expense_time": "2026-05-02", "accounting_date": "2026-05-02", "accounting_date_assumed": False,
        "original_currency_code": "USD", "original_amount_value": "3.00",
        "fx_meta": "冻结汇率 7.00 · 2026-05-02", "fx_pending": False,
    }
    return SimpleNamespace(**{**values, **changes})
