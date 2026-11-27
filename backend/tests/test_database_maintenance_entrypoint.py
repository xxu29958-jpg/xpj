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
    "--managed-schema-upgrade",
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
validation = launch._load_generation_program_validation_module()
target = launch._load_database_generation_target_module()
fresh = launch._load_fresh_schema_upgrade_module()
upgrade = launch._load_existing_dataset_upgrade_module()
assert callable(validation.validate_database_generation_program)
assert callable(target.run_database_generation_target_verification_action)
assert callable(fresh.run_fresh_schema_upgrade_action)
assert callable(upgrade.run_existing_dataset_upgrade_action)
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
        "_load_generation_program_validation_module",
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
        "_load_generation_program_validation_module",
        lambda: pytest.fail("validation loaded after nonempty stdin"),
    )
    with pytest.raises(RuntimeError, match="requires empty stdin"):
        launch._run_generation_program_validation(
            ["--validate-generation-program", *_program_args()],
            input_stream=io.BytesIO(b"{}"),
            output_stream=io.StringIO(),
        )


def test_managed_schema_mode_is_retired_before_libpq_or_action(monkeypatch) -> None:
    launch = _load_launch_module()
    argv = _managed_schema_args()
    _seal_pg_environment(monkeypatch, argv)
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.10")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        launch.sys,
        "executable",
        "ticketbox-database-maintenance.exe",
    )
    monkeypatch.setattr(
        launch,
        "_assert_maintenance_libpq_environment",
        lambda *_args: pytest.fail("retired managed action reached libpq guard"),
    )
    monkeypatch.setattr(launch.sys, "argv", ["ticketbox-database-maintenance.exe", *argv])
    with pytest.raises(RuntimeError, match="requires an explicit mode"):
        launch.main()


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
    argv = _target_args()
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


_ISOLATION_GUARD_PREAMBLE = r"""
import os
import sys
from pathlib import Path

mode = sys.argv[2]

FORBIDDEN_MODULES = {
    "app.config",
    "dotenv",
    "app.database._core",
    "app.services.file_service",
    "app.services.runtime_settings_store",
    "app.services.attachment_cleanup_service",
    "app.services.currency_binding_service",
}
FORBIDDEN_EVENTS: list[str] = []


class _ForbiddenImportBlocker:
    def find_spec(self, fullname, path, target=None):
        if fullname in FORBIDDEN_MODULES:
            msg = f"mode {mode} attempted forbidden import: {fullname}"
            FORBIDDEN_EVENTS.append(msg)
            raise AssertionError(msg)
        if fullname == "app.database":
            msg = f"mode {mode} attempted to import real app.database.__init__"
            FORBIDDEN_EVENTS.append(msg)
            raise AssertionError(msg)
        return None


def _forbidden_open_audit(event, args):
    if event != "open" or not args:
        return
    target = args[0]
    if isinstance(target, (str, bytes, os.PathLike)):
        name = Path(os.fsdecode(target)).name.casefold()
        if name in {".env", "runtime-settings.json"}:
            msg = f"mode {mode} attempted forbidden file open: {target!r}"
            FORBIDDEN_EVENTS.append(msg)
            raise AssertionError(msg)


sys.meta_path.insert(0, _ForbiddenImportBlocker())
sys.addaudithook(_forbidden_open_audit)


def assert_isolated() -> None:
    assert not FORBIDDEN_EVENTS, f"maintenance mode {mode} recorded forbidden events: {FORBIDDEN_EVENTS}"
    loaded = [name for name in FORBIDDEN_MODULES if name in sys.modules]
    assert not loaded, f"maintenance mode {mode} loaded forbidden runtime modules: {loaded}"
    assert "app.database" not in sys.modules, f"maintenance mode {mode} left app.database loaded"
    assert "SENTINEL_DOTENV_LOADED" not in os.environ, "maintenance mode loaded ambient .env"
"""


