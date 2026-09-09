"""An acknowledged-late manual rate must retain its own accepted version."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.errors import AppError
from app.schemas import ExchangeRateRequest
from app.services import exchange_rate_service as commands
from app.services.idempotency import IdempotencyOutcomeKind


def _body(**changes):
    return {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-09-08",
        "rate_to_cny": "150", "source": "manual", "expected_row_version": 0, **changes}


def _receipt(**changes):
    return {"public_id": "original-rate", "currency_code": "USD", "home_currency_code": "JPY",
        "rate_date": "2026-09-08", "rate_to_cny": "150.00000000", "source": "manual", "row_version": 1,
        "created_at": "2026-09-08T00:00:00Z", "updated_at": "2026-09-08T00:00:00Z", **changes}


def _call(**changes):
    return commands.set_exchange_rate_idempotently(None, tenant_id="owner", actor_account_id=1,
        payload=ExchangeRateRequest.model_validate(_body(**changes)), idempotency_key="original-key")


def test_manual_rate_requires_an_explicit_nonnegative_original_version():
    body = _body()
    del body["expected_row_version"]
    with pytest.raises(ValidationError, match="expected_row_version"):
        ExchangeRateRequest.model_validate(body)
    for value in (-1, True, 1.5):
        with pytest.raises(ValidationError, match="expected_row_version"):
            ExchangeRateRequest.model_validate(_body(expected_row_version=value))


def test_lost_ack_replays_original_rate_without_reading_or_mutating_current_row(monkeypatch):
    claim = SimpleNamespace(kind=IdempotencyOutcomeKind.HIT,
        row=SimpleNamespace(resource_id="original-rate", response_body=_receipt()))
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *a, **k: claim)
    monkeypatch.setattr(commands, "get_exchange_rate", lambda *a, **k: pytest.fail("cannot read latest on HIT"))
    result = _call()
    assert result.model_dump(mode="json") == _receipt()


@pytest.mark.parametrize("body", [None, {}, _receipt(home_currency_code=None), _receipt(row_version=0),
    _receipt(public_id="other-rate"), _receipt(home_currency_code="CNY"), _receipt(rate_to_cny="151"),
    _receipt(rate_date="2026-09-09"), _receipt(row_version=2)])
def test_unverified_original_receipt_stays_reviewable(monkeypatch, body):
    claim = SimpleNamespace(kind=IdempotencyOutcomeKind.HIT,
        row=SimpleNamespace(resource_id="original-rate", response_body=body))
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *a, **k: claim)
    monkeypatch.setattr(commands, "get_exchange_rate", lambda *a, **k: pytest.fail("cannot invent receipt from latest"))
    with pytest.raises(AppError) as caught:
        _call()
    assert (caught.value.error, caught.value.status_code) == ("exchange_rate_response_unverified", 409)


@pytest.mark.parametrize("change", [{"currency_code": "EUR"}, {"home_currency_code": "CNY"},
    {"rate_date": "2026-09-09"}, {"rate_to_cny": "151"}, {"source": "bank"}, {"expected_row_version": 1}])
def test_every_original_command_field_participates_in_the_fingerprint(monkeypatch, change):
    fingerprints = []

    def refuse(*a, **kwargs):
        fingerprints.append(kwargs["request_fingerprint"])
        return SimpleNamespace(kind=IdempotencyOutcomeKind.FINGERPRINT_MISMATCH)

    monkeypatch.setattr(commands, "claim_idempotency_key", refuse)
    for changes in ({}, change):
        with pytest.raises(AppError) as caught:
            _call(**changes)
        assert caught.value.error == "idempotency_key_reused"
    assert fingerprints[0] != fingerprints[1]


def test_actor_participates_in_the_original_fingerprint(monkeypatch):
    fingerprints = []

    def refuse(*a, **kwargs):
        fingerprints.append(kwargs["request_fingerprint"])
        return SimpleNamespace(kind=IdempotencyOutcomeKind.IN_PROGRESS)

    monkeypatch.setattr(commands, "claim_idempotency_key", refuse)
    for actor in (1, 2):
        with pytest.raises(AppError) as caught:
            commands.set_exchange_rate_idempotently(None, tenant_id="owner", actor_account_id=actor,
                payload=ExchangeRateRequest.model_validate(_body()), idempotency_key="original-key")
        assert caught.value.error == "idempotency_key_in_progress"
    assert fingerprints[0] != fingerprints[1]
