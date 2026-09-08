"""New fixed-expense intentions must name the currency of their entered amount."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import RecurringCandidateConfirmRequest, RecurringItemCreateRequest, RecurringItemUpdateRequest


@pytest.mark.parametrize(
    ("schema", "amount_field", "basis"),
    [
        (RecurringItemCreateRequest, "baseline_amount_cents", {}),
        (RecurringCandidateConfirmRequest, "amount_cents", {}),
        (RecurringItemUpdateRequest, "baseline_amount_cents", {"expected_row_version": 1}),
    ],
)
def test_new_recurring_intent_cannot_silently_choose_a_currency(schema, amount_field, basis):
    with pytest.raises(ValidationError, match="home_currency_code"):
        schema.model_validate({**basis, "merchant": "Subscription", amount_field: 1200})


@pytest.mark.parametrize(
    ("schema", "amount_field", "basis"),
    [
        (RecurringItemCreateRequest, "baseline_amount_cents", {}),
        (RecurringCandidateConfirmRequest, "amount_cents", {}),
        (RecurringItemUpdateRequest, "baseline_amount_cents", {"expected_row_version": 1}),
    ],
)
def test_new_recurring_intent_keeps_explicit_yen_units(schema, amount_field, basis):
    request = schema.model_validate(
        {**basis, "merchant": "Subscription", amount_field: 1200, "home_currency_code": "JPY"},
    )
    assert request.home_currency_code == "JPY"
    assert getattr(request, amount_field) == 1200


def test_recurring_response_keeps_the_recorded_currency_and_minor_units():
    from app.models import RecurringItem
    from app.services.recurring_service import recurring_item_response

    when = datetime(2026, 9, 1, tzinfo=UTC)
    item = RecurringItem(public_id="recurring", tenant_id="owner", merchant_name="Subscription",
        merchant_key="subscription", frequency="monthly", baseline_amount_cents=1200,
        last_amount_cents=1300, occurrence_count=3, home_currency_code="JPY",
        status="active", source="candidate", created_at=when, updated_at=when, row_version=4)
    response = recurring_item_response(item, next_due_date=None)
    assert response.home_currency_code == "JPY"
    assert response.baseline_amount_cents == 1200
    assert response.last_amount_cents == 1300
    assert response.row_version == 4
