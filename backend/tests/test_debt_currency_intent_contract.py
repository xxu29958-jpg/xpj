"""A debt amount needs its captured currency before any runtime negotiation."""

import pytest
from pydantic import ValidationError

from app.schemas import DebtCreateRequest

_FIELDS = {"direction": "owed_to_me", "counterparty_type": "external", "counterparty_label": "Alex", "principal_amount_cents": 1200}


def test_a_debt_create_without_the_amount_currency_is_not_a_complete_intent():
    with pytest.raises(ValidationError, match="home_currency_code"):
        DebtCreateRequest.model_validate(_FIELDS)


@pytest.mark.parametrize("home", ["CNY", "JPY"])
def test_a_debt_create_preserves_its_captured_currency(home):
    request = DebtCreateRequest.model_validate({**_FIELDS, "home_currency_code": home})
    assert request.model_dump(mode="json")["home_currency_code"] == home
    assert request.principal_amount_cents == 1200
