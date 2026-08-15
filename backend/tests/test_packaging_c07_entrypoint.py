"""Standalone frozen-entrypoint contracts for the exact C07 release edge."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE_REVISION = "20260722_0001"
TARGET_REVISION = "20260729_0001"
RELEASE_HEAD_REVISION = "20260809_0001"
OPERATION_ID = "11111111-1111-4111-8111-111111111111"
RESTORE_DATABASE = "ticketbox_c07_restore_11111111111141118111111111111111"
MIGRATOR_URL = (
    "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/"
)
DEADLINE = "2099-08-01T12:00:00.0000000Z"
SHA_A = "a" * 64
SHA_B = "b" * 64
PROGRAM_PATH = "DATABASE_GENERATION_PROGRAM.json"
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
import builtins
import importlib
import importlib.util
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

launch_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("ticketbox_c07_launch_probe", launch_path)
assert spec is not None and spec.loader is not None
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
assert not any(name == "app.database" or name.startswith("app.database.") for name in sys.modules)
production = launch._load_c07_production_migration_module()
assert production.PRODUCTION_MIGRATION_CONTEXT_SCHEMA == "ticketbox-c07-production-migration-context-v5"
context = SimpleNamespace(
    operation_id="11111111-1111-4111-8111-111111111111",
    operation_kind="c07_money_minor_bigint_v1",
    target_alembic_revision="20260729_0001",
    revision_manifest_sha256="A" * 64,
    maintenance_remaining_ceiling_ms=30_000,
)
program = SimpleNamespace(
    c07=SimpleNamespace(
        source_revision="20260722_0001",
        target_revision="20260729_0001",
        revision_manifest_sha256="a" * 64,
    )
)
production._validated_migrator_url = lambda value: value
production._validated_pgpass_path = lambda value: value
production.load_database_generation_program = lambda **_kwargs: program
production._hold_and_validate_artifacts = lambda *_args: object()
production.hold_protected_file_for_read = lambda path: nullcontext(path)
production._temporary_pgpass_environment = lambda _path: nullcontext()
class FakeEngine:
    def connect(self): return nullcontext(object())
    def dispose(self): return None

production._create_production_engine = lambda _parsed_url: FakeEngine()
production._transaction_timeout.c07_prearmed_transaction = (
    lambda _connection, *, timeout_ms: nullcontext()
)
production._migrate_with_connection = lambda _connection, **_kwargs: {
    "result": "standalone-action-entered"
}
original_import_module = importlib.import_module
original_import = builtins.__import__
def reject_database_import(name, *args, **kwargs):
    if name == "app.database" or name.startswith("app.database."):
        raise AssertionError("ordinary app.database facade imported during standalone action")
    return original_import(name, *args, **kwargs)
def reject_database_import_module(name, package=None):
    if name == "app.database" or name.startswith("app.database."):
        raise AssertionError("ordinary app.database facade imported during standalone action")
    return original_import_module(name, package)
builtins.__import__ = reject_database_import
importlib.import_module = reject_database_import_module
try:
    result = production.run_production_migration_action(
        database_url="postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/ticketbox",
        pgpassfile=Path("C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + "1" * 32),
        generation_program_path=Path("DATABASE_GENERATION_PROGRAM.json"),
        expected_generation_program_sha256="a" * 64,
        operation_id=context.operation_id,
        source_revision=program.c07.source_revision,
        target_revision=program.c07.target_revision,
        migration_context=context,
    )
finally:
    importlib.import_module = original_import_module
    builtins.__import__ = original_import
assert result == {"result": "standalone-action-entered"}
fresh = launch._load_c07_fresh_source_bootstrap_module()
assert callable(fresh.run_fresh_source_bootstrap_action)
maintenance = launch._load_c07_maintenance_upgrade_module()
assert not hasattr(maintenance, "get_installed_maintenance_plan")
managed = launch._load_managed_schema_upgrade_module()
assert not hasattr(managed, "get_managed_schema_plan")
assert callable(managed.validate_database_generation_program)
assert not any(name == "app.database" or name.startswith("app.database.") for name in sys.modules)
"""


