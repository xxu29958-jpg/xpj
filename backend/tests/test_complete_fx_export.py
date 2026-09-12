"""The exported offset row retains the frozen evidence from its fact projection."""

import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest

from app.models import ExpenseOffsetFact
from app.services import stats_service
from app.services.expense_service._query import _offset_stream_projection


@pytest.mark.parametrize("kind", ["refund", "chargeback", "reversal"])
def test_csv_offset_keeps_frozen_fx_through_the_shared_stream_projection(monkeypatch, kind):
    reversal = kind == "reversal"
    fact = ExpenseOffsetFact(
        public_id="offset-frozen", kind=kind, category="购物",
        original_currency_code="USD", original_amount_minor=2500,
        home_currency_code="JPY", amount_cents=3728,
        exchange_rate_to_cny=Decimal("149.12345678"),
        exchange_rate_date=date(2026, 5, 4 if reversal else 5),
        exchange_rate_source="manual",
    )
    row = SimpleNamespace(
        entry_kind="offset", offset=_offset_stream_projection(fact),
        root=SimpleNamespace(id=41, public_id="root-frozen", merchant="海外订单"),
        stream_date=date(2026, 5, 9), stream_amount_cents=0 if reversal else -3728,
        lineage_status="reversed" if reversal else "partially_refunded",
        lineage_home_net_cents=0 if reversal else 10000,
    )
    calls = []

    def filtered(db, **filters):
        calls.append((db, filters))
        return [row]

    monkeypatch.setattr(stats_service, "filtered_confirmed_stream", filtered)
    db = object()
    filters = {
        "tenant_id": "original-ledger", "month": "2026-05", "category": "购物",
        "tag": "旅行", "timezone_name": "Asia/Tokyo",
    }
    exported = list(csv.DictReader(StringIO(stats_service.export_confirmed_csv(db, **filters))))

    assert calls == [(db, filters)]
    assert len(exported) == 1
    actual = exported[0]
    assert list(actual)[4:9] == [
        "original_currency_code", "original_amount_minor", "exchange_rate_to_cny",
        "exchange_rate_date", "exchange_rate_source",
    ]
    assert {key: actual[key] for key in list(actual)[4:9]} == {
        "original_currency_code": "USD", "original_amount_minor": "2500",
        "exchange_rate_to_cny": "149.12345678",
        "exchange_rate_date": fact.exchange_rate_date.isoformat(), "exchange_rate_source": "manual",
    }
    assert actual["amount_cents"] == actual["amount_home_major"] == "3728"
    assert actual["home_currency_code"] == "JPY"
    assert actual["amount_yuan"] == ""
    assert actual["offset_kind"] == kind
    assert actual["stream_amount_cents"] == str(row.stream_amount_cents)
    assert actual["root_expense_public_id"] == "root-frozen"


def test_legacy_offset_without_fx_evidence_exports_blanks_without_inventing_a_quote(monkeypatch):
    fact = ExpenseOffsetFact(
        public_id="legacy", kind="refund", category="其他",
        original_currency_code="CNY", original_amount_minor=100,
        home_currency_code="CNY", amount_cents=100,
        exchange_rate_to_cny=None, exchange_rate_date=None, exchange_rate_source=None,
    )
    row = SimpleNamespace(
        entry_kind="offset", offset=_offset_stream_projection(fact),
        root=SimpleNamespace(id=1, public_id="root-legacy", merchant=None),
        stream_date=date(2026, 5, 9), stream_amount_cents=-100,
        lineage_status="partially_refunded", lineage_home_net_cents=100,
    )
    monkeypatch.setattr(stats_service, "filtered_confirmed_stream", lambda *args, **kwargs: [row])

    actual, = csv.DictReader(StringIO(stats_service.export_confirmed_csv(object(), tenant_id="owner")))

    assert [actual[key] for key in ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source")] == ["", "", ""]
    assert actual["amount_cents"] == actual["original_amount_minor"] == "100"
    assert actual["amount_yuan"] == actual["amount_home_major"] == "1.00"
