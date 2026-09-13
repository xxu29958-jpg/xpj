"""Budget saves must identify both the entered units and the version the user saw."""

import pytest
from pydantic import ValidationError

from app.schemas import BudgetMonthlyUpdateRequest


@pytest.mark.parametrize("missing", ["home_currency_code", "expected_row_version"])
def test_a_budget_save_cannot_omit_its_currency_or_observed_version(missing):
    body = {"total_amount_cents": 1200, "home_currency_code": "JPY", "expected_row_version": None}
    del body[missing]
    with pytest.raises(ValidationError) as error:
        BudgetMonthlyUpdateRequest.model_validate(body)
    assert any(item["loc"] == (missing,) and item["type"] == "missing" for item in error.value.errors())


def test_an_unconfigured_budget_has_an_explicit_absent_version_and_captured_units():
    payload = BudgetMonthlyUpdateRequest.model_validate({
        "total_amount_cents": 1200, "home_currency_code": "JPY", "expected_row_version": None,
    })
    assert payload.home_currency_code == "JPY" and payload.total_amount_cents == 1200
    assert payload.expected_row_version is None


def test_an_existing_budget_cannot_use_an_invented_zero_version():
    with pytest.raises(ValidationError) as error:
        BudgetMonthlyUpdateRequest.model_validate({
            "total_amount_cents": 1200, "home_currency_code": "JPY", "expected_row_version": 0,
        })
    assert any(item["loc"] == ("expected_row_version",) and item["type"] == "greater_than" for item in error.value.errors())
