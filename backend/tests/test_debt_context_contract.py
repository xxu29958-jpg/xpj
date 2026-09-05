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
