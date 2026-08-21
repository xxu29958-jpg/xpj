from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database._postgres_operation_failures import PostgresOperationFailureError

OPERATION_ID = "11111111-1111-4111-8111-111111111111"
PROGRAM_SHA256 = "a" * 64
SOURCE_REVISION = "base"
TARGET_REVISION = "20260729_0001"
MIGRATOR_URL = (
    "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/"
    "ticketbox?require_auth=scram-sha-256"
)


def _aggregate() -> PostgresOperationFailureError:
    return PostgresOperationFailureError(
        "database operation and cleanup failed",
        primary=KeyError("database primary failed"),
        cleanup=(RuntimeError("database cleanup failed"),),
    )


def _program() -> SimpleNamespace:
    return SimpleNamespace(
        payload_sha256=PROGRAM_SHA256,
        target_revision=TARGET_REVISION,
    )


def _assert_exact_failure_graph(error: BaseException, aggregate: PostgresOperationFailureError) -> None:
    assert error.__cause__ is aggregate
    assert aggregate.primary is not None
    assert aggregate.primary.args == ("database primary failed",)
    assert [str(cleanup) for cleanup in aggregate.cleanup] == ["database cleanup failed"]


def test_managed_schema_public_action_preserves_operation_failure_graph(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.database import _managed_schema_upgrade as managed

    aggregate = _aggregate()

    class FailingRuntime:
        def __init__(self, _contract) -> None:
            pass

        def run(self, **_kwargs) -> str:
            raise aggregate

    monkeypatch.setattr(managed, "load_database_generation_program", lambda **_kwargs: _program())
    monkeypatch.setattr(managed, "ManagedPostgresMigrationRuntimeV1", FailingRuntime)
    with pytest.raises(managed.ManagedSchemaUpgradeError) as caught:
        managed.run_managed_schema_upgrade_action(
            database_url=MIGRATOR_URL,
            pgpassfile=(tmp_path / ".pgpass").resolve(),
            generation_program_path=(tmp_path / "generation.json").resolve(),
            expected_generation_program_sha256=PROGRAM_SHA256,
            source_revision=SOURCE_REVISION,
            target_revision=TARGET_REVISION,
            generation_operation_id=OPERATION_ID,
        )
    _assert_exact_failure_graph(caught.value, aggregate)


def test_target_verification_public_action_preserves_operation_failure_graph(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.database import _database_generation_target_verification as target

    aggregate = _aggregate()
    monkeypatch.setattr(target, "load_database_generation_program", lambda **_kwargs: _program())

    def fail_target_read(**_kwargs):
        raise aggregate

    monkeypatch.setattr(target, "_read_target_facts", fail_target_read)
    with pytest.raises(target.DatabaseGenerationTargetVerificationError) as caught:
        target.run_database_generation_target_verification_action(
            database_url=MIGRATOR_URL,
            pgpassfile=(tmp_path / ".pgpass").resolve(),
            generation_program_path=(tmp_path / "generation.json").resolve(),
            expected_generation_program_sha256=PROGRAM_SHA256,
            operation_id=OPERATION_ID,
            database="ticketbox",
            restore_attempt_id="",
            target_revision=TARGET_REVISION,
        )
    _assert_exact_failure_graph(caught.value, aggregate)


def test_prearmed_transaction_rolls_back_baseexception_before_cleanup(monkeypatch) -> None:
    from app.database import _managed_postgres_migration_runtime as runtime

    observed_exit: list[tuple[type[BaseException] | None, BaseException | None]] = []
    interrupted = KeyboardInterrupt("transaction interrupted")

    class FailingTransaction:
        def __init__(self, connection) -> None:
            self.connection = connection

        def __enter__(self):
            return self.connection

        def __exit__(self, exc_type, exc, _traceback):
            observed_exit.append((exc_type, exc))
            if exc_type is not KeyboardInterrupt or exc is not interrupted:
                raise AssertionError("transaction interruption was exposed as commit")
            raise KeyError("transaction rollback failed")

    class FakeConnection:
        invalidated = False
        closed = False

        def begin(self):
            return FailingTransaction(self)

        def execute(self, _statement):
            return None

        def invalidate(self) -> None:
            self.invalidated = True
            raise AssertionError("transaction invalidate failed")

    connection = FakeConnection()
    monkeypatch.setattr(runtime, "_set_idle_session_timeout", lambda *_args, **_kwargs: 0)

    def fail_restore(*_args, **_kwargs) -> None:
        raise TypeError("timeout cleanup failed")

    monkeypatch.setattr(runtime, "_restore_idle_session_timeout", fail_restore)
    with (
        pytest.raises(BaseExceptionGroup) as caught,
        runtime._prearmed_transaction(
            connection,
            timeout_ms=1000,
            access_mode="read_write",
        ),
    ):
        raise interrupted
    assert observed_exit == [(KeyboardInterrupt, interrupted)]
    assert caught.value.exceptions[0] is interrupted
    assert caught.value.exceptions[1].args == ("transaction rollback failed",)
    assert str(caught.value.exceptions[2]) == "timeout cleanup failed"
    assert str(caught.value.exceptions[3]) == "transaction invalidate failed"
    assert connection.invalidated is True


def test_migration_owner_preserves_interrupt_and_engine_cleanup(tmp_path: Path, monkeypatch) -> None:
    from app.database import _managed_postgres_migration_runtime as runtime

    interrupted = KeyboardInterrupt("migration interrupted")
    connection_cleanup = KeyboardInterrupt("migration connection cleanup failed")
    environment_cleanup = ValueError("migration environment cleanup failed")
    protected_file_cleanup = OSError("migration protected-file cleanup failed")
    engine_cleanup = SystemExit("migration engine cleanup failed")

    @contextmanager
    def protected_file(path):
        try:
            yield path
        finally:
            raise protected_file_cleanup

    @contextmanager
    def environment(_path):
        try:
            yield
        finally:
            raise environment_cleanup

    @contextmanager
    def connection_context():
        try:
            yield object()
        finally:
            raise connection_cleanup

    @contextmanager
    def transaction_context(connection, **_kwargs):
        yield connection

    class FailingEngine:
        def connect(self):
            return connection_context()

        def dispose(self) -> None:
            raise engine_cleanup

    contract = runtime.ManagedPostgresRuntimeContractV1(
        database_name="ticketbox",
        migrator_role="ticketbox_migrator",
        schema_owner_role="ticketbox_owner",
        lease_label="ticketbox-migration",
        transaction_timeout_ms=1000,
    )
    owner = runtime.ManagedPostgresMigrationRuntimeV1(contract)
    monkeypatch.setattr(runtime, "hold_protected_file_for_read", protected_file)
    monkeypatch.setattr(runtime, "_temporary_pgpass_environment", environment)
    monkeypatch.setattr(runtime, "_create_engine", lambda _url: FailingEngine())
    monkeypatch.setattr(runtime, "_prearmed_transaction", transaction_context)

    def interrupt_transaction(*_args, **_kwargs):
        raise interrupted

    monkeypatch.setattr(owner, "_run_transaction", interrupt_transaction)
    with pytest.raises(BaseExceptionGroup) as caught:
        owner.run(
            database_url=MIGRATOR_URL,
            pgpassfile=(tmp_path / ".pgpass").resolve(),
            program=_program(),
            source_revision=SOURCE_REVISION,
            target_revision=TARGET_REVISION,
            generation_operation_id=OPERATION_ID,
        )
    assert caught.value.__cause__ is interrupted
    assert caught.value.exceptions == (
        interrupted,
        connection_cleanup,
        environment_cleanup,
        protected_file_cleanup,
        engine_cleanup,
    )


def test_target_owner_preserves_interrupt_and_engine_cleanup(tmp_path: Path, monkeypatch) -> None:
    from app.database import _database_generation_target_verification as target

    interrupted = KeyboardInterrupt("target read interrupted")
    connection_cleanup = SystemExit("target connection cleanup failed")
    environment_cleanup = LookupError("target environment cleanup failed")
    protected_file_cleanup = OSError("target protected-file cleanup failed")
    engine_cleanup = RuntimeError("target engine cleanup failed")

    @contextmanager
    def protected_file(path):
        try:
            yield path
        finally:
            raise protected_file_cleanup

    @contextmanager
    def environment(_path):
        try:
            yield
        finally:
            raise environment_cleanup

    @contextmanager
    def connection_context():
        try:
            yield object()
        finally:
            raise connection_cleanup

    @contextmanager
    def transaction_context(connection, **_kwargs):
        yield connection

    class FailingEngine:
        def connect(self):
            return connection_context()

        def dispose(self) -> None:
            raise engine_cleanup

    contract = target.ManagedPostgresRuntimeContractV1(
        database_name="ticketbox",
        migrator_role="ticketbox_migrator",
        schema_owner_role="ticketbox_owner",
        lease_label="ticketbox-migration",
        transaction_timeout_ms=1000,
    )
    monkeypatch.setattr(target, "hold_protected_file_for_read", protected_file)
    monkeypatch.setattr(target, "_temporary_pgpass_environment", environment)
    monkeypatch.setattr(target, "_create_engine", lambda _url: FailingEngine())
    monkeypatch.setattr(target, "_prearmed_transaction", transaction_context)

    def interrupt_owner(*_args, **_kwargs):
        raise interrupted

    monkeypatch.setattr(target, "assume_managed_postgres_schema_owner", interrupt_owner)
    with pytest.raises(BaseExceptionGroup) as caught:
        target._read_target_facts(
            parsed_url=SimpleNamespace(),
            pgpassfile=(tmp_path / ".pgpass").resolve(),
            contract=contract,
            target_revision=TARGET_REVISION,
        )
    assert caught.value.__cause__ is interrupted
    assert caught.value.exceptions == (
        interrupted,
        connection_cleanup,
        environment_cleanup,
        protected_file_cleanup,
        engine_cleanup,
    )


@pytest.mark.parametrize("boundary", ["setup", "restore"])
@pytest.mark.parametrize("cleanup_is_interrupt", [False, True])
def test_timeout_boundaries_preserve_interrupt_and_autocommit_cleanup(
    boundary: str,
    cleanup_is_interrupt: bool,
    monkeypatch,
) -> None:
    from app.database import _managed_postgres_migration_runtime as runtime

    if cleanup_is_interrupt:
        primary = RuntimeError(f"timeout {boundary} failed")
        cleanup_failure = KeyboardInterrupt("autocommit cleanup interrupted")
    else:
        primary = KeyboardInterrupt(f"timeout {boundary} interrupted")
        cleanup_failure = RuntimeError("autocommit cleanup failed")

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args) -> None:
            pass

    class FailingDriverConnection:
        def __init__(self) -> None:
            self._autocommit = False

        @property
        def autocommit(self) -> bool:
            return self._autocommit

        @autocommit.setter
        def autocommit(self, value: bool) -> None:
            if self._autocommit and not value:
                raise cleanup_failure
            self._autocommit = value

        def cursor(self):
            return Cursor()

    driver = FailingDriverConnection()
    connection = SimpleNamespace(
        connection=SimpleNamespace(driver_connection=driver),
        in_transaction=lambda: False,
    )
    def interrupt_timeout(_cursor):
        raise primary

    monkeypatch.setattr(runtime, "_timeout_setting", interrupt_timeout)
    with pytest.raises(BaseExceptionGroup) as caught:
        if boundary == "setup":
            runtime._set_idle_session_timeout(connection, 1000)
        else:
            runtime._restore_idle_session_timeout(connection, 0)
    assert caught.value.__cause__ is primary
    assert caught.value.exceptions == (primary, cleanup_failure)


def test_failure_ledger_preserves_baseexception_from_cleanup() -> None:
    from app.database._postgres_operation_failures import (
        raise_postgres_operation_failures,
    )

    primary = RuntimeError("ordinary primary")
    interrupted_cleanup = KeyboardInterrupt("cleanup interrupted")
    with pytest.raises(BaseExceptionGroup) as caught:
        raise_postgres_operation_failures(
            primary=primary,
            cleanup=[interrupted_cleanup],
            message="operation and cleanup failed",
        )
    assert caught.value.__cause__ is primary
    assert caught.value.exceptions == (primary, interrupted_cleanup)
