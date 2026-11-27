from __future__ import annotations

from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
ISS = WINDOWS / "installer" / "ticketbox.iss"
SETUP_LEASE = WINDOWS / "installer" / "setup_lease.iss"
SETUP_SECURITY = WINDOWS / "installer" / "setup_security.iss"
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
    lease = SETUP_LEASE.read_text(encoding="utf-8-sig")
    security = SETUP_SECURITY.read_text(encoding="utf-8-sig")
    private_result = (ISS.parent / "setup_private_result.iss").read_text(encoding="utf-8-sig")
    combined = text + security + lease + private_result
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
    install_code_before_uninstall = code_section.split("function TicketboxUninstallPreflightOk(", 1)[0]
    install_code_after_uninstall = code_section.split("procedure DeinitializeUninstall", 1)[1]
    assert "Exec(" not in install_code_before_uninstall
    assert "Exec(" not in install_code_after_uninstall
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
    assert "ticketbox-install-result.json" in combined
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
    assert "TicketboxAcquireSetupLease" in text
    assert "TicketboxSetupLeaseHandle" in text
    assert "#include \"setup_lease.iss\"" in text
    assert "CreateFileW" in security
    assert "SetKernelObjectSecurity" not in combined
    assert "SetSecurityInfo" in security
    assert "GetSecurityInfo" in security
    assert "ProtectedDaclSecurityInformation" in combined
    assert "TicketboxVerifyProtectedObject" in security
    assert "FILE_FLAG_OPEN_REPARSE_POINT" in combined
    prepare = text.split("function PrepareToInstall", 1)[1].split(
        "function TicketboxMsvcRuntimeIsCurrent", 1
    )[0]
    assert "TicketboxAcquireSetupLease" in prepare
    assert "TicketboxCloseHandle(TicketboxSetupLeaseHandle)" in lease
    assert "CreateMutexW" not in combined
    assert "SetupMutex=" not in text
    assert "TicketboxEnsureMsvcRuntime" not in prepare
    for token in FORBIDDEN_TOKENS:
        assert token not in text


def test_pairing_result_never_enters_the_user_readable_inno_temp_tree() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    security = SETUP_SECURITY.read_text(encoding="utf-8-sig")
    private_result = (ISS.parent / "setup_private_result.iss").read_text(encoding="utf-8-sig")

    assert "{tmp}\\ticketbox-install-result.json" not in text
    assert '#include "setup_private_result.iss"' in text
    assert "CreateDirectoryW" in security
    assert "TicketboxCreateProtectedDirectory" in private_result
    assert "TicketboxVerifyProtectedObject" in security
    assert "TicketboxResultDirectoryHandle" in text + private_result
    assert "TicketboxDeletePrivateResult" in text


def test_protected_directory_handle_can_query_reparse_and_directory_attributes() -> None:
    security = SETUP_SECURITY.read_text(encoding="utf-8-sig")
    directory_open = security.split("Handle := TicketboxOpenFile(", 1)[1].split(
        "if Handle = $FFFFFFFF", 1
    )[0]

    assert "Path, $000E0080" in directory_open


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
    lifecycle_run = next(
        line for line in text.splitlines() if line.startswith('Filename: "{app}\\bin\\lifecycle')
    )

    assert "ExpandConstant('{log}')" in postinstall
    assert "安装日志：" in postinstall
    assert "Log('Ticketbox install failed: ' + Reason)" in text
    assert "logoutput" in lifecycle_run.lower()


def test_setup_request_and_elevated_verifier_share_one_closed_machine_contract() -> None:
    from ticketbox_lifecycle.runtime import windows_shipment

    text = ISS.read_text(encoding="utf-8-sig")

    assert f'#define PgServiceName "{windows_shipment.PG_SERVICE_NAME}"' in text
    assert f'#define BackendServiceName "{windows_shipment.BACKEND_SERVICE_NAME}"' in text
    assert f'#define DefaultPgPort "{windows_shipment.PG_PORT}"' in text
    assert f'#define DefaultBackendPort "{windows_shipment.BACKEND_PORT}"' in text
    assert f'"postgres_major":{windows_shipment.POSTGRES_MAJOR}' in text
    assert '"program_data_root":"' in text
    assert "ExpandConstant('{commonappdata}\\Ticketbox')" in text
    assert '"data_root":"' in text
    assert "ExpandConstant('{commonappdata}\\Ticketbox\\data')" in text


