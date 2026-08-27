"""Frozen database-generation entrypoint contracts."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

OPERATION_ID = "11111111-1111-4111-8111-111111111111"
RESTORE_DATABASE = "ticketbox_generation_restore_11111111111141118111111111111111"
MIGRATOR_URL = "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/"
SOURCE_REVISION = "20260729_0001"
TARGET_REVISION = "20260809_0001"
PROGRAM_PATH = "DATABASE_GENERATION_PROGRAM.json"
SHA_A = "a" * 64
_RETIRED_SWITCHES = (
    "--c07-production-migrate",
    "--c07-fresh-source-bootstrap",
    "--c07-maintenance-upgrade",
    "--c07-money-facts-digest",
    "--c07-target-semantic-digest",
)
_LIBPQ_ENVIRONMENT_VARIABLES = (
    "PGHOST",
    "PGSSLNEGOTIATION",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGREQUIREAUTH",
    "PGCHANNELBINDING",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGOPTIONS",
    "PGAPPNAME",
    "PGSSLMODE",
    "PGREQUIRESSL",
    "PGSSLCOMPRESSION",
    "PGSSLCERT",
    "PGSSLKEY",
    "PGSSLCERTMODE",
    "PGSSLROOTCERT",
    "PGSSLCRL",
    "PGSSLCRLDIR",
    "PGSSLSNI",
    "PGREQUIREPEER",
    "PGSSLMINPROTOCOLVERSION",
    "PGSSLMAXPROTOCOLVERSION",
    "PGGSSENCMODE",
    "PGKRBSRVNAME",
    "PGGSSLIB",
    "PGGSSDELEGATION",
    "PGCONNECT_TIMEOUT",
    "PGCLIENTENCODING",
    "PGTARGETSESSIONATTRS",
    "PGLOADBALANCEHOSTS",
    "PGMINPROTOCOLVERSION",
    "PGMAXPROTOCOLVERSION",
    "PGDATESTYLE",
    "PGTZ",
    "PGGEQO",
    "PGSYSCONFDIR",
    "PGLOCALEDIR",
)

_STANDALONE_PROBE = r"""
import importlib.util
import sys
from pathlib import Path