def _load_launch_module():
    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location(
        "ticketbox_c07_launch",
        launch_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _maintenance_args(*, mode: str = "isolated_replay") -> list[str]:
    return [
        "--c07-maintenance-upgrade",
        "--mode",
        mode,
        "--database-url",
        MIGRATOR_URL + RESTORE_DATABASE,
        "--pgpassfile",
        "C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + ("1" * 32),
        "--generation-program-path",
        PROGRAM_PATH,
        "--expected-generation-program-sha256",
        SHA_A,
        "--operation-id",
        OPERATION_ID,
        "--source-revision",
        SOURCE_REVISION,
        "--target-revision",
        TARGET_REVISION,
        "--expected-revision-manifest-sha256",
        SHA_A,
        "--maintenance-deadline-utc",
        DEADLINE,
        "--maintenance-remaining-ceiling-ms",
        "60000",
        "--maintenance-authority-sha256",
        SHA_B,
    ]


def _target_args() -> list[str]:
    return [
        "--c07-target-semantic-digest",
        "--database-url",
        MIGRATOR_URL + "ticketbox",
        "--pgpassfile",
        "C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + ("1" * 32),
        "--generation-program-path",
        PROGRAM_PATH,
        "--expected-generation-program-sha256",
        SHA_A,
        "--operation-id",
        OPERATION_ID,
        "--database",
        "ticketbox",
        "--snapshot-id",
        "00000003-0000001B-1",
        "--source-revision",
        SOURCE_REVISION,
        "--target-revision",
        TARGET_REVISION,
        "--expected-revision-manifest-sha256",
        SHA_A,
        "--maintenance-deadline-utc",
        DEADLINE,
        "--maintenance-remaining-ceiling-ms",
        "60000",
        "--maintenance-authority-sha256",
        SHA_B,
    ]


def _production_args() -> list[str]:
    return [
        "--c07-production-migrate",
        "--database-url",
        MIGRATOR_URL + "ticketbox",
        "--pgpassfile",
        "C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + ("1" * 32),
        "--generation-program-path",
        PROGRAM_PATH,
        "--expected-generation-program-sha256",
        SHA_A,
        "--operation-id",
        OPERATION_ID,
        "--source-revision",
        SOURCE_REVISION,
        "--target-revision",
        TARGET_REVISION,
    ]


def _fresh_source_args() -> list[str]:
    return [
        "--c07-fresh-source-bootstrap",
        "--database-url",
        MIGRATOR_URL + "ticketbox_c07_fresh_source",
        "--pgpassfile",
        "C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + ("1" * 32),
        "--generation-program-path",
        PROGRAM_PATH,
        "--expected-generation-program-sha256",
        SHA_A,
        "--generation-operation-id",
        OPERATION_ID,
        "--source-revision",
        SOURCE_REVISION,
        "--target-revision",
        TARGET_REVISION,
    ]


def _managed_schema_args() -> list[str]:
    return [
        "--managed-schema-upgrade",
        "--database-url",
        MIGRATOR_URL + "ticketbox?require_auth=scram-sha-256",
        "--pgpassfile",
        "C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + ("1" * 32),
        "--generation-program-path",
        PROGRAM_PATH,
        "--expected-generation-program-sha256",
        SHA_A,
        "--source-revision",
        TARGET_REVISION,
        "--target-revision",
        RELEASE_HEAD_REVISION,
        "--generation-operation-id",
        OPERATION_ID,
    ]


def _money_facts_args() -> list[str]:
    return [
        "--c07-money-facts-digest",
        "--database-url",
        MIGRATOR_URL + "ticketbox",
        "--pgpassfile",
        "C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + ("1" * 32),
        "--operation-id",
        OPERATION_ID,
        "--database",
        "ticketbox",
        "--snapshot-id",
        "00000003-0000001B-1",
        "--maintenance-deadline-utc",
        DEADLINE,
        "--maintenance-remaining-ceiling-ms",
        "60000",
        "--maintenance-authority-sha256",
        SHA_B,
    ]


def _seal_c07_pg_environment(monkeypatch, argv: list[str]) -> Path:
    for name in list(os.environ):
        if name.upper().startswith("PG"):
            monkeypatch.delenv(name, raising=False)
    pgpassfile = Path(argv[argv.index("--pgpassfile") + 1])
    monkeypatch.setenv("PGPASSFILE", str(pgpassfile))
    return pgpassfile


def test_c07_actions_load_without_ordinary_database_facade() -> None:
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


def test_c07_maintenance_parser_rejects_descendant_mode() -> None:
    launch = _load_launch_module()
    with pytest.raises(SystemExit):
        launch._parse_c07_maintenance_upgrade_args(
            _maintenance_args(mode="installed_descendant")
        )


def test_c07_maintenance_helper_binds_exact_attested_result(monkeypatch) -> None:
    launch = _load_launch_module()
    monkeypatch.setattr(launch, "_resolve_generation_program", Path)
    captured: dict[str, object] = {}
    argv = _maintenance_args()
    _seal_c07_pg_environment(monkeypatch, argv)

    def run_action(**kwargs):
        captured.update(kwargs)
        return {
            "schema": "ticketbox-c07-maintenance-upgrade-result-v3",
            "mode": "isolated_replay",
            "operation_id": OPERATION_ID,
            "source_revision": SOURCE_REVISION,
            "target_revision": TARGET_REVISION,
            "revision_manifest_sha256": SHA_A,
            "maintenance_authority_sha256": SHA_B,
            "maintenance_remaining_ceiling_ms": 60000,
            "resource_shape_sha256": SHA_A,
            "result": "isolated_forward_replay_verified",
            "alembic_revision": TARGET_REVISION,
            "target_shape_sha256": SHA_A,
            "money_facts_sha256": SHA_B,
        }

    monkeypatch.setattr(
        launch,
        "_load_c07_maintenance_upgrade_module",
        lambda: SimpleNamespace(run_maintenance_upgrade_action=run_action),
    )
    output = io.StringIO()
    assert launch._run_c07_maintenance_upgrade(
        argv,
        input_stream=io.BytesIO(b""),
        output_stream=output,
    ) == 0
    assert captured["source_revision"] == SOURCE_REVISION
    assert captured["target_revision"] == TARGET_REVISION
    assert captured["expected_revision_manifest_sha256"] == SHA_A
    assert captured["maintenance_authority_sha256"] == SHA_B
    assert "password" not in str(captured["database_url"])
    assert "isolated_forward_replay_verified" in output.getvalue()


def test_c07_target_helper_emits_only_real_c07_attestations(monkeypatch) -> None:
    launch = _load_launch_module()
    monkeypatch.setattr(launch, "_resolve_generation_program", Path)
    captured: dict[str, object] = {}
    argv = _target_args()
    _seal_c07_pg_environment(monkeypatch, argv)

    def run_action(**kwargs):
        captured.update(kwargs)
        return {
            "schema": "ticketbox-c07-target-semantic-result-v1",
            "operation_id": OPERATION_ID,
            "database": "ticketbox",
            "snapshot_id": "00000003-0000001B-1",
            "source_revision": SOURCE_REVISION,
            "target_revision": TARGET_REVISION,
            "revision_manifest_sha256": SHA_A,
            "maintenance_authority_sha256": SHA_B,
            "maintenance_remaining_ceiling_ms": 60000,
            "alembic_revision": TARGET_REVISION,
            "resource_shape_sha256": SHA_A,
            "money_facts_sha256": SHA_B,
        }

    monkeypatch.setattr(
        launch,
        "_load_c07_maintenance_upgrade_module",
        lambda: SimpleNamespace(run_target_semantic_digest_action=run_action),
    )
    output = io.StringIO()
    assert launch._run_c07_target_semantic(
        argv,
        input_stream=io.BytesIO(b""),
        output_stream=output,
    ) == 0
    payload = output.getvalue()
    assert captured["snapshot_id"] == "00000003-0000001B-1"
    assert '"resource_shape_sha256"' in payload
    assert '"money_facts_sha256"' in payload
    assert "stable_replay_sha256" not in payload
    assert "device_close_sha256" not in payload
    assert "category_rule_public_id_sha256" not in payload
    assert "retention_evidence_sha256" not in payload


def test_c07_helper_rejects_nonempty_maintenance_input(monkeypatch) -> None:
    launch = _load_launch_module()
    monkeypatch.setattr(
        launch,
        "_load_c07_maintenance_upgrade_module",
        lambda: pytest.fail("action must not load after nonempty stdin"),
    )
    with pytest.raises(RuntimeError, match="requires empty stdin"):
        launch._run_c07_maintenance_upgrade(
            _maintenance_args(),
            input_stream=io.BytesIO(b"{}"),
            output_stream=io.StringIO(),
        )


def test_c07_libpq_environment_allows_only_the_exact_passfile(monkeypatch) -> None:
    launch = _load_launch_module()
    argv = _maintenance_args()
    pgpassfile = _seal_c07_pg_environment(monkeypatch, argv)

    launch._assert_c07_libpq_environment(pgpassfile)
    for name in _LIBPQ_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "ambient-libpq-authority")
        with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
            launch._assert_c07_libpq_environment(pgpassfile)
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("pgservice", "case-insensitive-ambient-authority")
    with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
        launch._assert_c07_libpq_environment(pgpassfile)
    monkeypatch.delenv("pgservice", raising=False)
    monkeypatch.setenv("PGPASSFILE", str(pgpassfile) + ".other")
    with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
        launch._assert_c07_libpq_environment(pgpassfile)


