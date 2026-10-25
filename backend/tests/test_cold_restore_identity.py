from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import (
    Account,
    AuthToken,
    DatasetAuthorityRecord,
    Device,
    InstallationOwnerClaim,
    Invitation,
    LedgerMember,
    PairingCode,
    UploadLink,
)
from app.services.cold_restore_identity import rebind_cold_dataset
from app.services.identity_service import bootstrap_installation_owner
from app.services.session_lifecycle_service import hash_secret
from app.services.time_service import now_utc
from tests.pairing_test_support import pairing_payload

OLD_INSTALL = "11111111-1111-4111-8111-111111111111"
NEW_INSTALL = "22222222-2222-4222-8222-222222222222"
BACKUP = "33333333-3333-4333-8333-333333333333"
SECRET = "cold-restore-source-bootstrap-secret-001"
NEW_SECRET = "cold-restore-target-bootstrap-secret-001"


def _source(db):
    bootstrap_installation_owner(db, operation_id="source-install", installation_id=OLD_INSTALL,
        bootstrap_secret=SECRET, commit=False)
    authority = db.get(DatasetAuthorityRecord, 1)
    authority.client_generation = OLD_INSTALL
    authority.restore_epoch = 0
    authority.restored_from_backup_id = None
    claim = db.get(InstallationOwnerClaim, "source-install")
    db.add(AuthToken(token_hash=hash_secret("old-bearer"), account_id=claim.account_id,
        device_id=claim.device_id, ledger_id=claim.ledger_id, scope="app"))
    db.add(UploadLink(token_hash=hash_secret("old-upload"), account_id=claim.account_id,
        device_id=claim.device_id, ledger_id=claim.ledger_id, default_timezone="Asia/Shanghai"))
    db.add(Invitation(token_hash=hash_secret("old-invite"), ledger_id=claim.ledger_id,
        role="viewer", created_by_account_id=claim.account_id, expires_at=now_utc() + timedelta(days=1)))
    db.flush()
    return {"dataset_id": authority.dataset_id, "install_id": OLD_INSTALL, "restore_epoch": 0,
        "schema_revision": authority.schema_revision}


def _restore(db, source):
    return rebind_cold_dataset(db, source=source, installation_id=NEW_INSTALL, backup_id=BACKUP,
        operation_id="restore-target", bootstrap_secret=NEW_SECRET, recovery_secret=SECRET)


def _memberships(db):
    return list(db.execute(select(LedgerMember.ledger_id, LedgerMember.account_id, LedgerMember.role,
        LedgerMember.disabled_at).order_by(LedgerMember.id)))


def test_restore_keeps_accounts_and_roles_revokes_old_capabilities_and_replays_once():
    with SessionLocal() as db:
        source = _source(db)
        roles = _memberships(db)
        accounts = list(db.scalars(select(Account.id)))
        old_device_ids = list(db.scalars(select(Device.id)))
        old_pairing_ids = list(db.scalars(select(PairingCode.id)))
        result = _restore(db, source)
        assert _restore(db, source) == result
        assert _memberships(db) == roles
        assert list(db.scalars(select(Account.id))) == accounts
        assert db.query(InstallationOwnerClaim).count() == 1
        assert db.query(Device).count() == len(old_device_ids) + 1
        assert db.query(PairingCode).count() == len(old_pairing_ids) + 1
        assert all(db.get(Device, row_id).revoked_at for row_id in old_device_ids)
        assert all(db.get(PairingCode, row_id).revoked_at for row_id in old_pairing_ids)
        for model in (AuthToken, UploadLink, Invitation):
            assert all(row.revoked_at for row in db.scalars(select(model)))
        authority = db.get(DatasetAuthorityRecord, 1)
        assert (authority.dataset_id, authority.client_generation, authority.restore_epoch,
            authority.restored_from_backup_id) == (source["dataset_id"], NEW_INSTALL, 1, BACKUP)


def test_os_maintenance_alone_cannot_reenroll_owner_without_source_recovery_material():
    with SessionLocal() as db:
        source = _source(db)
        with pytest.raises(AppError) as failure:
            rebind_cold_dataset(db, source=source, installation_id=NEW_INSTALL, backup_id=BACKUP,
                operation_id="restore-target", bootstrap_secret=NEW_SECRET, recovery_secret="wrong-recovery-material")
        assert failure.value.error == "restore_recovery_unauthorized"
        assert db.get(DatasetAuthorityRecord, 1).client_generation == OLD_INSTALL
        assert db.query(AuthToken).one().revoked_at is None


def test_restore_mismatched_dataset_and_failed_transaction_keep_original_identity(monkeypatch):
    with SessionLocal() as db:
        source = _source(db)
        db.commit()
        with pytest.raises(AppError) as failure:
            _restore(db, {**source, "dataset_id": BACKUP})
        assert failure.value.error == "restore_identity_mismatch"
        db.rollback()
        assert db.get(DatasetAuthorityRecord, 1).client_generation == OLD_INSTALL
        assert db.query(AuthToken).one().revoked_at is None
        from app.services.cold_restore_identity import claims
        def fail(*_args, **_kwargs):
            raise RuntimeError("interrupted before commit")
        monkeypatch.setattr(claims, "claim_result", fail)
        with pytest.raises(RuntimeError, match="interrupted"):
            _restore(db, source)
        db.rollback()
        assert db.get(DatasetAuthorityRecord, 1).client_generation == OLD_INSTALL
        assert db.get(DatasetAuthorityRecord, 1).restore_epoch == 0
        assert db.query(AuthToken).one().revoked_at is None
        assert db.query(InstallationOwnerClaim).one().installation_id == OLD_INSTALL


def test_restored_owner_reconnects_but_old_bearer_and_old_pairing_cannot_reenter():
    with SessionLocal() as db:
        source = _source(db)
        result = _restore(db, source)
        db.commit()
    from app.services.identity_service._installation_claim import derive_pairing_code
    with TestClient(app) as client:
        old = client.get("/api/auth/check", headers={"Authorization": "Bearer old-bearer"})
        assert old.status_code == 401
        old_pair = client.post("/api/auth/pair", json=pairing_payload(derive_pairing_code(SECRET)))
        assert old_pair.status_code != 200
        paired = client.post("/api/auth/pair", json=pairing_payload(result.pairing_code))
        assert paired.status_code == 200, paired.text
        replay = client.post("/api/auth/pair", json=pairing_payload(result.pairing_code))
        assert replay.status_code != 200


def test_verification_candidate_refuses_every_business_route_without_starting_workers(monkeypatch):
    import app.main as main
    called = []
    monkeypatch.setenv("TICKETBOX_RESTORE_VERIFY_ONLY", "1")
    monkeypatch.setattr(main, "wait_for_db", lambda: called.append("wait"))
    monkeypatch.setattr(main, "init_db", lambda: called.append("verify"))
    from app.services import background_task_executor
    monkeypatch.setattr(background_task_executor, "start_executor", lambda: pytest.fail("verification started a writer"))
    with TestClient(app) as client:
        for method, path in (("get", "/"), ("get", "/api/expenses"), ("post", "/api/auth/pair")):
            response = getattr(client, method)(path)
            assert response.status_code == 503
            assert response.json()["error"] == "restore_verification_in_progress"
    assert called == ["wait", "verify"]
