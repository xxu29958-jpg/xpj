"""Real PostgreSQL tests for same-transaction managed upgrade attestation and crash recovery."""

from __future__ import annotations

import hashlib
import json
import zipfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import NullPool

from app.database import _database_generation_executor as executor
from app.database import _managed_postgres_migration_runtime as managed_runtime
from app.database._database_generation_executor import (
    UPGRADE_ATTESTATION_META_KEY,
    UPGRADE_ATTESTATION_SCHEMA,
)
from app.database._existing_dataset_upgrade import (
    ExistingDatasetUpgradeError,
    run_existing_dataset_upgrade_action,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
)
from app.errors import AppError
from app.main import app
from app.services.app_meta_service import set_value
from app.services.installation_health_attestation import (
    sign_health_challenge,
    sign_runtime_mode_challenge,
)
from app.services.secure_file import write_protected_file_exclusive
from tests._infra.alembic_runtime import alembic_config_for_test, run_alembic_for_test
from tests._infra.postgres_topology_cleanup import cleanup_postgres_topology
from tests.managed_postgres_test_support import (
    _MIGRATOR_PASSWORD,
    _RUNTIME_PASSWORD,
    _connection_url,
    _create_roles_and_database,
    _new_managed_topology,
    _revision,
)

pytestmark = pytest.mark.real_db

_PREV_REVISION = "20261029_0002"
_HEAD_REVISION = "20261101_0001"
_INSTALL_ID = "11111111-1111-4111-8111-111111111111"
_DATASET_ID = "22222222-2222-4222-8222-222222222222"
_BACKUP_ID = "33333333-3333-4333-8333-333333333333"


@contextmanager
def _upgrade_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    initial_revision: str,
    restore_epoch: int = 0,
):
    topology = _new_managed_topology(tmp_path)
    primary: BaseException | None = None
    try:
        _create_roles_and_database(topology)
        owner_engine = create_engine(topology.owner_url, poolclass=NullPool, future=True)
        try:
            run_alembic_for_test(
                owner_engine,
                alembic_config_for_test(),
                command.upgrade,
                initial_revision,
            )
            with owner_engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE public.dataset_authority SET "
                        "dataset_id = :dataset_id, client_generation = :install_id, "
                        "restore_epoch = :restore_epoch, restored_from_backup_id = :backup_id "
                        "WHERE singleton_id = 1"
                    ),
                    {
                        "dataset_id": _DATASET_ID,
                        "install_id": _INSTALL_ID,
                        "restore_epoch": restore_epoch,
                        "backup_id": _BACKUP_ID if restore_epoch > 0 else None,
                    },
                )
        finally:
            owner_engine.dispose()
        topology.admin.execute(
            sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(topology.owner))
        )
        write_protected_file_exclusive(
            topology.pgpass,
            (
                f"127.0.0.1:{topology.migrator_url.port}:"
                f"{topology.database}:{topology.migrator}:{_MIGRATOR_PASSWORD}\n"
            ),
        )
        monkeypatch.delenv("PGPASSWORD", raising=False)
        yield topology
    except BaseException as exc:
        primary = exc
    cleanup_error: BaseException | None = None
    try:
        cleanup_postgres_topology(
            admin=topology.admin,
            database=topology.database,
            roles=(topology.runtime_role, topology.migrator, topology.owner),
        )
    except BaseException as exc:
        cleanup_error = exc
    if primary is not None and cleanup_error is not None:
        raise BaseExceptionGroup("upgrade topology body and cleanup failed", [primary, cleanup_error])
    if primary is not None:
        raise primary
    if cleanup_error is not None:
        raise cleanup_error


def _read_attestation(url) -> dict[str, object] | None:
    engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as conn:
            raw = conn.scalar(
                text("SELECT value FROM public.app_meta WHERE key = :key"),
                {"key": UPGRADE_ATTESTATION_META_KEY},
            )
            return None if raw is None else json.loads(str(raw))
    finally:
        engine.dispose()


