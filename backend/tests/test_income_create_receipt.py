"""Actual income create routes retain one original command and accepted snapshot."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_protocol_writer_context
from app.database import get_db
from app.errors import add_exception_handlers
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.routes import income_plans
from app.services import income_plan_service
from app.services.idempotency import IdempotencyOutcomeKind
from app.services.income_plan_service import _delivery


def _body(**changes):
    return {"label": "Original salary", "source_type": "salary", "frequency": "monthly",
        "amount_cents": 1200, "home_currency_code": "JPY", "pay_day": 10, "intent_month": "2026-09", **changes}


class MemorySession:
    def __init__(self):
        self.rows, self.receipts, self.commits = [], {}, []

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        for index, row in enumerate(self.rows, 1):
            if isinstance(row, MonthlyIncomePlan) and row.id is None:
                row.id, row.public_id, row.row_version = index, str(uuid4()), 1

    def commit(self):
        self.commits.append([row.response_body for row in self.receipts.values()])

    def refresh(self, _row):
        pass

    def scalar(self, _query):
        pytest.fail("Create replay must not reconstruct a receipt from current rows")


@pytest.fixture
def create_probe(monkeypatch):
    db = MemorySession()
    actor = SimpleNamespace(tenant_id="owner", account_id=1)
    def claim(_db, **fields):
        key = fields["tenant_id"], fields["idempotency_key"]
        if key not in db.receipts:
            db.receipts[key] = SimpleNamespace(**fields, response_body=None, resource_id=None)
            return SimpleNamespace(kind=IdempotencyOutcomeKind.PROCEED, row=db.receipts[key])
        row = db.receipts[key]
        kind = (IdempotencyOutcomeKind.HIT if row.request_fingerprint == fields["request_fingerprint"]
            else IdempotencyOutcomeKind.FINGERPRINT_MISMATCH)
        return SimpleNamespace(kind=kind, row=row)
    def accept(_db, row, *, response_body, resource_id, **_fields):
        row.response_body, row.resource_id = response_body, resource_id
    monkeypatch.setattr(_delivery, "claim_idempotency_key", claim)
    monkeypatch.setattr(_delivery, "mark_idempotency_succeeded", accept)
    monkeypatch.setattr(income_plan_service, "resolve_write_capability", lambda _db: None)
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(income_plans.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_protocol_writer_context] = lambda: actor
    with TestClient(app) as client:
        yield client, db, actor


def _post(client, **changes):
    return client.post("/api/income-plans", headers={"Idempotency-Key": "original-income"}, json=_body(**changes))


def test_lost_create_ack_replays_one_plan_revision_and_original_receipt(create_probe):
    client, db, _ = create_probe
    original = _post(client)
    assert original.status_code == 201, original.text
    plan = next(row for row in db.rows if isinstance(row, MonthlyIncomePlan))
    plan.label, plan.amount_cents, plan.status, plan.row_version = "Later edit", 9900, "archived", 3
    replay = _post(client)
    assert replay.status_code == 201, replay.text
    assert replay.json() == original.json()
    assert sum(isinstance(row, MonthlyIncomePlan) for row in db.rows) == 1
    assert sum(isinstance(row, IncomePlanRevision) for row in db.rows) == 1
    assert db.commits == [[original.json()]]


@pytest.mark.parametrize("key", [None, "", "x" * 65])
def test_create_requires_storable_original_key_before_mutation(create_probe, key):
    client, db, _ = create_probe
    headers = {} if key is None else {"Idempotency-Key": key}
    response = client.post("/api/income-plans", headers=headers, json=_body())
    assert response.status_code == 422, response.text
    assert response.json()["error"] == ("idempotency_key_required" if not key else "invalid_request")
    assert db.rows == [] and db.receipts == {} and db.commits == []


@pytest.mark.parametrize("changes", [
    {"amount_cents": 1300}, {"home_currency_code": "CNY"}, {"intent_month": "2026-08"},
    {"label": "Other"}, {"pay_day": 15}, {"source_type": "bonus"},
    {"frequency": "one_time", "income_month": "2026-09"},
])
def test_create_key_cannot_reinterpret_original_intent(create_probe, changes):
    client, db, _ = create_probe
    assert _post(client).status_code == 201
    refused = _post(client, **changes)
    assert refused.status_code == 422 and refused.json()["error"] == "idempotency_key_reused"
    assert len(db.commits) == 1


def test_create_key_captures_actor_and_remains_ledger_scoped(create_probe):
    client, db, actor = create_probe
    original = _post(client)
    actor.account_id = 2
    other_actor = _post(client)
    assert other_actor.status_code == 422 and other_actor.json()["error"] == "idempotency_key_reused"
    actor.tenant_id = "other-ledger"
    other_ledger = _post(client)
    assert other_ledger.status_code == 201
    assert other_ledger.json()["public_id"] != original.json()["public_id"]
    assert len(db.receipts) == 2


def test_in_progress_original_create_cannot_start_another_write(create_probe, monkeypatch):
    client, db, _ = create_probe
    monkeypatch.setattr(_delivery, "claim_idempotency_key", lambda *_a, **_k:
        SimpleNamespace(kind=IdempotencyOutcomeKind.IN_PROGRESS))
    response = _post(client)
    assert response.status_code == 409 and response.json()["error"] == "idempotency_key_in_progress"
    assert db.rows == [] and db.commits == []


@pytest.mark.parametrize("damage", ["missing", "currency", "resource", "shape"])
def test_missing_original_receipt_cannot_fall_back_to_latest_plan(create_probe, damage):
    client, db, _ = create_probe
    assert _post(client).status_code == 201
    receipt = db.receipts["owner", "original-income"]
    if damage == "missing":
        receipt.response_body = None
    elif damage == "currency":
        receipt.response_body.pop("home_currency_code")
    elif damage == "resource":
        receipt.resource_id = "different-plan"
    else:
        receipt.response_body = {"public_id": receipt.resource_id}
    response = _post(client)
    assert response.status_code == 409 and response.json()["error"] == "income_plan_response_unverified"
    assert len(db.commits) == 1
