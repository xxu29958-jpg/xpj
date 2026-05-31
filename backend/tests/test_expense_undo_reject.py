"""ADR-0038 undo contract tests: expense reject + restore within 5-min window.

Covers the Undo invariants:
- ``POST /api/expenses/{id}/undo`` after reject restores ``status='pending'`` and
  clears ``rejected_at``; writes a ``ledger_audit_logs action='undo'`` row.
- Undo on a never-rejected (pending / confirmed) expense → 404 (semantic match
  with merchant_alias / category_rule undo: not_found / past_window / wrong_status
  all collapse to 404 so client just re-fetches).
- Past-window reject → 404, even though row physically exists. Simulated by
  hand-aging ``rejected_at`` past the 5-min cutoff in ``soft_delete_policy``.
- Double-undo: second ``POST /undo`` is a no-op 404 (row already pending).
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

from api_contract_helpers import reject_expense_api, undo_expense_api
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerAuditLog
from app.services.soft_delete_policy import SOFT_DELETE_RETENTION
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES


def _create_pending(client: TestClient, *, identity) -> int:
    resp = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _reject(client: TestClient, expense_id: int, *, identity) -> None:
    resp = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


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
    other_headers = {"Authorization": f"Bearer {switch.json()['session_token']}"}

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

    _reject(client, first_id, identity=identity)
    # reject clears the duplicate pointer on `second` (and the duplicate_status
    # banner) so the user no longer sees a suspect tag against a rejected target.
    with SessionLocal() as db:
        second = db.scalar(select(Expense).where(Expense.id == second_id))
        assert second is not None
        assert second.duplicate_of_id is None
        assert second.duplicate_status == "none"

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
