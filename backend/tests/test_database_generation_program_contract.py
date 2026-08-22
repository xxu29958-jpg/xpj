"""Build-owned installed database generation program contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
COMPILER = BACKEND / "scripts" / "build_database_generation_program.py"
PROGRAM_READER = BACKEND / "app" / "database" / "_database_generation_program.py"
SOURCE_REVISION = "20260722_0001"
MONEY_BIGINT_REVISION = "20260729_0001"
TARGET_REVISION = "20260821_0001"
EXPECTED_PROGRAM_SHA256 = "f574c229c5ac7fd62c62b4209fdd32cbeb5ed38b50e414cddbac61ad7c3d9dd7"

_BUILD_COMPILER_PURITY_PROBE = r"""
import builtins
import dotenv
import dotenv.main
import importlib.util
import os
import sqlalchemy
import sqlalchemy.engine
import sqlalchemy.engine.create
import sys
import tempfile
from pathlib import Path

compiler_path = Path(sys.argv[1])
backend_root = Path(sys.argv[2])
original_import = builtins.__import__
original_engine = sqlalchemy.create_engine
original_engine_api = sqlalchemy.engine.create_engine
original_engine_impl = sqlalchemy.engine.create.create_engine
original_dotenv = dotenv.load_dotenv
original_dotenv_main = dotenv.main.load_dotenv
def reject_database_import(name, *args, **kwargs):
    if name == "app.database" or name.startswith("app.database."):
        raise AssertionError("build compiler imported runtime database authority")
    return original_import(name, *args, **kwargs)
def reject_engine(*_args, **_kwargs):
    raise AssertionError("build compiler created a runtime database engine")
def reject_dotenv(*_args, **_kwargs):
    raise AssertionError("build compiler loaded ambient dotenv state")
builtins.__import__ = reject_database_import
sqlalchemy.create_engine = reject_engine
sqlalchemy.engine.create_engine = reject_engine
sqlalchemy.engine.create.create_engine = reject_engine
dotenv.load_dotenv = reject_dotenv
dotenv.main.load_dotenv = reject_dotenv
os.environ["DATABASE_URL"] = "postgresql+psycopg://ambient.invalid/ticketbox"
os.environ["TICKETBOX_DATA_DIR"] = "Z:/ambient-ticketbox-data"
try:
    spec = importlib.util.spec_from_file_location("ticketbox_build_compiler_purity", compiler_path)
    assert spec is not None and spec.loader is not None
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "DATABASE_GENERATION_PROGRAM.json"
        print(compiler.write_program(backend_root=backend_root, output=output))
finally:
    dotenv.main.load_dotenv = original_dotenv_main
    dotenv.load_dotenv = original_dotenv
    sqlalchemy.engine.create.create_engine = original_engine_impl
    sqlalchemy.engine.create_engine = original_engine_api
    sqlalchemy.create_engine = original_engine
    builtins.__import__ = original_import
