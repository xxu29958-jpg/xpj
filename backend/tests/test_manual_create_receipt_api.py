"""PostgreSQL manual facts and original response receipts commit together."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, CategoryPreference, Expense, ExpenseRevision, ExpenseTag, Tag
from app.schemas import ExpenseManualCreateRequest
from app.services.expense_service import _create as owner
from app.services.identity_service import authenticate_session_token
from tests.expense_correction_support import idem


def _body(**changes):
    return {"client_ref": "original-manual", "home_currency_code": "CNY", "amount_cents": 1200,
        "merchant": "Original merchant", "category": "餐饮", "expense_time": "2026-09-09T00:00:00Z", **changes}


def _post(client, identity, body):
    return client.post("/api/expenses/manual", headers=identity.app_headers, json=body)


def test_original_create_response_survives_later_fact_correction(client, identity):
    body = _body(client_ref="r" * 64)
    first = _post(client, identity, body)
    assert first.status_code == 200, first.text
    accepted = first.json()
    changed = client.post(f"/api/expenses/{accepted['id']}/corrections", headers=idem(identity.app_headers),
        json={"expected_row_version": accepted["row_version"], "reason": "Actual amount corrected",
            "amount_cents": 3400, "merchant": "Corrected merchant"})
    assert changed.status_code == 201, changed.text
    assert changed.json()["expense"]["row_version"] > accepted["row_version"]
    replay = _post(client, identity, body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == accepted
    with SessionLocal() as db:
        assert db.get(Expense, accepted["id"]).amount_cents == 3400
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.operation == "create_manual_expense"))
        assert claim.response_body == accepted
        assert db.scalar(select(func.count()).select_from(Expense)) == 1


def test_pending_first_receipt_stays_pending_after_fx_and_confirmation(client, identity):
    body = _body()
    body.pop("amount_cents")
    body.update(original_currency="JPY", original_amount="12")
    first = _post(client, identity, body)
    assert first.status_code == 200, first.text
    accepted = first.json()
    assert (accepted["status"], accepted["fx_status"], accepted["amount_cents"], accepted["fact_revision"]) == (
        "pending", "pending", None, 0)
    rate = client.put("/api/exchange-rates/JPY/2026-09-09", headers=idem(identity.app_headers), json={
        "currency_code": "JPY", "home_currency_code": "CNY", "rate_date": "2026-09-09",
        "rate_to_cny": "0.05", "source": "manual", "expected_row_version": 0})
    assert rate.status_code == 200, rate.text
    unresolved = client.post(f"/api/expenses/{accepted['id']}/confirm", headers=idem(identity.app_headers),
        json={"expected_row_version": accepted["row_version"]})
    assert unresolved.status_code == 409, unresolved.text
    assert unresolved.json()["error"] == "exchange_rate_pending"
    reviewed = client.patch(f"/api/expenses/{accepted['id']}", headers=idem(identity.app_headers),
        json={"expected_row_version": accepted["row_version"],
            "original_currency_code": "JPY", "original_amount_minor": 12})
    assert reviewed.status_code == 200, reviewed.text
    assert (reviewed.json()["status"], reviewed.json()["fx_status"], reviewed.json()["amount_cents"]) == (
        "pending", "ready", 60)
    assert reviewed.json()["row_version"] > accepted["row_version"]
    confirmed = client.post(f"/api/expenses/{accepted['id']}/confirm", headers=idem(identity.app_headers),
        json={"expected_row_version": reviewed.json()["row_version"]})
    assert confirmed.status_code == 200, confirmed.text
    assert (confirmed.json()["status"], confirmed.json()["amount_cents"]) == ("confirmed", 60)
    replay = _post(client, identity, body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == accepted
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExpenseRevision)) == 1
        assert db.get(Expense, accepted["id"]).fact_revision == 1


@pytest.mark.parametrize("step", ["expense_to_response", "mark_idempotency_succeeded"])
def test_response_failure_rolls_back_fact_revision_associations_and_claim(client, identity, monkeypatch, step):
    tables = (Expense, ExpenseRevision, ExpenseTag, Tag, CategoryPreference, ApiIdempotencyKey)
    with SessionLocal() as db:
        before = [db.scalar(select(func.count()).select_from(table)) for table in tables]
    original = getattr(owner, step)
    def fail(*_args, **_kwargs):
        raise AppError("server_error", status_code=503)
    monkeypatch.setattr(owner, step, fail)
    body = _body(category="Receipt rollback category", tags="Receipt rollback tag")
    refused = _post(client, identity, body)
    assert refused.status_code == 503, refused.text
    with SessionLocal() as db:
        assert [db.scalar(select(func.count()).select_from(table)) for table in tables] == before
    monkeypatch.setattr(owner, step, original)
    retry = _post(client, identity, body)
    assert retry.status_code == 200, retry.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == before[0] + 1
        assert db.scalar(select(func.count()).select_from(ExpenseRevision)) == before[1] + 1
        assert db.scalar(select(func.count()).select_from(ExpenseTag)) > before[2]


@pytest.mark.real_db
def test_concurrent_same_original_key_returns_one_fact_and_identical_receipts(client, identity):
    barrier = Barrier(2)
    payload = ExpenseManualCreateRequest(**_body(client_ref=str(uuid4())))
    def submit(_index):
        with SessionLocal() as db:
            auth = authenticate_session_token(db, identity.app_token, {"app"})
            barrier.wait(timeout=10)
            return owner.create_manual_expense(db, payload, auth).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(submit, range(2)))
    assert first == second
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 1
        assert db.scalar(select(func.count()).select_from(ExpenseRevision)) == 1
        claims = db.scalars(select(ApiIdempotencyKey).where(ApiIdempotencyKey.operation == "create_manual_expense")).all()
        assert len(claims) == 1 and claims[0].response_body == first


def test_missing_saved_receipt_requires_review_without_current_state_fallback(client, identity):
    first = _post(client, identity, _body())
    assert first.status_code == 200, first.text
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.operation == "create_manual_expense"))
        claim.response_body = None
        db.commit()
    replay = _post(client, identity, _body())
    assert replay.status_code == 409, replay.text
    assert (replay.json()["error"], replay.json()["expense_id"]) == (
        "manual_create_original_requires_review", first.json()["id"])
