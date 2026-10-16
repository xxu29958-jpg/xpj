"""PostgreSQL proof that income create, monthly history and original receipt commit together."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, IncomePlanRevision, Ledger, MonthlyIncomePlan
from app.schemas import IncomePlanCreateRequest
from app.services import income_plan_service
from app.services.idempotency import IDEMPOTENCY_STATUS_IN_PROGRESS, fingerprint_request
from app.services.income_plan_service import _delivery
from app.services.time_service import now_utc
from tests._runtime_protocol import current_protocol_headers
from tests.pairing_test_support import invitation_accept_payload


def _body(**changes):
    return {"label": "Salary", "source_type": "salary", "frequency": "monthly",
        "amount_cents": 1200, "home_currency_code": "CNY", "pay_day": 1, "intent_month": "2026-09", **changes}


def _headers(identity, key):
    return {**identity.app_headers, "Idempotency-Key": key}


@pytest.mark.parametrize("frequency", ["monthly", "one_time"])
def test_create_ack_loss_counts_once_and_later_changes_cannot_rewrite_receipt(client, identity, monkeypatch, frequency):
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: datetime(2026, 9, 9, tzinfo=UTC))
    key = str(uuid4())
    body = _body(frequency=frequency, income_month="2026-09" if frequency == "one_time" else None)
    first = client.post("/api/income-plans", headers=_headers(identity, key), json=body)
    assert first.status_code == 201, first.text
    original = first.json()
    replay = client.post("/api/income-plans", headers=_headers(identity, key), json=body)
    assert replay.status_code == 201 and replay.json() == original
    forecast = client.get("/api/income-plans?month=2026-09", headers=identity.app_headers)
    assert forecast.status_code == 200, forecast.text
    assert forecast.json()["expected_amount_cents"] == 1200
    assert forecast.json()["effective_plan_count"] == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 1
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 1
        assert db.scalar(select(func.count()).select_from(ApiIdempotencyKey)
            .where(ApiIdempotencyKey.operation == "create_income_plan")) == 1
    path = f"/api/income-plans/{original['public_id']}"
    edited = client.patch(path, headers=_headers(identity, str(uuid4())), json={
        "expected_row_version": original["row_version"], "intent_month": "2026-09", "amount_cents": 9900,
    })
    assert edited.status_code == 200, edited.text
    archived = client.request("DELETE", path, headers=identity.app_headers, json={
        "expected_row_version": edited.json()["row_version"], "intent_month": "2026-09",
    })
    assert archived.status_code == 200, archived.text
    replay = client.post("/api/income-plans", headers=_headers(identity, key), json=body)
    assert replay.status_code == 201 and replay.json() == original
    with SessionLocal() as db:
        current = db.scalar(select(MonthlyIncomePlan).where(MonthlyIncomePlan.public_id == original["public_id"]))
        assert (current.status, current.amount_cents, current.row_version) == ("archived", 9900, 3)
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert receipt.response_body == original and receipt.resource_id == original["public_id"]
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 3


def test_receipt_failure_rolls_back_plan_revision_and_key(client, identity, monkeypatch):
    key = str(uuid4())
    accept = _delivery.mark_idempotency_succeeded
    def fail_receipt(*_args, **_kwargs):
        raise AppError("server_error", status_code=503)
    monkeypatch.setattr(_delivery, "mark_idempotency_succeeded", fail_receipt)
    failed = client.post("/api/income-plans", headers=_headers(identity, key), json=_body())
    assert failed.status_code == 503, failed.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 0
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
    monkeypatch.setattr(_delivery, "mark_idempotency_succeeded", accept)
    retried = client.post("/api/income-plans", headers=_headers(identity, key), json=_body())
    assert retried.status_code == 201, retried.text


def test_missing_accepted_create_receipt_is_reviewable_not_a_second_create(client, identity):
    key = str(uuid4())
    first = client.post("/api/income-plans", headers=_headers(identity, key), json=_body())
    assert first.status_code == 201, first.text
    original = first.json()
    for body, resource in (
        (None, original["public_id"]),
        ({name: value for name, value in original.items() if name != "home_currency_code"}, original["public_id"]),
        (original, "different-plan"),
        ({"public_id": original["public_id"]}, original["public_id"]),
    ):
        with SessionLocal() as db:
            receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
            receipt.response_body, receipt.resource_id = body, resource
            db.commit()
        replay = client.post("/api/income-plans", headers=_headers(identity, key), json=_body())
        assert replay.status_code == 409 and replay.json()["error"] == "income_plan_response_unverified"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 1
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 1


def test_create_key_is_scoped_to_ledger(client, identity):
    key = str(uuid4())
    original = client.post("/api/income-plans", headers=_headers(identity, key), json=_body())
    other = client.post("/api/income-plans", headers={**identity.gray_app_headers, "Idempotency-Key": key}, json=_body())
    assert original.status_code == other.status_code == 201, (original.text, other.text)
    assert original.json()["public_id"] != other.json()["public_id"]
    invite = client.post("/api/ledgers/owner/invitations", headers=identity.app_headers, json={"role": "member"})
    assert invite.status_code == 201, invite.text
    member = client.post("/api/invitations/accept", json=invitation_accept_payload(invite.json()["invite_token"]))
    assert member.status_code == 200, member.text
    member_headers = current_protocol_headers({"Authorization": f"Bearer {member.json()['session_token']}"})
    reused = client.post("/api/income-plans", headers={**member_headers, "Idempotency-Key": key}, json=_body())
    assert reused.status_code == 422 and reused.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        receipts = db.scalars(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)).all()
        assert {row.tenant_id for row in receipts} == {"owner", "tester_1"}


def test_create_requires_storable_original_key_before_mutation(client, identity):
    for key in (None, "", "x" * 65):
        headers = identity.app_headers if key is None else _headers(identity, key)
        response = client.post("/api/income-plans", headers=headers, json=_body())
        assert response.status_code == 422, response.text
        assert response.json()["error"] == ("idempotency_key_required" if not key else "invalid_request")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 0
        assert db.scalar(select(func.count()).select_from(ApiIdempotencyKey)
            .where(ApiIdempotencyKey.operation == "create_income_plan")) == 0


def test_create_key_cannot_reinterpret_original_intent(client, identity):
    key = str(uuid4())
    original = client.post("/api/income-plans", headers=_headers(identity, key), json=_body())
    assert original.status_code == 201, original.text
    for changes in (
        {"amount_cents": 1300}, {"home_currency_code": "JPY"}, {"intent_month": "2026-08"},
        {"label": "Other"}, {"pay_day": 15}, {"source_type": "bonus"},
        {"frequency": "one_time", "income_month": "2026-09"},
    ):
        refused = client.post("/api/income-plans", headers=_headers(identity, key), json=_body(**changes))
        assert refused.status_code == 422 and refused.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 1
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 1
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert receipt.response_body == original.json()


def test_in_progress_original_create_cannot_start_another_write(client, identity):
    key = str(uuid4())
    with SessionLocal() as db:
        actor = db.scalar(select(Ledger.owner_account_id).where(Ledger.ledger_id == "owner"))
        db.add(ApiIdempotencyKey(tenant_id="owner", idempotency_key=key, operation="create_income_plan",
            target_type="income_plan", target_id=None, status=IDEMPOTENCY_STATUS_IN_PROGRESS,
            request_fingerprint=fingerprint_request(operation="create_income_plan", target_id=None,
                body={"actor_account_id": actor, "intent": IncomePlanCreateRequest(**_body()).model_dump(mode="json")},
                expected_row_version=None), created_at=now_utc(), expires_at=now_utc() + timedelta(days=1)))
        db.commit()
    response = client.post("/api/income-plans", headers=_headers(identity, key), json=_body())
    assert response.status_code == 409 and response.json()["error"] == "idempotency_key_in_progress"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 0
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert receipt.status == IDEMPOTENCY_STATUS_IN_PROGRESS and receipt.response_body is None
