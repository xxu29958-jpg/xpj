from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from _powershell_contract import powershell_contract_engines

from app.version import BACKEND_VERSION

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent
PACKAGING = ROOT / "packaging"
PROVENANCE_HELPER = ROOT / "scripts" / "windows_build_provenance.ps1"
PYTHON_BUILD_ENVIRONMENT_HELPER = (
    ROOT / "scripts" / "windows_python_build_environment.ps1"
)
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


def test_sealed_python_build_environment_removes_and_restores_ambient_inputs(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        private_config = tmp_path / f"pyinstaller-{index}"
        command = (
            f". '{_ps_literal(PYTHON_BUILD_ENVIRONMENT_HELPER)}'; "
            "$env:UV_CONFIG_FILE='ambient-uv.toml'; "
            "$env:UV_NO_BINARY='1'; "
            "$env:PYTHONPATH='ambient-python-path'; "
            "$env:PYTHONWARNINGS='error'; "
            "$env:PYTHONNOUSERSITE='ambient-no-user-site'; "
            "$env:PYTHONDONTWRITEBYTECODE='ambient-bytecode'; "
            "$env:PYINSTALLER_CONFIG_DIR='ambient-pyinstaller'; "
            f"$sealed = Enter-TicketboxSealedPythonBuildEnvironment "
            f"-PyInstallerConfigDirectory '{_ps_literal(private_config)}'; "
            "try { "
            "$uv = @(Get-ChildItem Env: | Where-Object { $_.Name -like 'UV_*' }); "
            "if ($uv.Count -ne 0) { throw 'ambient UV input survived sealing' }; "
            "$unexpectedPython = @(Get-ChildItem Env: | Where-Object { "
            "$_.Name -like 'PYTHON*' -and $_.Name -notin "
            "@('PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE') }); "
            "if ($unexpectedPython.Count -ne 0) { throw 'ambient Python input survived sealing' }; "
            "if ($env:PYTHONNOUSERSITE -cne '1' -or "
            "$env:PYTHONDONTWRITEBYTECODE -cne '1') { "
            "throw 'approved Python policy is missing' }; "
            f"if ($env:PYINSTALLER_CONFIG_DIR -cne '{_ps_literal(private_config)}') {{ "
            "throw 'private PyInstaller config is missing' } "
            "} finally { Exit-TicketboxSealedPythonBuildEnvironment $sealed }; "
            "if ($env:UV_CONFIG_FILE -cne 'ambient-uv.toml' -or "
            "$env:UV_NO_BINARY -cne '1' -or "
            "$env:PYTHONPATH -cne 'ambient-python-path' -or "
            "$env:PYTHONWARNINGS -cne 'error' -or "
            "$env:PYTHONNOUSERSITE -cne 'ambient-no-user-site' -or "
            "$env:PYTHONDONTWRITEBYTECODE -cne 'ambient-bytecode' -or "
            "$env:PYINSTALLER_CONFIG_DIR -cne 'ambient-pyinstaller') { "
            "throw 'ambient build environment was not restored exactly' }"
        )
        result = _run_powershell(command, executable=engine)
        assert result.returncode == 0, result.stdout + result.stderr


def test_all_frozen_builds_share_sealed_binary_only_uv_policy() -> None:
    scripts = (
        ROOT / "scripts" / "build_backend_exe.ps1",
        REPO_ROOT / "desktop" / "scripts" / "build_manager_exe.ps1",
        REPO_ROOT / "distribution" / "windows" / "build" / "build_installer.ps1",
    )
    for script in scripts:
        text = script.read_text(encoding="utf-8-sig")
        assert "Enter-TicketboxSealedPythonBuildEnvironment" in text
        assert "Exit-TicketboxSealedPythonBuildEnvironment" in text
        for flag in ("--no-config", "--no-cache", "--no-python-downloads"):
            assert flag in text
        assert "--only-binary" in text
        assert '":all:"' in text
        assert "--link-mode" in text
        assert '"copy"' in text
        uv_calls = [line for line in text.splitlines() if "& $UvPath" in line]
        assert uv_calls
        assert all("@UvIsolationArguments" in line for line in uv_calls)
        assert text.count("& $UvPath @UvIsolationArguments pip sync") == 1
        assert text.count("--only-binary") == 1
        assert text.count('--link-mode "copy"') == 2
        assert "$env:UV_" not in text
        assert "[Environment]::SetEnvironmentVariable" not in text

    backend = scripts[0].read_text(encoding="utf-8-sig")
    manager = scripts[1].read_text(encoding="utf-8-sig")
    assert '@("-I", "-B", "-c", "import platform;' in backend
    assert '@("-I", "-B", "-c", "import platform;' in manager


def test_installer_publish_verification_rejects_provenance_byte_mutation(tmp_path: Path) -> None:
    publish = tmp_path / "publish"
    publish.mkdir()
    installer = publish / f"Ticketbox-Setup-{BACKEND_VERSION}.exe"
    provenance = publish / "BUILD_PROVENANCE.json"
    installer.write_bytes(b"exact-setup-bytes")
    provenance.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "artifact_type": "ticketbox-windows-installer-inputs",
                "git": {"commit": "a" * 40},
            }
        ),
        encoding="utf-8",
    )
    script = REPO_ROOT / "distribution" / "windows" / "build" / "build_installer.ps1"
    installer_sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    provenance_sha = hashlib.sha256(provenance.read_bytes()).hexdigest()
    command = (
        f"& '{_ps_literal(script)}' -VerifyOnly "
        f"-ExpectedInstallerSha256 '{installer_sha}' "
        f"-ExpectedProvenanceSha256 '{provenance_sha}' "
        f"-VerifyPublishDirectory '{_ps_literal(publish)}'"
    )

    accepted = _run_powershell(command)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    provenance.write_text(
        provenance.read_text(encoding="utf-8").replace("a" * 40, "b" * 40, 1),
        encoding="utf-8",
    )
    rejected = _run_powershell(command)
    assert rejected.returncode != 0
    assert "provenance" in (rejected.stdout + rejected.stderr).lower()