_MAINTENANCE_ISOLATION_PROBE = _ISOLATION_GUARD_PREAMBLE + r"""
import contextlib
import hashlib
import importlib.util
import io
import json
import zipfile
from uuid import uuid4

backend_root = Path(sys.argv[1])
launch_path = backend_root / "packaging" / "launch.py"
explicit_data_root = Path(sys.argv[3])
pgpass_path = Path(sys.argv[4])
backup_path = Path(sys.argv[5])
program_file = Path(sys.argv[6])
sys.path.insert(0, str(backend_root))

spec = importlib.util.spec_from_file_location("ticketbox_isolation_launch", launch_path)
assert spec is not None and spec.loader is not None
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
assert_isolated()

@contextlib.contextmanager
def _noop_secret(_path):
    yield _path

import sqlalchemy
from sqlalchemy import create_engine as _real_create_engine, event
from sqlalchemy.orm import Session
from app.services import secure_file

secure_file.hold_installer_machine_secret_for_read = _noop_secret
secure_file.hold_protected_file_for_read = _noop_secret

def _make_seeded_sqlite_engine(*, with_owner_and_original: bool, upload_root: Path):
    from sqlalchemy import CheckConstraint, JSON
    from sqlalchemy.dialects.postgresql import JSONB
    from app.database_model_registry import Base
    import app.models as m
    from app.services.identity_service import bootstrap_installation_owner

    db_file = explicit_data_root.parent / "probe.sqlite3"
    eng = _real_create_engine(f"sqlite:///{db_file.as_posix()}", future=True)

    @event.listens_for(eng, "connect")
    def _register_pg_shims(dbapi_connection, _connection_record):
        dbapi_connection.create_function("pg_advisory_xact_lock", -1, lambda *_args: None)

    @event.listens_for(eng, "before_cursor_execute", retval=True)
    def _rewrite_pg_session_sql(conn, cursor, statement, parameters, context, executemany):
        upper = statement.strip().upper()
        if upper.startswith(("SET ROLE", "RESET ROLE", "SET TRANSACTION READ ONLY", "SET LOCAL ")):
            return "SELECT 1", ()
        return statement, parameters

    for table in Base.metadata.tables.values():
        table.constraints = {c for c in table.constraints if not isinstance(c, CheckConstraint)}
        table.indexes = {idx for idx in table.indexes if "postgresql_where" not in idx.dialect_options.get("postgresql", {})}
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
    Base.metadata.create_all(eng)
    source_install = "11111111-1111-4111-8111-111111111111"
    dataset_id = "22222222-2222-4222-8222-222222222222"
    old_secret = "a" * 64
    if with_owner_and_original:
        with Session(eng, expire_on_commit=False) as db:
            claim = bootstrap_installation_owner(
                db,
                operation_id="fresh-op-1",
                installation_id=source_install,
                bootstrap_secret=old_secret,
                account_name="Owner",
                ledger_name="Mine",
                device_name="Win",
                commit=False,
            )
            db.add(
                m.DatasetAuthorityRecord(
                    singleton_id=1,
                    dataset_id=dataset_id,
                    client_generation=source_install,
                    restore_epoch=0,
                    schema_revision="20261101_0001",
                    schema_min_compatible="1.3.0",
                    semantic_revision="ticketbox-dataset-semantics-v1",
                )
            )
            img_bytes = b"\x89PNG\r\n\x1a\nexplicit-maintenance-original"
            img_sha = hashlib.sha256(img_bytes).hexdigest()
            img_path = upload_root / claim.ledger_id / "receipt.png"
            img_path.parent.mkdir(parents=True, exist_ok=True)
            img_path.write_bytes(img_bytes)
            db.add(
                m.Expense(
                    tenant_id=claim.ledger_id,
                    amount_cents=1200,
                    original_amount_minor=1200,
                    category="food",
                    image_path=f"uploads/{claim.ledger_id}/receipt.png",
                    image_hash=img_sha,
                )
            )
            db.commit()
    return eng, source_install, dataset_id, old_secret

DB_URL = "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256"

if mode == "--validate-generation-program":
    program_digest = hashlib.sha256(program_file.read_bytes()).hexdigest()
    launch._resolve_generation_program = lambda _p: program_file
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    rc = launch._dispatch_maintenance_mode(
        [
            "--validate-generation-program",
            "--generation-program-path",
            "DATABASE_GENERATION_PROGRAM.json",
            "--expected-generation-program-sha256",
            program_digest,
        ]
    )
    assert rc == 0
elif mode == "--fresh-schema-upgrade":
    sqlite_engine, source_install, dataset_id, _secret = _make_seeded_sqlite_engine(
        with_owner_and_original=False,
        upload_root=explicit_data_root / "app" / "uploads",
    )
    target_rev = json.loads(program_file.read_text(encoding="utf-8"))["target_revision"]
    mod = launch._load_fresh_schema_upgrade_module()
    alembic_upgraded: list[str] = []
    mod.create_engine = lambda *_a, **_kw: sqlite_engine
    mod._prearmed_transaction = lambda conn, **_kw: conn.begin()
    mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
    mod.seal_runtime_authority_tables = lambda *_a, **_kw: True
    mod.seal_upgrade_attestation_guard = lambda *_a, **_kw: True
    mod._current_revision = lambda _conn: target_rev if alembic_upgraded else None

    def _fake_alembic_upgrade(cfg, rev):
        assert cfg.attributes.get("connection") is not None
        alembic_upgraded.append(rev)

    mod.command.upgrade = _fake_alembic_upgrade
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--fresh-schema-upgrade",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--target-revision",
                target_rev,
                "--dataset-id",
                dataset_id,
                "--client-generation",
                source_install,
                "--schema-min-compatible",
                "1.3.0",
                "--semantic-revision",
                "ticketbox-dataset-semantics-v1",
                "--operation-id",
                "fresh-op-1",
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-fresh-schema-upgrade-result-v1"
    assert payload["result"] == "upgraded"
    assert alembic_upgraded == [target_rev]
    with sqlite_engine.connect() as conn:
        bound_row = conn.execute(
            sqlalchemy.text("SELECT dataset_id, client_generation, schema_revision FROM dataset_authority WHERE singleton_id = 1")
        ).mappings().one()
        assert bound_row["dataset_id"] == dataset_id
        assert bound_row["client_generation"] == source_install
        assert bound_row["schema_revision"] == target_rev
elif mode == "--database-generation-verify-target":
    sqlite_engine, _src, _ds, _secret = _make_seeded_sqlite_engine(
        with_owner_and_original=False,
        upload_root=explicit_data_root / "app" / "uploads",
    )
    program_digest = hashlib.sha256(program_file.read_bytes()).hexdigest()
    target_rev = json.loads(program_file.read_text(encoding="utf-8"))["target_revision"]
    launch._resolve_generation_program = lambda _p: program_file
    mod = launch._load_database_generation_target_module()
    mod._create_engine = lambda *_a, **_kw: sqlite_engine
    mod._prearmed_transaction = lambda conn, **_kw: conn.begin()
    mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
    mod.assert_release_head = lambda _conn, expected_revision: expected_revision
    mod.read_money_schema_shape = lambda _conn: {"shape_sha256": "b" * 64}
    mod.canonical_money_facts_sha256 = lambda _conn, **_kw: "c" * 64
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--database-generation-verify-target",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--generation-program-path",
                "DATABASE_GENERATION_PROGRAM.json",
                "--expected-generation-program-sha256",
                program_digest,
                "--operation-id",
                "11111111-1111-4111-8111-111111111111",
                "--database",
                "ticketbox",
                "--target-revision",
                target_rev,
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-database-generation-target-verification-v2"
    assert payload["alembic_revision"] == target_rev
    assert payload["resource_shape_sha256"] == "b" * 64
    assert payload["money_facts_sha256"] == "c" * 64
elif mode == "--upgrade-existing-dataset":
    import sqlite3

    source_install = "11111111-1111-4111-8111-111111111111"
    dataset_id = "22222222-2222-4222-8222-222222222222"
    upgrade_op_id = "55555555-5555-4555-8555-555555555555"
    source_rev = "20261029_0002"
    target_rev = json.loads(program_file.read_text(encoding="utf-8"))["target_revision"]

    upload_root = explicit_data_root / "app" / "uploads"
    owner_dir = upload_root / "owner"
    owner_dir.mkdir(parents=True, exist_ok=True)
    app_dir = explicit_data_root.parent / "app_program"
    pg_bin = app_dir / "postgresql" / "bin" / "postgres.exe"
    pg_bin.parent.mkdir(parents=True, exist_ok=True)
    pg_bin_bytes = b"pg-bin-payload"
    pg_bin.write_bytes(pg_bin_bytes)

    files_to_write = {
        "demo.png": b"\x89PNG\r\n\x1a\nexplicit-upgrade-img",
        "thumb.jpg": b"\xff\xd8\xffthumb-bytes",
        "pending.png": b"\x89PNG\r\n\x1a\npending-cleanup-img",
        "debt.png": b"\x89PNG\r\n\x1a\ndebt-bill-img",
        "debt_pending.png": b"\x89PNG\r\n\x1a\ndebt-pending-img",
    }
    shas: dict[str, str] = {}
    for fname, raw in files_to_write.items():
        (owner_dir / fname).write_bytes(raw)
        shas[fname] = hashlib.sha256(raw).hexdigest()

    rel_manifest_bytes = json.dumps({
        "release_id": "1.2.1",
        "max_schema_revision": source_rev,
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "immutable_payload": {
            "files": [
                {
                    "path": "postgresql/bin/postgres.exe",
                    "size": len(pg_bin_bytes),
                    "sha256": hashlib.sha256(pg_bin_bytes).hexdigest(),
                }
            ]
        },
    }).encode("utf-8")
    rel_manifest_sha = hashlib.sha256(rel_manifest_bytes).hexdigest()

    archive_files: dict[str, bytes] = {
        "data/pgdata/PG_VERSION": b"16\n",
        "data/pgdata/global/pg_control": b"pg-control-bytes",
        "data/app/.env": b"DATABASE_URL=postgresql://stub\n",
        "machine/installation.json": json.dumps({
            "schema": "ticketbox-installed-instance-v1",
            "install_id": source_install,
            "dataset_id": dataset_id,
            "expected_restore_epoch": 0,
            "active_release_id": "1.2.1",
            "release_manifest_sha256": rel_manifest_sha,
        }).encode("utf-8"),
        "machine/secrets/postgres.password": b"pw1\n",
        "machine/secrets/ticketbox_migrator.password": b"pw2\n",
        "machine/secrets/ticketbox_runtime.password": b"pw3\n",
        "machine/secrets/pgpass": b"127.0.0.1:5432:ticketbox:ticketbox_migrator:pw2\n",
        "machine/operations/history/op-install.json": json.dumps({
            "schema": "ticketbox-lifecycle-operation-v2",
            "phase": "committed",
            "kind": "install",
            "operation_id": "66666666-6666-4666-8666-666666666666",
            "install_id": source_install,
            "dataset_id": dataset_id,
            "release_manifest_sha256": rel_manifest_sha,
        }).encode("utf-8"),
        "program/releases/1.2.1/release-manifest.json": rel_manifest_bytes,
        "program/postgresql/bin/postgres.exe": pg_bin_bytes,
    }
    for fname, raw in files_to_write.items():
        archive_files[f"data/app/uploads/owner/{fname}"] = raw

    entries: dict[str, object] = {
        "program/": None,
        "machine/": None,
        "data/pgdata/": None,
        "data/attachments/": None,
        "data/app/": None,
    }
    for rel, raw in archive_files.items():
        entries[rel] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    cold_copy_manifest = {
        "schema": "ticketbox-beta-cold-copy-v2",
        "complete": True,
        "public_connectivity": {
            "excluded_directory": "machine/connectors/cloudflare/secrets",
            "credentials": "not_backed_up",
            "after_restore": "configure_again",
        },
        "identity": {
            "install_id": source_install,
            "dataset_id": dataset_id,
            "restore_epoch": 0,
            "schema_revision": source_rev,
            "release_id": "1.2.1",
            "release_manifest_sha256": rel_manifest_sha,
            "postgres_major": 16,
        },
        "entries": entries,
    }
    with zipfile.ZipFile(backup_path, "w") as zf:
        zf.writestr("COLD_COPY.json", json.dumps(cold_copy_manifest).encode("utf-8"))
        for dir_name in ("program/", "machine/", "data/pgdata/", "data/attachments/", "data/app/"):
            zf.writestr(dir_name, b"")
        for rel, raw in archive_files.items():
            zf.writestr(rel, raw)
    backup_sha = hashlib.sha256(backup_path.read_bytes()).hexdigest()

    # SQLite DB with attached `public` schema and JSONB converter matching psycopg dict return!
    sqlite3.register_converter("JSONB", lambda raw: json.loads(raw.decode("utf-8")))
    main_db = explicit_data_root.parent / "upgrade_main.sqlite3"
    public_db = explicit_data_root.parent / "upgrade_public.sqlite3"
    upgrade_engine = _real_create_engine(
        f"sqlite:///{main_db.as_posix()}",
        connect_args={"detect_types": sqlite3.PARSE_DECLTYPES},
        future=True,
    )

    @event.listens_for(upgrade_engine, "connect")
    def _attach_public(dbapi_connection, _connection_record):
        dbapi_connection.execute(f"ATTACH DATABASE '{public_db.as_posix()}' AS public")

    expense_cleanup_json = json.dumps({
        "request_id": str(uuid4()),
        "reason": "after_confirm",
        "requested_at": "2026-11-26T00:00:00Z",
        "image": {
            "reference": "uploads/owner/pending.png",
            "outcome": "pending",
            "completed_at": None,
            "error_code": None,
        },
        "thumbnail": None,
    })
    debt_cleanup_json = json.dumps({
        "request_id": str(uuid4()),
        "reason": "after_confirm",
        "requested_at": "2026-11-26T00:00:00Z",
        "image": {
            "reference": "uploads/owner/debt_pending.png",
            "outcome": "pending",
            "completed_at": None,
            "error_code": None,
        },
        "thumbnail": None,
    })
    with upgrade_engine.begin() as conn:
        conn.execute(sqlalchemy.text(
            "CREATE TABLE public.expenses ("
            "tenant_id TEXT, image_path TEXT, image_hash TEXT, image_deleted_at TEXT, "
            "thumbnail_path TEXT, thumbnail_deleted_at TEXT, attachment_cleanup_request JSONB)"
        ))
        conn.execute(sqlalchemy.text(
            "INSERT INTO public.expenses VALUES ("
            "'owner', 'uploads/owner/demo.png', :img_sha, NULL, "
            "'uploads/owner/thumb.jpg', NULL, :cleanup_json)"
        ), {"img_sha": shas["demo.png"], "cleanup_json": expense_cleanup_json})
        conn.execute(sqlalchemy.text(
            "CREATE TABLE public.debt_bill_captures ("
            "tenant_id TEXT, image_path TEXT, image_hash TEXT, image_deleted_at TEXT, "
            "attachment_cleanup_request JSONB)"
        ))
        conn.execute(sqlalchemy.text(
            "INSERT INTO public.debt_bill_captures VALUES ("
            "'owner', 'uploads/owner/debt.png', :debt_sha, NULL, :debt_cleanup)"
        ), {"debt_sha": shas["debt.png"], "debt_cleanup": debt_cleanup_json})

    mod = launch._load_existing_dataset_upgrade_module()
    verified_paths: list[str] = []
    orig_verify_file = mod._VerifiedBackupArchive.verify_file

    def _spied_verify_file(self, path, *, data_root, expected_sha256=None):
        verified_paths.append(Path(path).name)
        return orig_verify_file(self, path, data_root=data_root, expected_sha256=expected_sha256)

    mod._VerifiedBackupArchive.verify_file = _spied_verify_file

    def _sqlite_migration_run(self, **kwargs):
        pre = kwargs.get("pre_migration_check")
        assert callable(pre)
        with upgrade_engine.connect() as conn:
            pre(conn)
        return "upgraded"

    mod.ManagedPostgresMigrationRuntimeV1.run = _sqlite_migration_run
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--upgrade-existing-dataset",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--source-revision",
                source_rev,
                "--target-revision",
                target_rev,
                "--dataset-id",
                dataset_id,
                "--installation-id",
                source_install,
                "--expected-restore-epoch",
                "0",
                "--operation-id",
                upgrade_op_id,
                "--data-root",
                str(explicit_data_root),
                "--backup-archive",
                str(backup_path),
                "--backup-archive-sha256",
                backup_sha,
                "--app-dir",
                str(app_dir),
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-existing-dataset-upgrade-result-v1"
    assert payload["result"] == "upgraded"
    assert set(verified_paths) == {"demo.png", "thumb.jpg", "pending.png", "debt.png", "debt_pending.png"}, verified_paths
elif mode == "--fresh-owner-claim":
    sqlite_engine, source_install, _ds, secret = _make_seeded_sqlite_engine(
        with_owner_and_original=False,
        upload_root=explicit_data_root / "app" / "uploads",
    )
    sqlalchemy.create_engine = lambda *_a, **_kw: sqlite_engine
    # Run BOTH create and idempotent replay through the real dispatcher!
    for _pass in range(2):
        sys.stdin = io.TextIOWrapper(io.BytesIO((secret + "\n").encode("ascii")))
        rc = launch._dispatch_maintenance_mode(
            [
                "--fresh-owner-claim",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--operation-id",
                "fresh-op-1",
                "--installation-id",
                source_install,
            ]
        )
        assert rc == 0
elif mode == "--verify-preserved-dataset":
    upload_root = explicit_data_root / "app" / "uploads"
    sqlite_engine, source_install, dataset_id, _secret = _make_seeded_sqlite_engine(
        with_owner_and_original=True,
        upload_root=upload_root,
    )
    sqlalchemy.create_engine = lambda *_a, **_kw: sqlite_engine
    from app import cold_restore_runtime, database_maintenance_runtime as dmr
    real_ctx = dmr.standalone_database_package
    @contextlib.contextmanager
    def _instrumented_pkg():
        with real_ctx():
            from app.database import _managed_postgres_role_authority as role_mod
            from app.database import _release_schema_readiness as ready_mod
            role_mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
            ready_mod.assert_release_head = lambda *_a, **_kw: None
            yield
    cold_restore_runtime.standalone_database_package = _instrumented_pkg
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--verify-preserved-dataset",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--data-root",
                str(explicit_data_root),
                "--dataset-id",
                dataset_id,
                "--installation-id",
                source_install,
                "--expected-restore-epoch",
                "0",
                "--schema-revision",
                "20261101_0001",
                "--semantic-revision",
                "ticketbox-dataset-semantics-v1",
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-preserved-dataset-verify-v1"
    assert payload["verified_originals"] == 1
elif mode == "--restore-cold-dataset":
    upload_root = explicit_data_root / "app" / "uploads"
    sqlite_engine, source_install, dataset_id, old_secret = _make_seeded_sqlite_engine(
        with_owner_and_original=True,
        upload_root=upload_root,
    )
    sqlalchemy.create_engine = lambda *_a, **_kw: sqlite_engine
    from app import cold_restore_runtime, database_maintenance_runtime as dmr
    real_ctx = dmr.standalone_database_package
    @contextlib.contextmanager
    def _instrumented_pkg():
        with real_ctx():
            from app.database import _managed_postgres_role_authority as role_mod
            from app.database import _release_schema_readiness as ready_mod
            from app.database import _runtime_authority_privileges as priv_mod
            role_mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
            ready_mod.assert_release_head = lambda *_a, **_kw: None
            priv_mod.seal_upgrade_attestation_guard = lambda *_a, **_kw: True
            yield
    cold_restore_runtime.standalone_database_package = _instrumented_pkg
    body = json.dumps({
        "source": {
            "install_id": source_install,
            "dataset_id": dataset_id,
            "restore_epoch": 0,
            "schema_revision": "20261101_0001",
        },
        "installation_id": "33333333-3333-4333-8333-333333333333",
        "backup_id": "44444444-4444-4444-8444-444444444444",
        "operation_id": "restore-op-1",
        "bootstrap_secret": "b" * 64,
        "recovery_secret": old_secret,
    }).encode("utf-8")
    sys.stdin = io.TextIOWrapper(io.BytesIO(body))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--restore-cold-dataset",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--data-root",
                str(explicit_data_root),
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-cold-restore-dataset-v1"
    assert payload["verified_originals"] == 1
    assert payload["restore_epoch"] == 1
else:
    raise AssertionError(f"unknown mode {mode}")

assert_isolated()
"""


