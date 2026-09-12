"""ADR-0038 undo contract tests: expense reject + restore within 5-min window.

Covers the Undo invariants:
- ``POST /api/expenses/{id}/undo`` after a pending reject restores
  ``status='pending'`` from the row's pre-delete state, clears ``rejected_at``,
  and writes a ``ledger_audit_logs action='undo'`` row.
- A confirmed fact cannot enter the reject/undo lifecycle; it requires a
  reversal fact instead and remains unchanged.
- Undo on a never-rejected (pending / confirmed) expense → 404 (semantic match
  with merchant_alias / category_rule undo: not_found / past_window / wrong_status
  all collapse to 404 so client just re-fetches).
- Past-window reject → 404, even though row physically exists. Simulated by
  hand-aging ``rejected_at`` past the 5-min cutoff in ``soft_delete_policy``.
- A new Undo intent on an already restored row returns 404. A replay of the
  accepted Undo's original key/body returns its original successful receipt.
- Cross-tenant: undo on another ledger's rejected expense → 404 (ledger-scoped
  WHERE matches zero rows, indistinguishable from missing).
- No-auth: missing token → 401 (route-test-matrix audit gate).

Together with merchant_alias and category_rule undo, this confirms the
ADR-0038 undo pattern is consistent across all three resources that support it.
"""
# coverage: auth-401
# coverage: cross-ledger
# coverage: existence-404

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    reject_expense_api,
    undo_expense_api,
)
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, LedgerAuditLog
from app.services.soft_delete_policy import SOFT_DELETE_RETENTION
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._runtime_protocol import current_protocol_headers


def _create_pending(client: TestClient, *, identity) -> int:
    resp = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _create_confirmed(client: TestClient, *, identity) -> tuple[int, str]:
    expense_id = _create_pending(client, identity=identity)
    patch = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"amount_cents": 3500, "merchant": "Jack", "category": "其他"},
    )
    assert patch.status_code == 200, patch.text
    confirmed = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    return expense_id, body["confirmed_at"]


def _reject(client: TestClient, expense_id: int, *, identity) -> None:
    resp = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


def _post_losing_successful_ack(client, monkeypatch, endpoint, *, headers, body):
    def lose_response(response):
        if response.request.method == "POST" and response.request.url.path == endpoint and response.status_code == 200:
            raise httpx.ReadError("accepted response was not delivered", request=response.request)

    with monkeypatch.context() as patch:
        patch.setitem(client.event_hooks, "response", [lose_response])
        with pytest.raises(httpx.ReadError, match="accepted response was not delivered"):
            client.post(endpoint, headers=headers, json=body)


