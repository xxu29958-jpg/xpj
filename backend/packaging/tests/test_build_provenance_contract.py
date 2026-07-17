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

pytestmark = pytest.mark.packaging_resource("hermetic")

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent
PACKAGING = ROOT / "packaging"
PROVENANCE_HELPER = ROOT / "scripts" / "windows_build_provenance.ps1"


def _ps_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _run_powershell(
    command: str, executable: str = "powershell"
) -> subprocess.CompletedProcess[str]:
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
    (root / "migrations").mkdir()
    (root / "packaging").mkdir()
    (root / "scripts").mkdir()
    (root / "app" / "version.py").write_text('BACKEND_VERSION = "7.8.9"\n', encoding="utf-8")
    (root / "app" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "migrations" / "env.py").write_text("# migration\n", encoding="utf-8")
    for relative in (
        "alembic.ini",
        "requirements.txt",
        "requirements-build.txt",
        "requirements-build.lock",
        "packaging/prepare_windows_build_toolchain.ps1",
        "packaging/launch.py",
        "packaging/ticketbox-backend.spec",
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
                        "executable_sha256": hashlib.sha256(
                            python_source_payload
                        ).hexdigest(),
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
        f"# ticketbox-lock-input-sha256: {_lock_input_fingerprint(root)}\n"
        "pyinstaller==6.21.0\n",
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
    (dist / "_internal" / "runtime.dat").write_bytes(b"runtime-v1")
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
    "packaging/windows_service_lifecycle.ps1",
    "packaging/windows_installation_safety.ps1",
    "packaging/windows_lifecycle_receipt.ps1",
    "packaging/windows_lifecycle_lock.ps1",
    "packaging/hold_installer_lifecycle_lock.ps1",
    "packaging/hold_data_root_mutation_guard.ps1",
    "packaging/windows_database_safety.ps1",
    "packaging/windows_pg_recovery_tools.ps1",
    "packaging/windows_bundled_database.ps1",
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
            f"{operation} -BackendRoot '{_ps_literal(root)}' "
            f"-DistDir '{_ps_literal(dist)}' -ToolchainProvenance $toolchain "
            "-SourceSnapshot $source | Out-Null"
        )
    else:
        toolchain = ""
        invocation = f"{operation} '{_ps_literal(root)}' '{_ps_literal(dist)}' | Out-Null"
    return (
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"{toolchain}{invocation}"
    )