def _lock_input_fingerprint(root: Path) -> str:
    records: list[tuple[str, int, str]] = []
    for relative in sorted(("requirements-build.txt", "requirements.txt"), key=str.lower):
        payload = (root / relative).read_bytes()
        records.append((relative, len(payload), hashlib.sha256(payload).hexdigest()))
    material = "".join(f"{path}\0{size}\0{digest}\n" for path, size, digest in records)
    return hashlib.sha256(material.encode()).hexdigest()


def _assert_shawl_legal_evidence_chain(
    build: str,
    installer: str,
    shawl_source: dict[str, object],
) -> None:
    legal = shawl_source["legal"]
    assert isinstance(legal, dict)
    assert build.count("legal_archive = [ordered]@{") == 1
    assert build.count("legal_notice = $legalNoticeEvidence") == 1
    assert build.count("legal_archive = $ShawlProvenance.legal_archive") == 1
    assert build.count("legal_notice = $ShawlProvenance.legal_notice") == 1
    assert build.count("shawl = $BuildInputs.shawl") == 1
    for producer_mapping in (
        "name = [string]$installerVendorContracts.shawl.legal.archive_name",
        "url = [string]$installerVendorContracts.shawl.legal.url",
        "sha256 = ([string]$installerVendorContracts.shawl.legal.sha256).ToLowerInvariant()",
    ):
        assert build.count(producer_mapping) == 1
    for value in (
        legal["archive_name"],
        legal["url"],
        legal["sha256"],
        legal["notice_name"],
        legal["notice_sha256"],
    ):
        assert isinstance(value, str) and value
    expected_entry = f'Source: "vendor\\shawl\\{legal["notice_name"]}"; DestDir: "{{app}}\\shawl"; Flags: ignoreversion'
    assert [line.strip() for line in installer.splitlines() if str(legal["notice_name"]) in line] == [expected_entry]


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
        "scripts/windows_python_build_environment.ps1",
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
    (dist / "ticketbox-database-maintenance.exe").write_bytes(b"database-maintenance-v1")
    (dist / "DATABASE_GENERATION_PROGRAM.json").write_text(
        '{"schema":"synthetic-generation-program"}', encoding="utf-8"
    )
    (dist / "_internal" / "runtime.dat").write_bytes(b"runtime-v1")
    packaged_target = dist / "_internal" / "migrations" / "versions" / target_migration
    packaged_target.parent.mkdir(parents=True)
    packaged_target.write_text("# target migration\n", encoding="utf-8")
    return dist


