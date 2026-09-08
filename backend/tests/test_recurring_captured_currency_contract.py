"""New fixed-expense intentions must name the currency of their entered amount."""

import pytest
from pydantic import ValidationError

from app.schemas import RecurringCandidateConfirmRequest, RecurringItemCreateRequest


@pytest.mark.parametrize(
    ("schema", "amount_field"),
    [
        (RecurringItemCreateRequest, "baseline_amount_cents"),
        (RecurringCandidateConfirmRequest, "amount_cents"),
    ],
)
def test_new_recurring_intent_cannot_silently_choose_a_currency(schema, amount_field):
    with pytest.raises(ValidationError, match="home_currency_code"):
        schema.model_validate({"merchant": "Subscription", amount_field: 1200})


@pytest.mark.parametrize(
    ("schema", "amount_field"),
    [
        (RecurringItemCreateRequest, "baseline_amount_cents"),
        (RecurringCandidateConfirmRequest, "amount_cents"),
    ],
)
def test_new_recurring_intent_keeps_explicit_yen_units(schema, amount_field):
    request = schema.model_validate(
        {"merchant": "Subscription", amount_field: 1200, "home_currency_code": "JPY"},
    )
    assert request.home_currency_code == "JPY"
    assert getattr(request, amount_field) == 1200