def test_all_c07_database_entrypoints_reject_ambient_libpq_authority(
    monkeypatch,
) -> None:
    launch = _load_launch_module()

    def fail_loader():
        pytest.fail("C07 action loaded before the libpq environment guard")

    monkeypatch.setattr(launch, "_load_c07_production_migration_module", fail_loader)
    monkeypatch.setattr(launch, "_load_c07_fresh_source_bootstrap_module", fail_loader)
    monkeypatch.setattr(launch, "_load_c07_maintenance_upgrade_module", fail_loader)
    monkeypatch.setattr(launch, "_load_managed_schema_upgrade_module", fail_loader)
    entrypoints = (
        (launch._run_c07_production_migration, _production_args()),
        (launch._run_c07_fresh_source_bootstrap, _fresh_source_args()),
        (launch._run_c07_maintenance_upgrade, _maintenance_args()),
        (launch._run_c07_money_facts, _money_facts_args()),
        (launch._run_c07_target_semantic, _target_args()),
        (launch._run_managed_schema_upgrade, _managed_schema_args()),
    )
    for entrypoint, argv in entrypoints:
        _seal_c07_pg_environment(monkeypatch, argv)
        monkeypatch.setenv("PGHOSTADDR", "203.0.113.10")
        with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
            entrypoint(
                argv,
                input_stream=io.BytesIO(b""),
                output_stream=io.StringIO(),
            )
