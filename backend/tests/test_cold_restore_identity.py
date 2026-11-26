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


def test_restore_originals_verifies_debt_bill_capture_hash_and_rejects_tamper_and_bad_paths(
    tmp_path, monkeypatch,
):
    import hashlib

    from app import config
    from app.cold_restore_runtime import _verify_originals
    from app.database_maintenance_runtime import DatabaseMaintenanceContractError
    from app.models import DebtBillCapture, Expense

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True)
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    config.reset_settings_cache()

    try:
        with SessionLocal() as db:
            _source(db)
            claim = db.get(InstallationOwnerClaim, "source-install")
            ledger_dir = upload_dir / claim.ledger_id
            ledger_dir.mkdir(parents=True)

            capture_bytes = b"\x89PNG\r\n\x1a\nfake-debt-bill-original-bytes"
            capture_sha = hashlib.sha256(capture_bytes).hexdigest()
            capture_file = ledger_dir / "debt-bill.png"
            capture_file.write_bytes(capture_bytes)

            deleted_capture_bytes = b"\x89PNG\r\n\x1a\ncleaned-debt-bill"
            deleted_capture_sha = hashlib.sha256(deleted_capture_bytes).hexdigest()

            capture = DebtBillCapture(
                tenant_id=claim.ledger_id,
                created_by_account_id=claim.account_id,
                creation_key="c" * 64,
                capture_key="k" * 64,
                request_fingerprint="f" * 64,
                accepted_receipt={"ok": True},
                file_name="debt-bill.png",
                media_type="image/png",
                input_sha256=capture_sha,
                image_path=f"uploads/{claim.ledger_id}/debt-bill.png",
                image_hash=capture_sha,
                image_size_bytes=len(capture_bytes),
            )
            cleaned_capture = DebtBillCapture(
                tenant_id=claim.ledger_id,
                created_by_account_id=claim.account_id,
                creation_key="d" * 64,
                capture_key="m" * 64,
                request_fingerprint="e" * 64,
                accepted_receipt={"ok": True},
                file_name="cleaned.png",
                media_type="image/png",
                input_sha256=deleted_capture_sha,
                image_path=f"uploads/{claim.ledger_id}/cleaned-missing.png",
                image_hash=deleted_capture_sha,
                image_size_bytes=len(deleted_capture_bytes),
                image_deleted_at=now_utc(),
            )
            db.add_all([capture, cleaned_capture])
            db.flush()

            assert _verify_originals(db) == 1

            capture_file.write_bytes(b"\x89PNG\r\n\x1a\ntampered-debt-bill-original!")
            with pytest.raises(DatabaseMaintenanceContractError, match="debt_bill_capture"):
                _verify_originals(db)

            capture_file.write_bytes(capture_bytes)
            assert _verify_originals(db) == 1

            bad_expense = Expense(
                tenant_id=claim.ledger_id,
                amount_cents=1000,
                original_amount_minor=1000,
                category="餐饮",
                image_path="../../escape/evil.png",
            )
            db.add(bad_expense)
            db.flush()
            with pytest.raises(DatabaseMaintenanceContractError, match="invalid retained original reference"):
                _verify_originals(db)
    finally:
        monkeypatch.undo()
        config.reset_settings_cache()


@pytest.mark.real_db
def test_verify_preserved_dataset_transaction_is_read_only_and_checks_authority(
    tmp_path, monkeypatch,
):
    import hashlib

    from app import config
    from app.cold_restore_runtime import _verify_preserved_dataset_transaction
    from app.database import _managed_postgres_role_authority as role_authority
    from app.database import engine
    from app.database._managed_postgres_contract import DATABASE_NAME, MIGRATOR_ROLE, SCHEMA_OWNER_ROLE
    from app.database_maintenance_runtime import DatabaseMaintenanceContractError
    from app.models import DebtBillCapture

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True)
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    config.reset_settings_cache()

    try:
        with SessionLocal() as db:
            source = _source(db)
            claim = db.get(InstallationOwnerClaim, "source-install")
            ledger_dir = upload_dir / claim.ledger_id
            ledger_dir.mkdir(parents=True)
            capture_bytes = b"\x89PNG\r\n\x1a\npreserved-dataset-original"
            capture_sha = hashlib.sha256(capture_bytes).hexdigest()
            (ledger_dir / "preserved.png").write_bytes(capture_bytes)
            db.add(
                DebtBillCapture(
                    tenant_id=claim.ledger_id,
                    created_by_account_id=claim.account_id,
                    creation_key="1" * 64,
                    capture_key="2" * 64,
                    request_fingerprint="3" * 64,
                    accepted_receipt={"ok": True},
                    file_name="preserved.png",
                    media_type="image/png",
                    input_sha256=capture_sha,
                    image_path=f"uploads/{claim.ledger_id}/preserved.png",
                    image_hash=capture_sha,
                    image_size_bytes=len(capture_bytes),
                )
            )
            db.commit()

        monkeypatch.setattr(role_authority, "assume_managed_postgres_schema_owner", lambda *_a, **_kw: None)
        with engine.begin() as connection:
            result = _verify_preserved_dataset_transaction(
                connection,
                dataset_id=source["dataset_id"],
                installation_id=source["install_id"],
                expected_restore_epoch=source["restore_epoch"],
                schema_revision=source["schema_revision"],
                semantic_revision="ticketbox-dataset-semantics-v1",
                database_name=DATABASE_NAME,
                migrator_role=MIGRATOR_ROLE,
                schema_owner_role=SCHEMA_OWNER_ROLE,
            )
        assert result["schema"] == "ticketbox-preserved-dataset-verify-v1"
        assert result["verified_originals"] == 1

        with (
            pytest.raises(DatabaseMaintenanceContractError, match="does not match installation binding"),
            engine.begin() as connection,
        ):
            _verify_preserved_dataset_transaction(
                connection,
                dataset_id=source["dataset_id"],
                installation_id=source["install_id"],
                expected_restore_epoch=source["restore_epoch"] + 1,
                schema_revision=source["schema_revision"],
                semantic_revision="ticketbox-dataset-semantics-v1",
                database_name=DATABASE_NAME,
                migrator_role=MIGRATOR_ROLE,
                schema_owner_role=SCHEMA_OWNER_ROLE,
            )
    finally:
        monkeypatch.undo()
        config.reset_settings_cache()


def test_rebind_cold_dataset_with_summary_reports_exact_revoked_counts():
    from app.services.cold_restore_identity import rebind_cold_dataset_with_summary

    with SessionLocal() as db:
        source = _source(db)
        result, summary = rebind_cold_dataset_with_summary(
            db,
            source=source,
            installation_id=NEW_INSTALL,
            backup_id=BACKUP,
            operation_id="restore-target-r2",
            bootstrap_secret=NEW_SECRET,
            recovery_secret=SECRET,
        )
        assert result.pairing_code
        assert summary["auth_tokens"] >= 1
        assert summary["devices"] >= 1
        assert summary["pairing_codes"] >= 1
        assert summary["upload_links"] >= 1
        assert summary["invitations"] >= 1
