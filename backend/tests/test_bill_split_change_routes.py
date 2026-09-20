"""HTTP adapters retain protocol admission and pass signed, versioned intent."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_app_context, get_current_protocol_writer_context
from app.database import get_db
from app.errors import AppError, add_exception_handlers
from app.routes import debt_split_changes
from app.services.bill_split_service._agreement_queries import get_bill_split_agreement
from tests.test_bill_split_agreement_commands import agreement_db as agreement_db
from tests.test_bill_split_change_command_receipts import create


@pytest.fixture
def http(agreement_db, monkeypatch):
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(debt_split_changes.router)
    actor = SimpleNamespace(tenant_id="receiver-private", account_id=1)
    app.dependency_overrides[get_db] = lambda: agreement_db
    app.dependency_overrides[get_current_app_context] = lambda: actor
    app.dependency_overrides[get_current_protocol_writer_context] = lambda: actor
    calls = []
    proposal = create(agreement_db)
    agreement = get_bill_split_agreement(agreement_db, tenant_id=actor.tenant_id, actor_account_id=1, public_id="original")

    def capture(name, result):
        def call(db, **kwargs):
            calls.append((name, kwargs))
            return result
        return call

    monkeypatch.setattr(debt_split_changes, "get_bill_split_agreement", capture("read", agreement))
    for name in ("create", "accept", "reject", "withdraw"):
        monkeypatch.setattr(debt_split_changes, f"{name}_bill_split_change_idempotently",
            capture(name, agreement if name == "accept" else proposal))
    with TestClient(app) as client:
        yield client, calls, app


def test_preview_and_signed_proposal_reach_the_same_owner(http):
    client, calls, _ = http
    result = client.get("/api/debts/original/split-agreement?new_share_amount_cents=2500")
    assert result.status_code == 200
    assert calls[-1][1]["new_share_amount_cents"] == 2500
    payload = {"new_share_amount_cents": 2500, "settlement_net_amount_cents": -1500,
        "reason": "Refund", "expected_row_version": 4, "expected_return_row_version": 2}
    result = client.post("/api/debts/original/split-change-proposals", json=payload,
        headers={"Idempotency-Key": "frozen-intent"})
    assert result.status_code == 201
    assert calls[-1][1]["payload"].model_dump(exclude_none=True) == payload
    assert calls[-1][1]["actor_account_id"] == 1
    assert calls[-1][1]["idempotency_key"] == "frozen-intent"


@pytest.mark.parametrize("action", ["accept", "reject", "withdraw"])
def test_terminal_route_preserves_parent_proposal_and_key(http, action):
    client, calls, _ = http
    payload = {"expected_row_version": 4, "expected_return_row_version": 2} if action == "accept" else {}
    result = client.post(f"/api/debts/original/split-change-proposals/proposal/{action}",
        json=payload, headers={"Idempotency-Key": "frozen-terminal"})
    assert result.status_code == 200
    assert calls[-1][0] == action
    assert calls[-1][1]["proposal_public_id"] == "proposal"
    assert calls[-1][1]["public_id"] == "original"
    assert calls[-1][1]["idempotency_key"] == "frozen-terminal"


def test_protocol_refusal_precedes_money_writer(http):
    client, calls, app = http

    def refuse():
        raise AppError("permission_denied", status_code=403)

    app.dependency_overrides[get_current_protocol_writer_context] = refuse
    result = client.post("/api/debts/original/split-change-proposals/proposal/accept",
        json={"expected_row_version": 1}, headers={"Idempotency-Key": "not-admitted"})
    assert result.status_code == 403
    assert calls == []
