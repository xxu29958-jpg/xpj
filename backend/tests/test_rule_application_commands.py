"""Accepted application receipts protect retries, later facts and the commit boundary."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from api_contract_helpers import insert_confirmed_expense
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, LedgerMember, RuleApplicationBatch
from app.services.currency_binding_service import resolve_write_capability
from app.services.rule_application_service import _commands


def _expense(status: str) -> int:
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    expense_id = insert_confirmed_expense(amount_cents=1200, merchant="OriginalApplication", category="其他",
        expense_time=now, confirmed_at=now)
    if status == "pending":
        with SessionLocal() as db:
            resolve_write_capability(db)
            db.get(Expense, expense_id).status = "pending"
            db.get(Expense, expense_id).confirmed_at = None
            db.commit()
    return expense_id


def _preview(client, headers, status):
    path = "/api/rules/apply-pending/preview" if status == "pending" else "/api/rules/apply-confirmed"
    response = client.post(path, headers=headers)
    assert response.status_code == 200, response.text
    return {"confirm": True, "preview_token": response.json()["preview_token"]}


@pytest.mark.real_db
@pytest.mark.parametrize("status", ["pending", "confirmed"])
def test_original_application_concurrent_replay_retains_first_result_and_later_facts(client, identity, status):
    expense_id = _expense(status)
    created = client.post("/api/rules/categories", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"keyword": "OriginalApplication", "category": "餐饮"})
    assert created.status_code == 200, created.text
    path = f"/api/rules/apply-{status}"
    body = _preview(client, identity.app_headers, status)
    missing = client.post(path, headers=identity.app_headers, json=body)
    assert missing.status_code == 422 and missing.json()["error"] == "idempotency_key_required"
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(client.post, path, headers=headers, json=body) for _ in range(2)]
        first, second = [request.result(timeout=10) for request in requests]
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json()
    receipt = first.json()
    assert receipt["command_key"] == key and receipt["changed_count"] == 1
    with SessionLocal() as db:
        resolve_write_capability(db)
        batch = db.scalar(select(RuleApplicationBatch).where(RuleApplicationBatch.public_id == receipt["application_public_id"]))
        assert batch is not None and batch.changed_count == 1
        stored = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert stored.response_body == receipt and stored.resource_id == batch.public_id
        expense = db.get(Expense, expense_id)
        assert expense.category == "餐饮" and expense.status == status
        expense.category = "医疗"
        expense.row_version += 1
        later_version = expense.row_version
        db.commit()
    replay = client.post(path, headers=headers, json=body)
    assert replay.status_code == 200 and replay.json() == receipt
    mismatch = client.post(path, headers=headers, json={**body, "preview_token": "different-preview"})
    assert mismatch.status_code == 422 and mismatch.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.category == "医疗" and expense.row_version == later_version
        assert len(list(db.scalars(select(RuleApplicationBatch)))) == 1
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        member.role = "viewer"
        db.commit()
    assert client.post(path, headers=headers, json=body).status_code == 403


@pytest.mark.parametrize("status", ["pending", "confirmed"])
def test_zero_change_receipt_does_not_reinterpret_later_candidates(client, identity, status):
    path = f"/api/rules/apply-{status}"
    body = _preview(client, identity.app_headers, status)
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    first = client.post(path, headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["changed_count"] == 0 and first.json()["application_public_id"] is None
    expense_id = _expense(status)
    replay = client.post(path, headers=headers, json=body)
    assert replay.status_code == 200 and replay.json() == first.json()
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).category == "其他"
        assert list(db.scalars(select(RuleApplicationBatch))) == []


@pytest.mark.real_db
def test_application_fact_and_original_receipt_commit_together(client, identity, monkeypatch):
    expense_id = _expense("confirmed")
    created = client.post("/api/rules/categories", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"keyword": "OriginalApplication", "category": "餐饮"})
    assert created.status_code == 200, created.text
    body = _preview(client, identity.app_headers, "confirmed")
    key = str(uuid4())
    def fail_receipt(*args, **kwargs):
        raise AppError("synthetic_receipt_failure", status_code=409)
    with monkeypatch.context() as patch:
        patch.setattr(_commands, "mark_idempotency_succeeded", fail_receipt)
        failed = client.post("/api/rules/apply-confirmed", headers={**identity.app_headers, "Idempotency-Key": key}, json=body)
    assert failed.status_code == 409
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).category == "其他"
        assert list(db.scalars(select(RuleApplicationBatch))) == []
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
    accepted = client.post("/api/rules/apply-confirmed", headers={**identity.app_headers, "Idempotency-Key": key}, json=body)
    assert accepted.status_code == 200 and accepted.json()["changed_count"] == 1


@pytest.mark.parametrize("status", ["pending", "confirmed"])
def test_public_web_application_binding_csrf_and_current_permission_guard_original_receipt(client, identity, status):
    from app.routes.web_auth import SESSION_COOKIE_NAME
    from tests._infra.merchant_catalog import demote_owner_ledger_to_viewer
    from tests._web_native_form_support import hidden_post_forms
    from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

    expense_id = _expense(status)
    created = client.post("/api/rules/categories", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"keyword": "OriginalApplication", "category": "餐饮"})
    assert created.status_code == 200, created.text
    action = f"/web/rules/apply-{status}"
    preview_url = "/web/rules?ledger_id=owner&" + ("confirmed_preview=1" if status == "confirmed" else "apply_preview=1")
    headers = {"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json"}
    with closing(public_client()) as web, closing(public_client()) as another:
        web.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity))
        fields = hidden_post_forms(web.get(preview_url).text)[action]
        assert web.post(action, data={**fields, "csrf_token": "invalid"}, headers=headers).status_code == 403
        assert web.post(action, data={**fields, "ledger_id": "gray"}, headers=headers).status_code == 409
        another.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity))
        fresh = hidden_post_forms(another.get(preview_url).text)[action]
        refused = another.post(action, data={**fields, "csrf_token": fresh["csrf_token"]}, headers=headers)
        assert refused.status_code == 409 and refused.json()["error"] == "session_binding_changed"
        with SessionLocal() as db:
            assert db.get(Expense, expense_id).category == "其他"
            assert list(db.scalars(select(RuleApplicationBatch))) == []
        accepted = web.post(action, data=fields, headers=headers)
        assert accepted.status_code == 200, accepted.text
        result = accepted.json()
        assert result["ack"] == {"scope": json.loads(fields["draft_scope"]), "clientRef": fields["idempotency_key"]}
        assert result["receipt"]["changed_count"] == 1
        assert web.post(action, data=fields, headers=headers).json() == result
        demote_owner_ledger_to_viewer()
        assert web.post(action, data=fields, headers=headers).status_code == 403