def _write_valid_cold_copy_v2(
    archive_path: Path,
    *,
    dataset_id: str,
    installation_id: str,
    restore_epoch: int,
    source_revision: str,
    release_id: str = "1.2.1",
    extra_members: dict[str, bytes] | None = None,
    extra_index_only: dict[str, dict[str, object]] | None = None,
    omit_member: str | None = None,
    include_program_inventory: bool = True,
    corrupt_member_bytes: dict[str, bytes] | None = None,
    app_dir_for_pg: Path | None = None,
) -> str:
    program_files: dict[str, bytes] = {
        "postgresql/bin/postgres.exe": b"pg-17-binary-fixture",
        f"releases/{release_id}/backend/ticketbox-backend.exe": b"backend-binary-fixture",
        "bin/lifecycle/TicketboxLifecycle.exe": b"lifecycle-binary-fixture",
    }
    if app_dir_for_pg is not None:
        pg_bin = app_dir_for_pg / "postgresql" / "bin" / "postgres.exe"
        pg_bin.parent.mkdir(parents=True, exist_ok=True)
        pg_bin.write_bytes(program_files["postgresql/bin/postgres.exe"])
    manifest_payload: dict[str, object] = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": release_id,
        "product_version": release_id,
        "max_schema_revision": source_revision,
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
    }
    if include_program_inventory:
        manifest_payload["immutable_payload"] = {
            "files": [
                {
                    "path": rel,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for rel, data in sorted(program_files.items())
            ]
        }
    manifest_bytes = json.dumps(manifest_payload).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    origin_op = f"fresh-{manifest_sha}"
    members: dict[str, bytes] = {
        "data/pgdata/PG_VERSION": b"17\n",
        "data/pgdata/global/pg_control": b"clean-pg-control",
        "data/app/.env": b"SECRET=1\n",
        "machine/installation.json": json.dumps({
            "schema": "ticketbox-installed-instance-v1",
            "install_id": installation_id,
            "dataset_id": dataset_id,
            "expected_restore_epoch": restore_epoch,
            "active_release_id": release_id,
            "previous_release_id": None,
            "release_manifest_sha256": manifest_sha,
        }).encode("utf-8"),
        "machine/secrets/postgres.password": b"fixture-pg-secret",
        "machine/secrets/ticketbox_migrator.password": b"fixture-migrator-secret",
        "machine/secrets/ticketbox_runtime.password": b"fixture-runtime-secret",
        "machine/secrets/pgpass": b"127.0.0.1:5438:*:ticketbox_migrator:secret\n",
        f"program/releases/{release_id}/release-manifest.json": manifest_bytes,
        f"machine/operations/history/{origin_op}.json": json.dumps({
            "schema": "ticketbox-lifecycle-operation-v2",
            "operation_id": origin_op,
            "kind": "install",
            "target_release_id": release_id,
            "release_manifest_sha256": manifest_sha,
            "phase": "committed",
            "install_id": installation_id,
            "dataset_id": dataset_id,
        }).encode("utf-8"),
    }
    if include_program_inventory:
        for rel, data in program_files.items():
            members["program/" + rel] = data
    if extra_members:
        members.update(extra_members)
    if omit_member:
        members.pop(omit_member, None)
    dirs = (
        "program/",
        "program/postgresql/",
        "program/postgresql/bin/",
        "program/bin/",
        "program/bin/lifecycle/",
        "program/releases/",
        f"program/releases/{release_id}/",
        f"program/releases/{release_id}/backend/",
        "machine/",
        "machine/secrets/",
        "machine/operations/",
        "machine/operations/history/",
        "data/pgdata/",
        "data/pgdata/global/",
        "data/attachments/",
        "data/app/",
    )
    entries: dict[str, object] = dict.fromkeys(dirs, None)
    for name, payload in sorted(members.items()):
        entries[name] = {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    if extra_index_only:
        entries.update(extra_index_only)
    cold_manifest = {
        "schema": "ticketbox-beta-cold-copy-v2",
        "complete": True,
        "identity": {
            "install_id": installation_id,
            "dataset_id": dataset_id,
            "restore_epoch": restore_epoch,
            "release_id": release_id,
            "release_manifest_sha256": manifest_sha,
            "schema_revision": source_revision,
            "postgres_major": 17,
            "postgres_system_identifier": "123456789",
        },
        "entries": entries,
        "public_connectivity": {
            "excluded_directory": "machine/connectors/cloudflare/secrets",
            "credentials": "not_backed_up",
            "after_restore": "configure_again",
        },
    }
    with zipfile.ZipFile(archive_path, "w") as zf:
        for d in dirs:
            zf.writestr(d, b"")
        for name, payload in sorted(members.items()):
            actual_bytes = (
                corrupt_member_bytes[name]
                if corrupt_member_bytes and name in corrupt_member_bytes
                else payload
            )
            zf.writestr(name, actual_bytes)
        zf.writestr("COLD_COPY.json", json.dumps(cold_manifest))
    return hashlib.sha256(archive_path.read_bytes()).hexdigest()


def test_cross_revision_upgrade_writes_same_transaction_attestation_and_rejects_mismatched_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op_id = "upgrade-" + ("a" * 64)
    other_op_id = "upgrade-" + ("b" * 64)
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION, restore_epoch=3) as topology:
        original_exec = managed_runtime.execute_database_generation

        def fail_before_commit(*args, **kwargs):
            original_exec(*args, **kwargs)
            raise RuntimeError("injected pre-commit rollback")

        monkeypatch.setattr(managed_runtime, "execute_database_generation", fail_before_commit)
        with pytest.raises(ManagedPostgresMigrationRuntimeError):
            topology.runtime.run(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                program=topology.program,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                generation_operation_id=op_id,
                expected_dataset_id=_DATASET_ID,
                expected_restore_epoch=3,
                expected_installation_id=_INSTALL_ID,
            )
        monkeypatch.setattr(managed_runtime, "execute_database_generation", original_exec)
        assert _revision(topology.admin_database_url) == _PREV_REVISION
        assert _read_attestation(topology.admin_database_url) is None

        data_root = (tmp_path / "data").resolve()
        app_dir = (tmp_path / "app").resolve()
        (data_root / "app" / "uploads").mkdir(parents=True, exist_ok=True)
        fake_archive = (tmp_path / "empty-fake.tbxcold").resolve()
        with zipfile.ZipFile(fake_archive, "w") as zf:
            zf.writestr("COLD_COPY.json", json.dumps({"entries": {}}))
        fake_sha = hashlib.sha256(fake_archive.read_bytes()).hexdigest()
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=3,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=fake_archive,
                backup_archive_sha256=fake_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION
        assert _read_attestation(topology.admin_database_url) is None

        missing_pg_archive = (tmp_path / "missing-pg.tbxcold").resolve()
        missing_pg_sha = _write_valid_cold_copy_v2(
            missing_pg_archive,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=3,
            source_revision=_PREV_REVISION,
            omit_member="data/pgdata/global/pg_control",
            app_dir_for_pg=app_dir,
        )
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=3,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=missing_pg_archive,
                backup_archive_sha256=missing_pg_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        archive_path = (tmp_path / "valid-pre-upgrade.tbxcold").resolve()
        archive_sha = _write_valid_cold_copy_v2(
            archive_path,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=3,
            source_revision=_PREV_REVISION,
            app_dir_for_pg=app_dir,
        )

        # Missing app_dir must fail closed rather than skipping full PG tree verification.
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=3,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=archive_path,
                backup_archive_sha256=archive_sha,
                app_dir=None,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        result = run_existing_dataset_upgrade_action(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            source_revision=_PREV_REVISION,
            target_revision=_HEAD_REVISION,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            expected_restore_epoch=3,
            operation_id=op_id,
            data_root=data_root,
            backup_archive=archive_path,
            backup_archive_sha256=archive_sha,
            app_dir=app_dir,
            program=topology.program,
            contract=topology.contract,
            seal_runtime_authority=False,
            machine_secret=False,
        )
        assert result["result"] == "target_committed"
        assert result["backup_archive_sha256"] == archive_sha
        assert _revision(topology.admin_database_url) == _HEAD_REVISION
        assert _read_attestation(topology.admin_database_url) == {
            "schema": UPGRADE_ATTESTATION_SCHEMA,
            "operation_id": op_id,
            "dataset_id": _DATASET_ID,
            "restore_epoch": 3,
            "source_revision": _PREV_REVISION,
            "target_revision": _HEAD_REVISION,
            "backup_archive_sha256": archive_sha,
        }

        replay = run_existing_dataset_upgrade_action(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            source_revision=_PREV_REVISION,
            target_revision=_HEAD_REVISION,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            expected_restore_epoch=3,
            operation_id=op_id,
            data_root=data_root,
            backup_archive=archive_path,
            backup_archive_sha256=archive_sha,
            app_dir=app_dir,
            program=topology.program,
            contract=topology.contract,
            seal_runtime_authority=False,
            machine_secret=False,
        )
        assert replay["result"] == "target_observed_after_interruption"

        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=3,
                operation_id=other_op_id,
                data_root=data_root,
                backup_archive=archive_path,
                backup_archive_sha256=archive_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )


