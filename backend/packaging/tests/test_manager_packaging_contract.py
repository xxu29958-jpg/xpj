from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
PACKAGING = BACKEND_ROOT / "packaging"
DESKTOP = REPO_ROOT / "desktop"


def _read(path: Path, *, sig: bool = False) -> str:
    return path.read_text(encoding="utf-8-sig" if sig else "utf-8")


def _ps_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def test_manager_frozen_payload_is_a_separate_windowed_adapter() -> None:
    spec = _read(DESKTOP / "packaging" / "ticketbox-manager.spec")
    build = _read(DESKTOP / "scripts" / "build_manager_exe.ps1", sig=True)
    provenance = _read(
        DESKTOP / "scripts" / "windows_manager_build_provenance.ps1",
        sig=True,
    )

    assert 'name="ticketbox-manager"' in spec
    assert "console=False" in spec
    assert '"backend_manager", "ui.html"' in spec
    assert '"backend", "packaging", "ticketbox.ico"' in spec
    assert "Enter-TicketboxWindowsBuildLock $BackendRoot" in build
    assert "Get-TicketboxManagerSourceSnapshot $RepoRoot" in build
    assert "Copy-TicketboxFileSetSnapshot" in build
    assert "New-TicketboxManagerBuildToolchainProvenance" in build
    assert "Publish-TicketboxRecoverableDirectory" in build
    assert 'artifact_type = "ticketbox-frozen-desktop-manager"' in provenance
    assert 'Join-Path $DistDir "ticketbox-manager.exe"' in provenance
    assert "Assert-TicketboxManagerToolchainEvidence" in provenance


def test_inno_installs_manager_and_launches_only_as_the_original_user() -> None:
    installer = _read(PACKAGING / "ticketbox-installer.iss")
    flow = _read(PACKAGING / "ticketbox-installer-flow.isph")
    build = _read(PACKAGING / "build_inno_installer.ps1", sig=True)
    shared_provenance = _read(
        BACKEND_ROOT / "scripts" / "windows_build_provenance.ps1",
        sig=True,
    )

    assert (
        'Source: "..\\..\\desktop\\dist\\ticketbox-manager\\*"; '
        'DestDir: "{app}\\manager"; Flags: ignoreversion recursesubdirs createallsubdirs'
    ) in installer
    assert 'Name: "{autoprograms}\\小票夹\\管理小票夹"' in installer
    assert 'Filename: "{app}\\manager\\ticketbox-manager.exe"' in installer
    assert "CloseApplications=yes" in installer
    assert "RestartApplications=no" in installer
    assert "postinstall" not in installer
    assert "ExecAsOriginalUser(" in flow
    assert "Exec(" not in flow[flow.index("ManagerLaunchAttempted := True") :]
    assert "完成后打开小票夹管理器（推荐）" in flow
    assert flow.index("ReleaseLifecycleLock") < flow.index("ExecAsOriginalUser(")
    assert "$managerManifest = Assert-TicketboxManagerBuildManifest $RepoRoot $ManagerDist" in build
    assert "manager = [ordered]@{" in build
    assert "manager = $BuildInputs.manager" in build
    assert '"安装器 Desktop Manager provenance"' in shared_provenance
    assert "$manifest.manager" in shared_provenance
    assert "$ExpectedBuildInputs.manager" in shared_provenance
    assert "Copy-Item -Path (Join-Path $ManagerDist \"*\")" in build
    assert "Get-ChildItem -LiteralPath $stagedRepoRoot -Recurse -File" in build


def test_inno_replaces_each_immutable_payload_directory_before_copy() -> None:
    installer = _read(PACKAGING / "ticketbox-installer.iss")
    flow = _read(PACKAGING / "ticketbox-installer-flow.isph")
    install_delete = installer.index("[InstallDelete]")
    files = installer.index("[Files]")

    assert install_delete < files
    for destination in (
        r"{app}\program\ticketbox-backend\*",
        r"{app}\manager\*",
        r"{app}\pg\*",
        r"{app}\shawl\*",
        r"{app}\installer\*",
    ):
        assert (
            f'Type: filesandordirs; Name: "{destination}"; '
            "Check: AuthoritativePayloadReplacementPrepared"
        ) in installer
    assert "function AuthoritativePayloadReplacementPrepared(): Boolean;" in flow
    assert (
        "Result := LifecyclePrepared and\n"
        "    (not LifecycleExistingOperationCompleted);"
    ) in flow


def test_windows_release_lanes_build_manager_before_inno() -> None:
    for workflow in (
        REPO_ROOT / ".github" / "workflows" / "ci.yml",
        REPO_ROOT / ".gitea" / "workflows" / "windows-ci.yml",
    ):
        text = _read(workflow)
        manager_step = text.index("Frozen Desktop Manager locked release build")
        manager_command = text.index("desktop\\scripts\\build_manager_exe.ps1", manager_step)
        inno_step = text.index("Compile authoritative Inno installer")
        assert '"desktop/scripts"' in text
        assert manager_step < manager_command < inno_step