@pytest.mark.parametrize(
    "mode",
    [
        "--validate-generation-program",
        "--fresh-schema-upgrade",
        "--database-generation-verify-target",
        "--upgrade-existing-dataset",
        "--fresh-owner-claim",
        "--restore-cold-dataset",
        "--verify-preserved-dataset",
    ],
)
@pytest.mark.parametrize("with_installation_id", [False, True])
def test_all_seven_maintenance_modes_never_import_config_or_runtime_db_facade(
    tmp_path: Path,
    mode: str,
    with_installation_id: bool,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    ambient_app = tmp_path / "ambient" / "app"
    explicit_data = tmp_path / "explicit" / "data"
    (ambient_app / "runtime-settings").mkdir(parents=True)
    (explicit_data / "app" / "runtime-settings").mkdir(parents=True)
    (ambient_app / ".env").write_text("SENTINEL_DOTENV_LOADED=1\n", encoding="utf-8")
    (explicit_data / "app" / ".env").write_text("SENTINEL_DOTENV_LOADED=1\n", encoding="utf-8")
    # Corrupted/foreign-owned runtime-settings.json in both roots must never be read.
    (ambient_app / "runtime-settings" / "runtime-settings.json").write_text("{not-json", encoding="utf-8")
    (explicit_data / "app" / "runtime-settings" / "runtime-settings.json").write_text("{not-json", encoding="utf-8")
    pgpass_path = tmp_path / "pgpass"
    pgpass_path.write_text("127.0.0.1:5432:ticketbox:ticketbox_migrator:secret\n", encoding="utf-8")
    backup_path = tmp_path / "backup.tbxcold"
    program_file = tmp_path / "DATABASE_GENERATION_PROGRAM.json"
    from scripts.build_database_generation_program import write_program

    write_program(backend_root=backend_root, output=program_file)

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PG")
        and key not in {"TICKETBOX_DATA_DIR", "UPLOAD_DIR", "TICKETBOX_INSTALLATION_ID", "SENTINEL_DOTENV_LOADED"}
    }
    env["PGPASSFILE"] = str(pgpass_path)
    env["TICKETBOX_DATA_DIR"] = str(ambient_app)
    env["UPLOAD_DIR"] = str(ambient_app / "uploads")
    if with_installation_id:
        env["TICKETBOX_INSTALLATION_ID"] = "99999999-9999-4999-8999-999999999999"

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _MAINTENANCE_ISOLATION_PROBE,
            str(backend_root),
            mode,
            str(explicit_data),
            str(pgpass_path),
            str(backup_path),
            str(program_file),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"{mode} failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"


