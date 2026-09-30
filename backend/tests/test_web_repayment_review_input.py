"""Exact reviewed money stays separate from captured money and frozen home value."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.routes._web_repayment_review import _review_error, review_confirmation


def test_unchanged_original_preserves_known_home_amount_but_corrected_money_is_explicit() -> None:
    capture = SimpleNamespace(original_currency_code="CNY", original_amount_minor=10000,
        home_currency_code="USD", amount_cents=1400)
    values = {"target_choice": "debt:7", "original_currency": "CNY", "original_amount": "100.00"}
    unchanged = review_confirmation(values, capture)
    assert unchanged.original_currency is None and unchanged.original_amount is None
    assert "original_amount" not in unchanged.model_dump(exclude_unset=True)
    reviewed = review_confirmation({**values, "original_amount": "90.00"}, capture)
    assert reviewed.original_currency == "CNY" and reviewed.original_amount == Decimal("90.00")
    assert reviewed.target_debt_public_id == "debt" and reviewed.expected_row_version == 7
    assert capture.original_amount_minor == 10000 and capture.amount_cents == 1400


@pytest.mark.parametrize("currency,amount", [("JPY", "90.01"), ("CNY", "0"), ("CNY", "-1")])
def test_invalid_review_never_reinterprets_money(currency: str, amount: str) -> None:
    captured = SimpleNamespace(original_currency_code="CNY", original_amount_minor=10000)
    with pytest.raises(AppError):
        review_confirmation({"target_choice": "debt:7", "original_currency": currency, "original_amount": amount}, captured)


def test_reused_key_is_not_a_success_or_permission_to_replace_original() -> None:
    error = _review_error(AppError("idempotency_key_reused", status_code=422))
    assert error["result"] == "blocked" and error["rejected"] is False
    assert "不能认定本次处理成功" in error["error"]
