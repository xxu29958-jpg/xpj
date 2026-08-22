"""Failure-fidelity contracts for complete dataset backup and restore actions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

OPERATION_ID = "11111111-1111-4111-8111-111111111111"
INSTALLATION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TARGET_REVISION = "20260729_0001"
MIGRATOR_URL = "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256"


class _QuietContext:
    def __init__(self, value) -> None:
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *_args) -> bool:
        return False


class _RestoreConnection:
    def scalar(self, statement) -> int:
        if "FROM pg_namespace" in str(statement):
            return 0
        return 1

    def execute(self, _statement):
        return None


class _FailingTransaction(_QuietContext):
    def __init__(self, primary: BaseException, cleanup: BaseException) -> None:
        super().__init__(_RestoreConnection())
        self.primary = primary
        self.cleanup = cleanup

    def __exit__(self, exc_type, exc, _traceback) -> bool:
        assert exc_type is type(self.primary)
        assert exc is self.primary
        raise self.cleanup


class _RestoreEngine:
    def __init__(
        self,
        *,
        final: bool,
        primary: BaseException,
        cleanup: BaseException,
    ) -> None:
        self.final = final
        self.primary = primary
        self.cleanup = cleanup

    def connect(self):
        return _QuietContext(_RestoreConnection())

    def begin(self):
        if self.final:
            return _FailingTransaction(self.primary, self.cleanup)
        return _QuietContext(_RestoreConnection())

    def dispose(self) -> None:
        return None


def test_complete_backup_action_preserves_body_and_session_exit_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.database import _dataset_backup_action as action

    primary = RuntimeError("backup body failed")
    session_cleanup = SystemExit("backup session rollback interrupted")

    class FailingSession(_QuietContext):
        def __exit__(self, exc_type, exc, _traceback) -> bool:
            assert exc_type is RuntimeError
            assert exc is primary
            raise session_cleanup

    class Engine:
        def connect(self):
            return _QuietContext(object())

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(action, "validated_local_role_url", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(action, "hold_protected_file_for_read", lambda path: _QuietContext(path))
    monkeypatch.setattr(action, "_temporary_pgpass_environment", lambda path: _QuietContext(path))
    monkeypatch.setattr(action, "_create_engine", lambda _url: Engine())
    monkeypatch.setattr(action, "Session", lambda **_kwargs: FailingSession(object()))
    monkeypatch.setattr(
        action,
        "create_complete_backup_generation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(primary),
    )
    request = action.CompleteBackupRequest(
        backup_root=tmp_path,
        inventory_path=tmp_path / "backup-inventory.json",
        upload_root=tmp_path,
        database_url="postgresql+psycopg://ticketbox_backup@localhost/ticketbox",
        passfile=tmp_path / "pgpass",
        pg_dump_binary=tmp_path / "pg_dump.exe",
        pg_restore_binary=tmp_path / "pg_restore.exe",
        operation_id=OPERATION_ID,
        backup_id="22222222-2222-4222-8222-222222222222",
        release_id="release",
        backup_kind="manual",
        writer_fence_sha256="b" * 64,
        expected_current_sha256="c" * 64,
        expected_installation_id=INSTALLATION_ID,
        expected_dataset_id="33333333-3333-4333-8333-333333333333",
        expected_restore_epoch=0,
        expected_schema_revision=TARGET_REVISION,
    )

    with pytest.raises(BaseExceptionGroup) as caught:
        action.run_complete_dataset_backup_action(request)
    assert caught.value.exceptions == (primary, session_cleanup)


def test_isolated_restore_action_preserves_finalization_and_rollback_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.database._dataset_restore_action as action

    primary = RuntimeError("restore finalization failed")
    rollback_cleanup = SystemExit("restore rollback interrupted")
    source = SimpleNamespace(
        backup_id="22222222-2222-4222-8222-222222222222",
        authority=SimpleNamespace(schema_revision=TARGET_REVISION),
        originals=(),
    )
    plan = SimpleNamespace(
        dataset_id="33333333-3333-4333-8333-333333333333",
        restore_epoch=1,
        schema_revision=TARGET_REVISION,
    )
    engines = iter(
        (
            _RestoreEngine(final=False, primary=primary, cleanup=rollback_cleanup),
            _RestoreEngine(final=True, primary=primary, cleanup=rollback_cleanup),
        )
    )
    monkeypatch.setattr(action, "read_manifest", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(action, "resolve_restored_dataset_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(action, "_validated_migrator_url", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(action, "hold_protected_file_for_read", lambda path: _QuietContext(path))
    monkeypatch.setattr(action, "_temporary_pgpass_environment", lambda path: _QuietContext(path))
    monkeypatch.setattr(action, "_create_engine", lambda _url: next(engines))
    monkeypatch.setattr(action, "restore_postgres_archive", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(action, "materialize_restored_originals", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        action,
        "finalize_restored_dataset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(primary),
    )
    request = action.CompleteRestoreRequest(
        backup_generation=tmp_path,
        target_upload_root=tmp_path / "uploads",
        database_url="postgresql+psycopg://ticketbox_migrator@localhost/ticketbox",
        passfile=tmp_path / "pgpass",
        pg_restore_binary=tmp_path / "pg_restore.exe",
        active_installation_id=INSTALLATION_ID,
        active_dataset_id="33333333-3333-4333-8333-333333333333",
        active_restore_epoch=0,
        target_schema_revision=TARGET_REVISION,
        restore_role="ticketbox_owner",
    )

    with pytest.raises(BaseExceptionGroup) as caught:
        action.run_isolated_dataset_restore_action(request)
    assert caught.value.exceptions == (primary, rollback_cleanup)


def test_isolated_restore_action_rejects_foreign_dataset_before_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.database._dataset_restore_action as action
    from app.errors import AppError

    source = SimpleNamespace(
        backup_id="22222222-2222-4222-8222-222222222222",
        authority=SimpleNamespace(
            dataset_id="33333333-3333-4333-8333-333333333333",
            restore_epoch=4,
            schema_revision=TARGET_REVISION,
            semantic_revision="ticketbox-dataset-semantics-v1",
        ),
        originals=(),
    )
    monkeypatch.setattr(action, "read_manifest", lambda *_args, **_kwargs: source)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("foreign dataset reached a mutation adapter")

    for name in (
        "_validated_migrator_url",
        "_create_engine",
        "restore_postgres_archive",
        "materialize_restored_originals",
        "finalize_restored_dataset",
    ):
        monkeypatch.setattr(action, name, forbidden)
    request = action.CompleteRestoreRequest(
        backup_generation=tmp_path,
        target_upload_root=tmp_path / "uploads",
        database_url=MIGRATOR_URL,
        passfile=tmp_path / "pgpass",
        pg_restore_binary=tmp_path / "pg_restore.exe",
        active_installation_id=INSTALLATION_ID,
        active_dataset_id="44444444-4444-4444-8444-444444444444",
        active_restore_epoch=0,
        target_schema_revision=TARGET_REVISION,
        restore_role="ticketbox_owner",
    )

    with pytest.raises(AppError) as rejected:
        action.run_isolated_dataset_restore_action(request)

    assert rejected.value.error == "backup_incomplete"
    assert rejected.value.status_code == 409


def test_repeated_isolated_restore_discards_public_schema_before_reloading_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.database._dataset_restore_action as action

    statements: list[str] = []
    restored: list[Path] = []

    class Connection:
        def scalar(self, statement) -> int:
            statements.append(str(statement))
            return 0

        def execute(self, statement):
            statements.append(str(statement))
            return None

    class Engine:
        def begin(self):
            return _QuietContext(Connection())

    request = action.CompleteRestoreRequest(
        backup_generation=tmp_path,
        target_upload_root=tmp_path / "uploads",
        database_url=MIGRATOR_URL,
        passfile=tmp_path / "pgpass",
        pg_restore_binary=tmp_path / "pg_restore.exe",
        active_installation_id=INSTALLATION_ID,
        active_dataset_id="33333333-3333-4333-8333-333333333333",
        active_restore_epoch=0,
        target_schema_revision=TARGET_REVISION,
        restore_role="ticketbox_owner",
    )
    monkeypatch.setattr(
        action,
        "restore_postgres_archive",
        lambda **kwargs: restored.append(kwargs["archive"]),
    )
    monkeypatch.setattr(action, "materialize_restored_originals", lambda *_args, **_kwargs: None)

    action._reset_restore_target(Engine(), contexts=[])
    action._materialize_restore_payload(request)

    assert any("nspname !~ '^pg_'" in statement for statement in statements)
    assert not any("LIKE 'pg_%'" in statement for statement in statements)
    assert any("DROP SCHEMA public CASCADE" in statement for statement in statements)
    assert any('CREATE SCHEMA public AUTHORIZATION "ticketbox_owner"' in statement for statement in statements)
    assert restored == [tmp_path / action.DATABASE_ARCHIVE_NAME]

    class ForeignSchemaConnection(Connection):
        def scalar(self, statement) -> int:
            statements.append(str(statement))
            return 1

    class ForeignSchemaEngine:
        def begin(self):
            return _QuietContext(ForeignSchemaConnection())

    from app.errors import AppError

    statements.clear()
    with pytest.raises(AppError) as rejected:
        action._reset_restore_target(ForeignSchemaEngine(), contexts=[])
    assert rejected.value.status_code == 409
    assert not any("DROP SCHEMA" in statement for statement in statements)
