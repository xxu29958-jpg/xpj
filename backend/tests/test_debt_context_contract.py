"""Pure request boundary for optional external-debt context."""

import pytest
from pydantic import ValidationError

from app.schemas import DebtCreateRequest


def test_create_note_is_optional_and_bounded() -> None:
    fields = {
        "direction": "i_owe",
        "counterparty_type": "external",
        "counterparty_label": "同行人",
        "principal_amount_cents": 1200,
    }
    request = DebtCreateRequest(**fields, note="出差垫付的车费")
    assert request.note == "出差垫付的车费"
    assert request.model_dump(exclude_unset=True)["note"] == request.note
    assert DebtCreateRequest(**fields).note is None
    assert DebtCreateRequest(**fields, note=None).note is None
    assert DebtCreateRequest(**fields, note="事" * 500).note == "事" * 500
    with pytest.raises(ValidationError):
        DebtCreateRequest(**fields, note="事" * 501)


@pytest.mark.parametrize("separator", ["\r\n", "\r", "\n"])
def test_web_note_length_uses_textarea_newlines(separator: str) -> None:
    from app.routes.web_debt_create import _create_payload

    fields = {
        "direction": "i_owe",
        "counterparty_label": "同行人",
        "amount_major": "12.00",
        "currency_code": "CNY",
        "event_time": "2026-09-05T12:00",
        "debt_kind": "one_off",
        "installment_count": "",
        "installment_period_months": "",
        "home_currency": "CNY",
    }
    submitted_note = "事" * 249 + separator + "事" * 250
    request = _create_payload(**fields, note=submitted_note)
    assert request.note == "事" * 249 + "\n" + "事" * 250
    with pytest.raises(ValidationError):
        _create_payload(**fields, note=submitted_note + "事")
