from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent
PACKAGING = ROOT / "packaging"
PROVENANCE_HELPER = ROOT / "scripts" / "windows_build_provenance.ps1"
INSTALLATION_SAFETY = PACKAGING / "windows_installation_safety.ps1"


def _ps_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _run_powershell(command: str, executable: str = "powershell") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _lock_input_fingerprint(root: Path) -> str:
    records: list[tuple[str, int, str]] = []
    for relative in sorted(("requirements-build.txt", "requirements.txt"), key=str.lower):
        payload = (root / relative).read_bytes()
        records.append((relative, len(payload), hashlib.sha256(payload).hexdigest()))
    material = "".join(f"{path}\0{size}\0{digest}\n" for path, size, digest in records)
    return hashlib.sha256(material.encode()).hexdigest()


def _write_minimal_backend(root: Path) -> Path:
    (root / "app").mkdir(parents=True)
    (root / "migrations" / "versions").mkdir(parents=True)
    (root / "packaging").mkdir()
    (root / "scripts").mkdir()
    (root / "app" / "version.py").write_text('BACKEND_VERSION = "7.8.9"\n', encoding="utf-8")
    (root / "app" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "migrations" / "env.py").write_text("# migration\n", encoding="utf-8")
    target_migration = "20260729_0001_money_minor_bigint_expand.py"
    (root / "migrations" / "versions" / target_migration).write_text("# target migration\n", encoding="utf-8")
    for relative in (
        "alembic.ini",
        "requirements.txt",
        "requirements-build.txt",
        "requirements-build.lock",
        "packaging/prepare_windows_build_toolchain.ps1",
        "packaging/launch.py",
        "packaging/ticketbox-backend.spec",
        "scripts/build_database_generation_program.py",
        "scripts/build_backend_exe.ps1",
        "scripts/windows_build_provenance.ps1",
        "scripts/windows_backend_build_provenance.ps1",
    ):
        (root / relative).write_text(f"# {relative}\n", encoding="utf-8")
    python_source_payload = b"tool:python-source.exe"
    uv_payload = b"tool:uv.exe"
    (root / "packaging" / "windows-build-toolchain.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "python_version": "3.11.15",
                "uv_version": "0.11.7",
                "pyinstaller_version": "6.21.0",
                "build_tool_sources": {
                    "uv": {
                        "version": "0.11.7",
                        "archive_name": "uv.zip",
                        "url": "https://example.test/uv.zip",
                        "sha256": "1" * 64,
                        "executable_relative_path": "uv.exe",
                        "executable_sha256": hashlib.sha256(uv_payload).hexdigest(),
                    },
                    "python": {
                        "version": "3.11.15",
                        "archive_name": "python.tar.gz",
                        "url": "https://example.test/python.tar.gz",
                        "sha256": "2" * 64,
                        "archive_payload_root": "python",
                        "executable_relative_path": "python.exe",
                        "executable_sha256": hashlib.sha256(python_source_payload).hexdigest(),
                        "runtime_relative_path": "python311.dll",
                        "runtime_sha256": "3" * 64,
                    },
                    "inno_setup": {
                        "version": "6.7.1",
                        "archive_name": "inno.exe",
                        "url": "https://example.test/inno.exe",
                        "sha256": "4" * 64,
                        "compiler_relative_path": "ISCC.exe",
                        "compiler_sha256": "5" * 64,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "requirements-build.lock").write_text(
        f"# ticketbox-lock-input-sha256: {_lock_input_fingerprint(root)}\npyinstaller==6.21.0\n",
        encoding="utf-8",
    )
    for executable in (
        root / ".venv-build" / "Scripts" / "python.exe",
        root / ".venv-build" / "Scripts" / "pyinstaller.exe",
        root / "tools" / "uv.exe",
        root / "tools" / "python-source.exe",
    ):
        executable.parent.mkdir(parents=True, exist_ok=True)
        if executable.name == "python-source.exe":
            executable.write_bytes(python_source_payload)
        elif executable.name == "uv.exe":
            executable.write_bytes(uv_payload)
        else:
            executable.write_bytes(f"tool:{executable.name}".encode())
    dist = root / "dist" / "ticketbox-backend"
    (dist / "_internal").mkdir(parents=True)
    (dist / "ticketbox-backend.exe").write_bytes(b"frozen-exe-v1")
    (dist / "ticketbox-c07-migrator.exe").write_bytes(b"c07-migrator-v1")
    (dist / "DATABASE_GENERATION_PROGRAM.json").write_text(
        '{"schema":"synthetic-generation-program"}', encoding="utf-8"
    )
    (dist / "_internal" / "runtime.dat").write_bytes(b"runtime-v1")
    packaged_target = dist / "_internal" / "migrations" / "versions" / target_migration
    packaged_target.parent.mkdir(parents=True)
    packaged_target.write_text("# target migration\n", encoding="utf-8")
    return dist


_INSTALLER_RECIPE_PATHS = (
    "scripts/windows_build_provenance.ps1",
    "scripts/windows_backend_build_provenance.ps1",
    "requirements-build.lock",
    "packaging/windows-build-toolchain.json",
    "packaging/prepare_windows_build_toolchain.ps1",
    "packaging/prepare_windows_installer_vendor.ps1",
    "packaging/build_pg_bundle.ps1",
    "packaging/build_inno_installer.ps1",
    "packaging/ticketbox-installer.iss",
    "packaging/ticketbox-installer-windows.isph",
    "packaging/ticketbox-installer-flow.isph",
    "packaging/languages/ChineseSimplified.isl",
    "packaging/ticketbox.ico",
    "packaging/windows-release-config.json",
    "packaging/windows_release_config.ps1",
    "packaging/prepare_bundled_upgrade.ps1",
    "packaging/windows_service_contract.ps1",
    "packaging/windows_service_identity.ps1",
    "packaging/windows_service_lifecycle.ps1",
    "packaging/windows_installation_safety.ps1",
    "packaging/windows_lifecycle_receipt.ps1",
    "packaging/windows_lifecycle_lock.ps1",
    "packaging/hold_installer_lifecycle_lock.ps1",
    "packaging/hold_data_root_mutation_guard.ps1",
    "packaging/install_windows_prerequisites.ps1",
    "packaging/windows_database_safety.ps1",
    "packaging/windows_pg_recovery_tools.ps1",
    "packaging/windows_postgresql_database_catalog.ps1",
    "packaging/postgresql_database_catalog/primitives.ps1",
    "packaging/postgresql_database_catalog/query.ps1",
    "packaging/postgresql_database_catalog/codec.ps1",
    "packaging/postgresql_database_catalog/observation.ps1",
    "packaging/windows_postgresql_exported_snapshot.ps1",
    "packaging/postgresql_exported_snapshot/primitives.ps1",
    "packaging/postgresql_exported_snapshot/session.ps1",
    "packaging/postgresql_exported_snapshot/deadline_evidence.ps1",
    "packaging/windows_postgresql_writer_fence.ps1",
    "packaging/postgresql_writer_fence/primitives.ps1",
    "packaging/postgresql_writer_fence/observation_query.ps1",
    "packaging/postgresql_writer_fence/observation_codec.ps1",
    "packaging/postgresql_writer_fence/observation.ps1",
    "packaging/postgresql_writer_fence/reconcile_policy.ps1",
    "packaging/postgresql_writer_fence/precondition_guard.ps1",
    "packaging/postgresql_writer_fence/session_drain.ps1",
    "packaging/postgresql_writer_fence/reconciler.ps1",
    "packaging/c07_lifecycle/writer_fence.ps1",
    "packaging/c07_lifecycle/writer_fence/policy.ps1",
    "packaging/c07_lifecycle/writer_fence/adapter.ps1",
    "packaging/windows_bundled_database.ps1",
    "packaging/windows_c07_database.ps1",
    "packaging/windows_security_primitives.ps1",
    "packaging/security_primitives/byte_array.ps1",
    "packaging/security_primitives/token_privilege_native.ps1",
    "packaging/security_primitives/token_privilege.ps1",
    "packaging/security_primitives/descriptor_comparison.ps1",
    "packaging/security_primitives/descriptor_diagnostic.ps1",
    "packaging/security_primitives/file_security.ps1",
    "packaging/windows_c07_superuser_recovery.ps1",
    "packaging/windows_deadline_budget.ps1",
    "packaging/windows_c07_deadline_policy.ps1",
    "packaging/windows_c07_heartbeat_authority.ps1",
    "packaging/windows_c07_lifecycle.ps1",
    "packaging/windows_c07_heartbeat_helper.ps1",
    "packaging/windows_c07_failure_summary.ps1",
    "packaging/windows_atomic_artifacts.ps1",
    "packaging/atomic_artifacts/native.ps1",
    "packaging/atomic_artifacts/file.ps1",
    "packaging/atomic_artifacts/directory.ps1",
    "packaging/windows_c07_recovery_generation.ps1",
    "packaging/windows_c07_packaged_migration.ps1",
    "packaging/windows_backend_bootstrap.ps1",
    "packaging/windows_bootstrap_exposure_recovery.ps1",
    "packaging/install_bundled_services.ps1",
    "packaging/uninstall_bundled_services.ps1",
)


def _write_minimal_installer_recipe(root: Path) -> None:
    for relative in _INSTALLER_RECIPE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"recipe:{relative}\n", encoding="utf-8")


def _c07_smoke_evidence_command(dist: Path) -> str:
    target_migration = dist / "_internal" / "migrations" / "versions" / "20260729_0001_money_minor_bigint_expand.py"
    program = dist / "DATABASE_GENERATION_PROGRAM.json"
    return (
        f"$smokePayload = Get-TicketboxBackendPayloadSnapshot '{_ps_literal(dist)}'; "
        f"$helper = Get-TicketboxFileEvidence '{_ps_literal(dist)}' "
        f"'{_ps_literal(dist / 'ticketbox-c07-migrator.exe')}'; "
        f"$moduleSha = Get-TicketboxFileSha256 '{_ps_literal(target_migration)}'; "
        f"$programSha = Get-TicketboxFileSha256 '{_ps_literal(program)}'; "
        "$revision = [ordered]@{"
        "revision='20260729_0001';down_revision='20260722_0001';"
        "module_sha256=$moduleSha;transactionality='postgresql_single_transaction';"
        "reversibility='forward_only';downgrade_guard='raises_runtime_error_before_ddl';"
        "resources=@('meta:test-contract');"
        "asset_recovery='same_generation_database_and_assets'}; "
        "$revisionManifest = [ordered]@{"
        "schema='ticketbox-c07-revision-manifest-v1';"
        "operation_kind='c07_money_minor_bigint_v1';"
        "source_revision='20260722_0001';target_revision='20260729_0001';"
        "revisions=@($revision)}; "
        "$manifestJson = $revisionManifest | ConvertTo-Json -Depth 32 -Compress; "
        "$result = [ordered]@{"
        "schema='ticketbox-database-generation-program-validation-v1';"
        "source_revision='base';target_revision='20260729_0001';revision_count=1;"
        "generation_program_sha256=$programSha;"
        "c07_source_revision='20260722_0001';c07_target_revision='20260729_0001';"
        "c07_revision_manifest=$revisionManifest;"
        "c07_revision_manifest_sha256=(Get-TicketboxSha256HexFromText $manifestJson)}; "
        "$resultJson = $result | ConvertTo-Json -Depth 32 -Compress; "
        "$smoke = [ordered]@{"
        "schema='ticketbox-database-generation-helper-smoke-v1';helper=$helper;"
        "payload_algorithm=$smokePayload.algorithm;"
        "payload_fingerprint=$smokePayload.fingerprint;"
        "payload_file_count=@($smokePayload.files).Count;"
        "argv=@('--validate-generation-program','--generation-program-path',"
        "'DATABASE_GENERATION_PROGRAM.json','--expected-generation-program-sha256',$programSha);"
        "stdin='closed_empty_eof';"
        "environment='system-runtime-allowlist-without-pg-or-database-url-v1';"
        "exit_code=0;stderr='empty';"
        "stdout_json_sha256=(Get-TicketboxSha256HexFromText $resultJson);"
        "result=$result}; "
    )


def _manifest_command(root: Path, dist: Path, operation: str) -> str:
    if operation == "Write-TicketboxBackendBuildManifest":
        toolchain = (
            f"$config = Read-TicketboxWindowsBuildToolchain '{_ps_literal(root)}'; "
            "$toolchain = New-TicketboxBackendBuildToolchainProvenance "
            f"-BackendRoot '{_ps_literal(root)}' -Config $config "
            f"-PythonPath '{_ps_literal(root / '.venv-build/Scripts/python.exe')}' "
            f"-PythonSourcePath '{_ps_literal(root / 'tools/python-source.exe')}' "
            "-PythonVersion '3.11.15' "
            f"-UvPath '{_ps_literal(root / 'tools/uv.exe')}' -UvVersion '0.11.7' "
            f"-PyInstallerPath '{_ps_literal(root / '.venv-build/Scripts/pyinstaller.exe')}' "
            "-PyInstallerVersion '6.21.0' "
            "-InstalledDistributions @('pyinstaller==6.21.0','sample==1.0.0') "
            f"-PythonExecutionTree (Get-TicketboxExecutionTreeEvidence "
            f"'{_ps_literal(root / '.venv-build/Scripts/python.exe')}' "
            f"@([pscustomobject]@{{label='environment';path='{_ps_literal(root / '.venv-build')}'}})); "
        )
        invocation = (
            f"$source = Get-TicketboxBackendSourceSnapshot '{_ps_literal(root)}'; "
            f"{_c07_smoke_evidence_command(dist)}"
            f"{operation} -BackendRoot '{_ps_literal(root)}' "
            f"-DistDir '{_ps_literal(dist)}' -ToolchainProvenance $toolchain "
            f"-SourceSnapshot $source -DatabaseGenerationProgramPath "
            f"'{_ps_literal(dist / 'DATABASE_GENERATION_PROGRAM.json')}' "
            "-C07MigrationHelperSmokeEvidence $smoke | Out-Null"
        )
    else:
        toolchain = ""
        invocation = f"{operation} '{_ps_literal(root)}' '{_ps_literal(dist)}' | Out-Null"
    return f". '{_ps_literal(PROVENANCE_HELPER)}'; {toolchain}{invocation}"


def test_backend_manifest_rejects_source_and_executable_mutation(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    dist = _write_minimal_backend(backend)
    write = _run_powershell(_manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest"))
    assert write.returncode == 0, write.stderr

    manifest_path = dist / "BUILD_PROVENANCE.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 4
    assert manifest["artifact_type"] == "ticketbox-frozen-backend"
    assert manifest["backend_version"] == "7.8.9"
    assert len(manifest["source"]["fingerprint"]) == 64
    assert len(manifest["payload"]["fingerprint"]) == 64
    source_paths = {record["path"] for record in manifest["source"]["files"]}
    assert "scripts/build_database_generation_program.py" in source_paths
    assert "scripts/build_backend_exe.ps1" in source_paths
    assert "scripts/windows_build_provenance.ps1" in source_paths
    assert "scripts/windows_backend_build_provenance.ps1" in source_paths
    assert "packaging/windows-build-toolchain.json" in source_paths
    assert "packaging/prepare_windows_build_toolchain.ps1" in source_paths
    assert "requirements-build.lock" in source_paths
    assert manifest["toolchain"]["python"]["version"] == "3.11.15"
    assert manifest["toolchain"]["uv"]["version"] == "0.11.7"
    assert manifest["toolchain"]["pyinstaller"]["version"] == "6.21.0"
    assert manifest["payload"]["executable"]["sha256"] == hashlib.sha256(b"frozen-exe-v1").hexdigest()
    smoke = manifest["payload"]["c07_migration_helper_smoke"]
    assert smoke["helper"] == manifest["payload"]["c07_migration_helper"]
    assert smoke["payload_algorithm"] == manifest["payload"]["algorithm"]
    assert smoke["payload_fingerprint"] == manifest["payload"]["fingerprint"]
    assert smoke["payload_file_count"] == len(manifest["payload"]["files"])
    assert smoke["stdin"] == "closed_empty_eof"
    assert smoke["environment"] == ("system-runtime-allowlist-without-pg-or-database-url-v1")
    assert smoke["exit_code"] == 0
    assert smoke["stderr"] == "empty"
    assert smoke["result"]["source_revision"] == "base"
    assert smoke["result"]["target_revision"] == "20260729_0001"
    assert smoke["result"]["generation_program_sha256"] == manifest["payload"][
        "database_generation_program"
    ]["sha256"]

    validate = _manifest_command(backend, dist, "Assert-TicketboxBackendBuildManifest")
    assert _run_powershell(validate).returncode == 0

    manifest["payload"]["c07_migration_helper_smoke"]["result"]["source_revision"] = "other"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_helper_smoke = _run_powershell(validate)
    assert tampered_helper_smoke.returncode != 0
    assert "generation helper" in (
        tampered_helper_smoke.stdout + tampered_helper_smoke.stderr
    ).lower()
    rewrite = _run_powershell(_manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest"))
    assert rewrite.returncode == 0, rewrite.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["toolchain"]["pyinstaller"]["version"] = "6.20.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_toolchain = _run_powershell(validate)
    assert tampered_toolchain.returncode != 0
    assert "toolchain" in (tampered_toolchain.stdout + tampered_toolchain.stderr).lower()
    rewrite = _run_powershell(_manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest"))
    assert rewrite.returncode == 0, rewrite.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["source"]["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_source_record = _run_powershell(validate)
    assert tampered_source_record.returncode != 0
    assert "source" in (tampered_source_record.stdout + tampered_source_record.stderr).lower()
    rewrite = _run_powershell(_manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest"))
    assert rewrite.returncode == 0, rewrite.stderr

    (backend / "app" / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    stale_source = _run_powershell(validate)
    assert stale_source.returncode != 0
    assert "rebuild" in (stale_source.stdout + stale_source.stderr).lower()

    rewrite = _run_powershell(_manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest"))
    assert rewrite.returncode == 0, rewrite.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runtime_record = next(
        record for record in manifest["payload"]["files"] if record["path"] == "_internal/runtime.dat"
    )
    runtime_record["sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_non_exe_record = _run_powershell(validate)
    assert tampered_non_exe_record.returncode != 0
    assert "payload" in (tampered_non_exe_record.stdout + tampered_non_exe_record.stderr).lower()

    rewrite = _run_powershell(_manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest"))
    assert rewrite.returncode == 0, rewrite.stderr
    (dist / "ticketbox-backend.exe").write_bytes(b"frozen-exe-v2")
    stale_exe = _run_powershell(validate)
    assert stale_exe.returncode != 0

    assert "payload" in (stale_exe.stdout + stale_exe.stderr).lower()

    recipe_backend = tmp_path / "recipe-backend"
    _write_minimal_installer_recipe(recipe_backend)
    snapshot_path = tmp_path / "recipe.json"
    snapshot_command = (
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"Get-TicketboxInstallerRecipeSnapshot '{_ps_literal(recipe_backend)}' | "
        "ConvertTo-Json -Depth 8"
    )
    original = _run_powershell(snapshot_command)
    assert original.returncode == 0, original.stderr
    original_snapshot = json.loads(original.stdout)
    assert {record["path"] for record in original_snapshot["files"]} == set(_INSTALLER_RECIPE_PATHS)
    snapshot_path.write_text(json.dumps(original_snapshot), encoding="utf-8")

    changed_recipe = recipe_backend / "packaging" / "ticketbox-installer-flow.isph"
    changed_recipe.write_text("recipe mutation\n", encoding="utf-8")
    changed = _run_powershell(snapshot_command)
    assert changed.returncode == 0, changed.stderr
    assert json.loads(changed.stdout)["fingerprint"] != original_snapshot["fingerprint"]

    validate = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"$recorded = Get-Content -Raw -Encoding UTF8 '{_ps_literal(snapshot_path)}' | "
        "ConvertFrom-Json; "
        f"$actual = Get-TicketboxInstallerRecipeSnapshot '{_ps_literal(recipe_backend)}'; "
        "Assert-TicketboxFileSetSnapshot 'installer recipe' $recorded $actual"
    )
    assert validate.returncode != 0


def test_installed_c07_external_assets_are_manifest_bound_and_held(
    tmp_path: Path,
) -> None:
    safety = PACKAGING / "windows_installation_safety.ps1"
    for index, engine in enumerate(powershell_contract_engines()):
        install_dir = tmp_path / f"installed-authority-{index}"
        payload = install_dir / "program" / "ticketbox-backend"
        for relative, content in {
            "ticketbox-backend.exe": b"backend-exe",
            "ticketbox-c07-migrator.exe": b"migration-helper",
            "DATABASE_GENERATION_PROGRAM.json": b'{"schema":"synthetic-generation-program"}',
            "_internal/app/database/_c07_fresh_source_bootstrap.py": b"fresh",
            "_internal/app/database/_c07_maintenance_upgrade.py": b"maintenance",
            "_internal/app/database/_c07_production_migration.py": b"production",
            "_internal/app/database/_managed_schema_upgrade.py": b"managed-schema",
            "_internal/alembic.ini": b"[alembic]",
            "_internal/runtime.dat": b"runtime",
            "_internal/replacement.dat": b"replacement",
            "_internal/tzdata/zoneinfo/America/Indianapolis": b"tz-file",
            "_internal/tzdata/zoneinfo/America/Indiana/Indianapolis": b"tz-tree",
            "_internal/migrations/env.py": b"# env",
            ("_internal/migrations/versions/20260722_0001_bind_repayment_draft_idem_to_account.py"): b"# source",
            ("_internal/migrations/versions/20260729_0001_money_minor_bigint_expand.py"): b"# target",
            ("_internal/migrations/versions/20260802_0001_currency_binding_authority.py"): b"# c02 target",
            ("_internal/migrations/versions/20260809_0001_add_installation_owner_claim.py"): b"# release head",
        }.items():
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (install_dir / "installer").mkdir(parents=True)
        primary = install_dir / "installer" / "BUILD_PROVENANCE.json"
        secondary = payload / "BUILD_PROVENANCE.json"
        existing = payload / "_internal" / "migrations" / "env.py"
        runtime = payload / "_internal" / "runtime.dat"
        replacement = payload / "_internal" / "replacement.dat"
        extra = payload / "_internal" / "migrations" / "versions" / "extra.py"
        required_target = (
            payload / "_internal" / "migrations" / "versions" / "20260729_0001_money_minor_bigint_expand.py"
        )
        renamed_target = required_target.with_name("renamed-target.py")
        versions_dir = required_target.parent
        moved_versions = versions_dir.with_name("versions-moved")
        replace_backup = install_dir / "installer" / "replace-backup.dat"
        command = rf"""
. '{_ps_literal(safety)}'
. '{_ps_literal(PROVENANCE_HELPER)}'
$payload = '{_ps_literal(payload)}'
$primaryPath = '{_ps_literal(primary)}'
$secondaryPath = '{_ps_literal(secondary)}'
$installDir = '{_ps_literal(install_dir)}'
$existing = '{_ps_literal(existing)}'
$runtime = '{_ps_literal(runtime)}'
$replacement = '{_ps_literal(replacement)}'
$extra = '{_ps_literal(extra)}'
$requiredTarget = '{_ps_literal(required_target)}'
$renamedTarget = '{_ps_literal(renamed_target)}'
$versionsDir = '{_ps_literal(versions_dir)}'
$movedVersions = '{_ps_literal(moved_versions)}'
$replaceBackup = '{_ps_literal(replace_backup)}'
function Write-TestManifest {{
    $paths = @(
        Get-ChildItem -LiteralPath $payload -Recurse -File |
            Where-Object {{ $_.FullName -cne $secondaryPath }} |
            ForEach-Object {{ $_.FullName }}
    )
    $snapshot = Get-TicketboxFileSetSnapshot $payload $paths
    $helper = Get-TicketboxC07MigrationHelperEvidenceFromPayload $snapshot
    $program = Get-TicketboxFileEvidence `
        $payload `
        (Join-Path $payload 'DATABASE_GENERATION_PROGRAM.json')
    {_c07_smoke_evidence_command(payload)}
    $secondary = [ordered]@{{
        schema_version = 4
        artifact_type = 'ticketbox-frozen-backend'
        backend_version = '7.8.9'
        payload = [ordered]@{{
            algorithm = $snapshot.algorithm
            fingerprint = $snapshot.fingerprint
            files = @($snapshot.files)
            executable = Get-TicketboxFileEvidence $payload (Join-Path $payload 'ticketbox-backend.exe')
            database_generation_program = $program
            c07_migration_helper = $helper
            c07_migration_helper_smoke = $smoke
        }}
    }}
    Write-TicketboxJsonFile $secondaryPath $secondary
    $primary = [ordered]@{{
        schema_version = 3
        artifact_type = 'ticketbox-windows-installer-inputs'
        build_mode = 'installer-build'
        compiler_defines = @('/DTargetPgMajor=17')
        backend = [ordered]@{{
            version = '7.8.9'
            payload_algorithm = $snapshot.algorithm
            payload_fingerprint = $snapshot.fingerprint
            executable = $secondary.payload.executable
            database_generation_program = $program
            c07_migration_helper = $helper
            c07_migration_helper_smoke = $smoke
            manifest = [ordered]@{{
                path = 'dist/ticketbox-backend/BUILD_PROVENANCE.json'
                size = [int64](Get-Item -LiteralPath $secondaryPath).Length
                sha256 = Get-TicketboxFileSha256 $secondaryPath
            }}
        }}
        postgresql = [ordered]@{{ major = 17 }}
    }}
    Write-TicketboxJsonFile $primaryPath $primary
}}
Write-TestManifest
$lease = Enter-TicketboxInstalledC07PayloadAuthorityLease `
    -InstallDir $installDir `
    -InstallerManifestPath $primaryPath `
    -ExpectedPgMajor 17
try {{
    $existingBlocked = $false
    try {{ [System.IO.File]::WriteAllText($existing, 'tampered') }}
    catch {{ $existingBlocked = $true }}
    $appendBlocked = $false
    try {{
        $appendStream = [System.IO.File]::Open(
            $existing,
            [System.IO.FileMode]::Append,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $appendStream.Dispose()
    }}
    catch {{ $appendBlocked = $true }}
    $deleteBlocked = $false
    try {{ [System.IO.File]::Delete($runtime) }}
    catch {{ $deleteBlocked = $true }}
    if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {{
        $deleteBlocked = $false
    }}
    $renameBlocked = $false
    try {{ [System.IO.File]::Move($requiredTarget, $renamedTarget) }}
    catch {{ $renameBlocked = $true }}
    $replaceBlocked = $false
    try {{ [System.IO.File]::Replace($replacement, $existing, $replaceBackup) }}
    catch {{ $replaceBlocked = $true }}
    $parentRenameBlocked = $false
    try {{ [System.IO.Directory]::Move($versionsDir, $movedVersions) }}
    catch {{ $parentRenameBlocked = $true }}
    $additionBlocked = $false
    try {{ [System.IO.File]::WriteAllText($extra, 'extra') }}
    catch {{ $additionBlocked = $true }}
    if (
        -not $existingBlocked -or
        -not $appendBlocked -or
        -not $deleteBlocked -or
        -not $renameBlocked -or
        -not $replaceBlocked -or
        -not $parentRenameBlocked -or
        -not $additionBlocked
    ) {{
        throw (
            'payload lease did not block write/append/delete/rename/' +
            'replace/parent-rename/addition'
        )
    }}
}}
finally {{
    Close-TicketboxInstalledC07PayloadAuthorityLease $lease
}}
[System.IO.File]::WriteAllText($existing, '# restored after lease')
[System.IO.File]::AppendAllText($existing, '# append after lease')
[System.IO.File]::Move($requiredTarget, $renamedTarget)
[System.IO.File]::Move($renamedTarget, $requiredTarget)
[System.IO.Directory]::Move($versionsDir, $movedVersions)
[System.IO.Directory]::Move($movedVersions, $versionsDir)
[System.IO.File]::Delete($runtime)
if (Test-Path -LiteralPath $runtime) {{ throw 'payload delete remained blocked after lease' }}
[System.IO.File]::WriteAllText($runtime, 'runtime restored after lease')
[System.IO.File]::Replace($replacement, $existing, $replaceBackup)
if (Test-Path -LiteralPath $replacement) {{
    throw 'payload replace remained blocked after lease'
}}
if (-not (Test-Path -LiteralPath $replaceBackup -PathType Leaf)) {{
    throw 'payload replace backup was not created after lease'
}}
[System.IO.File]::Delete($replaceBackup)
[System.IO.File]::WriteAllText($existing, '# restored after replace')
[System.IO.File]::WriteAllText($replacement, 'replacement restored after lease')
[System.IO.File]::WriteAllText($extra, '# unsealed addition')
[System.IO.File]::Delete($extra)
Write-TestManifest
[System.IO.File]::WriteAllText($extra, '# not in secondary manifest')
$unrecordedRejected = $false
try {{
    [void](Enter-TicketboxInstalledC07PayloadAuthorityLease `
        -InstallDir $installDir `
        -InstallerManifestPath $primaryPath `
        -ExpectedPgMajor 17)
}}
catch {{ $unrecordedRejected = $true }}
if (-not $unrecordedRejected) {{ throw 'unrecorded migration asset was accepted' }}
[System.IO.File]::Delete($extra)
[System.IO.File]::Delete($requiredTarget)
Write-TestManifest
$criticalRejected = $false
try {{
    [void](Enter-TicketboxInstalledC07PayloadAuthorityLease `
        -InstallDir $installDir `
        -InstallerManifestPath $primaryPath `
        -ExpectedPgMajor 17)
}}
catch {{ $criticalRejected = $true }}
if (-not $criticalRejected) {{ throw 'missing target migration authority was accepted' }}
"""
        result = _run_powershell(command, executable=engine)
        assert result.returncode == 0, result.stdout + result.stderr


def test_backend_payload_snapshot_round_trips_canonical_manifest_order(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        payload_root = tmp_path / f"canonical-payload-{index}"
        command = rf"""
. '{_ps_literal(PROVENANCE_HELPER)}'
$root = '{_ps_literal(payload_root)}'
$relativePaths = [string[]]@(
    @($script:TicketboxInstalledC07ExternalAuthorityPaths) +
    @(
        '_internal/tzdata/zoneinfo/America/Indianapolis',
        '_internal/tzdata/zoneinfo/America/Indiana/Indianapolis',
        'case/a-lower.bin',
        'case/B-upper.bin',
        'i18n/eclair.bin',
        'i18n/omega.bin'
    )
)
$fullPaths = [string[]]@($relativePaths | ForEach-Object {{
    $path = Join-Path $root $_.Replace('/', '\')
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
    [IO.File]::WriteAllText($path, $_, [Text.UTF8Encoding]::new($false))
    $path
}})
$snapshot = Get-TicketboxFileSetSnapshot $root $fullPaths
$america = @($snapshot.files.path | Where-Object {{ $_ -like '*America/*' }})
if (
    ($america -join '|') -cne
    '_internal/tzdata/zoneinfo/America/Indiana/Indianapolis|_internal/tzdata/zoneinfo/America/Indianapolis'
) {{
    throw "Canonical manifest OrdinalIgnoreCase path order drifted: $($america -join '|')"
}}
$roundTrip = $snapshot | ConvertTo-Json -Depth 8 -Compress | ConvertFrom-Json
[void](ConvertTo-TicketboxInstalledPayloadRecords $roundTrip)
$reversed = [string[]]@($fullPaths)
[Array]::Reverse($reversed)
$repeated = Get-TicketboxFileSetSnapshot $root $reversed
Assert-TicketboxFileSetSnapshot 'canonical payload order' $snapshot $repeated

$oldFullPathOrder = Get-TicketboxOrdinalSortedPaths $fullPaths
$oldRecords = @($oldFullPathOrder | ForEach-Object {{
    Get-TicketboxFileEvidence $root $_
}})
$oldPayload = [pscustomobject][ordered]@{{
    algorithm = 'SHA-256'
    fingerprint = ('f' * 64 -join '')
    files = @($oldRecords)
}}
$oldRoundTrip = $oldPayload | ConvertTo-Json -Depth 8 -Compress | ConvertFrom-Json
$legacyOrderRejected = $false
try {{ [void](ConvertTo-TicketboxInstalledPayloadRecords $oldRoundTrip) }}
catch {{ $legacyOrderRejected = $_.Exception.Message -like '*排序*' }}
if (-not $legacyOrderRejected) {{
    throw 'Legacy full-path ordering unexpectedly satisfied canonical manifest order.'
}}

$script:SyntheticEvidenceIndex = 0
function Get-TicketboxFileEvidence([string]$Root, [string]$Path) {{
    $script:SyntheticEvidenceIndex += 1
    $syntheticPath = if ($script:SyntheticEvidenceIndex -eq 1) {{
        'case/A.bin'
    }} else {{
        'case/a.bin'
    }}
    return [ordered]@{{
        path = $syntheticPath
        size = [int64]1
        sha256 = ('a' * 64 -join '')
    }}
}}
$duplicateRejected = $false
try {{
    [void](Get-TicketboxFileSetSnapshot $root @('synthetic-one', 'synthetic-two'))
}}
catch {{ $duplicateRejected = $_.Exception.Message -like '*重复相对路径*' }}
if (-not $duplicateRejected) {{
    throw 'Comparer-equal duplicate manifest path was accepted.'
}}

$script:SyntheticEvidenceIndex = 0
function Get-TicketboxFileEvidence([string]$Root, [string]$Path) {{
    return [ordered]@{{
        path = 'case/k' + [char]0x212a + '.bin'
        size = [int64]1
        sha256 = ('b' * 64 -join '')
    }}
}}
$unicodeProducerRejected = $false
try {{ [void](Get-TicketboxFileSetSnapshot $root @('synthetic-unicode')) }}
catch {{ $unicodeProducerRejected = $_.Exception.Message -like '*可打印 ASCII*' }}
if (-not $unicodeProducerRejected) {{
    throw 'Runtime-sensitive Unicode producer path was accepted.'
}}
$unicodePayload = [pscustomobject][ordered]@{{
    algorithm = 'SHA-256'
    fingerprint = ('c' * 64 -join '')
    files = @([pscustomobject][ordered]@{{
        path = 'case/k' + [char]0x212a + '.bin'
        size = 1
        sha256 = ('b' * 64 -join '')
    }})
}}
$unicodeConsumerRejected = $false
try {{ [void](ConvertTo-TicketboxInstalledPayloadRecords $unicodePayload) }}
catch {{ $unicodeConsumerRejected = $_.Exception.Message -like '*canonical 相对路径*' }}
if (-not $unicodeConsumerRejected) {{
    throw 'Runtime-sensitive Unicode consumer path was accepted.'
}}
"""
        result = _run_powershell(command, executable=engine)
        assert result.returncode == 0, result.stdout + result.stderr


def test_installed_c07_payload_lease_close_preserves_dual_failures() -> None:
    for engine in powershell_contract_engines():
        command = rf"""
. '{_ps_literal(PROVENANCE_HELPER)}'
function Restore-TicketboxInstalledPayloadMutationDeny {{
    throw 'injected payload DACL restore crash'
}}
$lease = [pscustomobject]@{{
    Streams = @()
    StreamEvidence = @([pscustomobject]@{{ Path = 'missing-stream' }})
    Guard = [pscustomobject]@{{ Root = 'injected' }}
}}
$caught = $null
try {{ Close-TicketboxInstalledC07PayloadAuthorityLease $lease }}
catch {{ $caught = $_.Exception }}
if (
    $null -eq $caught -or
    $caught -isnot [AggregateException] -or
    $caught.InnerExceptions.Count -ne 2 -or
    $caught.InnerExceptions[0].Message -notlike '*evidence 数量漂移*' -or
    $caught.InnerExceptions[1].Message -cne
        'injected payload DACL restore crash' -or
    [string]$caught.Data['TicketboxC07FailureCode'] -cne
        'installed_payload_lease_close_failed'
) {{
    $innerMessages = @(
        $caught.InnerExceptions | ForEach-Object {{ $_.Message }}
    )
    throw (
        'payload lease dual failure was not preserved: ' +
        "type=$($caught.GetType().FullName) " +
        "count=$(@($caught.InnerExceptions).Count) " +
        "messages=$($innerMessages -join ' | ') " +
        "code=$($caught.Data['TicketboxC07FailureCode'])"
    )
}}
"""
        result = _run_powershell(command, executable=engine)
        assert result.returncode == 0, result.stdout + result.stderr


def test_interrupted_payload_mutation_deny_is_exactly_recoverable(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "install"
    payload_root = install_root / "program" / "ticketbox-backend"
    child = payload_root / "child"
    child.mkdir(parents=True)
    (child / "payload.bin").write_bytes(b"trusted-payload")

    for engine in powershell_contract_engines():
        command = rf"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(INSTALLATION_SAFETY)}'
. '{_ps_literal(PROVENANCE_HELPER)}'
$installRoot = '{_ps_literal(install_root)}'
$payloadRoot = '{_ps_literal(payload_root)}'
$identitySid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
Set-TicketboxExactDirectoryAcl `
    -Path $installRoot `
    -Accounts @($identitySid) `
    -OwnerAccount $identitySid `
    -Recurse

# This is the exact in-memory lease guard left durable when the installer
# process is killed before its finally block can restore OriginalAcl.
$guard = Add-TicketboxInstalledPayloadMutationDeny $payloadRoot
try {{
    $recovered = Remove-TicketboxInterruptedInstalledPayloadMutationDenyExact `
        -PayloadRoot $payloadRoot `
        -FullControlAccounts @($identitySid) `
        -OwnerAccount $identitySid
    if (-not $recovered) {{ throw 'exact stale mutation deny was not recovered' }}
    foreach ($entry in Get-TicketboxInstalledPayloadEntries $payloadRoot) {{
        $denyRules = @((Get-TicketboxInstalledPayloadAcl `
            $entry.FullName).GetAccessRules(
                $true,
                $true,
                [Security.Principal.SecurityIdentifier]
            ) | Where-Object {{
                $_.AccessControlType -eq
                    [Security.AccessControl.AccessControlType]::Deny
            }})
        if ($denyRules.Count -ne 0) {{
            throw "stale mutation deny remained on $($entry.FullName)"
        }}
    }}
}}
finally {{ Restore-TicketboxInstalledPayloadMutationDeny $guard }}

# A post-write verification failure must restore the exact durable deny before
# the operation error escapes, so a retry never observes a half-repaired ACL.
$guard = Add-TicketboxInstalledPayloadMutationDeny $payloadRoot
$script:originalStructuredEvidence =
    ${{function:Assert-TicketboxStructuredEvidence}}
function Assert-TicketboxStructuredEvidence {{
    param($Label, $Recorded, $Expected)
    if ($Label -ceq '中断 payload mutation deny 精确退役') {{
        throw 'injected post-write verification failure'
    }}
    & $script:originalStructuredEvidence $Label $Recorded $Expected
}}
$verificationRejected = $false
try {{
    try {{
        Remove-TicketboxInterruptedInstalledPayloadMutationDenyExact `
            -PayloadRoot $payloadRoot `
            -FullControlAccounts @($identitySid) `
            -OwnerAccount $identitySid | Out-Null
    }}
    catch {{
        $verificationRejected =
            $_.Exception.Message -ceq 'injected post-write verification failure'
    }}
    if (-not $verificationRejected) {{
        throw 'post-write verification failure was not preserved'
    }}
    $restoredDeny = @((Get-TicketboxInstalledPayloadAcl `
        $payloadRoot).GetAccessRules(
            $true,
            $true,
            [Security.Principal.SecurityIdentifier]
        ) | Where-Object {{
            $_.IdentityReference.Value -ceq 'S-1-1-0' -and
            $_.AccessControlType -eq
                [Security.AccessControl.AccessControlType]::Deny
        }})
    if ($restoredDeny.Count -ne 1) {{
        throw 'post-write verification failure did not restore exact deny'
    }}
}}
finally {{
    Set-Item `
        -LiteralPath Function:Assert-TicketboxStructuredEvidence `
        -Value $script:originalStructuredEvidence
    Restore-TicketboxInstalledPayloadMutationDeny $guard
}}

# A foreign/additional deny must not be normalized under cover of retry.
$guard = Add-TicketboxInstalledPayloadMutationDeny $payloadRoot
try {{
    $acl = Get-TicketboxInstalledPayloadAcl $payloadRoot
    $everyone = New-Object Security.Principal.SecurityIdentifier('S-1-1-0')
    $foreignRule = New-Object Security.AccessControl.FileSystemAccessRule(
        $everyone,
        [Security.AccessControl.FileSystemRights]::Read,
        [Security.AccessControl.AccessControlType]::Deny
    )
    [void]$acl.AddAccessRule($foreignRule)
    Set-TicketboxInstalledPayloadAcl $payloadRoot $acl
    $foreignRejected = $false
    try {{
        Remove-TicketboxInterruptedInstalledPayloadMutationDenyExact `
            -PayloadRoot $payloadRoot `
            -FullControlAccounts @($identitySid) `
            -OwnerAccount $identitySid | Out-Null
    }}
    catch {{ $foreignRejected = $true }}
    if (-not $foreignRejected) {{
        throw 'additional deny was accepted as the installer mutation lease'
    }}
    $remainingExact = @((Get-TicketboxInstalledPayloadAcl `
        $payloadRoot).GetAccessRules(
            $true,
            $true,
            [Security.Principal.SecurityIdentifier]
        ) | Where-Object {{
            $_.IdentityReference.Translate(
                [Security.Principal.SecurityIdentifier]
            ).Value -ceq 'S-1-1-0' -and
            $_.AccessControlType -eq
                [Security.AccessControl.AccessControlType]::Deny
        }})
    if ($remainingExact.Count -lt 2) {{
        throw 'failed closed recovery partially rewrote the drifted DACL'
    }}
}}
finally {{ Restore-TicketboxInstalledPayloadMutationDeny $guard }}
$finalDeny = @((Get-TicketboxInstalledPayloadAcl `
    $payloadRoot).GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ) | Where-Object {{
        $_.AccessControlType -eq
            [Security.AccessControl.AccessControlType]::Deny
    }})
if ($finalDeny.Count -ne 0) {{
    throw 'test fixture did not restore its original payload ACL'
}}
'OK'
"""
        result = _run_powershell(command, executable=engine)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip().splitlines()[-1] == "OK"


def test_installer_build_probes_and_records_local_vendor_provenance(
    tmp_path: Path,
) -> None:
    build = (PACKAGING / "build_inno_installer.ps1").read_text(encoding="utf-8-sig")
    installer = (PACKAGING / "ticketbox-installer.iss").read_text(encoding="utf-8")
    backend_spec = (PACKAGING / "ticketbox-backend.spec").read_text(encoding="utf-8")
    backend_build = (ROOT / "scripts" / "build_backend_exe.ps1").read_text(encoding="utf-8-sig")
    backend_provenance = (ROOT / "scripts" / "windows_backend_build_provenance.ps1").read_text(encoding="utf-8-sig")
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    toolchain_preparer = (PACKAGING / "prepare_windows_build_toolchain.ps1").read_text(encoding="utf-8-sig")
    vendor_preparer = (PACKAGING / "prepare_windows_installer_vendor.ps1").read_text(encoding="utf-8-sig")
    pg_bundler = (PACKAGING / "build_pg_bundle.ps1").read_text(encoding="utf-8-sig")
    toolchain = json.loads((PACKAGING / "windows-build-toolchain.json").read_text(encoding="utf-8"))
    postgres_source = toolchain["installer_vendor_sources"]["postgresql"]
    shawl_source = toolchain["installer_vendor_sources"]["shawl"]
    build_tool_sources = toolchain["build_tool_sources"]

    assert "$backendManifest = Assert-TicketboxBackendBuildManifest" in build
    assert "Remove-TicketboxPublishDirectoryVerified $targetPublishDir $publishRoot" not in build
    assert build.index("$InstallerBuildManifest") < build.index(
        "$backendManifest = Assert-TicketboxBackendBuildManifest"
    )
    assert 'Invoke-TicketboxExecutableProbe $postgresExe @("--version")' in build
    assert 'Invoke-TicketboxExecutableProbe $ExecutablePath @("--version")' in build
    assert 'Invoke-TicketboxExecutableProbe $ExecutablePath @("--help")' in build
    assert 'Assert-TicketboxVendorVersionAllowed $releaseConfig "postgres" $version' in build
    assert 'Assert-TicketboxVendorVersionAllowed $releaseConfig "shawl" $version' in build
    assert 'foreach ($directory in @("bin", "lib", "share"))' in build
    assert "Read-TicketboxPgBundleManifest $bundleManifestPath" in build
    assert "PostgreSQL bundle manifest 与 Windows 工具链 archive/payload pin 不一致" in build
    assert "archive_payload_fingerprint" in build
    assert postgres_source["payload_file_count"] > 0
    assert len(postgres_source["payload_fingerprint"]) == 64
    assert len(shawl_source["executable_sha256"]) == 64
    assert build_tool_sources["uv"]["version"] == toolchain["uv_version"]
    assert build_tool_sources["python"]["version"] == toolchain["python_version"]
    for source_name in ("uv", "python", "inno_setup"):
        source = build_tool_sources[source_name]
        assert source["url"].startswith("https://")
        assert len(source["sha256"]) == 64
    assert len(build_tool_sources["uv"]["executable_sha256"]) == 64
    assert len(build_tool_sources["python"]["executable_sha256"]) == 64
    assert len(build_tool_sources["python"]["runtime_sha256"]) == 64
    assert len(build_tool_sources["inno_setup"]["compiler_sha256"]) == 64
    assert "payload_fingerprint = $PostgresProvenance.bundle_snapshot.fingerprint" in build
    assert '"/DTargetPgMajor=$($postgresProvenance.major)"' in build
    assert '"/DLifecycleSafetyScriptSha256=$(Get-TicketboxFileSha256 $SafetyScript)"' in build
    assert (
        '"/DWindowsSecurityPrimitivesScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityPrimitivesScript)"' in build
    )
    assert (
        '"/DWindowsSecurityByteArrayScriptSha256=$(Get-TicketboxFileSha256 $WindowsSecurityByteArrayScript)"' in build
    )
    assert (
        '"/DWindowsSecurityTokenPrivilegeNativeScriptSha256='
        '$(Get-TicketboxFileSha256 $WindowsSecurityTokenPrivilegeNativeScript)"' in build
    )
    assert (
        '"/DWindowsSecurityTokenPrivilegeScriptSha256='
        '$(Get-TicketboxFileSha256 $WindowsSecurityTokenPrivilegeScript)"' in build
    )
    assert (
        '"/DWindowsSecurityDescriptorComparisonScriptSha256='
        '$(Get-TicketboxFileSha256 $WindowsSecurityDescriptorComparisonScript)"' in build
    )
    assert (
        '"/DWindowsSecurityDescriptorDiagnosticScriptSha256='
        '$(Get-TicketboxFileSha256 $WindowsSecurityDescriptorDiagnosticScript)"' in build
    )
    assert (
        '"/DWindowsSecurityFileSecurityScriptSha256='
        '$(Get-TicketboxFileSha256 $WindowsSecurityFileSecurityScript)"' in build
    )
    assert '"/DLifecycleLockScriptSha256=$(Get-TicketboxFileSha256 $LockScript)"' in build
    assert '"/DLifecycleHolderScriptSha256=$(Get-TicketboxFileSha256 $LockHolderScript)"' in build
    assert "upstream_authenticity_verified = $false" in build
    assert 'verification_scope = "build-time-local-payload-integrity-only"' in build
    assert "Get-TicketboxInstallerRecipeSnapshot" in build
    assert "Get-TicketboxGitProvenance $BackendRoot" in build
    assert "Get-TicketboxIsccProvenance $iscc" in build
    assert "Assert-TicketboxInstallerBuildProvenance" in build
    assert 'Assert-TicketboxStructuredEvidence `\n        "安装器 backend provenance"' in (
        PROVENANCE_HELPER.read_text(encoding="utf-8-sig")
    )
    assert "status_fingerprint = $GitProvenance.status_fingerprint" in build
    assert "executable = $CompilerProvenance.executable" in build
    assert "engine_version = $CompilerProvenance.engine_version" in build
    assert "Get-TicketboxIsccEngineVersion" in PROVENANCE_HELPER.read_text(encoding="utf-8-sig")
    assert "compiler_defines = @(Get-TicketboxNormalizedCompilerDefines $CompilerDefines)" in build
    assert "toolchain = $BackendManifest.toolchain" in build
    assert build.index("if ($CheckInputsOnly)") < build.index("$installerBuild = Write-InstallerBuildProvenance")
    assert build.index("Get-TicketboxIsccProvenance $iscc") < build.index(
        '& $iscc @defines "/O$compilerOutputDir" $stagedIssPath'
    )
    assert 'Assert-File $stagedInstaller "本轮 ISCC staging 安装包输出"' in build
    assert "OutputManifestFile=ticketbox-installer-content.tsv" in installer
    assert "function Assert-TicketboxInstallerCompilerContentManifest" in build
    assert '"Index", "SourceFilename", "TimeStamp", "Version"' in build
    assert "PreprocessingIndex" not in build
    assert "ISCC must compile the database generation program exactly once" in build
    assert "Get-TicketboxFileSha256 $expectedPath" in build
    assert build.index('& $iscc @defines "/O$compilerOutputDir" $stagedIssPath') < build.index(
        "Assert-TicketboxInstallerCompilerContentManifest `"
    )
    assert build.index("& $iscc @defines") < build.index(
        "$currentBackendManifest = Assert-TicketboxBackendBuildManifest"
    )
    assert build.index("& $iscc @defines") < build.index("$currentPostgresProvenance = Get-ValidatedPostgresProvenance")
    assert "$currentShawlProvenance = Get-ValidatedShawlProvenance" in build
    assert "Get-TicketboxFileSha256 $stagedInstaller" in build
    assert "BUILD_COMPLETE.json" in build
    assert "function Assert-TicketboxInstallerPublishUnit" in build
    assert "[switch]$VerifyOnly" in build
    assert "[string]$VerifyPublishDirectory" in build
    assert "[string]$InstallerHashOutputFile" in build
    assert "VerifyOnly 必须提供由本轮编译步骤外部保存的 ExpectedInstallerSha256" in build
    assert build.index("Write-TicketboxInstallerHashOutput `") < build.index(
        "Exit-TicketboxWindowsBuildLock $BuildLock"
    )
    assert build.count("Assert-TicketboxInstallerPublishUnit `") >= 3
    assert build.index("Write-TicketboxJsonFile $publishCompletion") < build.index(
        "Publish-TicketboxInstallerUnit `", build.index("Write-TicketboxJsonFile $publishCompletion")
    )
    assert "Remove-TicketboxPublishFilesVerified" in build
    for excluded_database_driver in ('"sqlite3"', '"_sqlite3"', '"pysqlite2"', '"MySQLdb"'):
        assert excluded_database_driver in backend_spec
    for standalone_module in (
        "app.database._c07_fresh_source_bootstrap",
        "app.database._c07_production_migration",
        "app.database._managed_schema_upgrade",
        "_c07_fresh_source_bootstrap.py",
        "_c07_production_migration.py",
        "_managed_schema_upgrade.py",
    ):
        assert f'"{standalone_module}"' in backend_spec
    for standalone_dependency in (
        "app.app_meta_observation",
        "app.canonical_money_facts",
        "app.canonical_money_facts_contract",
        "alembic.command",
        "alembic.config",
        "alembic.context",
        "alembic.migration",
        "alembic.operations",
        "alembic.script",
    ):
        assert f'"{standalone_dependency}"' in backend_spec
    assert "sys.path.insert(0, BACKEND)" in backend_spec
    assert 'collect_submodules("app", on_error="raise")' in backend_spec
    assert '"app.database._database_generation_program"' in backend_spec
    assert '"app.database_generation_c07_contract"' in backend_spec
    assert '"app.database_model_registry"' in backend_spec
    assert '"app.tenant_contract"' in backend_spec
    for required_archive_module in (
        "app.app_meta_observation",
        "app.canonical_money_facts",
        "app.canonical_money_facts_contract",
        "app.database._database_generation_program",
        "app.database_generation_c07_contract",
        "app.database_model_registry",
        "app.tenant_contract",
    ):
        assert f'"{required_archive_module}"' in backend_build
    assert 'Frozen backend archive omitted required app module: $requiredModule' in backend_build
    assert '"app\\database\\_c07_maintenance_plan.py"' in backend_build
    assert "Retired database generation contract returned to the source snapshot" in backend_build
    assert '"app.database._c07_maintenance_plan"' in backend_build
    assert "Frozen backend archive contains retired app module: $retiredModule" in backend_build
    assert 'name="ticketbox-c07-migrator"' in backend_spec
    assert '$stagedC07Helper = Join-Path $StagingDir "ticketbox-c07-migrator.exe"' in backend_build
    smoke_call = backend_build.index("$c07MigrationHelperSmoke = Invoke-TicketboxC07MigrationHelperSmoke")
    payload_gate = backend_build.index("Assert-TicketboxPostgresOnlyFrozenPayload `")
    manifest_write = backend_build.index("Write-TicketboxBackendBuildManifest `")
    assert payload_gate < smoke_call < manifest_write
    assert "-HelperPath $stagedC07Helper" in backend_build
    assert "-PayloadSnapshot $c07SmokePayloadSnapshot" in backend_build
    assert "-C07MigrationHelperSmokeEvidence $c07MigrationHelperSmoke" in backend_build
    payload_snapshot = backend_build.index("$c07SmokePayloadSnapshot = Get-TicketboxBackendPayloadSnapshot")
    payload_lock = backend_build.index("$C07SmokePayloadLocks = @(Enter-TicketboxFileSetReadLocks")
    payload_unlock = backend_build.index(
        "Exit-TicketboxFileSetReadLocks $C07SmokePayloadLocks",
        manifest_write,
    )
    publish = backend_build.index("Publish-TicketboxRecoverableDirectory `")
    assert payload_gate < payload_snapshot < payload_lock < smoke_call
    assert manifest_write < payload_unlock < publish
    assert "function Invoke-TicketboxC07MigrationHelperSmoke" in backend_provenance
    assert "$startInfo.FileName = $HelperPath" in backend_provenance
    assert "$startInfo.RedirectStandardInput = $true" in backend_provenance
    assert "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)" in backend_provenance
    assert "$process.StandardInput.Close()" in backend_provenance
    console_input_override = backend_provenance.index(
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)"
    )
    helper_start = backend_provenance.index("$process.Start()", console_input_override)
    console_input_restore = backend_provenance.index(
        "[Console]::InputEncoding = $previousConsoleInputEncoding", helper_start
    )
    stdin_close = backend_provenance.index("$process.StandardInput.Close()", console_input_restore)
    assert console_input_override < helper_start < console_input_restore < stdin_close
    assert "$processStarted = $process.Start()" in backend_provenance
    assert "if ($processStarted -and -not $process.HasExited)" in backend_provenance
    assert "$startInfo.EnvironmentVariables.Clear()" in backend_provenance
    assert '"--validate-generation-program "' in backend_provenance
    assert '"--generation-program-path "' in backend_provenance
    assert '" --expected-generation-program-sha256 "' in backend_provenance
    assert "Assert-TicketboxC07MigrationHelperSmokeResult `" in backend_provenance
    assert "([string]$programEvidence.sha256)" in backend_provenance
    assert backend_provenance.count("Get-TicketboxBackendPayloadSnapshot $DistDir") >= 2
    assert "payload_fingerprint = [string]$PayloadSnapshot.fingerprint" in (backend_provenance)
    assert (
        ci_workflow.count(
            "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\\build_backend_exe.ps1 -Clean"
        )
        == 2
    )
    assert 'Assert-File (Join-Path $BackendDist "ticketbox-c07-migrator.exe")' in build
    assert "Read-TicketboxWindowsBuildToolchain $BackendRoot" in backend_build
    assert "prepare_windows_build_toolchain.ps1" in backend_build
    assert "-Component Backend" in backend_build
    assert "--python $SourcePython" in backend_build
    assert '$env:UV_PYTHON_DOWNLOADS = "never"' in backend_build
    assert '$env:PYTHONNOUSERSITE = "1"' in backend_build
    assert '$env:PYTHONDONTWRITEBYTECODE = "1"' in backend_build
    assert "Creating process-private exact build venv" in backend_build
    assert "Get-Command uv" not in backend_build
    assert "Get-Command ISCC" not in build
    assert "Get-FileHash" not in backend_build
    assert "-Component Inno" in build
    assert "compiler_sha256" in build
    assert "ISCC identity 与固定官方归档合同不一致" in build
    assert "ISCC compiler tree during build" in build
    assert "Invoke-WebRequest" in toolchain_preparer
    assert toolchain_preparer.index("Assert-TicketboxSha256 $partialPath") < (
        toolchain_preparer.index("Move-Item -LiteralPath $partialPath")
    )
    assert "Assert-TicketboxRelativeArchivePath" in toolchain_preparer
    assert "ZIP entry 逃逸目标目录" in toolchain_preparer
    assert "TAR entry" in toolchain_preparer
    assert "New-TicketboxVerifiedArchiveLease" in toolchain_preparer
    assert "Get-FileHash" not in toolchain_preparer
    assert "[System.IO.FileAccess]::Read" in toolchain_preparer
    assert "[System.IO.FileShare]::Read" in toolchain_preparer
    assert "Assert-TicketboxNoReparseAncestors $ArchiveRoot" in toolchain_preparer
    assert toolchain_preparer.index("$installerLease = New-TicketboxVerifiedArchiveLease") < (
        toolchain_preparer.index("-FilePath $installerLease.Path")
    )
    assert toolchain_preparer.index("-FilePath $installerLease.Path") < (
        toolchain_preparer.index("$installerLease.Handle.Dispose()")
    )
    assert "Expand-Archive" not in vendor_preparer
    assert "Get-FileHash" not in vendor_preparer
    assert "New-TicketboxVerifiedArchiveLease" in vendor_preparer
    assert "Assert-TicketboxNoReparseAncestors $ArchiveDirectory" in vendor_preparer
    assert vendor_preparer.index("$actualHash = Get-TicketboxStreamSha256 $readHandle") < (
        vendor_preparer.index("return [pscustomobject]@{ Path = $privatePath; Handle = $readHandle }")
    )
    assert vendor_preparer.index("$executableHash = Get-TicketboxStreamSha256") < (vendor_preparer.index("--version"))
    assert "Get-TicketboxValidatedPgZipEntry" in pg_bundler
    assert "Get-FileHash" not in pg_bundler
    assert pg_bundler.index("Get-TicketboxValidatedPgZipEntry $entry") < pg_bundler.index('$full.StartsWith("pgsql/"')
    assert "大小写冲突或重复 entry" in pg_bundler
    assert "symlink/reparse/特殊 entry" in pg_bundler
    assert "canonical path 逃逸 staging" in pg_bundler
    assert "New-TicketboxVerifiedPgArchiveLease" in pg_bundler
    assert "$archiveLease.Handle.Dispose()" in pg_bundler
    assert "Remove-TicketboxVendorPath $OutDir" in pg_bundler
    assert "Get-Command uv" not in toolchain_preparer
    assert "choco" not in toolchain_preparer.lower()
    assert "Assert-TicketboxPostgresOnlyFrozenPayload `" in backend_build
    assert "pip sync --strict --require-hashes" in backend_build
    assert "$LockSnapshotPath" in backend_build
    assert "$sourceLockHash -cne $snapshotLockHash" in backend_build
    assert "$postSyncSnapshotLockHash -cne $sourceLockHash" in backend_build
    assert "Copy-TicketboxFileSetSnapshot" in backend_build
    assert "Enter-TicketboxFileSetReadLocks" in backend_build
    assert "Frozen backend source during dependency sync" in backend_build
    assert backend_build.index("$sourceBeforeFreeze = Get-TicketboxBackendSourceSnapshot") < backend_build.index(
        "pip sync --strict --require-hashes"
    )
    assert "$toolchain.lock_path" in backend_build
    assert "--distpath $StagingRoot" in backend_build
    assert '(Join-Path $InputSnapshotRoot "packaging\\ticketbox-backend.spec")' in backend_build
    assert backend_build.index("Read-TicketboxWindowsBuildToolchain $BackendRoot") < (
        backend_build.index("Publish-TicketboxRecoverableDirectory `")
    )
    assert backend_build.index("Assert-TicketboxBackendBuildManifest $BackendRoot $StagingDir") < (
        backend_build.index("Publish-TicketboxRecoverableDirectory `")
    )
    assert "-SourceSnapshot $sourceBeforeFreeze" in backend_build
    before_tree = backend_build.index("$executionTreeBeforeFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild")
    freeze = backend_build.index("& $PyBuild -I -B -m PyInstaller `")
    after_tree = backend_build.index("$executionTreeAfterFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild")
    assert before_tree < freeze < after_tree
    assert "PyInstaller interpreter and site-packages during freeze" in backend_build
    assert "Enter-TicketboxWindowsBuildLock $BackendRoot" in backend_build
    assert "Publish-TicketboxInstallerUnit `" in build
    assert "Enter-TicketboxWindowsBuildLock $BackendRoot" in build
    for writer in (toolchain_preparer, vendor_preparer, pg_bundler):
        assert "Enter-TicketboxWindowsBuildLock $BackendRoot" in writer
        assert "Exit-TicketboxWindowsBuildLock $BuildLock" in writer
    lock_helper = (ROOT / "scripts" / "windows_backend_build_provenance.ps1").read_text(encoding="utf-8-sig")
    assert 'return "Global\\Ticketbox.WindowsBuild.$hex"' in lock_helper
    assert "[System.IO.FileShare]::None" in lock_helper
    assert "[AppDomain]::CurrentDomain.SetData" in lock_helper
    assert ".ticketbox-backend.last-known-good" in backend_build
    assert ".ticketbox-backend.publish-receipt.json" in backend_build
    assert ".$publishUnitName.last-known-good" in build
    assert "Recover-TicketboxDirectoryPublication" in backend_build
    assert "Recover-TicketboxDirectoryPublication" in build
    assert backend_build.index("finally {", backend_build.index("catch {")) < backend_build.index(
        "Exit-TicketboxWindowsBuildLock $BuildLock"
    )
    assert 'Source: "..\\dist\\installer-input\\BUILD_PROVENANCE.json"' in installer
    assert "#error TargetPgMajor must be probed" in installer

    github_ci = (ROOT.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gitea_ci = (ROOT.parent / ".gitea" / "workflows" / "windows-ci.yml").read_text(encoding="utf-8")
    assert 'pip install "uv==' not in github_ci
    assert "choco install innosetup" not in github_ci
    assert "prepare_windows_build_toolchain.ps1 -Component Inno -Force" in github_ci
    assert "build_inno_installer.ps1 -VerifyOnly" in github_ci
    assert "steps.compile_installer.outputs.installer_sha256" in github_ci
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in github_ci
    assert "-VerifyPublishDirectory" in github_ci
    assert "prepare_windows_build_toolchain.ps1 -Component Inno -Force" in gitea_ci
    assert "build_inno_installer.ps1 -VerifyOnly" in gitea_ci
    assert "steps.compile_installer.outputs.installer_sha256" in gitea_ci
    assert "actions/download-artifact@9bc31d5ccc31df68ecc42ccf4149144866c47d8a" in gitea_ci
    assert "-VerifyPublishDirectory" in gitea_ci
    assert not re.search(r"uses:\s+[^\s]+@(?:v\d+|main|master)(?:\s|$)", github_ci)

    config = json.loads((PACKAGING / "windows-release-config.json").read_text(encoding="utf-8"))
    config_path = tmp_path / "windows-release-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    build_path = PACKAGING / "build_inno_installer.ps1"

    def probe(vendor: str, version: str) -> subprocess.CompletedProcess[str]:
        return _run_powershell(
            f"& '{_ps_literal(build_path)}' "
            f"-ReleaseConfigOverride '{_ps_literal(config_path)}' "
            f"-VersionPolicyContractProbe '{vendor}|{version}'"
        )

    assert probe("postgres", "17.10").returncode == 0
    assert probe("shawl", "1.9.0").returncode == 0
    assert probe("iscc", "6.7.1").returncode == 0
    override_real_build = _run_powershell(
        f"& '{_ps_literal(build_path)}' -ReleaseConfigOverride '{_ps_literal(config_path)}' -CheckSourceInputsOnly"
    )
    assert override_real_build.returncode != 0
    normalized_defines = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        "@(Get-TicketboxNormalizedCompilerDefines "
        "@('/DZulu=2','/DAlpha=1')) | ConvertTo-Json -Compress"
    )
    assert normalized_defines.returncode == 0, normalized_defines.stderr
    assert json.loads(normalized_defines.stdout) == ["/DAlpha=1", "/DZulu=2"]
    duplicate_define = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; Get-TicketboxNormalizedCompilerDefines @('/DAlpha=1','/DAlpha=2')"
    )
    assert duplicate_define.returncode != 0
    config["postgres_version_policy"]["minimum"] = "17.11"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert probe("postgres", "17.10").returncode != 0
    config["postgres_version_policy"]["minimum"] = "17.10"
    config["shawl_version_policy"]["minimum"] = "1.9.1"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert probe("shawl", "1.9.0").returncode != 0
    config["shawl_version_policy"]["minimum"] = "1.9.0"
    config["iscc_version_policy"]["minimum"] = "6.7.2"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert probe("iscc", "6.7.1").returncode != 0
    config["iscc_version_policy"]["minimum"] = "6.5.0"
    config["iscc_version_policy"]["maximum_exclusive"] = "6.7.1"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert probe("iscc", "6.7.1").returncode != 0


def _assert_frozen_database_payload_gate(build_script: str) -> None:
    call = "Assert-TicketboxPostgresOnlyFrozenPayload `"
    assert build_script.count(call) == 1
    assert build_script.index(call) < build_script.index("$manifestPath = Write-TicketboxBackendBuildManifest")
    assert build_script.index(call) < build_script.index("Publish-TicketboxRecoverableDirectory `")


def test_frozen_backend_rejects_forbidden_database_payloads_and_gate_mutation(
    tmp_path: Path,
) -> None:
    helper = ROOT / "scripts" / "windows_build_provenance.ps1"
    dist = tmp_path / "dist"
    internal = dist / "_internal"
    internal.mkdir(parents=True)
    (dist / "ticketbox-backend.exe").write_bytes(b"synthetic")
    clean_listing = "0, 1, 1, 1, 'm', 'app.main'"

    def inspect(listing: str = clean_listing) -> subprocess.CompletedProcess[str]:
        powershell_listing = listing.replace("'", "''")
        return _run_powershell(
            f". '{_ps_literal(helper)}'; "
            "Assert-TicketboxPostgresOnlyFrozenPayload "
            f"-DistDir '{_ps_literal(dist)}' "
            f"-ArchiveListing @('{powershell_listing}')"
        )

    clean = inspect()
    assert clean.returncode == 0, clean.stderr

    forbidden_binary = internal / "_sqlite3.pyd"
    forbidden_binary.write_bytes(b"sqlite")
    rejected_binary = inspect()
    assert rejected_binary.returncode != 0
    assert "forbidden" in (rejected_binary.stdout + rejected_binary.stderr).lower()
    forbidden_binary.unlink()

    suffixed_binary = internal / "sqlite3-0.dll"
    suffixed_binary.write_bytes(b"sqlite")
    assert inspect().returncode != 0
    suffixed_binary.unlink()

    forbidden_zip = internal / "base_library.zip"
    with zipfile.ZipFile(forbidden_zip, "w") as archive:
        archive.writestr("sqlite3/__init__.pyc", b"sqlite")
    rejected_zip = inspect()
    assert rejected_zip.returncode != 0
    forbidden_zip.unlink()

    allowed_dialect = inspect("0, 1, 1, 1, 'm', 'sqlalchemy.dialects.mysql.base'")
    assert allowed_dialect.returncode == 0, allowed_dialect.stderr
    rejected_embedded = inspect("0, 1, 1, 1, 'm', 'MySQLdb.connections'")
    assert rejected_embedded.returncode != 0

    backend_build = (ROOT / "scripts" / "build_backend_exe.ps1").read_text(encoding="utf-8-sig")
    _assert_frozen_database_payload_gate(backend_build)
    mutated = backend_build.replace(
        "Assert-TicketboxPostgresOnlyFrozenPayload `",
        "# mutation removed frozen database payload gate `",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_frozen_database_payload_gate(mutated)


def _assert_publish_unit_gates(build_script: str) -> None:
    call = "Assert-TicketboxInstallerPublishUnit `"
    assert build_script.count(call) == 3
    publish_function = build_script.index("function Publish-TicketboxInstallerUnit")
    function_validation = build_script.index(call, publish_function)
    recoverable_publish = build_script.index("Publish-TicketboxRecoverableDirectory `", publish_function)
    assert function_validation < recoverable_publish
    staging_validation = build_script.rindex(call)
    publish_call = build_script.rindex("Publish-TicketboxInstallerUnit `")
    assert staging_validation < publish_call


def _assert_external_publish_directory_name_is_not_authority(build_script: str) -> None:
    verify_only = build_script[
        build_script.index("if ($VerifyOnly) {") : build_script.index(
            "$buildStagingRoot = Join-Path $BackendRoot",
        )
    ]
    assert "$expectedVerifyDirectoryName = if ($VerifyPublishDirectory.Trim().Length -eq 0)" in verify_only
    assert "-ExpectedDirectoryName $expectedVerifyDirectoryName" in verify_only
    external_branch = verify_only[
        verify_only.index("$expectedVerifyDirectoryName = if") : verify_only.index(
            "$verifiedPublish = Assert-TicketboxInstallerPublishUnit",
        )
    ]
    assert "$publishUnitName" in external_branch
    assert 'else {\n        ""\n    }' in external_branch


def test_installer_publish_unit_validator_rejects_contract_mutations(
    tmp_path: Path,
) -> None:
    version = "7.8.9"
    installer_name = f"Ticketbox-Setup-{version}.exe"
    unit = tmp_path / f"Ticketbox-Setup-{version}"
    unit.mkdir()
    installer = unit / installer_name
    checksum = unit / f"{installer_name}.sha256"
    provenance = unit / "BUILD_PROVENANCE.json"
    completion = unit / "BUILD_COMPLETE.json"

    def write_valid_unit(installer_bytes: bytes = b"installer") -> str:
        for child in unit.iterdir():
            if child.is_file():
                child.unlink()
        installer.write_bytes(installer_bytes)
        provenance.write_text('{"schema_version": 3}\n', encoding="utf-8")
        installer_hash = hashlib.sha256(installer.read_bytes()).hexdigest()
        provenance_hash = hashlib.sha256(provenance.read_bytes()).hexdigest()
        checksum.write_text(
            f"{installer_hash}  {installer_name}{os.linesep}",
            encoding="utf-8",
            newline="",
        )
        completion.write_text(
            json.dumps(
                {
                    "schema": "ticketbox-installer-publish-v1",
                    "version": version,
                    "installer": installer_name,
                    "installer_sha256": installer_hash,
                    "checksum": f"{installer_name}.sha256",
                    "provenance": "BUILD_PROVENANCE.json",
                    "provenance_sha256": provenance_hash,
                }
            ),
            encoding="utf-8",
        )
        return installer_hash

    trusted_installer_hash = write_valid_unit()
    build_path = PACKAGING / "build_inno_installer.ps1"
    command = (
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"$scriptPath = '{_ps_literal(build_path)}'; "
        "$tokens = $null; $errors = $null; "
        "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
        "$scriptPath, [ref]$tokens, [ref]$errors); "
        "foreach ($name in @('Assert-TicketboxExactJsonProperties',"
        "'Assert-TicketboxInstallerPublishUnit')) { "
        "$functionAst = $ast.FindAll({ param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
        "-and $node.Name -ceq $name }, $true) | Select-Object -First 1; "
        "Invoke-Expression $functionAst.Extent.Text }; "
        "function Assert-Dir([string]$Path, [string]$Label) { "
        "if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw $Label } }; "
        "function Get-TicketboxFileSha256([string]$Path) { "
        "$stream = [System.IO.File]::OpenRead($Path); "
        "$sha = [System.Security.Cryptography.SHA256]::Create(); try { "
        "return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() "
        "} finally { $sha.Dispose(); $stream.Dispose() } }; "
        "function Assert-TicketboxInstallerBuildProvenance { return $true }; "
        "function Assert-TicketboxNoReparsePath { "
        "param($Path, $AllowedRoot, [switch]$AllowRoot, [switch]$InspectTree); return $Path }; "
        f"$BackendRoot = '{_ps_literal(ROOT)}'; "
        "Assert-TicketboxInstallerPublishUnit "
        f"-PublishDirectory '{_ps_literal(unit)}' -ExpectedVersion '{version}' "
        "-ExpectedCompilerProvenance ([pscustomobject]@{}) "
        "-ExpectedBuildInputs ([pscustomobject]@{}) "
        "-ExpectedCompilerDefines @('/DTest=1') "
        f"-ExpectedInstallerSha256 '{trusted_installer_hash}' "
        f"-ExpectedDirectoryName 'Ticketbox-Setup-{version}' | Out-Null"
    )

    valid = _run_powershell(command)
    assert valid.returncode == 0, valid.stderr

    downloaded_unit = tmp_path / "ticketbox-installer-verify-random"
    shutil.copytree(unit, downloaded_unit)
    downloaded_command = command.replace(
        _ps_literal(unit),
        _ps_literal(downloaded_unit),
        1,
    ).replace(
        f"-ExpectedDirectoryName 'Ticketbox-Setup-{version}'",
        "-ExpectedDirectoryName ''",
        1,
    )
    downloaded_valid = _run_powershell(downloaded_command)
    assert downloaded_valid.returncode == 0, downloaded_valid.stderr
    assert (
        _run_powershell(
            downloaded_command.replace(
                "-ExpectedDirectoryName ''",
                f"-ExpectedDirectoryName 'Ticketbox-Setup-{version}'",
                1,
            )
        ).returncode
        != 0
    )

    write_valid_unit(b"coordinated replacement")
    assert _run_powershell(command).returncode != 0

    write_valid_unit()
    (unit / "unexpected.txt").write_text("extra", encoding="utf-8")
    assert _run_powershell(command).returncode != 0

    write_valid_unit()
    checksum.write_text("0" * 64 + f"  {installer_name}{os.linesep}", encoding="utf-8")
    assert _run_powershell(command).returncode != 0

    write_valid_unit()
    completion_payload = json.loads(completion.read_text(encoding="utf-8"))
    completion_payload["unexpected"] = True
    completion.write_text(json.dumps(completion_payload), encoding="utf-8")
    assert _run_powershell(command).returncode != 0

    write_valid_unit()
    provenance.write_text('{"schema_version": 4}\n', encoding="utf-8")
    assert _run_powershell(command).returncode != 0

    build = build_path.read_text(encoding="utf-8-sig")
    _assert_publish_unit_gates(build)
    _assert_external_publish_directory_name_is_not_authority(build)
    mutated = build.replace(
        "Assert-TicketboxInstallerPublishUnit `",
        "# mutation removed publish-unit validation `",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_publish_unit_gates(mutated)
    external_directory_mutation = build.replace(
        'else {\n        ""\n    }\n    $verifiedPublish',
        "else {\n        $publishUnitName\n    }\n    $verifiedPublish",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_external_publish_directory_name_is_not_authority(external_directory_mutation)
    _assert_installer_publish_swap_rolls_back_and_then_replaces_atomically(tmp_path / "atomic-swap")
    _assert_installer_hash_output_is_external_and_durable(
        build_path,
        tmp_path / "hash-output",
    )


def _assert_installer_hash_output_is_external_and_durable(
    build_path: Path,
    tmp_path: Path,
) -> None:
    publish_root = tmp_path / "publish"
    publish_root.mkdir(parents=True)
    trusted_hash = "ab" * 32

    for index, engine in enumerate(powershell_contract_engines()):
        output_path = tmp_path / f"engine-{index}.txt"
        extract_function = (
            f"$scriptPath = '{_ps_literal(build_path)}'; "
            "$tokens = $null; $errors = $null; "
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
            "$scriptPath, [ref]$tokens, [ref]$errors); "
            "$functionAst = $ast.FindAll({ param($node) "
            "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $node.Name -ceq 'Write-TicketboxInstallerHashOutput' }, $true) | "
            "Select-Object -First 1; Invoke-Expression $functionAst.Extent.Text; "
            "function Assert-Dir([string]$Path, [string]$Label) { "
            "if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw $Label } }; "
        )
        write = _run_powershell(
            extract_function
            + "Write-TicketboxInstallerHashOutput "
            + f"-Path '{_ps_literal(output_path)}' "
            + f"-InstallerSha256 '{trusted_hash}' "
            + f"-PublishRoot '{_ps_literal(publish_root)}'",
            executable=engine,
        )
        assert write.returncode == 0, write.stdout + write.stderr
        assert output_path.read_bytes() == (f"installer_sha256={trusted_hash}{os.linesep}".encode())

        inside_publish = publish_root / f"engine-{index}.txt"
        rejected_inside = _run_powershell(
            extract_function
            + "Write-TicketboxInstallerHashOutput "
            + f"-Path '{_ps_literal(inside_publish)}' "
            + f"-InstallerSha256 '{trusted_hash}' "
            + f"-PublishRoot '{_ps_literal(publish_root)}'",
            executable=engine,
        )
        assert rejected_inside.returncode != 0
        assert not inside_publish.exists()

        rejected_hash = _run_powershell(
            extract_function
            + "Write-TicketboxInstallerHashOutput "
            + f"-Path '{_ps_literal(tmp_path / f'invalid-{index}.txt')}' "
            + "-InstallerSha256 'not-a-sha256' "
            + f"-PublishRoot '{_ps_literal(publish_root)}'",
            executable=engine,
        )
        assert rejected_hash.returncode != 0


def _assert_installer_publish_swap_rolls_back_and_then_replaces_atomically(
    tmp_path: Path,
) -> None:
    publish_root = tmp_path / "publish"
    target = publish_root / "Ticketbox-Setup-7.8.9"
    staging = publish_root / ".staging"
    backup = publish_root / ".backup"
    target.mkdir(parents=True)
    staging.mkdir()
    (target / "old.txt").write_text("last-known-good", encoding="utf-8")
    (staging / "new.txt").write_text("candidate", encoding="utf-8")
    build_path = PACKAGING / "build_inno_installer.ps1"
    command = (
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"$scriptPath = '{_ps_literal(build_path)}'; "
        "$tokens = $null; $errors = $null; "
        "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
        "$scriptPath, [ref]$tokens, [ref]$errors); "
        "$functionAst = $ast.FindAll({ param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
        "-and $node.Name -ceq 'Publish-TicketboxInstallerUnit' }, $true) | "
        "Select-Object -First 1; Invoke-Expression $functionAst.Extent.Text; "
        "function Assert-TicketboxNoReparsePath { "
        "param($Path, $AllowedRoot, [switch]$AllowRoot, [switch]$InspectTree); return $Path }; "
        "function Remove-TicketboxPublishDirectoryVerified { param($Path); "
        "Remove-Item -LiteralPath $Path -Recurse -Force }; "
        "function Assert-TicketboxInstallerPublishUnit { "
        "if ($script:FailValidation) { throw 'injected verification failure' } }; "
        f"$root = '{_ps_literal(publish_root)}'; "
        f"$target = '{_ps_literal(target)}'; "
        f"$staging = '{_ps_literal(staging)}'; "
        f"$backup = '{_ps_literal(backup)}'; "
        "$script:FailValidation = $true; "
        "$failed = $false; try { Publish-TicketboxInstallerUnit "
        "-StagingDirectory $staging -TargetDirectory $target "
        "-BackupDirectory $backup -PublishRoot $root -ExpectedVersion '7.8.9' "
        "-ExpectedCompilerProvenance @{} -ExpectedBuildInputs @{} "
        "-ExpectedCompilerDefines @('/DTest=1') -ExpectedInstallerSha256 ('a' * 64) "
        "-ExpectedDirectoryName 'Ticketbox-Setup-7.8.9' } catch { $failed = $true }; "
        "if (-not $failed -or -not (Test-Path (Join-Path $target 'old.txt')) -or "
        "(Test-Path (Join-Path $target 'new.txt')) -or (Test-Path $backup)) { "
        "throw 'failed swap did not restore last-known-good' }; "
        "New-Item -ItemType Directory -Path $staging | Out-Null; "
        "Set-Content -LiteralPath (Join-Path $staging 'new.txt') -Value 'candidate'; "
        "$script:FailValidation = $false; Publish-TicketboxInstallerUnit "
        "-StagingDirectory $staging -TargetDirectory $target "
        "-BackupDirectory $backup -PublishRoot $root -ExpectedVersion '7.8.9' "
        "-ExpectedCompilerProvenance @{} -ExpectedBuildInputs @{} "
        "-ExpectedCompilerDefines @('/DTest=1') -ExpectedInstallerSha256 ('a' * 64) "
        "-ExpectedDirectoryName 'Ticketbox-Setup-7.8.9'; "
        "if (-not (Test-Path (Join-Path $target 'new.txt')) -or "
        "(Test-Path (Join-Path $target 'old.txt')) -or (Test-Path $backup)) { "
        "throw 'successful swap did not publish exactly the candidate' }"
    )

    result = _run_powershell(command)

    assert result.returncode == 0, result.stderr


def _assert_windows_build_reparse_guard_rejects_ancestor_and_tree_junctions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir(parents=True)
    outside.mkdir()
    (outside / "payload.txt").write_text("outside", encoding="utf-8")
    junction = root / "redirect"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert created.returncode == 0, created.stderr
    command = (
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"Assert-TicketboxNoReparsePath -Path '{_ps_literal(root)}' "
        f"-AllowedRoot '{_ps_literal(root)}' -AllowRoot -InspectTree"
    )

    rejected = _run_powershell(command)

    assert rejected.returncode != 0
    assert "reparse" in (rejected.stdout + rejected.stderr).lower()
    ancestor_rejected = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"Assert-TicketboxNoReparsePath -Path "
        f"'{_ps_literal(junction / 'payload.txt')}' "
        f"-AllowedRoot '{_ps_literal(root)}'"
    )
    assert ancestor_rejected.returncode != 0
    assert "reparse" in (ancestor_rejected.stdout + ancestor_rejected.stderr).lower()
    assert (outside / "payload.txt").read_text(encoding="utf-8") == "outside"


def _assert_windows_build_lock_serializes_and_execution_tree_detects_drift(
    tmp_path: Path,
) -> None:
    tmp_path.mkdir(parents=True)
    ready = tmp_path / "ready.txt"
    release = tmp_path / "release.txt"
    holder = subprocess.Popen(
        [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                f". '{_ps_literal(PROVENANCE_HELPER)}'; "
                f"$lock = Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}'; "
                f"Set-Content -LiteralPath '{_ps_literal(ready)}' -Value ready; "
                f"$release = '{_ps_literal(release)}'; "
                "$deadline = [DateTime]::UtcNow.AddSeconds(30); "
                "try { while (-not (Test-Path -LiteralPath $release -PathType Leaf)) { "
                "if ([DateTime]::UtcNow -ge $deadline) { "
                "throw 'Timed out waiting for the test release signal.' }; "
                "Start-Sleep -Milliseconds 100 } } finally { "
                "Exit-TicketboxWindowsBuildLock $lock }"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        for _ in range(40):
            if ready.exists():
                break
            time.sleep(0.1)
        assert ready.exists()
        blocked = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}' 1 | Out-Null",
        )
        assert blocked.returncode != 0
        assert "timed out" in (blocked.stdout + blocked.stderr).lower()
        if shutil.which("pwsh"):
            blocked_pwsh = _run_powershell(
                f". '{_ps_literal(PROVENANCE_HELPER)}'; "
                f"Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}' 1 | Out-Null",
                executable="pwsh",
            )
            assert blocked_pwsh.returncode != 0
            assert "timed out" in (blocked_pwsh.stdout + blocked_pwsh.stderr).lower()
    finally:
        release.write_text("release\n", encoding="utf-8")
        stdout, stderr = holder.communicate(timeout=10)
    assert holder.returncode == 0, stdout + stderr
    reacquired = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"$lock = Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}' 1; "
        "Exit-TicketboxWindowsBuildLock $lock"
    )
    assert reacquired.returncode == 0, reacquired.stderr
    nested = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"$outer = Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}' 1; "
        f"$inner = Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}' 1; "
        "Exit-TicketboxWindowsBuildLock $inner; "
        "Exit-TicketboxWindowsBuildLock $outer"
    )
    assert nested.returncode == 0, nested.stderr
    if shutil.which("pwsh"):
        cross_engine = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$lock = Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}' 1; "
            "Exit-TicketboxWindowsBuildLock $lock",
            executable="pwsh",
        )
        assert cross_engine.returncode == 0, cross_engine.stderr

    environment = tmp_path / "environment"
    site_packages = environment / "Lib" / "site-packages"
    interpreter = environment / "Scripts" / "python.exe"
    site_packages.mkdir(parents=True)
    interpreter.parent.mkdir()
    interpreter.write_bytes(b"python")
    module = site_packages / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    drift = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"$components = @([pscustomobject]@{{label='environment';path='{_ps_literal(environment)}'}}); "
        f"$before = Get-TicketboxExecutionTreeEvidence '{_ps_literal(interpreter)}' $components; "
        f"Set-Content -LiteralPath '{_ps_literal(module)}' -Value 'VALUE = 2'; "
        f"$after = Get-TicketboxExecutionTreeEvidence '{_ps_literal(interpreter)}' $components; "
        "Assert-TicketboxStructuredEvidence 'execution tree' $before $after"
    )
    assert drift.returncode != 0
    assert "execution tree" in (drift.stdout + drift.stderr).lower()


def _assert_recoverable_directory_publication_handles_interrupted_swap_states(
    tmp_path: Path,
) -> None:
    root = tmp_path / "publish"
    target = root / "target"
    backup = root / ".target.last-known-good"
    staging = root / ".target.staging"
    receipt = root / ".target.publish-receipt.json"
    root.mkdir(parents=True)

    def prepare_receipt() -> str:
        return (
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$root = '{_ps_literal(root)}'; $target = '{_ps_literal(target)}'; "
            f"$backup = '{_ps_literal(backup)}'; $staging = '{_ps_literal(staging)}'; "
            f"$receiptPath = '{_ps_literal(receipt)}'; "
            "$record = [ordered]@{schema='ticketbox-directory-publication-v1'; "
            "phase='prepared'; publish_root=$root; target_path=$target; "
            "backup_path=$backup; staging_path=$staging; had_target=$true; "
            "new_identity=(Get-TicketboxDirectoryPublicationIdentity $staging); "
            "backup_identity=(Get-TicketboxDirectoryPublicationIdentity $target)}; "
            "Write-TicketboxDirectoryPublicationReceipt $receiptPath $record; "
        )

    target.mkdir()
    staging.mkdir()
    (target / "payload.txt").write_text("old", encoding="utf-8")
    (staging / "payload.txt").write_text("new", encoding="utf-8")
    interrupted_after_backup = _run_powershell(
        prepare_receipt()
        + "Move-Item -LiteralPath $target -Destination $backup; "
        + "Recover-TicketboxDirectoryPublication $target $backup $receiptPath $root"
    )
    assert interrupted_after_backup.returncode == 0, interrupted_after_backup.stderr
    assert (target / "payload.txt").read_text(encoding="utf-8").strip() == "old"
    assert not backup.exists()
    assert not staging.exists()
    assert not receipt.exists()

    staging.mkdir()
    (staging / "payload.txt").write_text("new", encoding="utf-8")
    interrupted_after_promote = _run_powershell(
        prepare_receipt()
        + "Move-Item -LiteralPath $target -Destination $backup; "
        + "Move-Item -LiteralPath $staging -Destination $target; "
        + "Recover-TicketboxDirectoryPublication $target $backup $receiptPath $root"
    )
    assert interrupted_after_promote.returncode == 0, interrupted_after_promote.stderr
    assert (target / "payload.txt").read_text(encoding="utf-8").strip() == "new"
    assert not backup.exists()
    assert not receipt.exists()

    staging.mkdir()
    (staging / "payload.txt").write_text("candidate", encoding="utf-8")
    missing_promoted_target = _run_powershell(
        prepare_receipt()
        + "$record.phase = 'promoted'; "
        + "Move-Item -LiteralPath $target -Destination $backup; "
        + "Move-Item -LiteralPath $staging -Destination $target; "
        + "Write-TicketboxDirectoryPublicationReceipt $receiptPath $record; "
        + "Remove-Item -LiteralPath $target -Recurse -Force; "
        + "Recover-TicketboxDirectoryPublication $target $backup $receiptPath $root"
    )
    assert missing_promoted_target.returncode == 0, missing_promoted_target.stderr
    assert (target / "payload.txt").read_text(encoding="utf-8").strip() == "new"
    assert not backup.exists()
    assert not staging.exists()
    assert not receipt.exists()

    staging.mkdir()
    (staging / "payload.txt").write_text("candidate", encoding="utf-8")
    unknown_backup = _run_powershell(
        prepare_receipt()
        + "Move-Item -LiteralPath $target -Destination $backup; "
        + "Set-Content -LiteralPath (Join-Path $backup 'payload.txt') -Value tampered; "
        + "Recover-TicketboxDirectoryPublication $target $backup $receiptPath $root"
    )
    assert unknown_backup.returncode != 0
    assert backup.exists()
    assert staging.exists()
    assert receipt.exists()

    for index, engine in enumerate(powershell_contract_engines()):
        case_alias_root = tmp_path / f"case-alias-{index}"
        case_alias_target = case_alias_root / "TargetUnit"
        case_alias_staging = case_alias_root / "targetunit"
        case_alias_backup = case_alias_root / ".target.last-known-good"
        case_alias_receipt = case_alias_root / ".target.publish-receipt.json"
        case_alias_target.mkdir(parents=True)
        (case_alias_target / "payload.txt").write_text("live", encoding="utf-8")
        case_alias_rejected = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$root = '{_ps_literal(case_alias_root)}'; "
            f"$target = '{_ps_literal(case_alias_target)}'; "
            f"$staging = '{_ps_literal(case_alias_staging)}'; "
            f"$backup = '{_ps_literal(case_alias_backup)}'; "
            f"$receipt = '{_ps_literal(case_alias_receipt)}'; "
            "if ($target.Equals($staging, [StringComparison]::Ordinal) -or "
            "-not $target.Equals($staging, [StringComparison]::OrdinalIgnoreCase)) { "
            "throw 'case-alias fixture is not a Windows path alias' }; "
            "$record = [ordered]@{schema='ticketbox-directory-publication-v1'; "
            "phase='prepared'; publish_root=$root; target_path=$target; "
            "backup_path=$backup; staging_path=$staging; had_target=$true; "
            "new_identity=(Get-TicketboxDirectoryPublicationIdentity $staging); "
            "backup_identity=(Get-TicketboxDirectoryPublicationIdentity $target)}; "
            "Write-TicketboxDirectoryPublicationReceipt $receipt $record; "
            "$payload = Join-Path $target 'payload.txt'; "
            "$payloadBefore = [Convert]::ToBase64String([IO.File]::ReadAllBytes($payload)); "
            "$before = [Convert]::ToBase64String([IO.File]::ReadAllBytes($receipt)); "
            "$failed = $false; try { "
            "Recover-TicketboxDirectoryPublication $target $backup $receipt $root "
            "} catch { $failed = $true }; "
            "$payloadAfter = [Convert]::ToBase64String([IO.File]::ReadAllBytes($payload)); "
            "$after = [Convert]::ToBase64String([IO.File]::ReadAllBytes($receipt)); "
            "if (-not $failed -or $payloadBefore -cne $payloadAfter -or "
            "$before -cne $after -or "
            "(Test-Path $backup)) { "
            "throw 'case-only staging alias mutated live publication authority' }",
            executable=engine,
        )
        assert case_alias_rejected.returncode == 0, case_alias_rejected.stdout + case_alias_rejected.stderr

        nested_root = tmp_path / f"nested-staging-{index}"
        nested_staging = nested_root / ".staging-parent" / "candidate"
        nested_target = nested_root / "target"
        nested_backup = nested_root / ".target.last-known-good"
        nested_receipt = nested_root / ".target.publish-receipt.json"
        nested_staging.mkdir(parents=True)
        (nested_staging / "payload.txt").write_text("new", encoding="utf-8")
        nested_publish = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$root = '{_ps_literal(nested_root)}'; "
            f"$staging = '{_ps_literal(nested_staging)}'; "
            f"$target = '{_ps_literal(nested_target)}'; "
            f"$backup = '{_ps_literal(nested_backup)}'; "
            f"$receipt = '{_ps_literal(nested_receipt)}'; "
            "Publish-TicketboxRecoverableDirectory "
            "-StagingDirectory $staging -TargetDirectory $target "
            "-BackupDirectory $backup -ReceiptPath $receipt -PublishRoot $root; "
            "if ((Get-Content (Join-Path $target 'payload.txt') -Raw).Trim() -cne 'new' -or "
            "(Test-Path $staging) -or (Test-Path $backup) -or (Test-Path $receipt)) { "
            "throw 'nested staging did not publish as one directory unit' }",
            executable=engine,
        )
        assert nested_publish.returncode == 0, nested_publish.stdout + nested_publish.stderr

        nested_recovery_root = tmp_path / f"nested-recovery-{index}"
        nested_recovery_staging = nested_recovery_root / ".staging-parent" / "candidate"
        nested_recovery_target = nested_recovery_root / "target"
        nested_recovery_backup = nested_recovery_root / ".target.last-known-good"
        nested_recovery_receipt = nested_recovery_root / ".target.publish-receipt.json"
        nested_recovery_staging.mkdir(parents=True)
        (nested_recovery_staging / "payload.txt").write_text(
            "recovered",
            encoding="utf-8",
        )
        nested_recovery = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$root = '{_ps_literal(nested_recovery_root)}'; "
            f"$staging = '{_ps_literal(nested_recovery_staging)}'; "
            f"$target = '{_ps_literal(nested_recovery_target)}'; "
            f"$backup = '{_ps_literal(nested_recovery_backup)}'; "
            f"$receipt = '{_ps_literal(nested_recovery_receipt)}'; "
            "$record = [ordered]@{schema='ticketbox-directory-publication-v1'; "
            "phase='prepared'; publish_root=$root; target_path=$target; "
            "backup_path=$backup; staging_path=$staging; had_target=$false; "
            "new_identity=(Get-TicketboxDirectoryPublicationIdentity $staging); "
            "backup_identity=$null}; "
            "Write-TicketboxDirectoryPublicationReceipt $receipt $record; "
            "Recover-TicketboxDirectoryPublication $target $backup $receipt $root; "
            "if ((Get-Content (Join-Path $target 'payload.txt') -Raw).Trim() -cne 'recovered' -or "
            "(Test-Path $staging) -or (Test-Path $backup) -or (Test-Path $receipt)) { "
            "throw 'nested prepared receipt did not recover initial publication' }",
            executable=engine,
        )
        assert nested_recovery.returncode == 0, nested_recovery.stdout + nested_recovery.stderr

        identical_root = tmp_path / f"identical-prepared-{index}"
        identical_target = identical_root / "target"
        identical_backup = identical_root / ".target.last-known-good"
        identical_staging = identical_root / ".target.staging"
        identical_receipt = identical_root / ".target.publish-receipt.json"
        identical_target.mkdir(parents=True)
        identical_staging.mkdir()
        (identical_target / "payload.txt").write_text("same", encoding="utf-8")
        (identical_staging / "payload.txt").write_text("same", encoding="utf-8")
        identical_recovery = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$root = '{_ps_literal(identical_root)}'; "
            f"$target = '{_ps_literal(identical_target)}'; "
            f"$backup = '{_ps_literal(identical_backup)}'; "
            f"$staging = '{_ps_literal(identical_staging)}'; "
            f"$receipt = '{_ps_literal(identical_receipt)}'; "
            "$record = [ordered]@{schema='ticketbox-directory-publication-v1'; "
            "phase='prepared'; publish_root=$root; target_path=$target; "
            "backup_path=$backup; staging_path=$staging; had_target=$true; "
            "new_identity=(Get-TicketboxDirectoryPublicationIdentity $staging); "
            "backup_identity=(Get-TicketboxDirectoryPublicationIdentity $target)}; "
            "if ($record.new_identity.fingerprint -cne "
            "$record.backup_identity.fingerprint) { "
            "throw 'identical fixture identities diverged' }; "
            "Write-TicketboxDirectoryPublicationReceipt $receipt $record; "
            "Recover-TicketboxDirectoryPublication $target $backup $receipt $root; "
            "if ((Get-Content (Join-Path $target 'payload.txt') -Raw).Trim() -cne 'same' -or "
            "(Test-Path $backup) -or (Test-Path $staging) -or (Test-Path $receipt)) { "
            "throw 'identical prepared state did not converge to one target' }",
            executable=engine,
        )
        assert identical_recovery.returncode == 0, identical_recovery.stdout + identical_recovery.stderr

        locked_root = tmp_path / f"locked-publish-{index}"
        locked_target = locked_root / "target"
        locked_backup = locked_root / ".target.last-known-good"
        locked_staging = locked_root / ".target.staging"
        locked_receipt = locked_root / ".target.publish-receipt.json"
        locked_target.mkdir(parents=True)
        locked_staging.mkdir()
        (locked_target / "a-before-lock.txt").write_text("old-a", encoding="utf-8")
        locked_file = locked_target / "z-locked.txt"
        locked_file.write_text("old-z", encoding="utf-8")
        (locked_staging / "candidate.txt").write_text("new", encoding="utf-8")
        locked_swap = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$root = '{_ps_literal(locked_root)}'; "
            f"$target = '{_ps_literal(locked_target)}'; "
            f"$backup = '{_ps_literal(locked_backup)}'; "
            f"$staging = '{_ps_literal(locked_staging)}'; "
            f"$receipt = '{_ps_literal(locked_receipt)}'; "
            f"$locked = '{_ps_literal(locked_file)}'; "
            "$stream = [IO.File]::Open($locked, [IO.FileMode]::Open, "
            "[IO.FileAccess]::Read, [IO.FileShare]::Read); "
            "$identity = Get-TicketboxDirectoryPublicationIdentity $target; "
            "if ([int]$identity.file_count -ne 2) { "
            "throw 'locked target identity preflight did not read both files' }; "
            "$failed = $false; try { "
            "Publish-TicketboxRecoverableDirectory "
            "-StagingDirectory $staging -TargetDirectory $target "
            "-BackupDirectory $backup -ReceiptPath $receipt -PublishRoot $root "
            "} catch { $failed = $true } finally { $stream.Dispose() }; "
            "$oldIsWhole = "
            "(Test-Path (Join-Path $target 'a-before-lock.txt') -PathType Leaf) -and "
            "(Test-Path (Join-Path $target 'z-locked.txt') -PathType Leaf) -and "
            "-not (Test-Path (Join-Path $target 'candidate.txt')) -and "
            "-not (Test-Path $backup) -and (Test-Path $staging -PathType Container); "
            "$newIsWhole = "
            "(Test-Path (Join-Path $target 'candidate.txt') -PathType Leaf) -and "
            "-not (Test-Path (Join-Path $target 'a-before-lock.txt')) -and "
            "-not (Test-Path (Join-Path $target 'z-locked.txt')) -and "
            "-not (Test-Path $backup) -and -not (Test-Path $staging); "
            "if (-not ($oldIsWhole -xor $newIsWhole) -or (Test-Path $receipt)) { "
            "throw 'locked publication produced a split or ambiguous directory state' }; "
            "if ($failed -and -not $oldIsWhole) { "
            "throw 'failed locked publication did not preserve the whole old unit' }",
            executable=engine,
        )
        assert locked_swap.returncode == 0, locked_swap.stdout + locked_swap.stderr

        rollback_root = tmp_path / f"rollback-recovery-{index}"
        rollback_target = rollback_root / "target"
        rollback_backup = rollback_root / ".target.last-known-good"
        rollback_staging = rollback_root / ".target.staging"
        rollback_receipt = rollback_root / ".target.publish-receipt.json"
        rollback_target.mkdir(parents=True)
        rollback_staging.mkdir()
        (rollback_target / "payload.txt").write_text("old", encoding="utf-8")
        (rollback_staging / "payload.txt").write_text("new", encoding="utf-8")
        rollback_recovery = _run_powershell(
            f". '{_ps_literal(PROVENANCE_HELPER)}'; "
            f"$root = '{_ps_literal(rollback_root)}'; "
            f"$target = '{_ps_literal(rollback_target)}'; "
            f"$backup = '{_ps_literal(rollback_backup)}'; "
            f"$staging = '{_ps_literal(rollback_staging)}'; "
            f"$receipt = '{_ps_literal(rollback_receipt)}'; "
            "$script:testReceiptPath = $receipt; "
            "$script:receiptLock = $null; $failed = $false; try { "
            "Publish-TicketboxRecoverableDirectory "
            "-StagingDirectory $staging -TargetDirectory $target "
            "-BackupDirectory $backup -ReceiptPath $receipt -PublishRoot $root "
            "-ValidatePublished { param($published) "
            "$script:receiptLock = [IO.File]::Open($script:testReceiptPath, "
            "[IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read); "
            "throw 'injected validation failure while receipt is locked' } "
            "} catch { $failed = $true } finally { "
            "if ($null -ne $script:receiptLock) { $script:receiptLock.Dispose() } }; "
            "if (-not $failed -or "
            "(Get-Content -LiteralPath (Join-Path $target 'payload.txt') -Raw).Trim() -cne 'old' -or "
            "(Test-Path $backup) -or (Test-Path $staging) -or "
            "-not (Test-Path $receipt -PathType Leaf)) { "
            "throw 'rollback did not retain the exact old target and stale receipt' }; "
            "Recover-TicketboxDirectoryPublication $target $backup $receipt $root; "
            "if ((Get-Content -LiteralPath (Join-Path $target 'payload.txt') -Raw).Trim() -cne 'old' -or "
            "(Test-Path $backup) -or (Test-Path $staging) -or (Test-Path $receipt)) { "
            "throw 'rollback-complete state did not converge after receipt unlock' }",
            executable=engine,
        )
        assert rollback_recovery.returncode == 0, rollback_recovery.stdout + rollback_recovery.stderr