def test_forged_target_revision_without_attestation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_HEAD_REVISION) as topology:
        assert _read_attestation(topology.admin_database_url) is None
        with pytest.raises(ManagedPostgresMigrationRuntimeError):
            topology.runtime.run(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                program=topology.program,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                generation_operation_id=str(uuid4()),
                expected_dataset_id=_DATASET_ID,
                expected_restore_epoch=0,
                expected_installation_id=_INSTALL_ID,
            )
        assert _read_attestation(topology.admin_database_url) is None


def test_same_schema_upgrade_enforces_target_postcondition_and_writes_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op_id = "upgrade-" + ("c" * 64)
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_HEAD_REVISION) as topology:
        original_postcondition = executor._assert_postcondition
        observed: list[str] = []

        def fail_postcondition(connection, revision):
            observed.append(revision.revision)
            raise RuntimeError("injected target postcondition failure")

        monkeypatch.setattr(executor, "_assert_postcondition", fail_postcondition)
        with pytest.raises(ManagedPostgresMigrationRuntimeError):
            topology.runtime.run(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                program=topology.program,
                source_revision=_HEAD_REVISION,
                target_revision=_HEAD_REVISION,
                generation_operation_id=op_id,
                expected_dataset_id=_DATASET_ID,
                expected_restore_epoch=0,
                expected_installation_id=_INSTALL_ID,
            )
        monkeypatch.setattr(executor, "_assert_postcondition", original_postcondition)
        assert observed == [_HEAD_REVISION]
        assert _read_attestation(topology.admin_database_url) is None

        first = topology.runtime.run(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            program=topology.program,
            source_revision=_HEAD_REVISION,
            target_revision=_HEAD_REVISION,
            generation_operation_id=op_id,
            expected_dataset_id=_DATASET_ID,
            expected_restore_epoch=0,
            expected_installation_id=_INSTALL_ID,
        )
        assert first == "target_committed"
        assert _read_attestation(topology.admin_database_url) == {
            "schema": UPGRADE_ATTESTATION_SCHEMA,
            "operation_id": op_id,
            "dataset_id": _DATASET_ID,
            "restore_epoch": 0,
            "source_revision": _HEAD_REVISION,
            "target_revision": _HEAD_REVISION,
            "backup_archive_sha256": None,
        }

        replay = topology.runtime.run(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            program=topology.program,
            source_revision=_HEAD_REVISION,
            target_revision=_HEAD_REVISION,
            generation_operation_id=op_id,
            expected_dataset_id=_DATASET_ID,
            expected_restore_epoch=0,
            expected_installation_id=_INSTALL_ID,
        )
        assert replay == "target_observed_after_interruption"

        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{topology.owner}"'))
                conn.execute(
                    text("UPDATE public.app_meta SET value = :value WHERE key = :key"),
                    {
                        "key": UPGRADE_ATTESTATION_META_KEY,
                        "value": json.dumps({
                            "schema": UPGRADE_ATTESTATION_SCHEMA,
                            "operation_id": op_id,
                            "dataset_id": _DATASET_ID,
                            "restore_epoch": 99,
                            "source_revision": _HEAD_REVISION,
                            "target_revision": _HEAD_REVISION,
                            "backup_archive_sha256": None,
                        }),
                    },
                )
        finally:
            admin_engine.dispose()

        with pytest.raises(ManagedPostgresMigrationRuntimeError):
            topology.runtime.run(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                program=topology.program,
                source_revision=_HEAD_REVISION,
                target_revision=_HEAD_REVISION,
                generation_operation_id=op_id,
                expected_dataset_id=_DATASET_ID,
                expected_restore_epoch=0,
                expected_installation_id=_INSTALL_ID,
            )