def test_replayed_original_reject_cannot_supply_a_later_rejections_undo_token(client, identity, monkeypatch):
    expense_id = _create_pending(client, identity=identity)
    endpoint = f"/api/expenses/{expense_id}"
    initial = client.get(endpoint, headers=identity.app_headers)
    assert initial.status_code == 200, initial.text
    original_body = {"expected_row_version": initial.json()["row_version"]}
    original_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    _post_losing_successful_ack(client, monkeypatch, f"{endpoint}/reject",
        headers=original_headers, body=original_body)
    with SessionLocal() as db:
        first = db.get(Expense, expense_id)
        assert first is not None and first.status == "rejected"
        first_version, first_rejected_at = first.row_version, first.rejected_at
        assert first_version == original_body["expected_row_version"] + 1

    undo = client.post(f"{endpoint}/undo",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": first_version})
    assert undo.status_code == 200, undo.text
    second = client.post(f"{endpoint}/reject",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": undo.json()["row_version"]})
    assert second.status_code == 200, second.text
    second_version = second.json()["row_version"]
    assert second_version > first_version

    replay = client.post(f"{endpoint}/reject", headers=original_headers, json=original_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["row_version"] == first_version
    assert replay.json()["status"] == "rejected"
    assert replay.json()["rejected_at"] == first_rejected_at.isoformat().replace("+00:00", "Z")
    stale_undo = client.post(f"{endpoint}/undo",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": replay.json()["row_version"]})
    assert stale_undo.status_code == 404, stale_undo.text
    assert stale_undo.json()["error"] == "expense_not_found"
    with SessionLocal() as db:
        current = db.get(Expense, expense_id)
        assert (current.status, current.row_version) == ("rejected", second_version)
        receipt = db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == original_headers["Idempotency-Key"]))
        assert receipt.response_body == replay.json()
        assert db.scalar(select(func.count()).select_from(LedgerAuditLog).where(
            LedgerAuditLog.resource_public_id == current.public_id,
            LedgerAuditLog.resource_type == "expense", LedgerAuditLog.action == "undo")) == 1


def test_first_delayed_reject_with_old_token_cannot_claim_another_rejection(client, identity):
    expense_id = _create_pending(client, identity=identity)
    endpoint = f"/api/expenses/{expense_id}/reject"
    with SessionLocal() as db:
        original_version = db.get(Expense, expense_id).row_version
    first = client.post(endpoint,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": original_version})
    assert first.status_code == 200, first.text
    key = str(uuid4())
    delayed = client.post(endpoint, headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": original_version})
    assert delayed.status_code == 409, delayed.text
    assert delayed.json()["error"] == "state_conflict"
    with SessionLocal() as db:
        current = db.get(Expense, expense_id)
        assert (current.status, current.row_version) == ("rejected", first.json()["row_version"])
        assert current.rejected_at.isoformat().replace("+00:00", "Z") == first.json()["rejected_at"]
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None


def test_undo_ack_loss_replays_original_success_without_a_second_restore(client, identity, monkeypatch):
    expense_id = _create_pending(client, identity=identity)
    _reject(client, expense_id, identity=identity)
    endpoint = f"/api/expenses/{expense_id}"
    rejected = client.get(endpoint, headers=identity.app_headers)
    assert rejected.status_code == 200, rejected.text
    original_body = {"expected_row_version": rejected.json()["row_version"]}
    key = str(uuid4())
    original_headers = {**identity.app_headers, "Idempotency-Key": key}
    _post_losing_successful_ack(client, monkeypatch, f"{endpoint}/undo",
        headers=original_headers, body=original_body)
    with SessionLocal() as db:
        restored = db.get(Expense, expense_id)
        assert (restored.status, restored.row_version, restored.rejected_at) == (
            "pending", original_body["expected_row_version"] + 1, None)
        restored_version = restored.row_version
    replay = client.post(f"{endpoint}/undo", headers=original_headers, json=original_body)
    assert replay.status_code == 200, replay.text
    assert (replay.json()["status"], replay.json()["row_version"], replay.json()["rejected_at"]) == (
        "pending", restored_version, None)
    with SessionLocal() as db:
        current = db.get(Expense, expense_id)
        assert (current.status, current.row_version) == ("pending", restored_version)
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert receipt is not None and receipt.status == "succeeded"
        assert receipt.response_body == replay.json()
        assert db.scalar(select(func.count()).select_from(LedgerAuditLog).where(
            LedgerAuditLog.resource_public_id == current.public_id,
            LedgerAuditLog.resource_type == "expense", LedgerAuditLog.action == "undo")) == 1


@pytest.mark.parametrize("operation", ["reject", "undo"])
def test_reject_or_undo_commit_failure_keeps_fact_audit_and_original_key_atomic(
    client, identity, operation,
):
    expense_id = _create_pending(client, identity=identity)
    if operation == "undo":
        _reject(client, expense_id, identity=identity)
    endpoint = f"/api/expenses/{expense_id}/{operation}"
    with SessionLocal() as db:
        original = db.get(Expense, expense_id)
        original_status, original_version, original_rejected_at = original.status, original.row_version, original.rejected_at
        public_id = original.public_id
    intended_status = "rejected" if operation == "reject" else "pending"
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"expected_row_version": original_version}
    interrupted = []

    def fail_business_commit(session):
        if session.in_nested_transaction():
            return
        actual = session.get(Expense, expense_id, populate_existing=True)
        if actual is None or (actual.status, actual.row_version) != (intended_status, original_version + 1):
            return
        interrupted.append((actual.status, actual.row_version))
        raise AppError("server_error", status_code=503)

    event.listen(Session, "before_commit", fail_business_commit)
    try:
        failed = client.post(endpoint, headers=headers, json=body)
    finally:
        event.remove(Session, "before_commit", fail_business_commit)
    assert interrupted == [(intended_status, original_version + 1)], "must interrupt the actual business commit"
    assert failed.status_code == 503, failed.text
    audit_query = select(func.count()).select_from(LedgerAuditLog).where(
        LedgerAuditLog.resource_public_id == public_id,
        LedgerAuditLog.resource_type == "expense", LedgerAuditLog.action == "undo")
    with SessionLocal() as db:
        current = db.get(Expense, expense_id)
        assert (current.status, current.row_version, current.rejected_at) == (
            original_status, original_version, original_rejected_at)
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
        assert db.scalar(audit_query) == 0
    retried = client.post(endpoint, headers=headers, json=body)
    assert retried.status_code == 200, retried.text
    assert (retried.json()["status"], retried.json()["row_version"]) == (intended_status, original_version + 1)
    with SessionLocal() as db:
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert receipt is not None and receipt.status == "succeeded"
        assert receipt.response_body == retried.json()
        assert db.scalar(audit_query) == int(operation == "undo")


def test_undo_after_reject_restores_pending_and_writes_audit(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    _reject(client, expense_id, identity=identity)

    response = undo_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == expense_id
    assert body["status"] == "pending"
    assert body.get("rejected_at") is None

    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "pending"
        assert row.rejected_at is None
        audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.action == "undo")
            .where(LedgerAuditLog.resource_type == "expense")
            .where(LedgerAuditLog.resource_public_id == row.public_id)
        )
        assert audit is not None, "undo must append a ledger_audit_logs row"


def test_confirmed_reject_requires_reversal_and_keeps_fact(
    client: TestClient, *, identity
) -> None:
    expense_id, confirmed_at = _create_confirmed(client, identity=identity)
    response = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "expense_reversal_required"

    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "confirmed"
        assert row.confirmed_at is not None
        assert row.confirmed_at.isoformat().replace("+00:00", "Z") == confirmed_at
        assert row.rejected_at is None


def test_undo_on_pending_expense_returns_404(client: TestClient, *, identity) -> None:
    # Never rejected — undo has nothing to restore.
    expense_id = _create_pending(client, identity=identity)
    response = undo_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"


def test_undo_after_window_expires_returns_404(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    _reject(client, expense_id, identity=identity)

    # Hand-age the rejected_at past the retention cutoff. cleanup_service may
    # not have run yet, but undo's atomic WHERE rejected_at >= cutoff predicate
    # is independent of cleanup timing.
    aged = now_utc() - SOFT_DELETE_RETENTION - timedelta(seconds=10)
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        row.rejected_at = aged
        db.commit()

    response = undo_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"

    # Row is still rejected — undo didn't accidentally flip status.
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "rejected"
        assert row.rejected_at is not None


def test_second_undo_on_restored_expense_returns_404(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(client, identity=identity)
    _reject(client, expense_id, identity=identity)

    first = undo_expense_api(client, expense_id, headers=identity.app_headers)
    assert first.status_code == 200, first.text

    second = undo_expense_api(client, expense_id, headers=identity.app_headers)
    assert second.status_code == 404, second.text
    assert second.json()["error"] == "expense_not_found"


def test_undo_for_missing_expense_returns_404(client: TestClient, *, identity) -> None:
    # Stable id well above any test-created row; no expense exists with this id.
    response = undo_expense_api(client, 999_999, headers=identity.app_headers)
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"


def test_undo_without_auth_returns_401(client: TestClient) -> None:
    # Route-test-matrix gate: every mutating route must have a 401 no-auth path.
    response = undo_expense_api(client, 1, headers={})
    assert response.status_code == 401, response.text
    assert response.json()["error"] == "invalid_token"


def test_undo_from_different_ledger_returns_404(client: TestClient, *, identity) -> None:
    # codex review P2: 真正的 cross-ledger 测试 — 之前的 `# coverage: cross-ledger`
    # 标记是过度声明, 实现里 tenant_id WHERE 兜得住但没测试覆盖。create + switch 到
    # 一个新 ledger, 用新 session_token 尝试 undo 旧 ledger 的 rejected expense → 404。
    expense_id = _create_pending(client, identity=identity)
    _reject(client, expense_id, identity=identity)

    create_ledger = client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "另一本"},
    )
    assert create_ledger.status_code == 201, create_ledger.text
    other_ledger_id = create_ledger.json()["ledger_id"]
    switch = client.post(
        f"/api/ledgers/{other_ledger_id}/switch",
        headers=identity.app_headers,
    )
    assert switch.status_code == 200, switch.text
    other_headers = current_protocol_headers({"Authorization": f"Bearer {switch.json()['session_token']}"})

    response = undo_expense_api(client, expense_id, headers=other_headers)
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"

    # Row must remain rejected in the original ledger (cross-tenant attempt didn't
    # accidentally flip its state, and didn't write a stray audit log either).
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert row is not None
        assert row.status == "rejected"
        assert row.rejected_at is not None
        cross_audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.action == "undo")
            .where(LedgerAuditLog.resource_type == "expense")
            .where(LedgerAuditLog.resource_public_id == row.public_id)
        )
        assert cross_audit is None, "cross-tenant undo must not append a ledger_audit_logs row"


