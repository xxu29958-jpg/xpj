"""An unsubmitted manual expense retains the money basis the user saw."""

import pytest

from app.errors import AppError


def test_native_old_form_without_captured_home_is_blocked_with_inputs_preserved():
    from app.routes.web_expense_create import _manual_expense_failure, _manual_expense_payload

    with pytest.raises(AppError) as error:
        _manual_expense_payload(amount_major="12", currency_code="JPY", merchant="", category="餐饮",
            note="", spent_at="2026-09-09T12:00", client_ref="a" * 32, home_currency="")
    assert error.value.error == "manual_currency_context_required"
    assert _manual_expense_failure(error.value)[1:] == (409, "blocked")