def test_postgres_runtime_role_cannot_mutate_upgrade_attestation_but_can_write_normal_app_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op_id = "upgrade-" + ("d" * 64)
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION, restore_epoch=1) as topology:
        outcome = topology.runtime.run(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            program=topology.program,
            source_revision=_PREV_REVISION,
            target_revision=_HEAD_REVISION,
            generation_operation_id=op_id,
            expected_dataset_id=_DATASET_ID,
            expected_restore_epoch=1,
            expected_installation_id=_INSTALL_ID,
        )
        assert outcome == "target_committed"

        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'GRANT CONNECT ON DATABASE "{topology.database}" TO "{topology.runtime_role}"'))
                conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{topology.runtime_role}"'))
                conn.execute(
                    text(
                        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.app_meta TO "{topology.runtime_role}"'
                    )
                )
        finally:
            admin_engine.dispose()

        runtime_url = _connection_url(
            database=topology.database,
            username=topology.runtime_role,
            password=_RUNTIME_PASSWORD,
            require_auth=True,
        )
        runtime_engine = create_engine(runtime_url, poolclass=NullPool, future=True)
        try:
            with runtime_engine.begin() as conn:
                readable = conn.scalar(
                    text("SELECT value FROM public.app_meta WHERE key = :key"),
                    {"key": UPGRADE_ATTESTATION_META_KEY},
                )
                assert readable is not None and json.loads(str(readable))["operation_id"] == op_id
                conn.execute(
                    text(
                        "INSERT INTO public.app_meta (key, value, updated_at) "
                        "VALUES ('learning_cleanup_last_run_at', '2026-11-26T00:00:00Z', NOW())"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE public.app_meta SET value = '2026-11-26T01:00:00Z' "
                        "WHERE key = 'learning_cleanup_last_run_at'"
                    )
                )

            for statement in (
                (
                    "UPDATE public.app_meta SET value = 'forged' "
                    f"WHERE key = '{UPGRADE_ATTESTATION_META_KEY}'"
                ),
                (
                    "UPDATE public.app_meta SET key = 'renamed_attestation' "
                    f"WHERE key = '{UPGRADE_ATTESTATION_META_KEY}'"
                ),
                (
                    f"UPDATE public.app_meta SET key = '{UPGRADE_ATTESTATION_META_KEY}' "
                    "WHERE key = 'learning_cleanup_last_run_at'"
                ),
                f"DELETE FROM public.app_meta WHERE key = '{UPGRADE_ATTESTATION_META_KEY}'",
                (
                    "INSERT INTO public.app_meta (key, value, updated_at) "
                    f"VALUES ('{UPGRADE_ATTESTATION_META_KEY}', 'forged', NOW()) "
                    "ON CONFLICT (key) DO UPDATE SET value = 'forged'"
                ),
                "DROP TRIGGER trg_ticketbox_guard_upgrade_attestation ON public.app_meta",
                "ALTER TABLE public.app_meta DISABLE TRIGGER ALL",
            ):
                with pytest.raises(ProgrammingError) as caught, runtime_engine.begin() as conn:
                    conn.execute(text(statement))
                assert isinstance(caught.value.orig, pg_errors.InsufficientPrivilege)

            with runtime_engine.begin() as conn:
                conn.execute(text("DELETE FROM public.app_meta WHERE key = 'learning_cleanup_last_run_at'"))
        finally:
            runtime_engine.dispose()

        assert _read_attestation(topology.admin_database_url)["operation_id"] == op_id


