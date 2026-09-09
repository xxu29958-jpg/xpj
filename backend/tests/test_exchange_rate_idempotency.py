"""Real rate commands retain their original result across correction and ACK loss."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, ExchangeRate
from app.schemas import ExchangeRateRequest
from app.services import exchange_rate_service as commands
from tests._runtime_protocol import negotiated_headers


def _body(**changes):
    return {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-09-08",
        "rate_to_cny": "150", "source": "manual", "expected_row_version": 0, **changes}


def _put(client, identity, *, key=None, body=None):
    body = body or _body()
    headers = {**identity.app_headers, "Idempotency-Key": key or str(uuid4())}
    return client.put(f"/api/exchange-rates/{body['currency_code']}/{body['rate_date']}",
        headers=negotiated_headers(client, headers), json=body)


@pytest.mark.parametrize("key", [None, "", "x" * 65])
def test_missing_or_unstorable_key_cannot_write_a_rate(client, identity, key):
    headers = dict(identity.app_headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    response = client.put("/api/exchange-rates/USD/2026-09-08",
        headers=negotiated_headers(client, headers), json=_body())
    assert response.status_code == 422, response.text
    assert response.json()["error"] == ("invalid_request" if key and len(key) > 64 else "idempotency_key_required")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExchangeRate)) == 0


def test_missing_occ_is_rejected_before_any_fact_or_receipt(client, identity):
    body = _body()
    del body["expected_row_version"]
    response = _put(client, identity, body=body)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExchangeRate)) == 0


def test_original_create_and_correction_replay_their_own_receipt_after_later_updates(client, identity):
    create_key, edit_key = str(uuid4()), str(uuid4())
    created = _put(client, identity, key=create_key)
    assert created.status_code == 200, created.text
    edit_body = _body(rate_to_cny="151", expected_row_version=created.json()["row_version"])
    edited = _put(client, identity, key=edit_key, body=edit_body)
    assert edited.status_code == 200, edited.text
    latest = _put(client, identity, body=_body(rate_to_cny="152", expected_row_version=edited.json()["row_version"]))
    assert latest.status_code == 200, latest.text
    assert latest.json()["row_version"] == 3
    assert _put(client, identity, key=create_key).json() == created.json()
    assert _put(client, identity, key=edit_key, body=edit_body).json() == edited.json()
    with SessionLocal() as db:
        row = db.scalar(select(ExchangeRate))
        assert (row.rate_to_cny, row.row_version) == (152, 3)
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == create_key))
        assert receipt.response_body == created.json()


@pytest.mark.parametrize("change", [{"currency_code": "EUR"}, {"home_currency_code": "CNY"},
    {"rate_date": "2026-09-09"}, {"rate_to_cny": "151"}, {"source": "bank"}, {"expected_row_version": 1}])
def test_reused_key_cannot_change_the_original_money_or_occ(client, identity, change):
    key = str(uuid4())
    assert _put(client, identity, key=key).status_code == 200
    changed = _put(client, identity, key=key, body=_body(**change))
    assert changed.status_code == 422, changed.text
    assert changed.json()["error"] == "idempotency_key_reused"


def test_new_create_or_stale_correction_cannot_overwrite_current_rate(client, identity):
    first = _put(client, identity)
    assert first.status_code == 200, first.text
    corrected = _put(client, identity, body=_body(rate_to_cny="151", expected_row_version=1))
    assert corrected.status_code == 200, corrected.text
    for version in (0, 1):
        stale = _put(client, identity, body=_body(rate_to_cny="149", expected_row_version=version))
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"] == "state_conflict"
    missing = _put(client, identity, body=_body(rate_date="2026-09-07", expected_row_version=1))
    assert missing.status_code == 409, missing.text
    with SessionLocal() as db:
        assert (db.scalar(select(ExchangeRate.rate_to_cny)), db.scalar(select(ExchangeRate.row_version))) == (151, 2)


def test_exact_date_query_returns_original_pair_and_version_without_a_recent_limit_guess(client, identity):
    original = _put(client, identity, body=_body(rate_date="2020-01-01"))
    assert original.status_code == 200, original.text
    assert _put(client, identity, body=_body(home_currency_code="CNY", rate_to_cny="7")).status_code == 200
    query = "/api/exchange-rates?currency_code=USD&home_currency_code=JPY&rate_date=2020-01-01&limit=1"
    assert client.get(query, headers=identity.app_headers).json()["items"] == [original.json()]
    assert client.get(query, headers=identity.gray_app_headers).json()["items"] == []
    assert client.get(query.replace("2020-01-01", "2020-01-02"), headers=identity.app_headers).json()["items"] == []


def test_same_key_in_another_ledger_has_its_own_rate_and_receipt(client, identity):
    key = str(uuid4())
    original = _put(client, identity, key=key)
    other = client.put("/api/exchange-rates/USD/2026-09-08",
        headers=negotiated_headers(client, {**identity.gray_app_headers, "Idempotency-Key": key}), json=_body())
    assert original.status_code == other.status_code == 200, (original.text, other.text)
    assert original.json()["public_id"] != other.json()["public_id"]
    assert _put(client, identity, key=key).json() == original.json()


def test_receipt_failure_rolls_back_both_insert_and_claim_then_original_can_retry(client, identity, monkeypatch):
    key = str(uuid4())
    original = commands.mark_idempotency_succeeded

    def fail_receipt(*args, **kwargs):
        raise AppError("server_error", status_code=503)

    monkeypatch.setattr(commands, "mark_idempotency_succeeded", fail_receipt)
    response = _put(client, identity, key=key)
    assert response.status_code == 503, response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExchangeRate)) == 0
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
    monkeypatch.setattr(commands, "mark_idempotency_succeeded", original)
    assert _put(client, identity, key=key).status_code == 200


def test_missing_original_response_cannot_be_replaced_with_latest(client, identity):
    key = str(uuid4())
    assert _put(client, identity, key=key).status_code == 200
    with SessionLocal() as db:
        row = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        row.response_body = None
        db.commit()
    replay = _put(client, identity, key=key)
    assert replay.status_code == 409, replay.text
    assert replay.json()["error"] == "exchange_rate_response_unverified"


@pytest.mark.parametrize("version", [0, 1])
def test_concurrent_original_creates_or_corrections_only_accept_one_version(client, identity, version):
    if version:
        assert _put(client, identity).status_code == 200
    barrier = Barrier(2)

    def submit(rate):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                result = commands.set_exchange_rate_idempotently(db, tenant_id="owner", actor_account_id=None,
                    payload=ExchangeRateRequest.model_validate(_body(rate_to_cny=rate, expected_row_version=version)),
                    idempotency_key=str(uuid4()))
                return result.row_version
            except AppError as exc:
                db.rollback()
                return exc.error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, ["151", "152"]))
    assert results.count(version + 1) == results.count("state_conflict") == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExchangeRate)) == 1
        assert db.scalar(select(ExchangeRate.row_version)) == version + 1
