"""Literal diagnostic presence must respect money units and explicit seconds."""
import pytest

from app.services.recognition_miss_service import _text_present


@pytest.mark.parametrize("text,exponent,value,expected", [
    ("￥1,234.50", 2, 123450, True),
    ("18.00元", 2, 1857, False),
    ("JPY 18", 0, 18, True),
    ("18", 2, 18, False),
    ("18", None, 18, None),
])
def test_literal_money_uses_the_saved_currency_exponent(text, exponent, value, expected):
    assert _text_present(text, "amount_cents", {"value": value, "minor_unit_exponent": exponent}) is expected


@pytest.mark.parametrize("text,seconds,expected", [
    ("2026年10月20日 12时30分", 0, True),
    ("2026-10-20 12:30:05", 0, False),
    ("2026年10月20日 12时30分05秒", 0, False),
    ("2026/10/20 12:30:05", 5, True),
    ("2026-10-20 12:30", 5, False),
])
def test_time_presence_does_not_erase_explicit_seconds(text, seconds, expected):
    final = {"year": 2026, "month": 10, "day": 20, "hour": 12, "minute": 30,
        "second": seconds, "precision": "instant"}
    assert _text_present(text, "expense_time", final) is expected