def test_runtime_cannot_mutate_upgrade_attestation_and_upgrade_verify_blocks_business_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(AppError) as caught:
        set_value(None, UPGRADE_ATTESTATION_META_KEY, "forged")  # type: ignore[arg-type]
    assert caught.value.error == "dataset_authority_read_only"

    import app.main as main_mod
    from app.services import background_task_executor

    called: list[str] = []
    attestation_key = "a" * 64
    challenge = "b" * 64
    monkeypatch.setenv("TICKETBOX_UPGRADE_VERIFY_ONLY", "1")
    monkeypatch.setenv("TICKETBOX_HEALTH_ATTESTATION_KEY", attestation_key)
    monkeypatch.setattr(main_mod, "wait_for_db", lambda: called.append("wait"))
    monkeypatch.setattr(main_mod, "init_db", lambda: called.append("verify"))
    monkeypatch.setattr(main_mod, "assert_installation_database_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(main_mod, "installation_owner_state", lambda *_a, **_k: "configured")
    monkeypatch.setattr(
        background_task_executor,
        "start_executor",
        lambda: pytest.fail("upgrade verification started background writer"),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        for method, path in (("get", "/"), ("get", "/api/expenses"), ("post", "/api/auth/pair")):
            response = getattr(client, method)(path)
            assert response.status_code == 503
            assert response.json()["error"] == "upgrade_verification_in_progress"
        health = client.get(
            "/api/health/installation",
            headers={"X-Ticketbox-Health-Challenge": challenge},
        )
        assert health.status_code == 200
        assert health.headers["X-Ticketbox-Runtime-Mode"] == "upgrade_verify_only"
        assert health.headers["X-Ticketbox-Health-Attestation"] == sign_health_challenge(
            attestation_key,
            challenge,
        )
        assert health.headers["X-Ticketbox-Runtime-Mode-Attestation"] == sign_runtime_mode_challenge(
            attestation_key,
            challenge,
            "upgrade_verify_only",
        )
        monkeypatch.setenv("TICKETBOX_UPGRADE_VERIFY_ONLY", "0")
        normal = client.get(
            "/api/health/installation",
            headers={"X-Ticketbox-Health-Challenge": challenge},
        )
        assert normal.status_code == 200
        assert normal.headers["X-Ticketbox-Runtime-Mode"] == "normal"
        assert normal.headers["X-Ticketbox-Runtime-Mode-Attestation"] == sign_runtime_mode_challenge(
            attestation_key,
            challenge,
            "normal",
        )
    assert called == ["wait", "verify"]


def test_missing_or_corrupt_retained_original_blocks_sql_upgrade_before_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import Session

    from app.models.currency_binding import InstallationCurrencyBinding
    from app.services.identity_service import bootstrap_installation_owner
    from app.services.time_service import now_utc

    op_id = "upgrade-" + ("f" * 64)
    image_bytes = b"\xff\xd8\xff\xe0retained-original-receipt"
    image_sha = hashlib.sha256(image_bytes).hexdigest()
    old_bytes = b"\xff\xd8\xff\xe0historical-replaced-receipt"
    old_sha = hashlib.sha256(old_bytes).hexdigest()
    bill_bytes = b"\xff\xd8\xff\xe0debt-bill-original"
    bill_sha = hashlib.sha256(bill_bytes).hexdigest()
    corrupt_bill = b"\xff\xd8\xff\xe0debt-bill-corrupted-pre-backup"
    rel_path = "uploads/owner/receipt.jpg"
    old_rel = "uploads/owner/old-receipt.jpg"
    bill_rel = "uploads/owner/bill.jpg"
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION, restore_epoch=0) as topology:
        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{topology.owner}"'))
                with Session(bind=conn, expire_on_commit=False) as db:
                    bootstrap_installation_owner(
                        db,
                        operation_id="source-install",
                        installation_id=_INSTALL_ID,
                        bootstrap_secret="retained-original-test-bootstrap-secret-01",
                        commit=False,
                    )
                    binding = db.get(InstallationCurrencyBinding, 1)
                    assert binding is not None
                    activated_at = now_utc()
                    binding.state = "ACTIVE"
                    binding.home_currency_code = "CNY"
                    binding.minor_unit_exponent = 2
                    binding.rounding_mode = "ROUND_HALF_UP"
                    binding.binding_revision = 1
                    binding.provenance = "TEST_FIXTURE"
                    binding.evidence_sha256 = "0" * 64
                    binding.updated_at = activated_at
                    binding.activated_at = activated_at
                    db.flush()
                owner_account_id = int(conn.scalar(text("SELECT id FROM public.accounts LIMIT 1")) or 0)
                conn.execute(text("SELECT set_config('xpj.currency_writer', '1:1', true)"))
                expense_id = int(
                    conn.scalar(
                        text(
                            "INSERT INTO public.expenses ("
                            "public_id, tenant_id, merchant, category, source, amount_cents, original_amount_minor, "
                            "home_currency_code, original_currency_code, fx_status, status, duplicate_status, "
                            "items_sum_status, row_version, fact_revision, "
                            "image_path, image_hash, image_deleted_at, created_at, updated_at"
                            ") VALUES ("
                            "'exp-orig-1', 'owner', 'Coffee', 'Food', 'manual', 1200, 1200, "
                            "'CNY', 'CNY', 'ready', 'confirmed', 'none', 'no_items', 1, 0, "
                            ":image_path, :image_hash, NULL, NOW(), NOW()"
                            ") RETURNING id"
                        ),
                        {"image_path": rel_path, "image_hash": image_sha},
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO public.api_idempotency_keys ("
                        "tenant_id, idempotency_key, operation, request_fingerprint, status, "
                        "resource_type, resource_id, response_body, created_at, completed_at, expires_at"
                        ") VALUES ("
                        "'owner', 'idem-hist-1', 'create_expense', :fp, 'succeeded', "
                        "'expense', 'exp-orig-1', CAST(:body AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        ")"
                    ),
                    {
                        "fp": "1" * 64,
                        "body": json.dumps({
                            "id": str(expense_id),
                            "public_id": "exp-orig-1",
                            "image_path": old_rel,
                            "image_hash": old_sha,
                            "image_deleted_at": None,
                        }),
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO public.api_idempotency_keys ("
                        "tenant_id, idempotency_key, operation, request_fingerprint, status, "
                        "resource_type, resource_id, response_body, created_at, completed_at, expires_at"
                        ") VALUES ("
                        "'owner', 'idem-hist-cleaned-1', 'create_expense', :fp1, 'succeeded', "
                        "'expense', 'exp-orig-1', CAST(:body1 AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        "), ("
                        "'owner', 'idem-hist-cleaned-2', 'clean_expense', :fp2, 'succeeded', "
                        "'expense', 'exp-orig-1', CAST(:body2 AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        ")"
                    ),
                    {
                        "fp1": "3" * 64,
                        "body1": json.dumps({
                            "id": expense_id,
                            "public_id": "exp-orig-1",
                            "image_path": "uploads/owner/cleaned-receipt.jpg",
                            "image_hash": "9" * 64,
                            "image_deleted_at": None,
                        }),
                        "fp2": "4" * 64,
                        "body2": json.dumps({
                            "id": str(expense_id),
                            "public_id": "exp-orig-1",
                            "image_path": "uploads/owner/cleaned-receipt.jpg",
                            "image_hash": "9" * 64,
                            "image_deleted_at": "2026-10-30T00:00:00Z",
                        }),
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO public.debt_bill_captures ("
                        "public_id, tenant_id, created_by_account_id, creation_key, capture_key, "
                        "request_fingerprint, accepted_receipt, file_name, media_type, input_sha256, "
                        "image_path, image_hash, image_size_bytes, status, row_version, created_at, updated_at"
                        ") VALUES ("
                        "'cap-orig-1', 'owner', :acct, 'ck-1', 'capk-1', :fp, CAST('{}' AS jsonb), "
                        "'bill.jpg', 'image/jpeg', :bill_sha, :bill_path, :bill_sha, :bill_len, "
                        "'pending', 1, NOW(), NOW()"
                        ")"
                    ),
                    {
                        "acct": owner_account_id,
                        "fp": "2" * 64,
                        "bill_sha": bill_sha,
                        "bill_path": bill_rel,
                        "bill_len": len(bill_bytes),
                    },
                )
        finally:
            admin_engine.dispose()

        data_root = (tmp_path / "data").resolve()
        uploads = data_root / "app" / "uploads" / "owner"
        uploads.mkdir(parents=True, exist_ok=True)
        upload_file = uploads / "receipt.jpg"
        old_file = uploads / "old-receipt.jpg"
        bill_file = uploads / "bill.jpg"
        archive_path = (tmp_path / "pre-upgrade.tbxcold").resolve()
        app_dir = (tmp_path / "app").resolve()

        def write_cold(
            entries: dict[str, object],
            members: dict[str, bytes] | None = None,
        ) -> str:
            index_only = {k: v for k, v in entries.items() if k not in (members or {})}
            return _write_valid_cold_copy_v2(
                archive_path,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                restore_epoch=0,
                source_revision=_PREV_REVISION,
                extra_members=members,
                extra_index_only=index_only,
                app_dir_for_pg=app_dir,
            )

        base_kwargs = {
            "database_url": topology.migrator_url.render_as_string(hide_password=False),
            "pgpassfile": topology.pgpass,
            "source_revision": _PREV_REVISION,
            "target_revision": _HEAD_REVISION,
            "dataset_id": _DATASET_ID,
            "installation_id": _INSTALL_ID,
            "expected_restore_epoch": 0,
            "operation_id": op_id,
            "data_root": data_root,
            "app_dir": app_dir,
            "program": topology.program,
            "contract": topology.contract,
            "seal_runtime_authority": False,
            "machine_secret": False,
        }

        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(**base_kwargs)
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        sha = write_cold({})
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        upload_file.write_bytes(image_bytes)
        old_file.write_bytes(old_bytes)
        bill_file.write_bytes(bill_bytes)

        index_only_entries = {
            "data/app/uploads/owner/receipt.jpg": {"size": len(image_bytes), "sha256": image_sha},
            "data/app/uploads/owner/old-receipt.jpg": {"size": len(old_bytes), "sha256": old_sha},
            "data/app/uploads/owner/bill.jpg": {"size": len(bill_bytes), "sha256": bill_sha},
        }
        sha_index_only = write_cold(index_only_entries)
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_index_only
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        full_members = {
            "data/app/uploads/owner/receipt.jpg": image_bytes,
            "data/app/uploads/owner/old-receipt.jpg": old_bytes,
            "data/app/uploads/owner/bill.jpg": bill_bytes,
        }
        sha_full = write_cold(index_only_entries, full_members)
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256="0" * 64
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        old_file.unlink()
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_full
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION
        old_file.write_bytes(old_bytes)

        corrupt_bill_sha = hashlib.sha256(corrupt_bill).hexdigest()
        bill_file.write_bytes(corrupt_bill)
        corrupt_entries = {
            **index_only_entries,
            "data/app/uploads/owner/bill.jpg": {"size": len(corrupt_bill), "sha256": corrupt_bill_sha},
        }
        corrupt_members = {**full_members, "data/app/uploads/owner/bill.jpg": corrupt_bill}
        sha_corrupt_bill = write_cold(corrupt_entries, corrupt_members)
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_corrupt_bill
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION
        bill_file.write_bytes(bill_bytes)

        sha_valid = write_cold(index_only_entries, full_members)
        result = run_existing_dataset_upgrade_action(
            **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_valid
        )
        assert result["result"] == "target_committed"
        assert result["backup_archive_sha256"] == sha_valid
        assert _revision(topology.admin_database_url) == _HEAD_REVISION
        attestation = _read_attestation(topology.admin_database_url)
        assert attestation is not None and attestation["backup_archive_sha256"] == sha_valid


def test_cold_restore_transaction_installs_upgrade_attestation_trigger_on_baseline_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import Session

    from app.cold_restore_runtime import _execute_cold_restore_transaction
    from app.services.identity_service import bootstrap_installation_owner

    old_secret = "cold-restore-baseline-owner-secret-0001"
    new_secret = "cold-restore-rebound-owner-secret-0002"
    new_install = "44444444-4444-4444-8444-444444444444"
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_HEAD_REVISION, restore_epoch=0) as topology:
        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(text("DROP TRIGGER IF EXISTS trg_ticketbox_guard_upgrade_attestation ON public.app_meta"))
                conn.execute(text(f'SET LOCAL ROLE "{topology.owner}"'))
                with Session(bind=conn, expire_on_commit=False) as db:
                    bootstrap_installation_owner(
                        db,
                        operation_id="source-install",
                        installation_id=_INSTALL_ID,
                        bootstrap_secret=old_secret,
                        commit=False,
                    )
                    db.flush()
                conn.execute(text("RESET ROLE"))
                conn.execute(text(f'GRANT CONNECT ON DATABASE "{topology.database}" TO "{topology.runtime_role}"'))
                conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{topology.runtime_role}"'))
                conn.execute(
                    text(
                        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.app_meta TO "{topology.runtime_role}"'
                    )
                )
        finally:
            admin_engine.dispose()

        data_root = (tmp_path / "restore-data").resolve()
        (data_root / "app" / "uploads").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("TICKETBOX_DATA_DIR", str(data_root / "app"))
        monkeypatch.setenv("UPLOAD_DIR", str(data_root / "app" / "uploads"))
        monkeypatch.setenv("PGPASSFILE", str(topology.pgpass))

        migrator_engine = create_engine(topology.migrator_url, poolclass=NullPool, future=True)
        try:
            with migrator_engine.begin() as conn:
                _execute_cold_restore_transaction(
                    conn,
                    {
                        "source": {
                            "install_id": _INSTALL_ID,
                            "dataset_id": _DATASET_ID,
                            "restore_epoch": 0,
                            "schema_revision": _HEAD_REVISION,
                        },
                        "installation_id": new_install,
                        "backup_id": _BACKUP_ID,
                        "operation_id": "restore-" + ("1" * 64),
                        "bootstrap_secret": new_secret,
                        "recovery_secret": old_secret,
                    },
                    database_name=topology.database,
                    migrator_role=topology.migrator,
                    schema_owner_role=topology.owner,
                )
        finally:
            migrator_engine.dispose()

        runtime_url = _connection_url(
            database=topology.database,
            username=topology.runtime_role,
            password=_RUNTIME_PASSWORD,
            require_auth=True,
        )
        runtime_engine = create_engine(runtime_url, poolclass=NullPool, future=True)
        try:
            with pytest.raises(ProgrammingError) as caught, runtime_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO public.app_meta (key, value, updated_at) "
                        f"VALUES ('{UPGRADE_ATTESTATION_META_KEY}', 'forged-after-restore', NOW())"
                    )
                )
            assert isinstance(caught.value.orig, pg_errors.InsufficientPrivilege)
            with runtime_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO public.app_meta (key, value, updated_at) "
                        "VALUES ('learning_cleanup_last_run_at', '2026-11-26T02:00:00Z', NOW())"
                    )
                )
        finally:
            runtime_engine.dispose()


