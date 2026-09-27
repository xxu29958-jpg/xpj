"""Original void receipts remain recoverable independently of later Debt reads."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, Debt, DebtVoid, Repayment, RepaymentVoid
from app.services import debt_command_service
from tests.test_debt_void import _create_debt, _record_repayment


def _void_request(client: TestClient, identity, kind: str) -> tuple[dict, str, dict, dict]:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    request = {"reason": "原记录有误", "expected_row_version": debt["row_version"]}
    if kind == "repayment-voids":
        repaid = _record_repayment(client, identity, debt["public_id"], 1000, debt["row_version"])
        request.update(repayment_public_id=repaid["repayment_public_id"], expected_row_version=repaid["row_version"])
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    route = f"/api/debts/{debt['public_id']}/{kind}"
    return debt, route, request, headers


def _original_void(client: TestClient, identity, kind: str) -> tuple[dict, str, dict, dict]:
    _debt, route, request, headers = _void_request(client, identity, kind)
    accepted = client.post(route, headers=headers, json=request)
    assert accepted.status_code == 201, accepted.json()
    return accepted.json(), route, request, headers


def _assert_one_original_fact(public_id: str, kind: str, key: str) -> None:
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        assert debt is not None
        if kind == "repayment-voids":
            facts = select(func.count()).select_from(RepaymentVoid).join(Repayment).where(Repayment.debt_id == debt.id)
        else:
            facts = select(func.count()).select_from(DebtVoid).where(DebtVoid.debt_id == debt.id)
        assert db.scalar(facts) == 1
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is not None


def test_recovered_repayment_void_returns_its_original_acceptance_after_another_payment(
    client: TestClient, *, identity,
) -> None:
    accepted, route, request, headers = _original_void(client, identity, "repayment-voids")
    later = _record_repayment(client, identity, accepted["public_id"], 2000, accepted["row_version"])
    assert later["paid_amount_cents"] == 2000
    assert accepted["paid_amount_cents"] == 0

    replayed = client.post(route, headers=headers, json=request)

    assert replayed.status_code == 201, replayed.json()
    assert replayed.json() == accepted, "An original void receipt cannot become a later payment's result"
    current = client.get(f"/api/debts/{accepted['public_id']}", headers=identity.app_headers).json()
    assert current["paid_amount_cents"] == 2000
    assert current["row_version"] == later["row_version"]
    _assert_one_original_fact(accepted["public_id"], "repayment-voids", headers["Idempotency-Key"])


@pytest.mark.parametrize("kind", ["void", "repayment-voids"])
def test_accepted_void_can_be_recovered_while_its_current_query_is_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, kind: str, *, identity,
) -> None:
    accepted, route, request, headers = _original_void(client, identity, kind)

    def unavailable_query(*args, **kwargs):
        raise AppError("debt_query_unavailable", status_code=503)

    monkeypatch.setattr(debt_command_service, "get_debt_response", unavailable_query)
    replayed = client.post(route, headers=headers, json=request)

    assert replayed.status_code == 201, "A failed display query cannot prevent recovery of the accepted original"
    assert replayed.json() == accepted
    _assert_one_original_fact(accepted["public_id"], kind, headers["Idempotency-Key"])
    with SessionLocal() as db:
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == headers["Idempotency-Key"]))
        assert receipt is not None and receipt.response_body == accepted


@pytest.mark.parametrize("kind", ["void", "repayment-voids"])
def test_void_and_original_receipt_are_committed_together_or_not_at_all(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, kind: str, *, identity,
) -> None:
    debt, route, request, headers = _void_request(client, identity, kind)
    before = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    real_query = debt_command_service.get_debt_response

    def unavailable_receipt(*args, **kwargs):
        raise AppError("debt_receipt_unavailable", status_code=503)

    monkeypatch.setattr(debt_command_service, "get_debt_response", unavailable_receipt)
    rejected = client.post(route, headers=headers, json=request)
    assert rejected.status_code == 503
    with SessionLocal() as db:
        parent = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        assert parent is not None and parent.row_version == request["expected_row_version"]
        assert db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == headers["Idempotency-Key"])) is None
        assert db.scalar(select(DebtVoid).where(DebtVoid.debt_id == parent.id)) is None
        assert db.scalar(select(RepaymentVoid).join(Repayment).where(Repayment.debt_id == parent.id)) is None
    current = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert current == before, "A missing durable original receipt must not leave a half-accepted void"
    monkeypatch.setattr(debt_command_service, "get_debt_response", real_query)
    accepted = client.post(route, headers=headers, json=request)
    assert accepted.status_code == 201, accepted.json()
    _assert_one_original_fact(debt["public_id"], kind, headers["Idempotency-Key"])


@pytest.mark.parametrize("kind", ["void", "repayment-voids"])
def test_legacy_void_without_original_receipt_is_explicit_and_never_rewritten(
    client: TestClient, kind: str, *, identity,
) -> None:
    accepted, route, request, headers = _original_void(client, identity, kind)
    with SessionLocal() as db:
        original = db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == headers["Idempotency-Key"]))
        assert original is not None
        original.response_body = None  # The pre-receipt command stored its accepted key and fact only.
        db.commit()
    recovered = client.post(route, headers=headers, json=request)
    assert recovered.status_code == 409
    assert recovered.json()["error"] == "debt_void_original_requires_review"
    current = client.get(f"/api/debts/{accepted['public_id']}", headers=identity.app_headers)
    assert current.status_code == 200 and current.json() == accepted
    _assert_one_original_fact(accepted["public_id"], kind, headers["Idempotency-Key"])
