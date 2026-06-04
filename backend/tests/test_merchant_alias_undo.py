"""ADR-0038 undo contract tests: merchant_alias soft-delete + restore.

Covers the Undo invariants this slice lands:
- DELETE soft-deletes (row hidden from reads, kept in DB).
- POST .../undo restores it and writes a ``ledger_audit_logs action='undo'`` row.
- undo of a live / unknown alias → 404.
- a soft-deleted key is reserved during its window (recreate → 409), and undo
  still restores the original.
- cleanup purges aged soft-deletes, spares fresh ones, and frees the key.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerAuditLog, MerchantAlias
from app.services.cleanup_service import (
    purge_expired_soft_deleted_merchant_aliases,
    purge_expired_soft_deletes,
)
from app.services.time_service import now_utc


def _create(client: TestClient, headers: dict[str, str], *, alias: str = "STARBUCKS 国贸店") -> dict:
    response = client.post(
        "/api/merchants/aliases",
        headers=headers,
        json={"canonical_merchant": "星巴克", "alias": alias},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _delete(client: TestClient, headers: dict[str, str], created: dict) -> None:
    response = client.request(
        "DELETE",
        f"/api/merchants/aliases/{created['public_id']}",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": created["row_version"]},
    )
    assert response.status_code == 200, response.text


def test_soft_delete_hides_alias_but_keeps_row(client: TestClient, *, identity) -> None:
    created = _create(client, identity.app_headers)
    _delete(client, identity.app_headers, created)

    listing = client.get("/api/merchants/aliases", headers=identity.app_headers)
    assert listing.status_code == 200, listing.text
    assert all(item["public_id"] != created["public_id"] for item in listing.json()["items"])

    with SessionLocal() as db:
        row = db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == created["public_id"]))
        assert row is not None
        assert row.deleted_at is not None


def test_undo_restores_alias_and_writes_audit(client: TestClient, *, identity) -> None:
    created = _create(client, identity.app_headers)
    _delete(client, identity.app_headers, created)

    undo = client.post(
        f"/api/merchants/aliases/{created['public_id']}/undo",
        headers=identity.app_headers,
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["public_id"] == created["public_id"]

    listing = client.get("/api/merchants/aliases", headers=identity.app_headers)
    assert any(item["public_id"] == created["public_id"] for item in listing.json()["items"])

    with SessionLocal() as db:
        audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.action == "undo")
            .where(LedgerAuditLog.resource_type == "merchant_alias")
            .where(LedgerAuditLog.resource_public_id == created["public_id"])
        )
        assert audit is not None


def test_undo_live_alias_returns_404(client: TestClient, *, identity) -> None:
    created = _create(client, identity.app_headers)
    undo = client.post(
        f"/api/merchants/aliases/{created['public_id']}/undo",
        headers=identity.app_headers,
    )
    assert undo.status_code == 404, undo.text
    assert undo.json()["error"] == "merchant_alias_not_found"


def test_undo_unknown_alias_returns_404(client: TestClient, *, identity) -> None:
    undo = client.post(
        "/api/merchants/aliases/no-such-public-id/undo",
        headers=identity.app_headers,
    )
    assert undo.status_code == 404, undo.text
    assert undo.json()["error"] == "merchant_alias_not_found"


def test_undo_without_auth_rejected(client: TestClient) -> None:
    # coverage: auth-401 — no Authorization header must be rejected, not run.
    undo = client.post("/api/merchants/aliases/anything/undo")
    assert undo.status_code == 401, undo.text
    assert undo.json()["error"] == "invalid_token"


def test_recreate_while_soft_deleted_conflicts_then_undo_restores(client: TestClient, *, identity) -> None:
    created = _create(client, identity.app_headers)
    _delete(client, identity.app_headers, created)

    # The soft-deleted key is reserved during its undo window.
    recreate = client.post(
        "/api/merchants/aliases",
        headers=identity.app_headers,
        json={"canonical_merchant": "星巴克", "alias": "STARBUCKS 国贸店"},
    )
    assert recreate.status_code == 409, recreate.text
    assert recreate.json()["error"] == "merchant_alias_conflict"

    # Undo still restores the original row (no duplicate could have been created).
    undo = client.post(
        f"/api/merchants/aliases/{created['public_id']}/undo",
        headers=identity.app_headers,
    )
    assert undo.status_code == 200, undo.text


def test_undo_past_retention_window_returns_404(client: TestClient, *, identity) -> None:
    """codex P1: a soft-deleted row aged past the retention window must NOT be
    undoable even when cleanup's purge has not run yet — restore semantics must
    match purge, otherwise an expired row could be resurrected during purge lag.
    """
    created = _create(client, identity.app_headers)
    _delete(client, identity.app_headers, created)

    # Backdate deleted_at past the 5-minute window (purge has not run yet).
    with SessionLocal() as db:
        row = db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == created["public_id"]))
        assert row is not None
        row.deleted_at = now_utc() - timedelta(minutes=6)
        db.commit()
        # Row physically still here — only the window has lapsed.
        assert row.deleted_at is not None

    undo = client.post(
        f"/api/merchants/aliases/{created['public_id']}/undo",
        headers=identity.app_headers,
    )
    assert undo.status_code == 404, undo.text
    assert undo.json()["error"] == "merchant_alias_not_found"


def test_purge_removes_aged_soft_deletes_and_spares_fresh(client: TestClient, *, identity) -> None:
    aged = _create(client, identity.app_headers, alias="AGED 店")
    fresh = _create(client, identity.app_headers, alias="FRESH 店")
    _delete(client, identity.app_headers, aged)
    _delete(client, identity.app_headers, fresh)

    with SessionLocal() as db:
        row = db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == aged["public_id"]))
        assert row is not None
        tenant_id = row.tenant_id
        row.deleted_at = now_utc() - timedelta(minutes=10)
        db.commit()

    with SessionLocal() as db:
        purged = purge_expired_soft_deleted_merchant_aliases(db, tenant_id)
    assert purged == 1

    with SessionLocal() as db:
        assert db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == aged["public_id"])) is None
        assert db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == fresh["public_id"])) is not None

    # The purged key is free again.
    recreate = client.post(
        "/api/merchants/aliases",
        headers=identity.app_headers,
        json={"canonical_merchant": "星巴克", "alias": "AGED 店"},
    )
    assert recreate.status_code == 201, recreate.text


def test_global_purge_removes_aged_spares_fresh(client: TestClient, *, identity) -> None:
    """ADR-0038 undo: the scheduler's tenant-less global purge sweeps aged
    soft-deletes and leaves rows still inside the window."""
    aged = _create(client, identity.app_headers, alias="AGED 全局")
    fresh = _create(client, identity.app_headers, alias="FRESH 全局")
    _delete(client, identity.app_headers, aged)
    _delete(client, identity.app_headers, fresh)

    with SessionLocal() as db:
        row = db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == aged["public_id"]))
        assert row is not None
        row.deleted_at = now_utc() - timedelta(minutes=10)
        db.commit()

    with SessionLocal() as db:
        purged = purge_expired_soft_deletes(db)
    assert purged == 1

    with SessionLocal() as db:
        assert db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == aged["public_id"])) is None
        assert db.scalar(select(MerchantAlias).where(MerchantAlias.public_id == fresh["public_id"])) is not None


def test_purge_scheduler_disabled_by_default() -> None:
    """The purge scheduler is opt-in (SOFT_DELETE_PURGE_AUTO_ENABLED), so it
    must not spin up a background thread under the default config."""
    from app.services.soft_delete_purge_scheduler import start_soft_delete_purge_scheduler

    scheduler = start_soft_delete_purge_scheduler()
    try:
        assert scheduler.enabled is False
        assert scheduler.thread is None
    finally:
        scheduler.stop()