def test_upgrade_cli_requires_backup_archive_and_sha256_arguments(tmp_path: Path) -> None:
    import importlib.util

    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location("ticketbox_upgrade_cli_parse_probe", launch_path)
    assert spec is not None and spec.loader is not None
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)

    base = [
        "--upgrade-existing-dataset",
        "--database-url",
        "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5438/ticketbox",
        "--pgpassfile",
        str(tmp_path / "pgpass"),
        "--source-revision",
        _PREV_REVISION,
        "--target-revision",
        _HEAD_REVISION,
        "--dataset-id",
        _DATASET_ID,
        "--installation-id",
        _INSTALL_ID,
        "--expected-restore-epoch",
        "0",
        "--operation-id",
        "upgrade-" + ("a" * 64),
        "--data-root",
        str(tmp_path / "data"),
    ]
    with pytest.raises(SystemExit):
        launch._parse_existing_dataset_upgrade_args(base)
    with pytest.raises(SystemExit):
        launch._parse_existing_dataset_upgrade_args([*base, "--backup-archive", str(tmp_path / "pre.tbxcold")])
    parsed = launch._parse_existing_dataset_upgrade_args([
        *base,
        "--backup-archive",
        str(tmp_path / "pre.tbxcold"),
        "--backup-archive-sha256",
        "b" * 64,
    ])
    assert parsed.backup_archive == tmp_path / "pre.tbxcold"
    assert parsed.backup_archive_sha256 == "b" * 64


