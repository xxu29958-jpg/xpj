"""Missing historical rates expose the original command's repair context."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.models import Expense, ExpenseOffsetFact
from app.schemas import ExpenseOffsetCorrectionRequest, ExpenseOffsetCreateRequest
from app.services import expense_offset_money as offsets
from app.services.debt_service import _money as debts

REQUESTED = date(2026, 5, 4)
PUBLISHED = date(2026, 5, 3)


def _expense():
    return Expense(home_currency_code="CNY", original_currency_code="USD",
        original_amount_minor=1000, amount_cents=7000,
        exchange_rate_to_cny=Decimal(7), exchange_rate_date=PUBLISHED,
        exchange_rate_source="manual")


def _offset():
    return ExpenseOffsetFact(id=1, kind="refund", original_amount_minor=100,
        amount_cents=700, accounting_date=PUBLISHED, exchange_rate_to_cny=Decimal(7),
        exchange_rate_date=PUBLISHED, exchange_rate_source="manual")


def _correction(accounting_date):
    return ExpenseOffsetCorrectionRequest(original_amount_minor=100,
        accounting_date=accounting_date, category="购物", offset_reason="实际退款",
        correction_reason="更正日期", expected_row_version=1)


def _assert_repair(error, *, home="CNY"):
    assert error.status_code == 409
    assert error.error == "exchange_rate_pending"
    assert error.details == {"currency_code": "USD", "home_currency_code": home,
        "rate_date": REQUESTED.isoformat()}


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_debt_missing_rate_keeps_original_accounting_day_and_parent_home(monkeypatch, home):
    lookup = Mock(return_value=(None, None, "pending", REQUESTED))
    monkeypatch.setattr(debts, "resolve_payload_rate", lookup)
    with pytest.raises(AppError) as refused:
        debts.freeze_home_amount(Mock(), tenant_id="owner", home_currency_code=home,
            amount_cents=None, original_currency="USD", original_amount=Decimal("1"),
            event_time=datetime(2026, 5, 3, 16, 30, tzinfo=UTC))
    _assert_repair(refused.value, home=home)
    assert lookup.call_args.kwargs["rate_date"] == REQUESTED


@pytest.mark.parametrize("kind", ["refund", "chargeback"])
def test_new_offset_missing_rate_exposes_original_pair_and_date(monkeypatch, kind):
    monkeypatch.setattr(offsets, "resolve_payload_rate",
        lambda *a, **kw: (None, None, "pending", REQUESTED))
    payload = ExpenseOffsetCreateRequest(kind=kind, original_amount_minor=100,
        accounting_date=REQUESTED, reason="实际退款", expected_row_version=1)
    with pytest.raises(AppError) as refused:
        offsets.resolve_offset_money(Mock(), tenant_id="owner", expense=_expense(),
            offsets=[], payload=payload)
    _assert_repair(refused.value)


def test_offset_date_correction_missing_rate_exposes_new_requested_date(monkeypatch):
    monkeypatch.setattr(offsets, "resolve_payload_rate",
        lambda *a, **kw: (None, None, "pending", REQUESTED))
    offset = _offset()
    with pytest.raises(AppError) as refused:
        offsets.resolve_corrected_offset_money(Mock(), tenant_id="owner", expense=_expense(),
            offset=offset, active_offsets=[offset], payload=_correction(REQUESTED))
    _assert_repair(refused.value)


def test_unchanged_date_correction_and_reversal_preserve_frozen_reference(monkeypatch):
    monkeypatch.setattr(offsets, "resolve_payload_rate", Mock(side_effect=AssertionError("frozen")))
    expense, offset = _expense(), _offset()
    corrected = offsets.resolve_corrected_offset_money(Mock(), tenant_id="owner", expense=expense,
        offset=offset, active_offsets=[offset], payload=_correction(PUBLISHED))
    reversal = offsets.resolve_offset_money(Mock(), tenant_id="owner", expense=expense, offsets=[],
        payload=ExpenseOffsetCreateRequest(kind="reversal", accounting_date=REQUESTED,
            reason="原交易撤销", expected_row_version=1))
    assert (corrected.amount_cents, corrected.exchange_rate_date) == (700, PUBLISHED)
    assert (reversal.amount_cents, reversal.exchange_rate_date) == (7000, PUBLISHED)


def test_known_rate_rounding_to_zero_does_not_offer_fake_missing_rate_repair(monkeypatch):
    monkeypatch.setattr(offsets, "resolve_payload_rate",
        lambda *a, **kw: (Decimal("0.00000001"), "manual", "ready", REQUESTED))
    with pytest.raises(AppError) as refused:
        offsets.resolve_offset_money(Mock(), tenant_id="owner", expense=_expense(), offsets=[],
            payload=ExpenseOffsetCreateRequest(kind="refund", original_amount_minor=1,
                accounting_date=REQUESTED, reason="实际退款", expected_row_version=1))
    assert refused.value.error == "exchange_rate_required"
    assert refused.value.details is None
