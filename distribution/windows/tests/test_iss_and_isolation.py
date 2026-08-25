from __future__ import annotations

from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
ISS = WINDOWS / "installer" / "ticketbox.iss"
LIFECYCLE = WINDOWS / "lifecycle"
LIFECYCLE_SPEC = WINDOWS / "build" / "ticketbox-lifecycle.spec"
INSTALLED_MANIFEST = WINDOWS / "build" / "installed_payload_manifest.ps1"
BUILD_INSTALLER = WINDOWS / "build" / "build_installer.ps1"


FORBIDDEN_TOKENS = (
    "windows_lifecycle_receipt.ps1",
    "windows_owner_handoff.ps1",
    "hold_installer_lifecycle_lock.ps1",
    "DATABASE_GENERATION_PROGRAM.json",
    "ticketbox-windows-lifecycle-receipt-v9",
    "install_bundled_services.ps1",
    "prepare_bundled_upgrade.ps1",
)


def _iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".pyc", ".png", ".ico", ".exe"}:
            continue
        files.append(path)
    return files


def test_new_tree_does_not_import_old_packaging_owners() -> None:
    roots = (WINDOWS / "installer", WINDOWS / "lifecycle", WINDOWS / "build")
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(_iter_text_files(root))
    for path in files:
        if path.name in {"check_source_inputs.ps1", "ticketbox.iss", "build_installer.ps1"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        assert "backend/packaging" not in lower.replace("\\", "/")
        assert "backend\\packaging" not in text
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"{path} still names {token}"


def test_iss_prepare_is_readonly_and_postinstall_only_observes_run_results() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    assert "[Setup]" in text
    assert "PrivilegesRequired=admin" in text
    assert "CloseApplications=no" in text
    assert "CloseApplications=yes" not in text
    assert "PrepareToInstall" in text
    assert "TicketboxExactActiveCanContinue" in text
    assert "TicketboxCommittedReplayCanContinue" in text
    assert "FileExists(BindingPath) and (not TicketboxCommittedReplayCanContinue())" in text
    assert "Utf8Encode(Payload)" in text
    assert "AnsiString(Payload)" not in text
    assert "Command := 'resume'" in text
    assert "TicketboxLifecycle.exe" in text
    assert any(line.strip() == "[Run]" for line in text.splitlines())
    run_section = text.split("[Run]", 1)[1].split("[", 1)[0]
    assert "vc_redist.x64.exe" in run_section
    assert "TicketboxLifecycle.exe" in run_section
    assert "{code:TicketboxLifecycleParams}" in run_section
    assert "nowait" not in run_section.lower()
    assert "shellexec" not in run_section.lower()
    assert "ignoreerrors" not in run_section.lower()
    assert "postinstall" not in run_section.lower()
    assert "AfterInstall: TicketboxProvision" not in text
    assert "TicketboxLifecycleParams" in text
    assert "waituntilterminated" in text.lower()
    assert "GetCustomSetupExitCode" in text
    assert "CurStepChanged" in text
    assert "ssPostInstall" in text
    postinstall = text.split("procedure CurStepChanged", 1)[1]
    assert "Exec(" not in postinstall
    assert "RaiseException" not in postinstall
    code_section = text.split("[Code]", 1)[1]
    assert "Exec(" not in code_section
    assert "RaiseException" not in code_section
    assert "TicketboxInstallFailed" in text
    assert "安装未完成" in text
    assert "FinishedHeadingLabel.Caption" in text
    assert "TicketboxResultIsCommitted" in text
    assert "Observed <> OperationId" in text
    assert '"ok": false' in text
    assert "active.json" in text
    assert "operations\\history" in text
    assert "fresh-{#ReleaseManifestSha256}" in text
    assert "resume" in text
    assert '"ok": true' in text
    assert '"phase": "committed"' in text
    assert "last-result.json" not in text
    assert "ticketbox-install-result.json" in text
    files_section = text.split("[Files]", 1)[1].split("[", 1)[0]
    assert "TicketboxBackendLauncher.exe" not in files_section
    assert "vc_redist.x64.exe" in files_section
    assert "dontcopy" not in files_section.lower()
    assert "onlyifdoesntexist" in files_section.lower()
    assert "Check: TicketboxExactResumeMaterialization" in files_section
    assert "Check: TicketboxFreshMaterialization" in files_section
    assert "ExtractTemporaryFile" not in text
    assert "VCRUNTIME140.dll" in text
    assert "install_bundled_services.ps1" not in text
    assert "powershell" not in text.lower()
    assert "GetSHA256OfFile" in text
    assert "TicketboxExpectedReleaseManifestSha256" in text
    assert "LowerCase(GetSHA256OfFile(ManifestPath))" in text
    assert "ManifestSha <> LowerCase(TicketboxExpectedReleaseManifestSha256)" in text
    assert "release_manifest_sha256" in text
    prepare = text.split("function PrepareToInstall", 1)[1].split("end;", 1)[0]
    assert "TicketboxEnsureMsvcRuntime" not in prepare
    for token in FORBIDDEN_TOKENS:
        assert token not in text


def test_setup_refuses_every_install_root_except_exact_program_files() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    prepare = text.split("function PrepareToInstall", 1)[1].split(
        "function TicketboxMsvcRuntimeIsCurrent", 1
    )[0]

    assert "DefaultDirName={autopf}\\Ticketbox" in text
    assert "DisableDirPage=yes" in text
    assert "UsePreviousAppDir=no" in text
    assert "TicketboxInstallRootIsExact" in prepare
    assert "{autopf}\\Ticketbox" in text
    assert "安装目录必须是受保护的 Program Files" in prepare


def test_setup_failure_surfaces_include_the_actual_log_path() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    postinstall = text.split("procedure CurStepChanged", 1)[1]

    assert "ExpandConstant('{log}')" in postinstall
    assert "安装日志：" in postinstall
    assert "Log('Ticketbox install failed: ' + Reason)" in text


def test_prepare_to_install_failures_surface_reason_retry_and_log() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    helper = text.split("function TicketboxPrepareFailure", 1)[1].split(
        "function PrepareToInstall", 1
    )[0]
    prepare = text.split("function PrepareToInstall", 1)[1].split(
        "function TicketboxMsvcRuntimeIsCurrent", 1
    )[0]

    assert "Log('Ticketbox preflight failed: ' + Reason)" in helper
    assert "重新运行同一个安装包" in helper
    assert "ExpandConstant('{log}')" in helper
    assert prepare.count("Result := TicketboxPrepareFailure(") == 5
    literal_assignments = [
        line.strip()
        for line in prepare.splitlines()
        if line.strip().startswith("Result := '")
    ]
    assert literal_assignments == ["Result := '';"]


def test_elevated_lifecycle_is_an_installed_onedir_payload() -> None:
    spec = LIFECYCLE_SPEC.read_text(encoding="utf-8")
    installer = ISS.read_text(encoding="utf-8-sig")
    manifest = INSTALLED_MANIFEST.read_text(encoding="utf-8-sig")

    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert "PyInstaller onefile" not in spec
    assert 'Source: "..\\payload\\TicketboxLifecycle\\*"' in installer
    assert "recursesubdirs createallsubdirs" in installer
    assert 'Filename: "{app}\\bin\\lifecycle\\TicketboxLifecycle.exe"' in installer
    assert 'WorkingDir: "{app}\\bin\\lifecycle"' in installer
    assert '"bin/lifecycle"' in manifest
    assert 'Source = Join-Path $StagedPayloadDir "TicketboxLifecycle.exe"' not in manifest


def test_lifecycle_freeze_uses_only_the_exact_pinned_python() -> None:
    build = BUILD_INSTALLER.read_text(encoding="utf-8-sig")

    assert r'build\windows-toolchain' in build
    assert '("python\\{0}"' in build
    assert "prepare_windows_build_toolchain.ps1" in build
    assert "-Component Backend" in build
    assert "Get-TicketboxFileSetSnapshot $ToolchainRoot $toolchainPaths" in build
    assert "Enter-TicketboxFileSetReadLocks" in build
    assert "Pinned lifecycle build toolchain" in build
    assert "New-TicketboxBackendBuildToolchainProvenance" in build
    assert '$BuildInputs["lifecycle"]' in build
    assert "& $venvPython -I -B -m PyInstaller" in build
    assert "--clean" in build
    assert "Enter-TicketboxSealedPythonBuildEnvironment" in build
    assert "-PyInstallerConfigDirectory $LifecyclePyInstallerConfig" in build
    assert "[Environment]::SetEnvironmentVariable" not in build
    assert "& $lifecyclePython -m venv" not in build
    assert "Get-Command python" not in build
    assert "expectedPythonPrefix" not in build
    assert ".StartsWith($expectedPython" not in build


def test_old_fresh_iss_is_not_the_shipped_installer() -> None:
    old = REPO / "backend" / "packaging" / "ticketbox-installer.iss"
    assert not old.exists(), "old Inno recipe must be physically deleted from shipment"


def test_installer_verifies_msvc_runtime_is_not_older_than_bundled_redist() -> None:
    text = ISS.read_text(encoding="utf-8-sig")

    assert "GetVersionNumbersString(TicketboxMsvcRedistSource)" in text
    assert "GetPackedVersion(RuntimePath, InstalledVersion)" in text
    assert "StrToVersion(TicketboxRequiredMsvcRuntimeVersion, RequiredVersion)" in text
    assert "ComparePackedVersion(InstalledVersion, RequiredVersion) < 0" in text