def test_pass4_backup_archive_parity_with_cold_restore_source_and_full_member_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle_root = str(Path(__file__).resolve().parents[2] / "distribution" / "windows" / "lifecycle")
    monkeypatch.syspath_prepend(lifecycle_root)
    from ticketbox_lifecycle.errors import LifecycleError
    from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
    from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest

    op_id = "upgrade-" + ("7" * 64)
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION, restore_epoch=1) as topology:
        data_root = (tmp_path / "data").resolve()
        (data_root / "app" / "uploads").mkdir(parents=True, exist_ok=True)
        app_dir = (tmp_path / "app").resolve()

        valid_archive = (tmp_path / "parity-valid.tbxcold").resolve()
        valid_sha = _write_valid_cold_copy_v2(
            valid_archive,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=1,
            source_revision=_PREV_REVISION,
            app_dir_for_pg=app_dir,
        )
        restore_req = InstallRequest(
            schema=REQUEST_SCHEMA,
            command="restore",
            operation_id="restore-" + ("0" * 64),
            request_hash="pending",
            target_release_id="1.2.1",
            app_dir=str(app_dir),
            data_root=str(data_root),
            program_data_root=str(tmp_path / "programdata"),
            pg_service_name="TicketboxPg",
            backend_service_name="TicketboxBackend",
            pg_port=5432,
            backend_port=8000,
            postgres_major=17,
            release_manifest_sha256="0" * 64,
            schema_revision=_PREV_REVISION,
            semantic_revision="ticketbox-dataset-semantics-v1",
        )
        with valid_archive.open("rb") as stream:
            source = ColdRestoreSource(stream, valid_sha, restore_req)
            assert source.identity["dataset_id"] == _DATASET_ID

        no_inventory = (tmp_path / "no-inventory.tbxcold").resolve()
        no_inventory_sha = _write_valid_cold_copy_v2(
            no_inventory,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=1,
            source_revision=_PREV_REVISION,
            include_program_inventory=False,
        )
        with pytest.raises(LifecycleError), no_inventory.open("rb") as stream:
            ColdRestoreSource(stream, no_inventory_sha, restore_req)
        with pytest.raises(ExistingDatasetUpgradeError) as no_inv_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=1,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=no_inventory,
                backup_archive_sha256=no_inventory_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "program inventory" in str(no_inv_exc.value.__cause__.__cause__)

        corrupt_member = (tmp_path / "corrupt-extra.tbxcold").resolve()
        corrupt_member_sha = _write_valid_cold_copy_v2(
            corrupt_member,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=1,
            source_revision=_PREV_REVISION,
            extra_members={"data/app/unrelated.bin": b"good-bytes"},
            corrupt_member_bytes={"data/app/unrelated.bin": b"tampered-bytes"},
        )
        with pytest.raises(LifecycleError), corrupt_member.open("rb") as stream:
            ColdRestoreSource(stream, corrupt_member_sha, restore_req)
        with pytest.raises(ExistingDatasetUpgradeError) as corrupt_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=1,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=corrupt_member,
                backup_archive_sha256=corrupt_member_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "checksum mismatch" in str(corrupt_exc.value.__cause__.__cause__)

        result = run_existing_dataset_upgrade_action(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            source_revision=_PREV_REVISION,
            target_revision=_HEAD_REVISION,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            expected_restore_epoch=1,
            operation_id=op_id,
            data_root=data_root,
            backup_archive=valid_archive,
            backup_archive_sha256=valid_sha,
            app_dir=app_dir,
            program=topology.program,
            contract=topology.contract,
            seal_runtime_authority=False,
            machine_secret=False,
        )
        assert result["result"] == "target_committed"