@pytest.mark.parametrize("executable", powershell_contract_engines())
def test_manager_source_contract_is_identical_across_powershell_engines(
    executable: str,
) -> None:
    command = (
        f". '{_ps_literal(BACKEND_ROOT / 'scripts' / 'windows_build_provenance.ps1')}'; "
        f". '{_ps_literal(BACKEND_ROOT / 'scripts' / 'windows_backend_build_provenance.ps1')}'; "
        f". '{_ps_literal(DESKTOP / 'scripts' / 'windows_manager_build_provenance.ps1')}'; "
        f"$contract = Read-TicketboxManagerBuildContract '{_ps_literal(REPO_ROOT)}'; "
        f"$snapshot = Get-TicketboxManagerSourceSnapshot '{_ps_literal(REPO_ROOT)}'; "
        "Write-Output ($contract.toolchain.pyinstaller_version + '|' + $snapshot.fingerprint)"
    )
    result = subprocess.run(
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
    assert result.returncode == 0, result.stderr
    version, fingerprint = result.stdout.strip().split("|", 1)
    assert version == "6.21.0"
    assert len(fingerprint) == 64


@pytest.mark.parametrize("executable", powershell_contract_engines())
def test_installer_provenance_binds_manager_evidence_and_rejects_tampering(
    executable: str,
    tmp_path: Path,
) -> None:
    build_path = PACKAGING / "build_inno_installer.ps1"
    manifest_path = tmp_path / "BUILD_PROVENANCE.json"
    command = (
        f". '{_ps_literal(BACKEND_ROOT / 'scripts' / 'windows_build_provenance.ps1')}'; "
        f"$scriptPath = '{_ps_literal(build_path)}'; "
        "$tokens = $null; $errors = $null; "
        "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
        "$scriptPath, [ref]$tokens, [ref]$errors); "
        "$functionAst = $ast.FindAll({ param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
        "-and $node.Name -ceq 'Write-InstallerBuildProvenance' }, $true) | "
        "Select-Object -First 1; "
        "if ($null -eq $functionAst) { throw 'writer function missing' }; "
        "Invoke-Expression $functionAst.Extent.Text; "
        f"$root = '{_ps_literal(BACKEND_ROOT)}'; "
        f"$manifestPath = '{_ps_literal(manifest_path)}'; "
        "$recipe = Get-TicketboxInstallerRecipeSnapshot $root; "
        "$git = Get-TicketboxGitProvenance $root; "
        "$compiler = [pscustomobject]@{ "
        "product_name = 'Inno Setup'; product_version = '6.7.1'; "
        "file_version = '6.7.1.0'; engine_version = '6.7.1'; "
        "version_policy = [ordered]@{ exact = '6.7.1' }; "
        "executable = [ordered]@{ path = 'ISCC.exe'; size = 123; sha256 = ('a' * 64) } }; "
        "$inputs = [ordered]@{ "
        "backend = [ordered]@{ version = '1.2.0'; fingerprint = ('b' * 64) }; "
        "manager = [ordered]@{ version = '1.2.0'; fingerprint = ('c' * 64) }; "
        "postgresql = [ordered]@{ version = '17.10-1'; fingerprint = ('d' * 64) }; "
        "shawl = [ordered]@{ version = '1.9.0'; fingerprint = ('e' * 64) }; "
        "installed_payload_budget = [ordered]@{ "
        "InstalledPayloadRequiredBytes = 1024; InstalledPayloadFileCount = 1; "
        "generated_manifest_max_bytes = 512; "
        "derivation = 'verified_installed_file_sizes_plus_bounded_generated_manifest' } }; "
        "$defines = @('/DAppVersion=1.2.0'); "
        "Write-InstallerBuildProvenance $inputs $recipe $git $compiler $defines $manifestPath | Out-Null; "
        "Assert-TicketboxInstallerBuildProvenance $root $manifestPath $compiler $inputs $defines | Out-Null; "
        "$recorded = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json; "
        "if ($null -eq $recorded.manager -or $recorded.manager.fingerprint -cne ('c' * 64)) { "
        "throw 'manager evidence was not persisted' }; "
        "$recorded.manager.fingerprint = ('f' * 64); "
        "Write-TicketboxJsonFile $manifestPath $recorded; "
        "$rejected = $false; try { "
        "Assert-TicketboxInstallerBuildProvenance $root $manifestPath $compiler $inputs $defines | Out-Null "
        "} catch { $rejected = $true }; "
        "if (-not $rejected) { throw 'tampered manager evidence was accepted' }"
    )
    result = subprocess.run(
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
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