def test_windows_build_lock_is_bound_to_current_requirement_inputs(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    _write_minimal_backend(backend)
    command = (
        f". '{_ps_literal(PROVENANCE_HELPER)}'; Read-TicketboxWindowsBuildToolchain '{_ps_literal(backend)}' | Out-Null"
    )
    assert _run_powershell(command).returncode == 0

    (backend / "requirements.txt").write_text("sample==2.0.0\n", encoding="utf-8")
    stale = _run_powershell(command)
    assert stale.returncode != 0
    assert "stale" in (stale.stdout + stale.stderr).lower()
    _assert_windows_build_reparse_guard_rejects_ancestor_and_tree_junctions(tmp_path / "reparse")
    _assert_windows_build_lock_serializes_and_execution_tree_detects_drift(tmp_path / "lock-and-drift")
    _assert_recoverable_directory_publication_handles_interrupted_swap_states(tmp_path / "publication-recovery")


def test_inno_version_floor_and_protected_child_logs_are_fail_closed() -> None:
    windows = (PACKAGING / "ticketbox-installer-windows.isph").read_text(encoding="utf-8")
    installer = (PACKAGING / "ticketbox-installer.iss").read_text(encoding="utf-8")

    assert "EvaluateBackendVersionFloorDecision" in windows
    assert "CheckBackendVersionFloor" in windows
    assert "CompareSupportedNumericVersions(TargetVersion, InstalledVersion" in windows
    assert "if Comparison < 0 then" in windows
    formal_query = windows.index("HasFormalVersion := RegQueryStringValue(")
    assert "'Software\\Ticketbox'," in windows[formal_query : formal_query + 180]
    assert "'BackendVersion'," in windows[formal_query : formal_query + 180]
    assert "TicketboxLegacyUninstallKey" in windows
    assert "CurrentVersion\\Uninstall\\{" in windows
    assert "'{#TicketboxAppIdGuid}' + '}_is1'" in windows
    assert "TryGetTrustedLegacyBackendVersion" in windows
    assert "'DisplayVersion'" in windows
    assert "'DisplayName'" in windows
    assert "'InstallLocation'" in windows
    assert "DirExists(ExpandFileName(Trim(InstallLocation)))" in windows
    assert "CanonicalVersionGateInstallPath(RegisteredInstallDir)" in windows
    assert '#define TicketboxAppIdGuid "C97812CE-7486-41D0-AB68-7558A916F6E3"' in installer
    assert '#define TicketboxAppId "{{" + TicketboxAppIdGuid + "}"' in installer
    assert "AppId={#TicketboxAppId}" in installer
    assert installer.count("C97812CE-7486-41D0-AB68-7558A916F6E3") == 1
    assert "RegWriteStringValue(" in windows
    assert "'BackendVersion'," in windows
    assert "CompareText(Context, 'Ticketbox service installation') = 0" in windows
    assert "{commoncf64}\\Ticketbox\\installer-logs" in windows
    assert "function PrepareProtectedInstallerLog(Context: String; var LogPath: String): Boolean;" in windows
    assert "SetArrayLength(LogHeader, 4);" in windows
    assert "SCHEMA=ticketbox-installer-child-log-v1" in windows
    assert "INSTALLER_OWNER_PID=" in windows
    assert "LOG_SEQUENCE=" in windows
    assert "CONTEXT=" in windows
    assert "SaveStringsToUTF8File(LogPath, LogHeader, False)" in windows
    assert "SaveStringToFile(LogPath" not in windows
    assert "PrepareProtectedInstallerLog(Context, LogPath)" in windows
    assert "Start-Transcript -LiteralPath $LogPath -Append -Force" in windows
    assert "HardenLifecycleLockPath(LogPath, False)" in windows
    assert "could not start PowerShell" not in windows
    assert "failed. PowerShell exit code" not in windows
    assert "\u9000\u51fa\u7801" not in windows
    assert "\u8be6\u7ec6\u65e5\u5fd7\uff1a" not in windows

    decision_start = windows.index("function EvaluateBackendVersionFloorDecision")
    decision_end = windows.index("function CheckBackendVersionFloor", decision_start)
    decision = windows[decision_start:decision_end]
    trusted_legacy = decision.index("else if HasTrustedLegacyVersion then")
    existing_install = decision.index("else if HasExistingInstall then")
    comparison = decision.index("Comparison := CompareSupportedNumericVersions")
    assert trusted_legacy < existing_install < comparison
    assert "exit;" not in decision[trusted_legacy:existing_install]
    fresh_exit = "else\n  begin\n    Result := True;\n    exit;\n  end;"
    fresh = decision.index(fresh_exit, existing_install)
    assert fresh < comparison
    assert "exit;" not in decision[fresh + len(fresh_exit) : comparison]

    allow = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' -VersionFloorContractProbe '1.2.0||1.1.9|true'"
    )
    assert allow.returncode == 0, allow.stderr
    assert allow.stdout.strip() == "allow"
    downgrade = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' -VersionFloorContractProbe '1.1.9||1.2.0|true'"
    )
    assert downgrade.returncode != 0
    missing_trusted_version = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' -VersionFloorContractProbe '1.2.0|||true'"
    )
    assert missing_trusted_version.returncode != 0
    fresh_probe = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' -VersionFloorContractProbe '1.2.0|||false'"
    )
    assert fresh_probe.returncode == 0, fresh_probe.stderr
    assert fresh_probe.stdout.strip() == "fresh"
    interrupted_downgrade = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' "
        "-VersionFloorContractProbe '1.2.0|1.1.0|1.3.0||true'"
    )
    assert interrupted_downgrade.returncode != 0
    interrupted_repair = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' "
        "-VersionFloorContractProbe '1.3.0|1.1.0|1.3.0||true'"
    )
    assert interrupted_repair.returncode == 0, interrupted_repair.stderr
    assert interrupted_repair.stdout.strip() == "allow"


def test_windows_ci_names_source_preflight_without_claiming_a_build() -> None:
    for workflow in (
        REPO_ROOT / ".github" / "workflows" / "ci.yml",
        REPO_ROOT / ".gitea" / "workflows" / "windows-ci.yml",
    ):
        text = workflow.read_text(encoding="utf-8")
        assert "Installer source preflight (Windows PowerShell 5.1)" in text
        assert "Installer source preflight (PowerShell 7)" in text
        assert "shell: pwsh" in text
        assert "run: pwsh " in text
        assert "build_inno_installer.ps1 -CheckSourceInputsOnly" in text
        assert "build_inno_installer.ps1 -CheckInputsOnly" not in text
