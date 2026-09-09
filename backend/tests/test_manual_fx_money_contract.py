"""The rate command must capture its target before transport can renegotiate."""

import pytest
from pydantic import ValidationError

from app.schemas import ExchangeRateRequest


def test_a_manual_rate_without_its_target_is_not_a_money_command():
    with pytest.raises(ValidationError, match="home_currency_code"):
        ExchangeRateRequest.model_validate({
            "currency_code": "USD", "rate_date": "2026-09-08", "rate_to_cny": "150", "expected_row_version": 0,
        })


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_the_rate_command_preserves_its_explicit_target(home):
    command = ExchangeRateRequest.model_validate({
        "currency_code": "USD", "home_currency_code": home,
        "rate_date": "2026-09-08", "rate_to_cny": "150", "expected_row_version": 0,
    })
    assert command.model_dump(mode="json")["home_currency_code"] == home