_FROZEN_SEAM_PROBE = r"""
import sys
from pathlib import Path

backend_root = Path(sys.argv[1])
fake_meipass = Path(sys.argv[2])
sys.path.insert(0, str(backend_root))

# Simulate PyInstaller frozen layout: ONLY physical action files exist on disk under
# _MEIPASS/app/database/, while __init__.py does NOT exist on disk (lives in PYZ).
sys.frozen = True
sys._MEIPASS = str(fake_meipass)

from app.database_maintenance_runtime import standalone_database_package

assert not (fake_meipass / "app" / "database" / "__init__.py").exists()
with standalone_database_package():
    assert "app.database" in sys.modules
    assert sys.modules["app.database"].__path__ == [str((fake_meipass / "app" / "database").resolve())]
assert "app.database" not in sys.modules
"""


def test_standalone_database_package_works_in_frozen_meipass_without_init_py(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    fake_meipass = tmp_path / "meipass"
    db_dir = fake_meipass / "app" / "database"
    db_dir.mkdir(parents=True)
    (db_dir / "_fresh_schema_upgrade.py").write_text("# shipped physical action\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _FROZEN_SEAM_PROBE, str(backend_root), str(fake_meipass)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"frozen seam probe failed:\n{completed.stderr}"


def test_resolve_protected_image_empty_reference_does_not_call_get_settings(monkeypatch) -> None:
    from app.errors import AppError
    from app.services import file_service

    def _boom():
        raise AssertionError("get_settings must not be called for empty image reference")

    monkeypatch.setattr(file_service, "get_settings", _boom)
    assert file_service.resolve_upload_path_for_tenant("", "owner") is None
    assert file_service.resolve_upload_path_for_tenant(None, "owner") is None
    with pytest.raises(AppError) as caught:
        file_service.resolve_protected_image("", "owner")
    assert caught.value.error == "image_not_found"
    assert caught.value.status_code == 404


_BARE_OPEN_AUDIT_PROBE = _ISOLATION_GUARD_PREAMBLE + r"""
target_name = sys.argv[1]
caught_direct = False
try:
    open(target_name, encoding="utf-8")
except AssertionError as exc:
    assert "attempted forbidden file open" in str(exc)
    caught_direct = True
assert caught_direct, f"shared isolation guard failed to block bare relative open: {target_name}"

# Even when the open() AssertionError is swallowed, assert_isolated() MUST still fail on FORBIDDEN_EVENTS.
try:
    assert_isolated()
except AssertionError as exc:
    assert "recorded forbidden events" in str(exc)
else:
    raise SystemExit("assert_isolated() failed to catch swallowed forbidden open event")
"""


@pytest.mark.parametrize("bare_name", [".env", "runtime-settings.json"])
def test_forbidden_open_audit_catches_bare_relative_sensitive_files(tmp_path: Path, bare_name: str) -> None:
    (tmp_path / bare_name).write_text("sentinel\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _BARE_OPEN_AUDIT_PROBE, bare_name, "negative-self-check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"bare open audit probe failed for {bare_name}:\n{completed.stderr}"