launch_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("ticketbox_generation_probe", launch_path)
assert spec is not None and spec.loader is not None
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
assert not any(name == "app.database" or name.startswith("app.database.") for name in sys.modules)
managed = launch._load_managed_schema_upgrade_module()
target = launch._load_database_generation_target_module()
fresh = launch._load_fresh_schema_upgrade_module()
assert callable(managed.validate_database_generation_program)
assert callable(managed.run_managed_schema_upgrade_action)
assert callable(target.run_database_generation_target_verification_action)
assert callable(fresh.run_fresh_schema_upgrade_action)
assert not any(name == "app.database" or name.startswith("app.database.") for name in sys.modules)
"""


def _load_launch_module():
    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location("ticketbox_generation_launch", launch_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pgpass_path() -> str:
    return "C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + ("1" * 32)


def _program_args() -> list[str]:
    return [
        "--generation-program-path",
        PROGRAM_PATH,
        "--expected-generation-program-sha256",
        SHA_A,
    ]


def _managed_schema_args() -> list[str]:
    return [
        "--managed-schema-upgrade",
        "--database-url",
        MIGRATOR_URL + "ticketbox?require_auth=scram-sha-256",
        "--pgpassfile",
        _pgpass_path(),
        *_program_args(),
        "--source-revision",
        SOURCE_REVISION,
        "--target-revision",
        TARGET_REVISION,
        "--generation-operation-id",
        OPERATION_ID,
    ]


def _target_args() -> list[str]:
    return [
        "--database-generation-verify-target",
        "--database-url",
        MIGRATOR_URL + RESTORE_DATABASE,
        "--pgpassfile",
        _pgpass_path(),
        *_program_args(),
        "--operation-id",
        OPERATION_ID,
        "--database",
        RESTORE_DATABASE,
        "--restore-attempt-id",
        OPERATION_ID,
        "--target-revision",
        TARGET_REVISION,
    ]


def _seal_pg_environment(monkeypatch, argv: list[str]) -> Path:
    for name in list(os.environ):
        if name.upper().startswith("PG"):
            monkeypatch.delenv(name, raising=False)
    pgpassfile = Path(argv[argv.index("--pgpassfile") + 1])
    monkeypatch.setenv("PGPASSFILE", str(pgpassfile))
    return pgpassfile


def test_generation_actions_load_without_runtime_database_facade() -> None:
    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///must-not-be-consumed.db"
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _STANDALONE_PROBE, str(launch_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_retired_c07_modes_fail_before_backend_start(monkeypatch) -> None:
    launch = _load_launch_module()
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        launch.sys,
        "executable",
        "ticketbox-database-maintenance.exe",
    )
    monkeypatch.setattr(
        launch,
        "configure_environment",
        lambda: pytest.fail("retired mode reached backend startup"),
    )
    for switch in _RETIRED_SWITCHES:
        monkeypatch.setattr(
            launch.sys,
            "argv",
            ["ticketbox-database-maintenance.exe", switch],
        )
        with pytest.raises(RuntimeError, match="requires an explicit mode"):
            launch.main()


def test_generation_program_validation_does_not_require_libpq(monkeypatch) -> None:
    launch = _load_launch_module()
    monkeypatch.setattr(launch, "_resolve_generation_program", Path)
    monkeypatch.setattr(
        launch,
        "_load_managed_schema_upgrade_module",
        lambda: type(
            "Managed",
            (),
            {
                "validate_database_generation_program": staticmethod(
                    lambda **_kwargs: dict.fromkeys(
                        launch._GENERATION_PROGRAM_VALIDATION_FIELDS, "bound"
                    )
                )
            },
        )(),
    )
    output = io.StringIO()
    argv = ["--validate-generation-program", *_program_args()]
    assert launch._run_generation_program_validation(
        argv, input_stream=io.BytesIO(b""), output_stream=output
    ) == 0
    assert "generation_program_sha256" in output.getvalue()


def test_generation_program_validation_rejects_nonempty_input(monkeypatch) -> None:
    launch = _load_launch_module()
    monkeypatch.setattr(
        launch,
        "_load_managed_schema_upgrade_module",
        lambda: pytest.fail("validation loaded after nonempty stdin"),
    )
    with pytest.raises(RuntimeError, match="requires empty stdin"):
        launch._run_generation_program_validation(
            ["--validate-generation-program", *_program_args()],
            input_stream=io.BytesIO(b"{}"),
            output_stream=io.StringIO(),
        )


def test_managed_schema_mode_rejects_ambient_libpq(monkeypatch) -> None:
    launch = _load_launch_module()
    argv = _managed_schema_args()
    _seal_pg_environment(monkeypatch, argv)
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.10")
    monkeypatch.setattr(
        launch,
        "_load_managed_schema_upgrade_module",
        lambda: pytest.fail("managed action loaded before libpq guard"),
    )
    with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
        launch._run_managed_schema_upgrade(
            argv, input_stream=io.BytesIO(b""), output_stream=io.StringIO()
        )


def test_target_verification_mode_rejects_ambient_libpq(monkeypatch) -> None:
    launch = _load_launch_module()
    argv = _target_args()
    _seal_pg_environment(monkeypatch, argv)
    monkeypatch.setenv("PGOPTIONS", "-c search_path=attacker")
    monkeypatch.setattr(
        launch,
        "_load_database_generation_target_module",
        lambda: pytest.fail("target action loaded before libpq guard"),
    )
    with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
        launch._run_database_generation_target_verification(
            argv, input_stream=io.BytesIO(b""), output_stream=io.StringIO()
        )


def test_libpq_environment_allows_only_exact_passfile(monkeypatch) -> None:
    launch = _load_launch_module()
    argv = _managed_schema_args()
    pgpassfile = _seal_pg_environment(monkeypatch, argv)
    launch._assert_maintenance_libpq_environment(pgpassfile)
    for name in _LIBPQ_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "ambient-libpq-authority")
        with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
            launch._assert_maintenance_libpq_environment(pgpassfile)
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGPASSFILE", str(pgpassfile) + ".other")
    with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
        launch._assert_maintenance_libpq_environment(pgpassfile)


def test_prearmed_transaction_preserves_primary_and_timeout_cleanup(monkeypatch) -> None:
    from app.database import _managed_postgres_migration_runtime as runtime

    class FailingTransaction:
        def __init__(self, connection) -> None:
            self.connection = connection

        def __enter__(self):
            return self.connection

        def __exit__(self, exc_type, exc, _traceback):
            assert exc_type is RuntimeError
            assert str(exc) == "transaction primary failed"
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
        pytest.raises(runtime.PostgresOperationFailureError) as caught,
        runtime._prearmed_transaction(
            connection,
            timeout_ms=1000,
            access_mode="read_write",
        ),
    ):
        raise RuntimeError("transaction primary failed")
    assert str(caught.value.primary) == "transaction primary failed"
    assert caught.value.cleanup[0].args == ("transaction rollback failed",)
    assert str(caught.value.cleanup[1]) == "timeout cleanup failed"
    assert str(caught.value.cleanup[2]) == "transaction invalidate failed"
    assert connection.invalidated is True


def test_timeout_configuration_preserves_sql_and_autocommit_cleanup() -> None:
    from app.database import _managed_postgres_migration_runtime as runtime

    class FailingCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args) -> None:
            raise TypeError("timeout SQL failed")

    class FailingDriverConnection:
        def __init__(self) -> None:
            self._autocommit = False

        @property
        def autocommit(self) -> bool:
            return self._autocommit

        @autocommit.setter
        def autocommit(self, value: bool) -> None:
            if self._autocommit and not value:
                raise KeyError("autocommit cleanup failed")
            self._autocommit = value

        def cursor(self) -> FailingCursor:
            return FailingCursor()

    class FailingConnection:
        def __init__(self) -> None:
            self.connection = type(
                "DriverProxy",
                (),
                {"driver_connection": FailingDriverConnection()},
            )()

        def in_transaction(self) -> bool:
            return False

    for action in (
        lambda connection: runtime._set_idle_session_timeout(connection, 1000),
        lambda connection: runtime._restore_idle_session_timeout(connection, 0),
    ):
        with pytest.raises(runtime.PostgresOperationFailureError) as caught:
            action(FailingConnection())
        assert isinstance(caught.value.primary, TypeError)
        assert str(caught.value.primary) == "timeout SQL failed"
        assert len(caught.value.cleanup) == 1
        assert isinstance(caught.value.cleanup[0], KeyError)
        assert caught.value.cleanup[0].args == ("autocommit cleanup failed",)


def test_managed_migration_preserves_primary_and_engine_cleanup(tmp_path: Path, monkeypatch) -> None:
    from app.database import _managed_postgres_migration_runtime as runtime
    from app.database._database_generation_program import DatabaseGenerationProgram

    @contextmanager
    def protected(path: Path):
        yield path

    class FailingConnection:
        def __enter__(self):
            raise KeyError("migration primary failed")

        def __exit__(self, *_args):
            return False

    class FailingEngine:
        def connect(self):
            return FailingConnection()

        def dispose(self) -> None:
            raise RuntimeError("migration dispose failed")

    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setattr(runtime, "hold_protected_file_for_read", protected)
    monkeypatch.setattr(runtime, "_create_engine", lambda _url: FailingEngine())
    contract = runtime.ManagedPostgresRuntimeContractV1(
        database_name="ticketbox",
        migrator_role="ticketbox_migrator",
        schema_owner_role="ticketbox_owner",
        lease_label="ticketbox database generation",
        transaction_timeout_ms=1000,
    )
    program = DatabaseGenerationProgram(
        path=(tmp_path / PROGRAM_PATH).resolve(),
        payload_sha256=SHA_A,
        source_revision="base",
        target_revision=TARGET_REVISION,
        revisions=(),
    )
    with pytest.raises(runtime.PostgresOperationFailureError) as caught:
        runtime.ManagedPostgresMigrationRuntimeV1(contract).run(
            database_url=MIGRATOR_URL + "ticketbox?require_auth=scram-sha-256",
            pgpassfile=(tmp_path / ".pgpass").resolve(),
            program=program,
            source_revision=SOURCE_REVISION,
            target_revision=TARGET_REVISION,
            generation_operation_id=OPERATION_ID,
        )
    assert isinstance(caught.value.primary, runtime.ManagedPostgresMigrationRuntimeError)
    assert isinstance(caught.value.primary.__cause__, KeyError)
    assert caught.value.primary.__cause__.args == ("migration primary failed",)
    assert [str(error) for error in caught.value.cleanup] == ["migration dispose failed"]


def test_target_verification_preserves_primary_and_engine_cleanup(tmp_path: Path, monkeypatch) -> None:
    from sqlalchemy.engine import make_url

    from app.database import _database_generation_target_verification as target
    from app.database import _managed_postgres_migration_runtime as runtime

    @contextmanager
    def protected(path: Path):
        yield path

    class FailingConnection:
        def __enter__(self):
            raise KeyError("target primary failed")

        def __exit__(self, *_args):
            return False

    class FailingEngine:
        def connect(self):
            return FailingConnection()

        def dispose(self) -> None:
            raise RuntimeError("target dispose failed")

    monkeypatch.setattr(target, "hold_protected_file_for_read", protected)
    monkeypatch.setattr(target, "_temporary_pgpass_environment", protected)
    monkeypatch.setattr(target, "_create_engine", lambda _url: FailingEngine())
    contract = runtime.ManagedPostgresRuntimeContractV1(
        database_name="ticketbox",
        migrator_role="ticketbox_migrator",
        schema_owner_role="ticketbox_owner",
        lease_label="ticketbox database generation",
        transaction_timeout_ms=1000,
    )
    with pytest.raises(runtime.PostgresOperationFailureError) as caught:
        target._read_target_facts(
            parsed_url=make_url(MIGRATOR_URL + "ticketbox?require_auth=scram-sha-256"),
            pgpassfile=(tmp_path / ".pgpass").resolve(),
            contract=contract,
            target_revision=TARGET_REVISION,
        )
    assert isinstance(caught.value.primary, target.DatabaseGenerationTargetVerificationError)
    assert isinstance(caught.value.primary.__cause__, KeyError)
    assert caught.value.primary.__cause__.args == ("target primary failed",)
    assert [str(error) for error in caught.value.cleanup] == ["target dispose failed"]