# Must match $script:TicketboxInstallerRecipeRelativePaths in
# backend/scripts/windows_build_provenance.ps1 (repo-root relative).
_INSTALLER_RECIPE_PATHS = (
    "backend/scripts/windows_build_provenance.ps1",
    "backend/scripts/windows_backend_build_provenance.ps1",
    "backend/scripts/windows_python_build_environment.ps1",
    "backend/requirements-build.lock",
    "backend/packaging/windows-build-toolchain.json",
    "backend/packaging/prepare_windows_build_toolchain.ps1",
    "backend/packaging/prepare_windows_installer_vendor.ps1",
    "backend/packaging/build_pg_bundle.ps1",
    "backend/packaging/languages/ChineseSimplified.isl",
    "backend/packaging/ticketbox.ico",
    "backend/packaging/windows-release-config.json",
    "distribution/windows/installer/ticketbox.iss",
    "distribution/windows/installer/setup_security.iss",
    "distribution/windows/installer/setup_lease.iss",
    "distribution/windows/installer/setup_private_result.iss",
    "distribution/windows/build/build_installer.ps1",
    "distribution/windows/build/check_source_inputs.ps1",
    "distribution/windows/build/installed_payload_manifest.ps1",
    "distribution/windows/build/ticketbox-lifecycle.spec",
    "distribution/windows/payload/release-manifest.json",
    "distribution/windows/lifecycle/ticketbox_lifecycle/__init__.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/__main__.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/cli.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/errors.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/schemas.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/adapters/__init__.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/adapters/ports.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/domain/__init__.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/domain/binding.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/domain/install.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/domain/planner.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/policy/__init__.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/policy/postgres_roles.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/policy/windows_scm_contract.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/__init__.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/command.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_process.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_account.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/durable_files.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/postgres_connection.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/layout.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/mutex.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/filesystem_stores.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_adapters.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_credentials.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_alembic.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_dataset.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_file_security.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_files.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_postgres.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_pgdata_security.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_postgres_identity.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_scm.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_scm_observation.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_security.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_security_native.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_known_folders.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_shipment.py",
    "distribution/windows/lifecycle/ticketbox_lifecycle/runtime/windows_services.py",
)


def _write_minimal_installer_recipe(root: Path) -> None:
    for relative in _INSTALLER_RECIPE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"recipe:{relative}\n", encoding="utf-8")


def _assert_installer_recipe_closes_the_lifecycle_source_set_and_bytes() -> None:
    lifecycle_prefix = "distribution/windows/lifecycle/ticketbox_lifecycle/"
    lifecycle_root = REPO_ROOT / "distribution" / "windows" / "lifecycle" / "ticketbox_lifecycle"
    source_paths = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in lifecycle_root.rglob("*.py")
    }
    listed_paths = {
        path for path in _INSTALLER_RECIPE_PATHS if path.startswith(lifecycle_prefix)
    }
    assert listed_paths == source_paths

    completed = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"Get-TicketboxInstallerRecipeSnapshot '{_ps_literal(REPO_ROOT / 'backend')}' | "
        "ConvertTo-Json -Depth 8"
    )
    assert completed.returncode == 0, completed.stderr
    snapshot = json.loads(completed.stdout)
    records = {record["path"]: record for record in snapshot["files"]}
    for relative in source_paths:
        source = REPO_ROOT / relative
        assert records[relative] == {
            "path": relative,
            "size": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }


