"""Frozen database-generation entrypoint contracts."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

OPERATION_ID = "11111111-1111-4111-8111-111111111111"
RESTORE_DATABASE = "ticketbox_c07_restore_11111111111141118111111111111111"
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
assert callable(managed.validate_database_generation_program)
assert callable(managed.run_managed_schema_upgrade_action)
assert callable(target.run_database_generation_target_verification_action)
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
    monkeypatch.setattr(launch.sys, "executable", "ticketbox-c07-migrator.exe")
    monkeypatch.setattr(
        launch,
        "configure_environment",
        lambda: pytest.fail("retired mode reached backend startup"),
    )
    for switch in _RETIRED_SWITCHES:
        monkeypatch.setattr(launch.sys, "argv", ["ticketbox-c07-migrator.exe", switch])
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
    launch._assert_c07_libpq_environment(pgpassfile)
    for name in _LIBPQ_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "ambient-libpq-authority")
        with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
            launch._assert_c07_libpq_environment(pgpassfile)
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGPASSFILE", str(pgpassfile) + ".other")
    with pytest.raises(RuntimeError, match="libpq environment is not sealed"):
        launch._assert_c07_libpq_environment(pgpassfile)
