"""Real PostgreSQL tests for same-transaction managed upgrade attestation and crash recovery."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
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
from tests._managed_upgrade_fixtures import (
    _BACKUP_ID,
    _DATASET_ID,
    _HEAD_REVISION,
    _INSTALL_ID,
    _PREV_REVISION,
    _read_attestation,
    _upgrade_topology,
    _write_valid_cold_copy_v2,
)
from tests.managed_postgres_test_support import _RUNTIME_PASSWORD, _connection_url, _revision

pytestmark = pytest.mark.real_db


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
                    upload_root=data_root / "app" / "uploads",
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