def test_setup_failure_uses_stable_code_not_unescaped_json_message() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    failure = text.split("function TicketboxResultFailure", 1)[1].split(
        "function WriteFreshInstallRequest", 1
    )[0]

    assert "TicketboxJsonString(String(Text), 'message')" not in failure
    assert "生命周期控制器报告失败" in failure
    assert "错误代码：" in failure


def test_postinstall_messages_honor_silent_suppression() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    postinstall = text.split("procedure CurStepChanged", 1)[1].split(
        "procedure CurPageChanged", 1
    )[0]

    assert not any(line.lstrip().startswith("MsgBox(") for line in postinstall.splitlines())
    assert postinstall.count("SuppressibleMsgBox(") == 2
    assert postinstall.count("MB_OK, IDOK") == 2


def test_prepare_to_install_failures_surface_reason_retry_and_log() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    helper = text.split("function TicketboxPrepareFailure", 1)[1].split(
        "function PrepareToInstall", 1
    )[0]
    prepare = text.split("function PrepareToInstall", 1)[1].split(
        "function TicketboxMsvcRuntimeIsCurrent", 1
    )[0]

    assert "Log('Ticketbox preflight failed: ' + Reason)" in helper
    assert "TicketboxActionRecoveryText" in helper
    recovery = text.split("function TicketboxActionRecoveryText", 1)[1].split("function TicketboxPrepareFailure", 1)[0]
    assert "重新运行同一个安装包" in recovery
    assert "保留源备份和失败候选" in recovery
    assert "ExpandConstant('{log}')" in helper
    assert prepare.count("Result := TicketboxPrepareFailure(") == 9
    assert "TicketboxUninstallFilesDir" in prepare
    assert "TicketboxPathAbsentOrAdminWriteOnlyDir" in prepare
    assert "TicketboxPathAbsentOrAdminProtectedDir(TicketboxUninstallFilesDir)" in prepare
    assert "TicketboxRestorePreflight" in prepare
    assert "RESTORESHA256" in recovery
    assert "SOURCEISOLATED" in recovery
    assert "TicketboxPreparePrivateResult" in prepare
    assert "受保护的首次配对结果" in (
        ISS.parent / "setup_private_result.iss"
    ).read_text(encoding="utf-8-sig")
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
    assert 'Source: "{#TicketboxRepositorySource}\\distribution\\windows\\payload\\TicketboxLifecycle\\*"' in installer
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