def test_pass4_historical_receipt_pg_integer_hex_and_overflow_match_source_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import Session

    from app.services.identity_service import bootstrap_installation_owner

    op_id = "upgrade-" + ("8" * 64)
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION) as topology:
        data_root = (tmp_path / "data").resolve()
        (data_root / "app" / "uploads" / "owner").mkdir(parents=True, exist_ok=True)
        missing_rel = "uploads/owner/hex-missing.jpg"
        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{topology.owner}"'))
                with Session(bind=conn, expire_on_commit=False) as db:
                    bootstrap_installation_owner(
                        db,
                        operation_id="source-install",
                        installation_id=_INSTALL_ID,
                        bootstrap_secret="hex-overflow-test-bootstrap-secret-01",
                        commit=False,
                    )
                    db.flush()
                conn.execute(
                    text(
                        "INSERT INTO public.api_idempotency_keys ("
                        "tenant_id, idempotency_key, operation, request_fingerprint, status, "
                        "resource_type, resource_id, response_body, created_at, completed_at, expires_at"
                        ") VALUES ("
                        "'owner', 'hex-id-key', 'create_expense', :fp, 'succeeded', "
                        "'expense', 'exp-hex-42', CAST(:body AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        ")"
                    ),
                    {
                        "fp": "a" * 64,
                        "body": json.dumps({
                            "id": "0x2a",
                            "public_id": "exp-hex-42",
                            "image_path": missing_rel,
                            "image_hash": "a" * 64,
                            "image_deleted_at": None,
                        }),
                    },
                )
        finally:
            admin_engine.dispose()

        app_dir = (tmp_path / "app").resolve()
        archive_path = (tmp_path / "hex-check.tbxcold").resolve()
        archive_sha = _write_valid_cold_copy_v2(
            archive_path,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=0,
            source_revision=_PREV_REVISION,
            app_dir_for_pg=app_dir,
        )
        with pytest.raises(ExistingDatasetUpgradeError) as hex_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=0,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=archive_path,
                backup_archive_sha256=archive_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "retained original" in str(hex_exc.value.__cause__.__cause__)
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE public.api_idempotency_keys "
                        "SET response_body = CAST(:body AS json) "
                        "WHERE idempotency_key = 'hex-id-key'"
                    ),
                    {
                        "body": json.dumps({
                            "id": "2147483648",
                            "public_id": "exp-overflow",
                            "image_path": missing_rel,
                            "image_hash": "a" * 64,
                            "image_deleted_at": None,
                        })
                    },
                )
        finally:
            admin_engine.dispose()

        with pytest.raises(ExistingDatasetUpgradeError) as overflow_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=0,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=archive_path,
                backup_archive_sha256=archive_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "projection failed" in str(overflow_exc.value.__cause__.__cause__)
        assert _revision(topology.admin_database_url) == _PREV_REVISION