def test_undo_does_not_restore_cleared_duplicate_references(
    client: TestClient, *, identity
) -> None:
    # codex review P2: reject_expense clears duplicate_of_id on rows that pointed
    # at this expense (duplicate_service.clear_duplicate_references_to). undo only
    # restores status/rejected_at/updated_at; the cleared pointers stay None.
    #
    # This test pins the documented limitation so a future "restore symmetry"
    # change is a deliberate decision, not a silent surprise. If we ever decide
    # to re-detect duplicates on undo, flip these assertions and document the
    # symmetry in post_undo_expense.
    first_id = _create_pending(client, identity=identity)
    second_id = _create_pending(client, identity=identity)
    # Re-uploading the same PNG_BYTES makes the second pending row a "suspected"
    # duplicate of the first; second.duplicate_of_id == first.id.
    with SessionLocal() as db:
        second = db.scalar(select(Expense).where(Expense.id == second_id))
        assert second is not None
        assert second.duplicate_of_id == first_id, "test precondition: duplicate detection wired"
        before_clear_row_version = second.row_version
        before_clear_updated_at = second.updated_at

    _reject(client, first_id, identity=identity)
    # reject clears the duplicate pointer on `second` (and the duplicate_status
    # banner) so the user no longer sees a suspect tag against a rejected target.
    with SessionLocal() as db:
        second = db.scalar(select(Expense).where(Expense.id == second_id))
        assert second is not None
        assert second.duplicate_of_id is None
        assert second.duplicate_status == "none"
        assert second.row_version == before_clear_row_version + 1
        assert second.updated_at >= before_clear_updated_at

    response = undo_expense_api(client, first_id, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    # The undo restored the rejected target, but the duplicate pointer on `second`
    # was already wiped at reject time — undo does NOT walk the graph backwards to
    # rediscover it. Documented behaviour; user can re-upload or manually flag.
    with SessionLocal() as db:
        second = db.scalar(select(Expense).where(Expense.id == second_id))
        assert second is not None
        assert second.duplicate_of_id is None, (
            "undo does not restore cleared duplicate references — see post_undo_expense KDoc"
        )
        assert second.duplicate_status == "none"