def test_installer_distinguishes_upgrade_completion_without_first_time_pairing_code() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    security = SETUP_SECURITY.read_text(encoding="utf-8-sig")
    build = BUILD_INSTALLER.read_text(encoding="utf-8-sig")
    manifest = INSTALLED_MANIFEST.read_text(encoding="utf-8-sig")
    committed = text.split("function TicketboxResultIsCommitted", 1)[1].split(
        "function TicketboxResultFailure", 1
    )[0]
    upgrade_preflight = text.split("function TicketboxUpgradePreflight", 1)[1].split(
        "function TicketboxRestorePreflight", 1
    )[0]
    recovery = text.split("function TicketboxActionRecoveryText", 1)[1].split(
        "function TicketboxUpgradePreflight", 1
    )[0]
    deinit = text.split("procedure DeinitializeSetup", 1)[1].split(
        "function TicketboxMsvcRuntimeIsCurrent", 1
    )[0]
    files_section = text.split("[Files]", 1)[1].split("[", 1)[0]
    icons_section = text.split("[Icons]", 1)[1].split("[", 1)[0]
    run_section = text.split("[Run]", 1)[1].split("[", 1)[0]
    cur_step = text.split("procedure CurStepChanged", 1)[1].split("procedure CurPageChanged", 1)[0]
    readonly_admin_fn = security.split("function TicketboxVerifyReadOnlyAdminDirectory", 1)[1]

    assert "TicketboxUpgradeRequested" in text
    assert "TicketboxUpgradeStageReady" in text
    assert "TicketboxUpgradeNeedsVcRedist" in text
    assert "upgrade-{#ReleaseManifestSha256}" in text
    assert "Command := 'upgrade'" in text
    assert "if TicketboxUpgradeRequested then" in committed
    assert "(TicketboxJsonString(Body, 'command') = 'upgrade')" in committed
    assert "(TicketboxPairingCode = '') and (TicketboxPairingExpiresAt = '')" in committed
    assert "(TicketboxPairingCode <> '') and (TicketboxPairingExpiresAt <> '')" in committed
    assert "/UPGRADE=YES" in recovery
    assert "TicketboxJsonString(BindingBody, 'active_release_id')" in upgrade_preflight
    assert "StrToVersion(InstalledRelease, InstalledVer)" in upgrade_preflight
    assert "StrToVersion('{#ReleaseId}', TargetVer)" in upgrade_preflight
    assert "ComparePackedVersion(TargetVer, InstalledVer)" in upgrade_preflight
    assert "if Cmp < 0 then" in upgrade_preflight
    assert "if (Cmp = 0) and" in upgrade_preflight
    assert "(not TicketboxExactActiveCanContinue())" in upgrade_preflight
    assert "(not TicketboxCommittedReplayCanContinue())" in upgrade_preflight
    assert "TicketboxPathIsNonReparseType(ExpandConstant('{autopf}'), True)" in upgrade_preflight
    assert "TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageParent)" in upgrade_preflight
    assert "TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageDir)" in upgrade_preflight
    assert "DirExists(ExpandConstant('{app}\\releases\\{#ReleaseId}'))" not in upgrade_preflight
    assert "TicketboxParseRemovedConnectorState" not in text
    assert "TicketboxManagedConnectorBlocksUpgrade" not in text
    assert "TicketboxJsonHasLiteral" not in text
    assert "TicketboxCloudflared" not in text
    assert "ConvertSecurityDescriptorToStringSecurityDescriptorW@advapi32.dll" in security
    assert "TicketboxDescriptorDaclSddl" in readonly_admin_fn
    assert "TicketboxSetSecurityInfo" not in readonly_admin_fn
    assert "[InstallDelete]" not in text
    assert "CurStep = ssInstall" in cur_step
    assert "TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageParent)" in cur_step
    assert "TicketboxPathAbsentOrAdminProtectedDir(TicketboxUpgradeStageDir)" in cur_step
    assert "(not DelTree(TicketboxUpgradeStageDir, True, True, True))" in cur_step
    assert "TicketboxMarkInstallFailed('无法清理残留的受管升级暂存目录')" in cur_step
    assert cur_step.count("TicketboxCreateProtectedDirectory(") == 3
    assert "TicketboxCreateProtectedDirectory(\n      TicketboxUninstallFilesDir," in cur_step
    assert "(not DelTree(TicketboxUpgradeStageDir, True, True, True))" in deinit
    assert "TicketboxStageHasOnlyKnownEntries(TicketboxUpgradeStageDir)" in deinit
    assert deinit.index("TicketboxStageHasOnlyKnownEntries(TicketboxUpgradeStageDir)") < deinit.index(
        "DelTree(TicketboxUpgradeStageDir"
    )
    assert "Log('Ticketbox upgrade stage cleanup incomplete:" in deinit
    assert "DestDir: \"{app}\\bin\\lifecycle\"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxDirectSharedMaterialization" in files_section
    assert "DestDir: \"{app}\\releases\\{#ReleaseId}\\lifecycle\"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: TicketboxFreshMaterialization" in files_section
    assert "DestDir: \"{app}\\releases\\{#ReleaseId}\"; Flags: ignoreversion onlyifdoesntexist; Check: TicketboxExactResumeMaterialization" in files_section
    upgrade_file_lines = [
        line.strip()
        for line in files_section.splitlines()
        if "Check: TicketboxUpgradeStageReady" in line
    ]
    assert len(upgrade_file_lines) == 7
    assert all('DestDir: "{autopf}\\Ticketbox-UpgradeStage\\{#ReleaseId}' in line for line in upgrade_file_lines)
    assert all("{app}" not in line for line in upgrade_file_lines)
    assert "Check: TicketboxUpgradeNeedsVcRedist" in run_section
    assert 'Filename: "{autopf}\\Ticketbox-UpgradeStage\\{#ReleaseId}\\lifecycle\\TicketboxLifecycle.exe"' in run_section
    assert "Check: TicketboxDirectSharedMaterialization" in icons_section
    assert "--staged-release-root" in text
    assert "TicketboxUpgradeStageOwned" in text
    assert '"releases/$Version/lifecycle"' in manifest
    assert "upgrade_startup_probe" in build
    assert "$lifecycleExe upgrade --help" in build

    shortcut_src = (LIFECYCLE / "ticketbox_lifecycle" / "runtime" / "windows_shortcut.py").read_text(encoding="utf-8")
    shell_src = (REPO / "desktop" / "backend_manager" / "desktop_shell.py").read_text(encoding="utf-8")
    assert 'AppUserModelID: "Ticketbox.Manager"' in icons_section
    assert 'MANAGER_APP_ID = "Ticketbox.Manager"' in shortcut_src
    assert 'MANAGER_APP_ID = "Ticketbox.Manager"' in shell_src


