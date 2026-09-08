"""Debt creation retains its money meaning through negotiation and old receipts."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Debt, Repayment
from app.services.exchange_rate_service import upsert_exchange_rate
from app.services.idempotency import fingerprint_request
from tests._runtime_protocol import negotiated_headers

_BODY = {"direction": "owed_to_me", "counterparty_type": "external", "counterparty_label": "Alex", "principal_amount_cents": 1200}


def test_debt_creation_uses_the_intent_currency_instead_of_the_current_default(client: TestClient, identity):
    key = str(uuid4())
    body = {**_BODY, "home_currency_code": "JPY"}
    headers = {**identity.app_headers, "Idempotency-Key": key}
    response = client.post("/api/debts", headers=negotiated_headers(client, headers), json=body)
    assert response.status_code == 201, response.json()
    assert response.json()["home_currency_code"] == "JPY"
    assert response.json()["principal_amount_cents"] == 1200
    repeated = client.post("/api/debts", headers=negotiated_headers(client, headers), json=body)
    assert repeated.status_code == 201, repeated.json()
    assert repeated.json()["public_id"] == response.json()["public_id"]
    changed = client.post("/api/debts", headers=negotiated_headers(client, headers), json={**body, "home_currency_code": "CNY"})
    assert changed.status_code == 422
    assert changed.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 1


def test_foreign_repayment_uses_the_parent_currency_and_rate_pair(client: TestClient, identity):
    created = client.post("/api/debts", headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())}),
                          json={**_BODY, "home_currency_code": "JPY"})
    assert created.status_code == 201, created.json()
    with SessionLocal() as db:
        for home, rate in (("CNY", "7"), ("JPY", "150")):
            upsert_exchange_rate(db, tenant_id="owner", currency_code="USD", home_currency_code=home,
                                 rate_date=date(2026, 9, 8), rate_to_cny=Decimal(rate))
    public_id = created.json()["public_id"]
    paid = client.post(f"/api/debts/{public_id}/repayments",
                       headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
                       json={"original_currency": "USD", "original_amount": "1",
                             "paid_at": "2026-09-08T02:00:00Z", "expected_row_version": created.json()["row_version"]})
    assert paid.status_code == 201, paid.json()
    assert paid.json()["home_currency_code"] == "JPY"
    assert paid.json()["paid_amount_cents"] == 150
    assert paid.json()["remaining_amount_cents"] == 1050
    with SessionLocal() as db:
        repayment = db.scalar(select(Repayment))
        assert repayment.original_currency_code == "USD"
        assert repayment.original_amount_minor == 100
        assert repayment.exchange_rate_to_cny == Decimal("150")


def test_old_accepted_debt_replays_only_with_its_original_request_and_currency(client: TestClient, identity):
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    response = client.post("/api/debts", headers=negotiated_headers(client, headers), json={**_BODY, "home_currency_code": "CNY"})
    assert response.status_code == 201, response.json()
    with SessionLocal() as db:
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        debt = db.scalar(select(Debt).where(Debt.public_id == response.json()["public_id"]))
        assert receipt is not None and debt is not None
        # Model the released receipt shape; the financial fact stays unchanged.
        old_fingerprint = fingerprint_request(
            operation=receipt.operation, target_id=key,
            body={**_BODY, "actor_account_id": debt.created_by_account_id}, expected_row_version=None,
        )
        receipt.request_fingerprint = old_fingerprint
        db.commit()
    repeated = client.post("/api/debts", headers=negotiated_headers(client, headers), json={**_BODY, "home_currency_code": "CNY"})
    assert repeated.status_code == 201, repeated.json()
    assert repeated.json() == response.json()
    for changed in ({"home_currency_code": "JPY"}, {"principal_amount_cents": 1300}):
        rejected = client.post("/api/debts", headers=negotiated_headers(client, headers), json={**_BODY, "home_currency_code": "CNY", **changed})
        assert rejected.status_code == 422
        assert rejected.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 1
        assert db.scalar(select(ApiIdempotencyKey.request_fingerprint).where(ApiIdempotencyKey.idempotency_key == key)) == old_fingerprint