def test_backend_manifest_rejects_source_and_executable_mutation(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    dist = _write_minimal_backend(backend)
    write = _run_powershell(
        _manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest")
    )
    assert write.returncode == 0, write.stderr

    manifest_path = dist / "BUILD_PROVENANCE.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 3
    assert manifest["artifact_type"] == "ticketbox-frozen-backend"
    assert manifest["backend_version"] == "7.8.9"
    assert len(manifest["source"]["fingerprint"]) == 64
    assert len(manifest["payload"]["fingerprint"]) == 64
    source_paths = {record["path"] for record in manifest["source"]["files"]}
    assert "scripts/build_backend_exe.ps1" in source_paths
    assert "scripts/windows_build_provenance.ps1" in source_paths
    assert "scripts/windows_backend_build_provenance.ps1" in source_paths
    assert "packaging/windows-build-toolchain.json" in source_paths
    assert "packaging/prepare_windows_build_toolchain.ps1" in source_paths
    assert "requirements-build.lock" in source_paths
    assert manifest["toolchain"]["python"]["version"] == "3.11.15"
    assert manifest["toolchain"]["uv"]["version"] == "0.11.7"
    assert manifest["toolchain"]["pyinstaller"]["version"] == "6.21.0"
    assert manifest["payload"]["executable"]["sha256"] == hashlib.sha256(
        b"frozen-exe-v1"
    ).hexdigest()

    validate = _manifest_command(backend, dist, "Assert-TicketboxBackendBuildManifest")
    assert _run_powershell(validate).returncode == 0

    manifest["toolchain"]["pyinstaller"]["version"] = "6.20.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_toolchain = _run_powershell(validate)
    assert tampered_toolchain.returncode != 0
    assert "toolchain" in (tampered_toolchain.stdout + tampered_toolchain.stderr).lower()
    rewrite = _run_powershell(
        _manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest")
    )
    assert rewrite.returncode == 0, rewrite.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["source"]["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_source_record = _run_powershell(validate)
    assert tampered_source_record.returncode != 0
    assert "source" in (
        tampered_source_record.stdout + tampered_source_record.stderr
    ).lower()
    rewrite = _run_powershell(
        _manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest")
    )
    assert rewrite.returncode == 0, rewrite.stderr

    (backend / "app" / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    stale_source = _run_powershell(validate)
    assert stale_source.returncode != 0
    assert "rebuild" in (stale_source.stdout + stale_source.stderr).lower()

    rewrite = _run_powershell(
        _manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest")
    )
    assert rewrite.returncode == 0, rewrite.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runtime_record = next(
        record
        for record in manifest["payload"]["files"]
        if record["path"] == "_internal/runtime.dat"
    )
    runtime_record["sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_non_exe_record = _run_powershell(validate)
    assert tampered_non_exe_record.returncode != 0
    assert "payload" in (
        tampered_non_exe_record.stdout + tampered_non_exe_record.stderr
    ).lower()

    rewrite = _run_powershell(
        _manifest_command(backend, dist, "Write-TicketboxBackendBuildManifest")
    )
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
    assert {record["path"] for record in original_snapshot["files"]} == set(
        _INSTALLER_RECIPE_PATHS
    )
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


def test_installer_build_probes_and_records_local_vendor_provenance(
    tmp_path: Path,
) -> None:
    build = (PACKAGING / "build_inno_installer.ps1").read_text(encoding="utf-8-sig")
    installer = (PACKAGING / "ticketbox-installer.iss").read_text(encoding="utf-8")
    backend_spec = (PACKAGING / "ticketbox-backend.spec").read_text(encoding="utf-8")
    backend_build = (ROOT / "scripts" / "build_backend_exe.ps1").read_text(
        encoding="utf-8-sig"
    )
    toolchain_preparer = (PACKAGING / "prepare_windows_build_toolchain.ps1").read_text(
        encoding="utf-8-sig"
    )
    vendor_preparer = (PACKAGING / "prepare_windows_installer_vendor.ps1").read_text(
        encoding="utf-8-sig"
    )
    pg_bundler = (PACKAGING / "build_pg_bundle.ps1").read_text(encoding="utf-8-sig")
    toolchain = json.loads(
        (PACKAGING / "windows-build-toolchain.json").read_text(encoding="utf-8")
    )
    postgres_source = toolchain["installer_vendor_sources"]["postgresql"]
    shawl_source = toolchain["installer_vendor_sources"]["shawl"]
    build_tool_sources = toolchain["build_tool_sources"]

    assert '$backendManifest = Assert-TicketboxBackendBuildManifest' in build
    assert "Remove-TicketboxPublishDirectoryVerified $targetPublishDir $publishRoot" not in build
    assert build.index("$InstallerBuildManifest") < build.index(
        '$backendManifest = Assert-TicketboxBackendBuildManifest'
    )
    assert 'Invoke-TicketboxExecutableProbe $postgresExe @("--version")' in build
    assert 'Invoke-TicketboxExecutableProbe $ExecutablePath @("--version")' in build
    assert 'Invoke-TicketboxExecutableProbe $ExecutablePath @("--help")' in build
    assert 'Assert-TicketboxVendorVersionAllowed $releaseConfig "postgres" $version' in build
    assert 'Assert-TicketboxVendorVersionAllowed $releaseConfig "shawl" $version' in build
    assert 'foreach ($directory in @("bin", "lib", "share"))' in build
    assert 'Read-TicketboxPgBundleManifest $bundleManifestPath' in build
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
    assert '"/DLifecycleLockScriptSha256=$(Get-TicketboxFileSha256 $LockScript)"' in build
    assert '"/DLifecycleHolderScriptSha256=$(Get-TicketboxFileSha256 $LockHolderScript)"' in build
    assert 'upstream_authenticity_verified = $false' in build
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
    assert "Get-TicketboxIsccEngineVersion" in PROVENANCE_HELPER.read_text(
        encoding="utf-8-sig"
    )
    assert "compiler_defines = @(Get-TicketboxNormalizedCompilerDefines $CompilerDefines)" in build
    assert "toolchain = $BackendManifest.toolchain" in build
    assert build.index("if ($CheckInputsOnly)") < build.index(
        "$installerBuild = Write-InstallerBuildProvenance"
    )
    assert build.index("Get-TicketboxIsccProvenance $iscc") < build.index(
        "& $iscc @defines \"/O$compilerOutputDir\" $stagedIssPath"
    )
    assert "Assert-File $stagedInstaller \"本轮 ISCC staging 安装包输出\"" in build
    assert build.index("& $iscc @defines") < build.index(
        "$currentBackendManifest = Assert-TicketboxBackendBuildManifest"
    )
    assert build.index("& $iscc @defines") < build.index(
        "$currentPostgresProvenance = Get-ValidatedPostgresProvenance"
    )
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
    assert vendor_preparer.index("$executableHash = Get-TicketboxStreamSha256") < (
        vendor_preparer.index("--version")
    )
    assert "Get-TicketboxValidatedPgZipEntry" in pg_bundler
    assert "Get-FileHash" not in pg_bundler
    assert pg_bundler.index("Get-TicketboxValidatedPgZipEntry $entry") < pg_bundler.index(
        '$full.StartsWith("pgsql/"'
    )
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
    before_tree = backend_build.index(
        "$executionTreeBeforeFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild"
    )
    freeze = backend_build.index("& $PyBuild -I -B -m PyInstaller `")
    after_tree = backend_build.index(
        "$executionTreeAfterFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild"
    )
    assert before_tree < freeze < after_tree
    assert "PyInstaller interpreter and site-packages during freeze" in backend_build
    assert "Enter-TicketboxWindowsBuildLock $BackendRoot" in backend_build
    assert "Publish-TicketboxInstallerUnit `" in build
    assert "Enter-TicketboxWindowsBuildLock $BackendRoot" in build
    for writer in (toolchain_preparer, vendor_preparer, pg_bundler):
        assert "Enter-TicketboxWindowsBuildLock $BackendRoot" in writer
        assert "Exit-TicketboxWindowsBuildLock $BuildLock" in writer
    lock_helper = (ROOT / "scripts" / "windows_backend_build_provenance.ps1").read_text(
        encoding="utf-8-sig"
    )
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

    github_ci = (ROOT.parent / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    gitea_ci = (ROOT.parent / ".gitea" / "workflows" / "windows-ci.yml").read_text(
        encoding="utf-8"
    )
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

    config = json.loads(
        (PACKAGING / "windows-release-config.json").read_text(encoding="utf-8")
    )
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
        f"& '{_ps_literal(build_path)}' "
        f"-ReleaseConfigOverride '{_ps_literal(config_path)}' -CheckSourceInputsOnly"
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
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        "Get-TicketboxNormalizedCompilerDefines @('/DAlpha=1','/DAlpha=2')"
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
    assert build_script.index(call) < build_script.index(
        "$manifestPath = Write-TicketboxBackendBuildManifest"
    )
    assert build_script.index(call) < build_script.index(
        "Publish-TicketboxRecoverableDirectory `"
    )


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

    backend_build = (ROOT / "scripts" / "build_backend_exe.ps1").read_text(
        encoding="utf-8-sig"
    )
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
    recoverable_publish = build_script.index(
        "Publish-TicketboxRecoverableDirectory `", publish_function
    )
    assert function_validation < recoverable_publish
    staging_validation = build_script.rindex(call)
    publish_call = build_script.rindex("Publish-TicketboxInstallerUnit `")
    assert staging_validation < publish_call


def _assert_external_publish_directory_name_is_not_authority(build_script: str) -> None:
    verify_only = build_script[
        build_script.index("if ($VerifyOnly) {") : build_script.index(
            '$buildStagingRoot = Join-Path $BackendRoot',
        )
    ]
    assert "$expectedVerifyDirectoryName = if ($VerifyPublishDirectory.Trim().Length -eq 0)" in verify_only
    assert '-ExpectedDirectoryName $expectedVerifyDirectoryName' in verify_only
    external_branch = verify_only[
        verify_only.index("$expectedVerifyDirectoryName = if") : verify_only.index(
            "$verifiedPublish = Assert-TicketboxInstallerPublishUnit",
        )
    ]
    assert "$publishUnitName" in external_branch
    assert 'else {\n        ""\n    }' in external_branch


@pytest.mark.packaging_resource("windows_host")
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
    assert _run_powershell(
        downloaded_command.replace(
            "-ExpectedDirectoryName ''",
            f"-ExpectedDirectoryName 'Ticketbox-Setup-{version}'",
            1,
        )
    ).returncode != 0

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
        'else {\n        $publishUnitName\n    }\n    $verifiedPublish',
        1,
    )
    with pytest.raises(AssertionError):
        _assert_external_publish_directory_name_is_not_authority(
            external_directory_mutation
        )
    _assert_installer_publish_swap_rolls_back_and_then_replaces_atomically(
        tmp_path / "atomic-swap"
    )
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
        assert output_path.read_bytes() == (
            f"installer_sha256={trusted_hash}{os.linesep}".encode()
        )

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
                "try { Start-Sleep -Seconds 4 } finally { "
                "Exit-TicketboxWindowsBuildLock $lock }"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for _ in range(40):
        if ready.exists():
            break
        time.sleep(0.1)
    assert ready.exists(), holder.communicate(timeout=5)
    blocked = _run_powershell(
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"Enter-TicketboxWindowsBuildLock '{_ps_literal(tmp_path)}' 1 | Out-Null"
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


@pytest.mark.packaging_resource("windows_host")
def test_windows_build_lock_is_bound_to_current_requirement_inputs(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    _write_minimal_backend(backend)
    command = (
        f". '{_ps_literal(PROVENANCE_HELPER)}'; "
        f"Read-TicketboxWindowsBuildToolchain '{_ps_literal(backend)}' | Out-Null"
    )
    assert _run_powershell(command).returncode == 0

    (backend / "requirements.txt").write_text("sample==2.0.0\n", encoding="utf-8")
    stale = _run_powershell(command)
    assert stale.returncode != 0
    assert "stale" in (stale.stdout + stale.stderr).lower()
    _assert_windows_build_reparse_guard_rejects_ancestor_and_tree_junctions(
        tmp_path / "reparse"
    )
    _assert_windows_build_lock_serializes_and_execution_tree_detects_drift(
        tmp_path / "lock-and-drift"
    )
    _assert_recoverable_directory_publication_handles_interrupted_swap_states(
        tmp_path / "publication-recovery"
    )


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
    assert "Start-Transcript -LiteralPath $LogPath -Append -Force" in windows
    assert "HardenLifecycleLockPath(LogPath, False)" in windows
    assert "could not start PowerShell" not in windows
    assert "failed. PowerShell exit code" not in windows
    assert "\u9000\u51fa\u7801" in windows
    assert "\u8be6\u7ec6\u65e5\u5fd7\uff1a" in windows

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
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' "
        "-VersionFloorContractProbe '1.2.0||1.1.9|true'"
    )
    assert allow.returncode == 0, allow.stderr
    assert allow.stdout.strip() == "allow"
    downgrade = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' "
        "-VersionFloorContractProbe '1.1.9||1.2.0|true'"
    )
    assert downgrade.returncode != 0
    missing_trusted_version = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' "
        "-VersionFloorContractProbe '1.2.0|||true'"
    )
    assert missing_trusted_version.returncode != 0
    fresh_probe = _run_powershell(
        f"& '{_ps_literal(PACKAGING / 'build_inno_installer.ps1')}' "
        "-VersionFloorContractProbe '1.2.0|||false'"
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
        assert "XPJ_AUDIT_DEFAULT_REF: refs/remotes/origin/main" in text
