"""Build-owned installed database generation program contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
COMPILER = BACKEND / "scripts" / "build_database_generation_program.py"
PROGRAM_READER = BACKEND / "app" / "database" / "_database_generation_program.py"
SOURCE_REVISION = "20260722_0001"
C07_REVISION = "20260729_0001"
TARGET_REVISION = "20260809_0001"
EXPECTED_PROGRAM_SHA256 = (
    "f4b65fe1b5e998e5b98cc993f12dec4d01a6ca9ecdbdf74bc5a67678b36aa9a1"
)


def _load(path: Path, name: str):
    assert path.is_file(), f"missing contracted module: {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_build_compiler_emits_one_canonical_base_to_head_program(
    tmp_path: Path,
) -> None:
    compiler = _load(COMPILER, "ticketbox_generation_program_compiler")
    output = tmp_path / "DATABASE_GENERATION_PROGRAM.json"

    first_sha = compiler.write_program(backend_root=BACKEND, output=output)
    first_payload = output.read_bytes()
    second_sha = compiler.write_program(backend_root=BACKEND, output=output)
    program = json.loads(output.read_text(encoding="utf-8"))

    assert (
        first_sha
        == second_sha
        == hashlib.sha256(first_payload).hexdigest()
        == EXPECTED_PROGRAM_SHA256
    )
    assert output.read_bytes() == first_payload
    assert set(program) == {
        "revisions",
        "schema",
        "source_revision",
        "target_revision",
    }
    assert program["schema"] == "ticketbox-database-generation-program-v1"
    assert program["source_revision"] == "base"
    assert program["target_revision"] == TARGET_REVISION
    assert len(program["revisions"]) == 43

    previous = None
    c07_entries = []
    for revision in program["revisions"]:
        assert revision["down_revision"] == previous
        module = BACKEND.joinpath(*revision["module_path"].split("/"))
        assert module.parent == BACKEND / "migrations" / "versions"
        assert revision["module_sha256"] == hashlib.sha256(module.read_bytes()).hexdigest()
        if revision["revision"] == C07_REVISION:
            c07_entries.append(revision)
        previous = revision["revision"]
    assert previous == TARGET_REVISION
    assert len(c07_entries) == 1
    assert c07_entries[0]["down_revision"] == SOURCE_REVISION
    assert c07_entries[0]["context"]["kind"] == "c07_ceremony_v1"


def test_runtime_reader_binds_program_and_revision_bytes(tmp_path: Path) -> None:
    compiler = _load(COMPILER, "ticketbox_generation_program_compiler_runtime")
    reader = _load(PROGRAM_READER, "ticketbox_generation_program_reader")
    output = tmp_path / "DATABASE_GENERATION_PROGRAM.json"
    expected_sha = compiler.write_program(backend_root=BACKEND, output=output)

    program = reader.load_database_generation_program(
        path=output,
        expected_sha256=expected_sha,
    )
    assert program.source_revision == "base"
    assert program.target_revision == TARGET_REVISION
    assert program.c07.source_revision == SOURCE_REVISION
    assert program.c07.target_revision == C07_REVISION
    assert program.suffix(SOURCE_REVISION, TARGET_REVISION)[0].revision == C07_REVISION

    output.write_bytes(output.read_bytes() + b"\n")
    with pytest.raises(reader.DatabaseGenerationProgramError):
        reader.load_database_generation_program(
            path=output,
            expected_sha256=expected_sha,
        )


def test_frozen_runtime_loads_program_from_exact_build_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = _load(COMPILER, "ticketbox_generation_program_compiler_frozen")
    reader = _load(PROGRAM_READER, "ticketbox_generation_program_reader_frozen")
    program_path = tmp_path / "DATABASE_GENERATION_PROGRAM.json"
    expected_sha = compiler.write_program(backend_root=BACKEND, output=program_path)
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


def test_installed_lifecycle_uses_program_without_runtime_graph_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = _load(COMPILER, "ticketbox_generation_program_compiler_lifecycle")
    output = tmp_path / "DATABASE_GENERATION_PROGRAM.json"
    expected_sha = compiler.write_program(backend_root=BACKEND, output=output)
    from app.database._database_generation_program import (
        load_database_generation_program,
    )

    program = load_database_generation_program(
        path=output,
        expected_sha256=expected_sha,
    )
    from alembic import script as alembic_script

    from app.database import _c07_execution, _lifecycle

    monkeypatch.setattr(
        alembic_script.ScriptDirectory,
        "from_config",
        lambda _config: pytest.fail("installed runtime must not discover Alembic graph"),
    )

    context = _lifecycle.load_alembic_context(installed_program=program)

    assert context.head_revision == program.target_revision
    assert context.known_revisions == frozenset(
        revision.revision for revision in program.revisions
    )
    assert _c07_execution._revision_includes_c07(
        program.target_revision,
        alembic_config=context.config,
    )


def test_installed_init_db_passes_frozen_program_to_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.database as database
    from app.database import _database_generation_program as program_reader
    from app.database._lifecycle import DatabaseLifecycleAction

    installed_program = object()
    observed: list[object] = []
    monkeypatch.setattr(database, "_warn_if_default_database_url", lambda: None)
    monkeypatch.setattr(database, "_is_installed_host_database", lambda: True)
    monkeypatch.setattr(
        program_reader,
        "load_installed_database_generation_program",
        lambda: installed_program,
    )
    monkeypatch.setattr(
        database,
        "inspect_database_lifecycle",
        lambda: SimpleNamespace(has_existing_schema=False),
    )
    monkeypatch.setattr(
        database,
        "load_alembic_context",
        lambda *, installed_program: (
            observed.append(installed_program)
            or SimpleNamespace(head_revision=TARGET_REVISION)
        ),
    )
    monkeypatch.setattr(database, "_assert_revision_contains_c07", lambda *a, **k: None)
    monkeypatch.setattr(
        database,
        "plan_database_lifecycle",
        lambda *_args: SimpleNamespace(
            action=DatabaseLifecycleAction.REFUSE,
            refusal_reason="contract-stop;",
        ),
    )

    with pytest.raises(database.DatabaseMigrationPreflightError, match="contract-stop"):
        database.init_db()

    assert observed == [installed_program]


def test_installed_migration_has_one_program_authority_and_no_runtime_graph() -> None:
    runtime_planners = {
        "app.database._c07_fresh_source_bootstrap": "app/database/_c07_fresh_source_bootstrap.py",
        "app.database._c07_maintenance_plan": "app/database/_c07_maintenance_plan.py",
        "app.database._c07_maintenance_upgrade_action": "app/database/_c07_maintenance_upgrade_action.py",
        "app.database._database_generation_executor": "app/database/_database_generation_executor.py",
        "app.database._managed_schema_upgrade": "app/database/_managed_schema_upgrade.py",
        "app.database._managed_postgres_migration_runtime": "app/database/_managed_postgres_migration_runtime.py",
    }
    for module_name, relative in runtime_planners.items():
        source = (BACKEND / relative).read_text(encoding="utf-8")
        assert "ScriptDirectory" not in source, module_name
        assert "command.upgrade" not in source, module_name

    launch = (BACKEND / "packaging" / "launch.py").read_text(encoding="utf-8")
    bridge = (BACKEND / "packaging" / "windows_c07_packaged_migration.ps1").read_text(
        encoding="utf-8-sig"
    )
    installer = (BACKEND / "packaging" / "install_bundled_services.ps1").read_text(
        encoding="utf-8-sig"
    )
    combined = launch + bridge + installer
    assert "--validate-generation-program" in launch
    assert "Get-TicketboxInstalledDatabaseGenerationProgram" in installer
    assert "--c07-installed-upgrade-plan" not in combined
    assert "--managed-schema-plan" not in combined
    assert "Get-TicketboxC07InstalledUpgradePlan" not in installer
    assert "Get-TicketboxInstalledManagedSchemaPlan" not in installer


def test_build_and_installed_identity_ship_the_exact_program() -> None:
    build = (BACKEND / "scripts" / "build_backend_exe.ps1").read_text(
        encoding="utf-8-sig"
    )
    provenance = (
        BACKEND / "scripts" / "windows_backend_build_provenance.ps1"
    ).read_text(encoding="utf-8-sig")
    installation = (
        BACKEND / "packaging" / "windows_installation_safety.ps1"
    ).read_text(encoding="utf-8-sig")
    for source in (build, provenance, installation):
        assert "DATABASE_GENERATION_PROGRAM.json" in source
    assert "build_database_generation_program.py" in build
    assert "$stagedDatabaseGenerationProgram" in build
    assert "--validate-generation-program" in provenance
    assert "database_generation_program" in provenance
    assert "DatabaseGenerationProgramSha256" in installation
    assert "Resolve-TicketboxInstalledDatabaseGenerationProgramPath" in installation