assert not any(name == "app.database" or name.startswith("app.database.") for name in sys.modules)
"""


def _load(path: Path, name: str):
    assert path.is_file(), f"missing contracted module: {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _compile_program(tmp_path: Path, module_name: str) -> tuple[Path, str]:
    output = tmp_path / "DATABASE_GENERATION_PROGRAM.json"
    return output, _load(COMPILER, module_name).write_program(backend_root=BACKEND, output=output)


def _source(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding="utf-8-sig")


def test_build_compiler_emits_one_canonical_base_to_head_program(
    tmp_path: Path,
) -> None:
    compiler = _load(COMPILER, "ticketbox_generation_program_compiler")
    output = tmp_path / "DATABASE_GENERATION_PROGRAM.json"

    first_sha = compiler.write_program(backend_root=BACKEND, output=output)
    first_payload = output.read_bytes()
    second_sha = compiler.write_program(backend_root=BACKEND, output=output)
    program = json.loads(output.read_text(encoding="utf-8"))

    assert first_sha == second_sha == hashlib.sha256(first_payload).hexdigest() == EXPECTED_PROGRAM_SHA256
    assert output.read_bytes() == first_payload
    assert set(program) == {"revisions", "schema", "source_revision", "target_revision"}
    assert program["schema"] == "ticketbox-database-generation-program-v2"
    assert program["source_revision"] == "base"
    assert program["target_revision"] == TARGET_REVISION
    assert len(program["revisions"]) == 44

    previous = None
    money_bigint_entries = []
    for revision in program["revisions"]:
        assert revision["down_revision"] == previous
        module = BACKEND.joinpath(*revision["module_path"].split("/"))
        assert module.parent == BACKEND / "migrations" / "versions"
        assert revision["module_sha256"] == hashlib.sha256(module.read_bytes()).hexdigest()
        if revision["revision"] == MONEY_BIGINT_REVISION:
            money_bigint_entries.append(revision)
        previous = revision["revision"]
    assert previous == TARGET_REVISION
    assert len(money_bigint_entries) == 1
    assert money_bigint_entries[0]["down_revision"] == SOURCE_REVISION


def test_build_program_delegates_every_revision_to_alembic(
    tmp_path: Path,
) -> None:
    """The frozen program selects bytes and order, never a second executor."""

    output, _expected_sha = _compile_program(
        tmp_path,
        "ticketbox_generation_program_compiler_alembic_owner",
    )
    program = json.loads(output.read_text(encoding="utf-8"))

    expected_keys = {
        "down_revision",
        "module_path",
        "module_sha256",
        "postcondition",
        "revision",
    }
    assert program["revisions"]
    assert all(set(revision) == expected_keys for revision in program["revisions"])


def test_build_compiler_is_isolated_from_runtime_database_authority() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _BUILD_COMPILER_PURITY_PROBE,
            str(COMPILER),
            str(BACKEND),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == EXPECTED_PROGRAM_SHA256


def test_runtime_reader_binds_program_and_revision_bytes(tmp_path: Path) -> None:
    reader = _load(PROGRAM_READER, "ticketbox_generation_program_reader")
    output, expected_sha = _compile_program(tmp_path, "ticketbox_generation_program_compiler_runtime")

    program = reader.load_database_generation_program(path=output, expected_sha256=expected_sha)
    assert program.source_revision == "base"
    assert program.target_revision == TARGET_REVISION
    assert program.suffix(SOURCE_REVISION, TARGET_REVISION)[0].revision == MONEY_BIGINT_REVISION

    with pytest.raises(reader.DatabaseGenerationProgramError):
        reader.load_database_generation_program(
            path=output,
            expected_sha256="0" * 64,
        )

    output.write_bytes(output.read_bytes() + b"\n")
    with pytest.raises(reader.DatabaseGenerationProgramError):
        reader.load_database_generation_program(path=output, expected_sha256=expected_sha)


def test_frozen_runtime_loads_program_from_exact_build_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _load(PROGRAM_READER, "ticketbox_generation_program_reader_frozen")
    program_path, expected_sha = _compile_program(tmp_path, "ticketbox_generation_program_compiler_frozen")
    executable = tmp_path / "ticketbox-backend.exe"
    executable.write_bytes(b"frozen-backend")
    manifest = {
        "artifact_type": "ticketbox-frozen-backend",
        "payload": {
            "database_generation_program": {
                "path": program_path.name,
                "sha256": expected_sha,
                "size": program_path.stat().st_size,
            }
        },
        "schema_version": 4,
    }
    (tmp_path / "BUILD_PROVENANCE.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    program = reader.load_installed_database_generation_program()

    assert program.path == program_path
    assert program.payload_sha256 == expected_sha
    manifest["payload"]["database_generation_program"]["size"] += 1
    (tmp_path / "BUILD_PROVENANCE.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with pytest.raises(reader.DatabaseGenerationProgramError):
        reader.load_installed_database_generation_program()


def test_installed_lifecycle_planning_uses_program_without_graph_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, expected_sha = _compile_program(tmp_path, "ticketbox_generation_program_compiler_lifecycle")
    from app.database._database_generation_program import (
        load_database_generation_program,
    )

    program = load_database_generation_program(
        path=output,
        expected_sha256=expected_sha,
    )
    from alembic import script as alembic_script

    from app.database import _lifecycle

    monkeypatch.setattr(
        alembic_script.ScriptDirectory,
        "from_config",
        lambda _config: pytest.fail("installed runtime must not discover Alembic graph"),
    )

    context = _lifecycle.load_alembic_context(installed_program=program)

    assert context.head_revision == program.target_revision
    assert context.known_revisions == frozenset(revision.revision for revision in program.revisions)
    assert program.revision_includes(
        program.target_revision,
        "20260729_0001",
    )


@pytest.mark.parametrize("action_name", ["FRESH_UPGRADE", "MANAGED_UPGRADE", "NOOP"])
def test_installed_init_db_uses_one_frozen_release_fact(
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
) -> None:
    import app.database as database
    from app.database import _database_generation_program as program_reader
    from app.database._lifecycle import DatabaseLifecycleAction

    installed_program = object()
    observed: list[object] = []
    generation_authorities: list[object] = []
    monkeypatch.setattr(database, "_warn_if_default_database_url", lambda: None)
    monkeypatch.delenv("TICKETBOX_DATA_ROOT_MARKER_PATH", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(program_reader, "load_installed_database_generation_program", lambda: installed_program)
    monkeypatch.setattr(database, "inspect_database_lifecycle", lambda: SimpleNamespace(has_existing_schema=False))

    def load_context(*, installed_program: object) -> SimpleNamespace:
        observed.append(installed_program)
        return SimpleNamespace(head_revision=TARGET_REVISION)

    def stop_on_authority(_engine: object, program: object) -> None:
        generation_authorities.append(program)
        raise RuntimeError("authority-observed")

    monkeypatch.setattr(database, "load_alembic_context", load_context)
    monkeypatch.setattr(database, "_assert_existing_schema_compatible", lambda *_a, **_k: None)
    monkeypatch.setattr(database, "assert_database_generation_startup_ready", stop_on_authority)
    monkeypatch.setattr(database, "_apply_schema_lifecycle", lambda *_a: pytest.fail("frozen DDL"))
    monkeypatch.setattr(
        database,
        "plan_database_lifecycle",
        lambda *_a: SimpleNamespace(action=getattr(DatabaseLifecycleAction, action_name)),
    )

    if action_name == "NOOP":
        with pytest.raises(RuntimeError, match="authority-observed"):
            database.init_db()
        assert generation_authorities == [installed_program]
    else:
        with pytest.raises(database.DatabaseMigrationPreflightError, match="安装版"):
            database.init_db()
        assert generation_authorities == []

    assert observed == [installed_program]


def test_installed_migration_keeps_program_authority_and_alembic_execution() -> None:
    runtime_consumers = {
        "app.database._managed_schema_upgrade": "app/database/_managed_schema_upgrade.py",
        "app.database._managed_postgres_migration_runtime": "app/database/_managed_postgres_migration_runtime.py",
        "app.database._database_generation_target_verification": "app/database/_database_generation_target_verification.py",
    }
    for module_name, relative in runtime_consumers.items():
        source = _source(relative)
        assert "ScriptDirectory" not in source, module_name
        assert "command.upgrade" not in source, module_name

    executor = _source("app/database/_database_generation_executor.py")
    assert "from alembic import command" in executor
    assert 'config.attributes["connection"] = connection' in executor
    assert "command.upgrade(config, target_revision)" in executor
    for foreign_writer in (
        "module.upgrade()",
        "INSERT INTO public.alembic_version",
        "UPDATE public.alembic_version",
    ):
        assert foreign_writer not in executor

    env_source = _source("migrations/env.py")
    imports, separator, database_url_body = env_source.partition("def _database_url()")
    assert separator
    assert "from app.config import get_settings" not in imports
    assert "from app.config import get_settings" in database_url_body

    assert not (BACKEND / "scripts" / "c07_money_bigint_ceremony.py").exists()

    launch = _source("packaging/launch.py")
    bridge = _source("packaging/windows_database_generation_program_adapter.ps1")
    owner = _source("packaging/windows_database_generation.ps1")
    credentials = _source("packaging/windows_database_generation_credentials.ps1")
    role_fence = _source("packaging/windows_database_generation_role_fence.ps1")
    database_binding = _source("packaging/windows_database_generation_database_binding.ps1")
    installer = _source("packaging/install_bundled_services.ps1")
    combined = launch + bridge + owner + credentials + role_fence + database_binding + installer
    assert "--validate-generation-program" in launch
    assert "Get-TicketboxInstalledDatabaseGenerationProgram" in bridge
    assert "Get-TicketboxInstalledDatabaseGenerationProgram" not in (
        owner + credentials + role_fence + database_binding
    )
    assert installer.count("Invoke-TicketboxInstalledDatabaseGeneration `") == 1
    for retired in (
        "--c07-installed-upgrade-plan",
        "--managed-schema-plan",
        "--c07-production-migrate",
        "--c07-fresh-source-bootstrap",
        "--c07-maintenance-upgrade",
        "--c07-money-facts-digest",
        "--c07-target-semantic-digest",
    ):
        assert retired not in combined
    for retired in ("Get-TicketboxC07InstalledUpgradePlan", "Get-TicketboxInstalledManagedSchemaPlan"):
        assert retired not in installer


def test_program_validation_result_is_closed_and_c07_free(tmp_path: Path) -> None:
    from app.database import _managed_schema_upgrade as managed

    output, expected_sha = _compile_program(
        tmp_path,
        "ticketbox_generation_program_compiler_validation_result",
    )

    assert managed.validate_database_generation_program(
        generation_program_path=output,
        expected_generation_program_sha256=expected_sha,
    ) == {
        "schema": "ticketbox-database-generation-program-validation-v2",
        "source_revision": "base",
        "target_revision": TARGET_REVISION,
        "revision_count": 44,
        "generation_program_sha256": expected_sha,
    }


def test_managed_action_rejects_an_intermediate_program_target_before_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database import _managed_schema_upgrade as managed

    output, expected_sha = _compile_program(
        tmp_path,
        "ticketbox_generation_program_compiler_intermediate_target",
    )
    monkeypatch.setattr(
        managed,
        "ManagedPostgresMigrationRuntimeV1",
        lambda *_args, **_kwargs: pytest.fail("runtime created for intermediate target"),
    )

    with pytest.raises(
        managed.ManagedSchemaUpgradeError,
        match="target differs from the generation program",
    ):
        managed.run_managed_schema_upgrade_action(
            database_url="postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/ticketbox",
            pgpassfile=tmp_path / (".ticketbox-pgpass-1-" + "0" * 32),
            generation_program_path=output,
            expected_generation_program_sha256=expected_sha,
            source_revision=SOURCE_REVISION,
            target_revision=MONEY_BIGINT_REVISION,
            generation_operation_id="11111111-1111-4111-8111-111111111111",
        )


def test_build_and_installed_identity_ship_the_exact_program() -> None:
    build = _source("scripts/build_backend_exe.ps1")
    provenance = _source("scripts/windows_backend_build_provenance.ps1")
    installation = _source("packaging/windows_installation_safety.ps1")
    for source in (build, provenance, installation):
        assert "DATABASE_GENERATION_PROGRAM.json" in source
    assert "build_database_generation_program.py" in build
    assert "$stagedDatabaseGenerationProgram" in build
    assert "--validate-generation-program" in provenance
    assert "database_generation_program" in provenance
    assert "DatabaseGenerationProgramSha256" in installation
    assert "Resolve-TicketboxInstalledDatabaseGenerationProgramPath" in installation