def test_installer_rev32_uninstall_reinstall_r2_and_u1_three_way_boundaries() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    security = SETUP_SECURITY.read_text(encoding="utf-8-sig")
    build = BUILD_INSTALLER.read_text(encoding="utf-8-sig")

    assert "Uninstallable=yes" in text
    assert "UninstallFilesDir={commoncf64}\\Ticketbox\\uninstall" in text
    assert "UninstallDisplayName=小票夹" in text
    assert "UninstallDisplayIcon={app}\\ticketbox.ico" in text
    assert "[UninstallRun]" not in text
    assert "[UninstallDelete]" not in text
    assert "InitializeUninstall" in text
    assert "CurUninstallStepChanged" in text
    assert "DeinitializeUninstall" in text
    assert "TicketboxVerifyAdminWriteOnlyDirectory" in security
    assert "TicketboxDaclSddlIsAdminWriteOnly" in security

    private_result = (ISS.parent / "setup_private_result.iss").read_text(encoding="utf-8-sig")
    for retired in (
        "TicketboxHasJsonUnicodeEscape",
        "TicketboxJsonUniqueString",
        "TicketboxJsonTopLevelUniqueString",
        "TicketboxJsonSkipWhitespace",
        "TicketboxJsonScanString",
        "TicketboxJsonSkipValue",
        "TicketboxWriteUninstallRequest",
        "TicketboxUninstallRequestPath",
        "TicketboxUninstallRequestOwned",
    ):
        assert retired not in text
    assert "TicketboxWriteFile" not in security
    assert "WriteFile@kernel32.dll" not in security

    uninstall_result_fn = text.split("function TicketboxUninstallResultIsCommitted: Boolean;", 1)[1].split(
        "function TicketboxUninstallPreflightOk(", 1
    )[0]
    assert "Length(ObservedOpId) <> 74" in uninstall_result_fn
    assert "Copy(ObservedOpId, 1, 10) <> 'uninstall-'" in uninstall_result_fn
    assert "TicketboxIsHexSha256(DigestPart)" in uninstall_result_fn
    assert "DigestPart <> LowerCase(DigestPart)" in uninstall_result_fn
    assert "TicketboxJsonString(Body, 'command') <> 'uninstall'" in uninstall_result_fn
    assert "TicketboxJsonString(Body, 'code') <> 'uninstalled_data_preserved'" in uninstall_result_fn

    uninstall_preflight_fn = text.split("function TicketboxUninstallPreflightOk(", 1)[1].split(
        "procedure TicketboxReportUninstallRefused", 1
    )[0]
    assert "DeleteFile(" not in uninstall_preflight_fn
    assert "SaveStringToFile(" not in uninstall_preflight_fn
    assert "--request" not in uninstall_preflight_fn
    assert "--result" not in uninstall_preflight_fn
    assert "TicketboxPathIsNonReparseType(LifecycleExe, False)" in uninstall_preflight_fn
    assert "'uninstall --check-preflight'" in uninstall_preflight_fn
    assert "Result := ResultCode = 0;" in uninstall_preflight_fn

    init_uninstall = text.split("function InitializeUninstall: Boolean;", 1)[1].split(
        "procedure CurUninstallStepChanged", 1
    )[0]
    assert "Exec(" not in init_uninstall
    assert "DeleteFile(" not in init_uninstall
    assert "TicketboxAbortUninstall" not in init_uninstall
    assert "TicketboxReportUninstallRefused" in init_uninstall
    assert "if not TicketboxPathIsNonReparseType(LifecycleExe, False) then" in init_uninstall
    assert "if not TicketboxUninstallPreflightOk(LifecycleDir, LifecycleExe) then" in init_uninstall
    assert init_uninstall.index("TicketboxPathIsNonReparseType(LifecycleExe, False)") < init_uninstall.index(
        "TicketboxUninstallPreflightOk(LifecycleDir, LifecycleExe)"
    )
    assert "TicketboxPathExists(TicketboxActivePath)" in init_uninstall
    assert "FileExists(TicketboxActivePath)" not in init_uninstall
    assert "TicketboxAcquireSetupLease" not in init_uninstall
    assert "TicketboxPreparePrivateResult" not in init_uninstall
    assert "Result := False;" in init_uninstall

    cur_uninstall = text.split("procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);", 1)[1].split(
        "procedure DeinitializeUninstall;", 1
    )[0]
    assert "CurUninstallStep <> usUninstall" in cur_uninstall
    assert "if not TicketboxPathIsNonReparseType(LifecycleExe, False) then" in cur_uninstall
    assert "if not TicketboxUninstallPreflightOk(LifecycleDir, LifecycleExe) then" in cur_uninstall
    assert cur_uninstall.index("TicketboxPathIsNonReparseType(LifecycleExe, False)") < cur_uninstall.index(
        "TicketboxUninstallPreflightOk(LifecycleDir, LifecycleExe)"
    )
    assert "TicketboxPathExists(TicketboxActivePath)" in cur_uninstall
    assert "FileExists(TicketboxActivePath)" not in cur_uninstall
    assert "installation.json" not in cur_uninstall
    assert "--request" not in cur_uninstall
    assert "TicketboxAcquireSetupLease" in cur_uninstall
    assert "TicketboxPreparePrivateResult" in cur_uninstall
    assert cur_uninstall.index("CurUninstallStep <> usUninstall") < cur_uninstall.index("TicketboxAcquireSetupLease")
    assert cur_uninstall.index("TicketboxAcquireSetupLease") < cur_uninstall.index("TicketboxUninstallPreflightOk")
    assert cur_uninstall.index("TicketboxUninstallPreflightOk(LifecycleDir, LifecycleExe)") < cur_uninstall.index(
        "TicketboxPreparePrivateResult"
    )
    assert cur_uninstall.index("TicketboxPreparePrivateResult") < cur_uninstall.index(
        "uninstall --from-installed --result"
    )
    assert "Params := 'uninstall --from-installed --result \"' + TicketboxResultPath + '\"';" in cur_uninstall
    assert "Exec(LifecycleExe, Params, LifecycleDir, SW_HIDE, ewWaitUntilTerminated, ResultCode)" in cur_uninstall
    assert "(ResultCode <> 0)" in cur_uninstall
    assert "(not TicketboxUninstallResultIsCommitted)" in cur_uninstall
    assert "TicketboxAbortUninstall" in cur_uninstall
    assert "Abort;" in cur_uninstall
    deinit_uninstall = text.split("procedure DeinitializeUninstall;", 1)[1].split(
        "function TicketboxRestoreGuidanceText", 1
    )[0]
    assert "TicketboxReleasePrivateResult;" in deinit_uninstall
    assert "TicketboxReleaseSetupLease;" in deinit_uninstall
    assert "if TicketboxResultDirectoryHandle = 0 then" in private_result

    assert "FindFirstFileW@kernel32.dll" in security
    assert "function TicketboxFindNextFile(Handle, FindData: LongWord): LongBool;\nexternal 'FindNextFileW@kernel32.dll stdcall';" in security
    assert "function TicketboxFindClose(Handle: LongWord): LongBool;\nexternal 'FindClose@kernel32.dll stdcall';" in security
    dir_empty_fn = text.split("function TicketboxDirectoryIsEmpty(", 1)[1].split(
        "function TicketboxIsKnownStageRootEntry(", 1
    )[0]
    stage_known_fn = text.split("function TicketboxStageHasOnlyKnownEntries(", 1)[1].split(
        "function TicketboxUpgradeStageReusableOrEmpty(", 1
    )[0]
    for enum_fn in (dir_empty_fn, stage_known_fn):
        assert "Result := False;" in enum_fn
        assert "Result := True;" not in enum_fn
        assert "TicketboxFindFirstFile(" in enum_fn
        assert "TicketboxFindNextFile(" in enum_fn
        assert "TicketboxFindClose(" in enum_fn
        assert "if Handle = $FFFFFFFF then\n      Exit;" in enum_fn
        assert enum_fn.count("DLLGetLastError = 18") == 1
        assert enum_fn.index("if not TicketboxFindNextFile(") < enum_fn.index("DLLGetLastError = 18")

    stage_reuse = text.split("function TicketboxUpgradeStageReusableOrEmpty(", 1)[1].split(
        "function TicketboxInstallRootIsExact", 1
    )[0]
    assert "TicketboxStageHasOnlyKnownEntries(StageDir)" in stage_reuse
    assert "TicketboxIsKnownStageRootEntry" in text

    upgrade_preflight = text.split("function TicketboxUpgradePreflight", 1)[1].split(
        "function TicketboxReinstallPreflight", 1
    )[0]
    cur_step = text.split("procedure CurStepChanged", 1)[1].split("procedure CurPageChanged", 1)[0]
    ss_install_block = cur_step.split("if CurStep = ssPostInstall then", 1)[0]
    assert ss_install_block.count("TicketboxMarkInstallFailed(") == 7
    assert ss_install_block.count("Abort;") == 7
    assert "Exit;" not in ss_install_block
    assert "TicketboxUpgradeStageReusableOrEmpty(TicketboxUpgradeStageDir)" in upgrade_preflight
    assert "TicketboxUpgradeStageReusableOrEmpty(TicketboxUpgradeStageDir)" in cur_step
    assert cur_step.index("TicketboxUpgradeStageReusableOrEmpty") < cur_step.index("DelTree(TicketboxUpgradeStageDir")

    guidance_fn = text.split("function TicketboxRestoreGuidanceText: String;", 1)[1].split(
        "procedure CurStepChanged", 1
    )[0]
    assert "TicketboxReconnectGuidance" in guidance_fn
    post_ok = cur_step.split("if TicketboxUpgradeRequested then", 1)[1]
    assert post_ok.index("Log('Ticketbox recovery guidance") < post_ok.index("TicketboxDeletePrivateResult;")
    assert post_ok.index("SuppressibleMsgBox(SuccessMessage") < post_ok.index("TicketboxDeletePrivateResult;")

    assert "TicketboxReinstallRequested" in text
    assert "TicketboxReinstallPreflight" in text
    assert "/REINSTALL=YES" in text
    assert "Command := 'reinstall'" in text
    assert "reinstall-{#ReleaseManifestSha256}" in text

    assert "TicketboxRestoreMode" in text
    assert "RESTOREMODE" in text
    assert "cross-machine" in text
    assert "--restore-mode" in text
    assert "TicketboxRestoreModeResult" in text
    assert "TicketboxReconnectGuidance" in text
    assert "TicketboxRestoreGuidanceText" in text
    assert "吊销或停用旧远端公网隧道" in text
    assert "Outbox" in text

    assert "--rollback-on-failure" in text
    assert "rolled_back_to_previous" in text
    assert "upgrade_failed_restored_previous" in text
    assert "TicketboxUpgradeRolledBack" in text
    assert "Result := 3" in text

    for probe in (
        "upgrade_startup_probe",
        "rollback_upgrade_startup_probe",
        "uninstall_startup_probe",
        "reinstall_startup_probe",
        "purge_data_startup_probe",
    ):
        assert probe in build
