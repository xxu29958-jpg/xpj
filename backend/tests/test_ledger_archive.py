"""Ledger archive / unarchive — reversible, owner-only soft-delete.

Archiving sets ``ledgers.archived_at``; every active surface already filters
``archived_at IS NULL``, so the ledger disappears without deleting a row and is
fully restorable. These tests pin the service invariants (owner-only, default
protected, atomic idempotent flip, audited) and the Owner Console HTTP flow.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import Account, Ledger, LedgerAuditLog, LedgerMember
from app.routes.owner_console import _require_local as _require_local_console
from app.routes.owner_ledgers import _require_local as _require_local_ledgers
from app.services import ledger_service
from app.services.owner_console_service import get_owner_account_id
from app.tenants import DEFAULT_TENANT_ID


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local_console] = lambda: None
    app.dependency_overrides[_require_local_ledgers] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local_console, None)
    app.dependency_overrides.pop(_require_local_ledgers, None)


def _owner_id() -> int:
    with SessionLocal() as db:
        owner_id = get_owner_account_id(db)
        assert owner_id is not None
        return owner_id


def _archived_at(ledger_id: str):
    with SessionLocal() as db:
        return db.scalar(select(Ledger.archived_at).where(Ledger.ledger_id == ledger_id))


def _audit_count(action: str, ledger_id: str) -> int:
    with SessionLocal() as db:
        return len(
            db.scalars(
                select(LedgerAuditLog)
                .where(LedgerAuditLog.ledger_id == ledger_id)
                .where(LedgerAuditLog.action == action)
            ).all()
        )


# --- service layer -------------------------------------------------------


def test_archive_hides_ledger_and_records_audit(identity) -> None:
    owner_id = _owner_id()
    with SessionLocal() as db:
        assert ledger_service.archive_ledger(db, ledger_id="tester_1", actor_account_id=owner_id) is True

    assert _archived_at("tester_1") is not None
    assert _audit_count(ledger_service.AUDIT_LEDGER_ARCHIVED, "tester_1") == 1

    with SessionLocal() as db:
        active = {s.ledger_id for s in ledger_service.list_managed_ledgers_for_account(db, account_id=owner_id)}
        archived = {s.ledger_id for s in ledger_service.list_archived_ledgers_for_account(db, account_id=owner_id)}
    assert "tester_1" not in active
    assert "tester_1" in archived


def test_archive_is_idempotent(identity) -> None:
    """A second archive is a no-op (``False``) — the ``WHERE archived_at IS NULL``
    predicate, not a Python pre-check, gates the flip, so it never double-audits."""
    owner_id = _owner_id()
    with SessionLocal() as db:
        assert ledger_service.archive_ledger(db, ledger_id="tester_1", actor_account_id=owner_id) is True
        assert ledger_service.archive_ledger(db, ledger_id="tester_1", actor_account_id=owner_id) is False
    assert _audit_count(ledger_service.AUDIT_LEDGER_ARCHIVED, "tester_1") == 1


def test_unarchive_restores(identity) -> None:
    owner_id = _owner_id()
    with SessionLocal() as db:
        ledger_service.archive_ledger(db, ledger_id="tester_1", actor_account_id=owner_id)
    with SessionLocal() as db:
        assert ledger_service.unarchive_ledger(db, ledger_id="tester_1", actor_account_id=owner_id) is True

    assert _archived_at("tester_1") is None
    assert _audit_count(ledger_service.AUDIT_LEDGER_UNARCHIVED, "tester_1") == 1
    with SessionLocal() as db:
        active = {s.ledger_id for s in ledger_service.list_managed_ledgers_for_account(db, account_id=owner_id)}
    assert "tester_1" in active


def test_unarchive_idempotent_on_active(identity) -> None:
    owner_id = _owner_id()
    with SessionLocal() as db:
        assert ledger_service.unarchive_ledger(db, ledger_id="tester_1", actor_account_id=owner_id) is False
    assert _audit_count(ledger_service.AUDIT_LEDGER_UNARCHIVED, "tester_1") == 0


def test_cannot_archive_default_ledger(identity) -> None:
    owner_id = _owner_id()
    with SessionLocal() as db, pytest.raises(AppError) as excinfo:
        ledger_service.archive_ledger(db, ledger_id=DEFAULT_TENANT_ID, actor_account_id=owner_id)
    assert excinfo.value.error == "cannot_archive_default_ledger"
    assert _archived_at(DEFAULT_TENANT_ID) is None


def test_non_owner_member_cannot_archive(identity) -> None:
    """Even an active member (non-owner) of the ledger cannot archive it."""
    with SessionLocal() as db:
        stranger = Account(display_name="路人")
        db.add(stranger)
        db.flush()
        db.add(LedgerMember(ledger_id="tester_1", account_id=stranger.id, role="member"))
        db.commit()
        stranger_id = stranger.id

    with SessionLocal() as db, pytest.raises(AppError) as excinfo:
        ledger_service.archive_ledger(db, ledger_id="tester_1", actor_account_id=stranger_id)
    assert excinfo.value.error == "ledger_forbidden"
    assert _archived_at("tester_1") is None


# --- Owner Console HTTP flow ---------------------------------------------


def test_console_archive_then_unarchive_via_http(local_client: TestClient) -> None:
    archive = local_client.post("/owner/ledgers/tester_1/archive", follow_redirects=False)
    assert archive.status_code == 303
    assert _archived_at("tester_1") is not None

    page = local_client.get("/owner/ledgers")
    assert page.status_code == 200
    assert "已归档账本" in page.text  # the restore section now renders

    unarchive = local_client.post("/owner/ledgers/tester_1/unarchive", follow_redirects=False)
    assert unarchive.status_code == 303
    assert _archived_at("tester_1") is None


def test_console_archive_default_shows_error_not_silent(local_client: TestClient) -> None:
    resp = local_client.post(f"/owner/ledgers/{DEFAULT_TENANT_ID}/archive", follow_redirects=False)
    assert resp.status_code == 200  # re-renders the page with the reason, no redirect
    assert "默认账本不能归档" in resp.text
    assert _archived_at(DEFAULT_TENANT_ID) is None