def _database_maintenance_smoke_evidence_command(dist: Path) -> str:
    program = dist / "DATABASE_GENERATION_PROGRAM.json"
    return (
        f"$smokePayload = Get-TicketboxBackendPayloadSnapshot '{_ps_literal(dist)}'; "
        f"$helper = Get-TicketboxFileEvidence '{_ps_literal(dist)}' "
        f"'{_ps_literal(dist / 'ticketbox-database-maintenance.exe')}'; "
        f"$programSha = Get-TicketboxFileSha256 '{_ps_literal(program)}'; "
        "$result = [ordered]@{"
        "schema='ticketbox-database-generation-program-validation-v2';"
        "source_revision='base';target_revision='20260809_0001';revision_count=43;"
        "generation_program_sha256=$programSha}; "
        "$resultJson = $result | ConvertTo-Json -Depth 32 -Compress; "
        "$smoke = [ordered]@{"
        "schema='ticketbox-database-maintenance-helper-smoke-v1';helper=$helper;"
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
            f"{_database_maintenance_smoke_evidence_command(dist)}"
            f"{operation} -BackendRoot '{_ps_literal(root)}' "
            f"-DistDir '{_ps_literal(dist)}' -ToolchainProvenance $toolchain "
            f"-SourceSnapshot $source -DatabaseGenerationProgramPath "
            f"'{_ps_literal(dist / 'DATABASE_GENERATION_PROGRAM.json')}' "
            "-DatabaseMaintenanceHelperSmokeEvidence $smoke | Out-Null"
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
    assert "scripts/windows_python_build_environment.ps1" in source_paths
    assert "packaging/windows-build-toolchain.json" in source_paths
    assert "packaging/prepare_windows_build_toolchain.ps1" in source_paths
    assert "requirements-build.lock" in source_paths
    assert manifest["toolchain"]["python"]["version"] == "3.11.15"
    assert manifest["toolchain"]["uv"]["version"] == "0.11.7"
    assert manifest["toolchain"]["pyinstaller"]["version"] == "6.21.0"
    assert manifest["payload"]["executable"]["sha256"] == hashlib.sha256(b"frozen-exe-v1").hexdigest()
    smoke = manifest["payload"]["database_maintenance_helper_smoke"]
    assert smoke["helper"] == manifest["payload"]["database_maintenance_helper"]
    assert smoke["payload_algorithm"] == manifest["payload"]["algorithm"]
    assert smoke["payload_fingerprint"] == manifest["payload"]["fingerprint"]
    assert smoke["payload_file_count"] == len(manifest["payload"]["files"])
    assert smoke["stdin"] == "closed_empty_eof"
    assert smoke["environment"] == ("system-runtime-allowlist-without-pg-or-database-url-v1")
    assert smoke["exit_code"] == 0
    assert smoke["stderr"] == "empty"
    assert smoke["result"]["source_revision"] == "base"
    assert smoke["result"]["target_revision"] == "20260809_0001"
    assert smoke["result"]["generation_program_sha256"] == manifest["payload"]["database_generation_program"]["sha256"]

    validate = _manifest_command(backend, dist, "Assert-TicketboxBackendBuildManifest")
    assert _run_powershell(validate).returncode == 0

    manifest["payload"]["database_maintenance_helper_smoke"]["result"]["source_revision"] = "other"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_helper_smoke = _run_powershell(validate)
    assert tampered_helper_smoke.returncode != 0
    assert "generation helper" in (tampered_helper_smoke.stdout + tampered_helper_smoke.stderr).lower()
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

    recipe_repo = tmp_path / "recipe-repo"
    _write_minimal_installer_recipe(recipe_repo)
    recipe_backend = recipe_repo / "backend"
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

    changed_recipe = (
        recipe_repo / "distribution" / "windows" / "installer" / "ticketbox.iss"
    )
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


def test_installer_compiles_only_from_locked_snapshot_and_clean_git() -> None:
    _assert_installer_recipe_closes_the_lifecycle_source_set_and_bytes()
    build = (
        REPO_ROOT / "distribution" / "windows" / "build" / "build_installer.ps1"
    ).read_text(encoding="utf-8-sig")
    provenance = PROVENANCE_HELPER.read_text(encoding="utf-8-sig")
    toolchain = json.loads(
        (REPO_ROOT / "backend" / "packaging" / "windows-build-toolchain.json").read_text(
            encoding="utf-8"
        )
    )

    assert toolchain["python_version"] == "3.11.16"
    assert toolchain["build_tool_sources"]["python"] == {
        "version": "3.11.16",
        "archive_name": "cpython-3.11.16+20260825-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20260825/cpython-3.11.16%2B20260825-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        "sha256": "f91242b07e318d2540f9da71162b92d494c39745abde9b994d7d906756453fc9",
        "archive_payload_root": "python",
        "executable_relative_path": "python.exe",
        "executable_sha256": "f2bb6d49cdd2fb49d0ce63c2a0143da37d9a4d52694803c2f92fd31db7fcb88b",
        "runtime_relative_path": "python311.dll",
        "runtime_sha256": "d736a23d96e127fb01c0508efadeb08a47363c7b17d54a03de7ec6e881549d0d",
    }

    assert "$BuildLock = Enter-TicketboxWindowsBuildLock $BackendRoot" in build
    assert "$RecipeLocks = Enter-TicketboxFileSetReadLocks" in build
    assert "$ShipmentLocks = Enter-TicketboxFileSetReadLocks" in build
    assert build.count("Copy-TicketboxFileSetSnapshot") >= 2
    assert "$StagedIssPath" in build
    assert "@defines $StagedIssPath" in build
    assert "@defines $IssPath" not in build
    assert "if ([bool]$git.dirty)" in build
    assert "$manifestTemplatePath = Join-Path $StagedPayloadDir" in build
    assert "--distpath $StagedPayloadDir" in build
    assert "--distpath $PayloadDir" not in build
    assert "$startupProbeOutput = @(& $lifecycleExe --help 2>&1)" in build
    assert '$lifecycleToolchain["startup_probe"] = [ordered]@{' in build
    assert "tree =" in provenance
    assert "$manifest.git.tree -cne $currentGit.tree" in provenance


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
        assert "distribution\\windows\\build\\check_source_inputs.ps1" in text
        assert (
            "distribution\\windows\\build\\build_installer.ps1 "
            "-InstallerHashOutputFile"
        ) in text
        assert (
            "distribution\\windows\\build\\build_installer.ps1 "
            "-VerifyOnly"
        ) in text
        assert "build_inno_installer.ps1" not in text
        assert "CheckSourceInputsOnly" not in text
        assert "CheckInputsOnly" not in text
