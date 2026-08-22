"""H2 restore identity, attachment, and sanitation contracts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, engine
from app.database._dataset_restore_authority import (
    SANITATION_TABLES,
    assert_restored_dataset_candidate_accepted,
    finalize_restored_dataset,
)
from app.database._dataset_restore_security import RESTORE_TABLE_SECURITY
from app.database_model_registry import Base
from app.errors import AppError
from app.services.dataset_authority_service import (
    DATASET_SEMANTIC_REVISION,
    DatasetAuthority,
    read_dataset_authority,
)
from app.services.dataset_backup_contract import (
    DATABASE_ARCHIVE_NAME,
    MANIFEST_NAME,
    DatabaseArtifact,
    DatasetBackupManifest,
    OriginalArtifact,
    encode_manifest,
)
from app.services.dataset_restore_service import materialize_restored_originals, resolve_restored_dataset_plan

_EXPECTED_SANITATION_TABLES = {
    "desktop_activation_attempts",
    "session_refresh_attempts",
    "auth_tokens",
    "device_enrollment_attempts",
    "installation_owner_claims",
    "bootstrap_secret_consumptions",
    "upload_link_daily_usage",
    "upload_link_remote_attempts",
    "upload_links",
    "pairing_attempt_failures",
    "pairing_codes",
    "invitations",
    "installation_idempotency_keys",
    "scheduler_leases",
    "budget_advisor_quota_locks",
    "ai_transaction_temp_id_map",
}


def test_every_registered_table_has_one_restore_security_classification() -> None:
    import app.models  # noqa: F401 - populate the production SQLAlchemy registry

    assert set(RESTORE_TABLE_SECURITY) == set(Base.metadata.tables)
    assert set(RESTORE_TABLE_SECURITY.values()) <= {"preserve", "sanitize", "filter"}
    assert {
        table
        for table, classification in RESTORE_TABLE_SECURITY.items()
        if classification == "sanitize"
    } == set(SANITATION_TABLES)
    assert RESTORE_TABLE_SECURITY["app_meta"] == "filter"


def _manifest(tmp_path: Path, *, authority) -> tuple[Path, DatasetBackupManifest]:
    generation = tmp_path / "ticketbox-backup-0b5de24e-bf77-4d7a-814a-5ce680091ff2"
    original = generation / "originals" / "owner" / "2026" / "08" / "receipt.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"restored-original")
    database = generation / DATABASE_ARCHIVE_NAME
    database.write_bytes(b"database-archive")
    manifest = DatasetBackupManifest(
        backup_id="0b5de24e-bf77-4d7a-814a-5ce680091ff2",
        operation_id="79bf3956-69c1-4996-a011-d7a4fc74fa41",
        backup_kind="manual",
        created_at=datetime(2026, 8, 21, 3, 4, 5, tzinfo=UTC),
        release_id="restore-fixture",
        writer_fence_sha256="c" * 64,
        authority=authority,
        database=DatabaseArtifact(
            size_bytes=database.stat().st_size,
            sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        ),
        originals=(
            OriginalArtifact(
                storage_key="originals/owner/2026/08/receipt.png",
                size_bytes=original.stat().st_size,
                sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                tenant_ids=("owner",),
            ),
        ),
    )
    (generation / MANIFEST_NAME).write_bytes(encode_manifest(manifest))
    return generation, manifest


def _authority() -> DatasetAuthority:
    return DatasetAuthority(
        dataset_id="5895e71e-1c87-4a59-b1c7-04f68817795e",
        client_generation="bf70f3b2-f2fe-41d9-a694-c0e33208d2b5",
        restore_epoch=3,
        schema_revision="20260821_0001",
        schema_min_compatible="1.0.0",
        semantic_revision=DATASET_SEMANTIC_REVISION,
        created_at=datetime(2026, 8, 21, 3, 4, 5, tzinfo=UTC),
        restored_from_backup_id=None,
    )


def test_restore_epoch_advances_without_shipping_an_unowned_clone_mode(tmp_path: Path) -> None:
    authority = _authority()
    _generation, manifest = _manifest(tmp_path, authority=authority)

    restored = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=authority.dataset_id,
        active_restore_epoch=authority.restore_epoch + 4,
        target_schema_revision=authority.schema_revision,
    )
    assert restored.dataset_id == authority.dataset_id
    assert restored.client_generation != authority.client_generation
    assert restored.restore_epoch == authority.restore_epoch + 5
    assert restored.restored_from_backup_id == manifest.backup_id

    from app.services import dataset_restore_service

    assert "clone_dataset_id" not in dataset_restore_service.CompleteRestoreRequest.__dataclass_fields__
    assert "clone_dataset_id" not in resolve_restored_dataset_plan.__annotations__


def test_restore_rejects_a_backup_from_a_foreign_dataset(tmp_path: Path) -> None:
    authority = _authority()
    _generation, manifest = _manifest(tmp_path, authority=authority)

    with pytest.raises(AppError) as rejected:
        resolve_restored_dataset_plan(
            manifest,
            active_dataset_id="7adafba4-2f79-4627-8620-62ee79a8e481",
            active_restore_epoch=0,
            target_schema_revision=authority.schema_revision,
        )

    assert rejected.value.error == "backup_incomplete"
    assert rejected.value.status_code == 409


def test_restore_materializes_originals_into_absent_candidate_root(tmp_path: Path) -> None:
    authority = _authority()
    generation, manifest = _manifest(tmp_path, authority=authority)
    target = tmp_path / "candidate" / "uploads"
    target.parent.mkdir()

    observed = materialize_restored_originals(
        generation,
        target_upload_root=target,
    )

    assert observed == manifest
    assert (target / "owner/2026/08/receipt.png").read_bytes() == b"restored-original"

    retried = materialize_restored_originals(
        generation,
        target_upload_root=target,
    )
    assert retried == manifest

    (target / "owner/2026/08/receipt.png").write_bytes(b"corrupt-after-first-restore")
    with pytest.raises(AppError) as corrupt:
        materialize_restored_originals(
            generation,
            target_upload_root=target,
        )
    assert corrupt.value.error == "backup_incomplete"

    (target / "owner/2026/08/receipt.png").write_bytes(b"restored-original")
    (target / "owner/orphan.png").write_bytes(b"orphan-after-first-restore")
    with pytest.raises(AppError) as orphaned:
        materialize_restored_originals(
            generation,
            target_upload_root=target,
        )
    assert orphaned.value.error == "backup_incomplete"


def test_restore_rebuilds_exact_interrupted_originals_staging(tmp_path: Path) -> None:
    authority = _authority()
    generation, manifest = _manifest(tmp_path, authority=authority)
    target = tmp_path / "candidate" / "uploads"
    target.parent.mkdir()
    staging = target.parent / f".uploads-restore-{manifest.backup_id}.staging"
    staging.mkdir()
    (staging / "partial").write_bytes(b"interrupted")

    materialize_restored_originals(generation, target_upload_root=target)

    assert not staging.exists()
    assert (target / "owner/2026/08/receipt.png").read_bytes() == b"restored-original"


def test_restore_preserves_materialization_and_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_restore_service

    generation, _manifest_value = _manifest(tmp_path, authority=_authority())
    target = tmp_path / "candidate" / "uploads"
    target.parent.mkdir()
    primary = OSError("copy failed")
    cleanup = SystemExit("cleanup interrupted")
    monkeypatch.setattr(
        dataset_restore_service.shutil, "copyfile", lambda *_args, **_kwargs: (_ for _ in ()).throw(primary)
    )
    monkeypatch.setattr(
        dataset_restore_service.shutil, "rmtree", lambda *_args, **_kwargs: (_ for _ in ()).throw(cleanup)
    )

    with pytest.raises(BaseExceptionGroup) as caught:
        materialize_restored_originals(generation, target_upload_root=target)
    assert caught.value.exceptions[0] is primary
    assert caught.value.exceptions[1] is cleanup


def test_restore_sanitation_allowlist_is_independent_and_closed() -> None:
    assert set(SANITATION_TABLES) == _EXPECTED_SANITATION_TABLES


def test_restore_finalization_executes_every_sanitation_delete_once(tmp_path: Path) -> None:
    _generation, manifest = _manifest(tmp_path, authority=_authority())
    plan = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=manifest.authority.dataset_id,
        active_restore_epoch=manifest.authority.restore_epoch,
        target_schema_revision=manifest.authority.schema_revision,
    )
    deleted: list[str] = []
    executed_sql: list[str] = []

    class MappingResult:
        def mappings(self):
            return self

        def one(self):
            return {
                "dataset_id": manifest.authority.dataset_id,
                "restore_epoch": manifest.authority.restore_epoch,
                "schema_revision": manifest.authority.schema_revision,
                "client_generation": manifest.authority.client_generation,
                "schema_min_compatible": manifest.authority.schema_min_compatible,
                "semantic_revision": manifest.authority.semantic_revision,
                "restored_from_backup_id": manifest.authority.restored_from_backup_id,
            }

    class RecordingConnection:
        def scalar(self, statement):
            assert str(statement) == "SELECT version_num FROM alembic_version"
            return plan.schema_revision

        def execute(self, statement, _parameters=None):
            sql = str(statement)
            executed_sql.append(sql)
            if sql.startswith("SELECT dataset_id"):
                return MappingResult()
            if sql.startswith('DELETE FROM "'):
                deleted.append(sql.removeprefix('DELETE FROM "').removesuffix('"'))
            return None

    finalize_restored_dataset(RecordingConnection(), source=manifest, plan=plan)  # type: ignore[arg-type]

    assert set(deleted) == _EXPECTED_SANITATION_TABLES
    assert len(deleted) == len(_EXPECTED_SANITATION_TABLES)
    app_meta_filter = next(sql for sql in executed_sql if sql.startswith("DELETE FROM app_meta"))
    assert "csrf_signing_key" in app_meta_filter
    assert "database_generation_binding" in app_meta_filter
    assert "budget_advisor_audit_key" not in app_meta_filter


def test_candidate_acceptance_requires_final_authority_and_empty_host_capabilities(
    tmp_path: Path,
) -> None:
    _generation, manifest = _manifest(tmp_path, authority=_authority())
    plan = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=manifest.authority.dataset_id,
        active_restore_epoch=manifest.authority.restore_epoch,
        target_schema_revision=manifest.authority.schema_revision,
    )

    class MappingResult:
        def mappings(self):
            return self

        def one(self):
            return {
                "dataset_id": plan.dataset_id,
                "restore_epoch": plan.restore_epoch,
                "schema_revision": plan.schema_revision,
                "client_generation": plan.client_generation,
                "schema_min_compatible": plan.schema_min_compatible,
                "semantic_revision": plan.semantic_revision,
                "restored_from_backup_id": plan.restored_from_backup_id,
            }

    class AcceptedConnection:
        def scalar(self, statement):
            sql = str(statement)
            if sql == "SELECT version_num FROM alembic_version":
                return plan.schema_revision
            if sql.startswith("SELECT count(*) FROM"):
                return 0
            raise AssertionError(sql)

        def execute(self, statement):
            assert str(statement).startswith("SELECT dataset_id")
            return MappingResult()

    assert_restored_dataset_candidate_accepted(AcceptedConnection(), plan=plan)  # type: ignore[arg-type]

    class UnsanitizedConnection(AcceptedConnection):
        def scalar(self, statement):
            sql = str(statement)
            if 'FROM "auth_tokens"' in sql:
                return 1
            return super().scalar(statement)

    with pytest.raises(AppError) as rejected:
        assert_restored_dataset_candidate_accepted(UnsanitizedConnection(), plan=plan)  # type: ignore[arg-type]
    assert rejected.value.error == "backup_incomplete"


@pytest.mark.real_db
def test_restore_finalization_revokes_host_credentials_without_deleting_business_rows(
    tmp_path: Path,
) -> None:
    with SessionLocal() as db:
        authority = read_dataset_authority(db)
    _generation, manifest = _manifest(tmp_path, authority=authority)
    plan = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=authority.dataset_id,
        active_restore_epoch=authority.restore_epoch,
        target_schema_revision=authority.schema_revision,
    )

    with engine.begin() as connection:
        expense_count = connection.scalar(text("SELECT count(*) FROM expenses"))
        connection.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) VALUES "
                "('csrf_signing_key', 'host-secret', CURRENT_TIMESTAMP), "
                "('database_generation_binding', 'stale-binding', CURRENT_TIMESTAMP), "
                "('budget_advisor_audit_key', 'old-install-secret', CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
        )
        connection.execute(
            text(
                "INSERT INTO bootstrap_secret_consumptions (secret_hash, consumed_at) "
                "VALUES (:secret_hash, CURRENT_TIMESTAMP) "
                "ON CONFLICT (secret_hash) DO UPDATE SET consumed_at = EXCLUDED.consumed_at"
            ),
            {"secret_hash": "f" * 64},
        )
        finalize_restored_dataset(connection, source=manifest, plan=plan)
        finalize_restored_dataset(connection, source=manifest, plan=plan)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM expenses")) == expense_count
        assert connection.scalar(text("SELECT count(*) FROM auth_tokens")) == 0
        assert connection.scalar(text("SELECT count(*) FROM upload_links")) == 0
        assert connection.scalar(text("SELECT count(*) FROM pairing_codes")) == 0
        assert connection.scalar(text("SELECT count(*) FROM bootstrap_secret_consumptions")) == 0
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app_meta WHERE key IN "
                    "('csrf_signing_key', 'database_generation_binding')"
                )
            )
            == 0
        )
        assert (
            connection.scalar(text("SELECT value FROM app_meta WHERE key = 'budget_advisor_audit_key'"))
            == "old-install-secret"
        )
        restored = (
            connection.execute(
                text(
                    "SELECT dataset_id, restore_epoch, restored_from_backup_id "
                    "FROM dataset_authority WHERE singleton_id = 1"
                )
            )
            .mappings()
            .one()
        )
    assert dict(restored) == {
        "dataset_id": plan.dataset_id,
        "restore_epoch": plan.restore_epoch,
        "restored_from_backup_id": manifest.backup_id,
    }


@pytest.mark.real_db
def test_restore_sanitation_rolls_back_if_authority_publication_fails(tmp_path: Path) -> None:
    with SessionLocal() as db:
        authority = read_dataset_authority(db)
    _generation, manifest = _manifest(tmp_path, authority=authority)
    plan = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=authority.dataset_id,
        active_restore_epoch=authority.restore_epoch,
        target_schema_revision=authority.schema_revision,
    )
    invalid_plan = replace(plan, client_generation="not-a-uuid")

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) VALUES "
                "('budget_advisor_audit_key', 'must-survive-rollback', CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        finalize_restored_dataset(connection, source=manifest, plan=invalid_plan)

    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT value FROM app_meta WHERE key = 'budget_advisor_audit_key'"))
            == "must-survive-rollback"
        )
        persisted = connection.execute(
            text("SELECT dataset_id, client_generation, restore_epoch FROM dataset_authority WHERE singleton_id = 1")
        ).one()
    assert tuple(persisted) == (
        authority.dataset_id,
        authority.client_generation,
        authority.restore_epoch,
    )
