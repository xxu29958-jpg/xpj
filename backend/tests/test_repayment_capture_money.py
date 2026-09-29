"""Captured originals survive FX refusal; human review creates one authoritative repayment."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Repayment
from app.services.debt_service import _money
from tests._infra.currency import activate_test_currency_authority
from tests._runtime_protocol import negotiated_headers


@pytest.mark.currency_binding_unbound
def test_foreign_capture_review_preserves_original_and_replays_one_confirmed_fact(client, identity, monkeypatch):
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "USD")
    headers = negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    created = client.post("/api/debts", headers=headers, json={"home_currency_code": "USD",
        "direction": "i_owe", "counterparty_type": "external", "counterparty_label": "花呗",
        "principal_amount_cents": 10000})
    assert created.status_code == 201, created.json()
    debt = created.json()
    captured_at = "2026-01-12T04:34:56Z"
    captured = client.post("/api/repayment-drafts", headers=identity.app_headers, json={"source": "alipay",
        "original_currency": "CNY", "original_amount": "100.00", "captured_at": captured_at,
        "notification_key": "one-original-cny-payment"})
    assert captured.status_code == 201, captured.json()
    draft = captured.json()
    assert (draft["status"], draft["amount_cents"], draft["home_currency_code"]) == ("pending", None, "USD")
    assert (draft["original_currency_code"], draft["original_amount_minor"]) == ("CNY", 10000)
    target = f"/api/repayment-drafts/{draft['public_id']}"
    request = {"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"],
        "original_currency": "CNY", "original_amount": "90.00"}
    confirm_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    monkeypatch.setattr(_money, "resolve_payload_rate", lambda *args, **kwargs: (None, None, "pending", None))
    refused = client.post(target + "/confirm", headers=confirm_headers, json=request)
    assert (refused.status_code, refused.json()["error"]) == (409, "exchange_rate_pending")
    assert client.get(target, headers=identity.app_headers).json()["status"] == "pending"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Repayment)) == 0
    rate_dates = []

    def available_rate(*args, **kwargs):
        rate_dates.append(kwargs["rate_date"])
        assert (kwargs["home_currency_code"], kwargs["currency_code"]) == ("USD", "CNY")
        return Decimal("0.14"), "isolated-test-rate", "ready", kwargs["rate_date"]

    monkeypatch.setattr(_money, "resolve_payload_rate", available_rate)
    committed = client.post(target + "/confirm", headers=confirm_headers, json=request)
    assert committed.status_code == 201, committed.json()
    replay = client.post(target + "/confirm", headers=confirm_headers, json=request)
    assert replay.status_code == 201 and replay.json() == committed.json()
    assert committed.json()["original_amount_minor"] == 10000  # capture is not rewritten by review
    with SessionLocal() as db:
        fact = db.scalars(select(Repayment)).one()
        assert (fact.amount_cents, fact.original_amount_minor, fact.original_currency_code) == (1260, 9000, "CNY")
        assert fact.paid_at == datetime(2026, 1, 12, 4, 34, 56, tzinfo=UTC)
    assert [value.isoformat() for value in rate_dates] == ["2026-01-12"]
    changed = client.post(target + "/confirm", headers=confirm_headers, json={**request, "original_amount": "100.00"})
    assert (changed.status_code, changed.json()["error"]) == (422, "idempotency_key_reused")
    assert client.get(target, headers=identity.app_headers).json()["status"] == "confirmed"
    history = client.get("/api/repayment-drafts?status=all", headers=identity.app_headers).json()["items"]
    assert [row["public_id"] for row in history] == [draft["public_id"]]
    assert client.get("/api/repayment-drafts", headers=identity.app_headers).json()["items"] == []

    # The existing Android/Web confirm action can also use the unedited captured money.
    second = client.post("/api/repayment-drafts", headers=identity.app_headers, json={"source": "alipay",
        "amount_cents": 2500, "captured_at": captured_at, "notification_key": "another-original-payment"}).json()
    current = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    original = client.post(f"/api/repayment-drafts/{second['public_id']}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": current["row_version"]})
    assert original.status_code == 201, original.json()
    with SessionLocal() as db:
        fact = db.scalar(select(Repayment).where(Repayment.public_id == original.json()["committed_repayment_public_id"]))
        assert (fact.amount_cents, fact.original_amount_minor, fact.original_currency_code) == (350, 2500, "CNY")
