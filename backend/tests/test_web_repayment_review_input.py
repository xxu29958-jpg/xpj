"""Exact reviewed money stays separate from captured money and frozen home value."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.routes._web_repayment_review import _review_error, review_confirmation


def test_unchanged_original_preserves_known_home_amount_but_corrected_money_is_explicit() -> None:
    capture = SimpleNamespace(original_currency_code="CNY", original_amount_minor=10000,
        home_currency_code="USD", amount_cents=1400)
    values = {"target_with_expected_row_version": "debt:7", "original_currency": "CNY", "original_amount": "100.00"}
    unchanged = review_confirmation(values, capture)
    assert unchanged.original_currency is None and unchanged.original_amount is None
    assert "original_amount" not in unchanged.model_dump(exclude_unset=True)
    assert "target_choice_explicit" not in unchanged.model_dump(exclude_unset=True)
    selected = review_confirmation({**values, "target_choice_explicit": "true"}, capture)
    assert selected.target_choice_explicit and selected.target_debt_public_id == "debt"
    reviewed = review_confirmation({**values, "original_amount": "90.00"}, capture)
    assert reviewed.original_currency == "CNY" and reviewed.original_amount == Decimal("90.00")
    assert reviewed.target_debt_public_id == "debt" and reviewed.expected_row_version == 7
    assert capture.original_amount_minor == 10000 and capture.amount_cents == 1400


@pytest.mark.parametrize("currency,amount", [("JPY", "90.01"), ("CNY", "0"), ("CNY", "-1")])
def test_invalid_review_never_reinterprets_money(currency: str, amount: str) -> None:
    captured = SimpleNamespace(original_currency_code="CNY", original_amount_minor=10000)
    with pytest.raises(AppError):
        review_confirmation({"target_with_expected_row_version": "debt:7", "original_currency": currency, "original_amount": amount}, captured)


def test_reused_key_is_not_a_success_or_permission_to_replace_original() -> None:
    error = _review_error(AppError("idempotency_key_reused", status_code=422))
    assert error["result"] == "blocked" and error["rejected"] is False
    assert "不能认定本次处理成功" in error["error"]


def test_reviewed_date_is_explicit_and_does_not_replace_frozen_captured_money() -> None:
    capture = SimpleNamespace(original_currency_code="CNY", original_amount_minor=10000,
        home_currency_code="USD", amount_cents=1400)
    values = {"target_with_expected_row_version": "debt:7", "original_currency": "CNY", "original_amount": "100.00",
        "payment_date": "2026-08-31", "calendar_revision": "3"}
    reviewed = review_confirmation(values, capture)
    assert reviewed.time_input.precision == "date_only"
    assert str(reviewed.time_input.user_local_date) == "2026-08-31" and reviewed.time_input.calendar_revision == 3
    assert reviewed.original_amount is None and reviewed.original_currency is None
    unchanged = review_confirmation({**values, "payment_date": ""}, capture)
    assert "time_input" not in unchanged.model_dump(exclude_unset=True)
    with pytest.raises(AppError):
        review_confirmation({**values, "payment_date": "2026-02-30"}, capture)


@pytest.mark.parametrize("time_fields", [{"payment_date": "", "calendar_revision": "3"}, {}])
def test_native_blank_date_retains_ack_identity_without_backfilling_legacy_input(monkeypatch, time_fields):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routes import web_repayment_drafts as routes

    monkeypatch.setattr(routes, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(routes, "_resolve_selected_ledger_id", lambda *_a, **_k: "ledger")
    monkeypatch.setattr(routes, "_actor_account_id", lambda *_a: 1)
    monkeypatch.setattr(routes, "submit_review", lambda *_a, **kw: kw["values"])
    app = FastAPI()
    app.dependency_overrides[routes.LocalOnly.dependency] = lambda: None
    app.dependency_overrides[routes.get_db] = lambda: None
    app.add_api_route("/{public_id}/review", routes.web_submit_repayment_review, methods=["POST"], response_model=None)
    response = TestClient(app).post("/capture/review", data={"draft_public_id": "capture", "ledger_id": "ledger", **time_fields})
    assert response.status_code == 200
    actual = response.json()
    assert {key: actual[key] for key in ("payment_date", "calendar_revision") if key in actual} == time_fields
