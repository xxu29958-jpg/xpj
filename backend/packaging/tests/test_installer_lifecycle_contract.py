from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from _pg_recovery_contract import assert_pg_recovery_toolset_behavior

ROOT = Path(__file__).resolve().parents[3]
PACKAGING = ROOT / "backend" / "packaging"


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def _read_installer() -> str:
    return "\n".join(
        _read(name)
        for name in (
            "ticketbox-installer.iss",
            "ticketbox-installer-windows.isph",
            "ticketbox-installer-flow.isph",
        )
    )


def test_inno_runs_preflight_before_copy_and_skips_late_duplicate_backup() -> None:
    installer = _read_installer()

    pre_copy_dependencies = (
        "prepare_bundled_upgrade.ps1",
        "windows_service_contract.ps1",
        "windows_service_lifecycle.ps1",
        "windows_installation_safety.ps1",
        "windows_lifecycle_receipt.ps1",
        "windows_lifecycle_lock.ps1",
        "windows_database_safety.ps1",
        "windows_pg_recovery_tools.ps1",
        "windows_release_config.ps1",
        "windows-release-config.json",
    )
    for name in pre_copy_dependencies:
        assert f'Source: "{name}"; Flags: dontcopy noencryption' in installer
        assert f"ExtractTemporaryFile('{name}')" in installer

    installed_dependencies = pre_copy_dependencies + (
        "windows_bundled_database.ps1",
        "windows_backend_bootstrap.ps1",
        "windows_bootstrap_exposure_recovery.ps1",
        "install_bundled_services.ps1",
        "uninstall_bundled_services.ps1",
    )
    for name in installed_dependencies:
        assert f'Source: "{name}"; DestDir: "{{app}}\\installer"; Flags: ignoreversion' in installer
    assert 'Source: "..\\scripts\\windows_build_provenance.ps1"; DestName: "windows_build_provenance.ps1"; Flags: dontcopy noencryption' in installer
    assert 'Source: "..\\scripts\\windows_build_provenance.ps1"; DestDir: "{app}\\installer"; DestName: "windows_build_provenance.ps1"; Flags: ignoreversion' in installer
    assert 'Source: "..\\scripts\\windows_backend_build_provenance.ps1"; DestName: "windows_backend_build_provenance.ps1"; Flags: dontcopy noencryption' in installer
    assert 'Source: "..\\scripts\\windows_backend_build_provenance.ps1"; DestDir: "{app}\\installer"; DestName: "windows_backend_build_provenance.ps1"; Flags: ignoreversion' in installer
    assert installer.index("ExtractTemporaryFile('windows_backend_build_provenance.ps1')") < installer.index(
        "ExtractTemporaryFile('windows_build_provenance.ps1')"
    )
    assert "ExtractTemporaryFile('windows_build_provenance.ps1')" in installer

    prepare = _read("prepare_bundled_upgrade.ps1")
    install = _read("install_bundled_services.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")
    for script in (prepare, install, uninstall):
        assert ". $ReleaseConfigScript" in script
        assert ". $LifecycleScript" in script
        assert ". $SafetyScript" in script
        assert ". $LockScript" in script
    for script in (prepare, install):
        assert ". $DatabaseSafetyScript" in script
    assert ". $DatabaseScript" in install
    assert ". $BackendBootstrapScript" in install
    assert installer.index("function PrepareToInstall") < installer.index("procedure CurStepChanged")
    assert "SkipPreUpgradeBackup" not in installer
    assert "LifecycleReceiptPath" in installer
    assert "installer-lifecycle-receipt.json" in installer
    assert "{commoncf64}\\Ticketbox\\installer-lifecycle-receipt.json" in installer
    assert "{tmp}\\ticketbox-lifecycle-receipt.json" not in installer
    assert "Read-TicketboxLifecycleReceipt" in install
    assert "Write-TicketboxLifecycleReceipt" in prepare
    assert "RecoverPreparedInstall" in installer
    assert "LifecycleInstallCompleted" in installer
    assert "LifecycleFilesMayBeReplaced" in installer
    assert "OwnerHandoffExpected" in installer
    assert "OwnerHandoffMemo" in installer
    assert "OwnerHandoffConfirmation" in installer
    assert "TNewCheckBox.Create(WizardForm.FinishedPage)" in installer
    assert "owner-bootstrap.txt" in installer
    assert "owner-handoff-pending" in installer
    assert "LoadStringsFromFile" in installer
    assert "一次性绑定信息" in installer
    assert "HasCurrentOwnerHandoffPendingArtifact" in installer
    assert "INSTALLER_OWNER_PID=" in installer
    flow = _read("ticketbox-installer-flow.isph")
    finished_page = flow[flow.index("procedure CurPageChanged") : flow.index("function NextButtonClick")]
    finish_click = flow[flow.index("function NextButtonClick") : flow.index("function PrepareToInstall")]
    assert "OwnerHandoffMemo.Visible := True" in finished_page
    assert "OwnerHandoffConfirmation.Visible := True" in finished_page
    assert "owner-handoff-pending" not in finished_page
    confirmation = finish_click.index("if not OwnerHandoffConfirmation.Checked")
    cleanup_call = finish_click.index("' -CompleteOwnerHandoffOnly'")
    verify_deleted = finish_click.index("if FileExists(HandoffPath) or FileExists(HandoffPendingPath)")
    clear_ui_secret = finish_click.index("OwnerHandoffMemo.Text := ''")
    assert confirmation < cleanup_call < verify_deleted < clear_ui_secret
    assert "DeleteFile(HandoffPendingPath)" not in flow
    assert "Ticketbox owner bootstrap handoff completion" in finish_click
    assert "LastPowerShellChildSucceeded" in finish_click
    assert '"CompleteOwnerHandoffOnly"' in installer
    assert "[switch]$CompleteOwnerHandoffOnly" in install
    cleanup_mode = install[install.index("if ($CompleteOwnerHandoffOnly)") :]
    assert cleanup_mode.index("Enter-TicketboxLifecycleLock") < cleanup_mode.index(
        "Complete-TicketboxOwnerBootstrapHandoff"
    )
    assert cleanup_mode.index("Complete-TicketboxOwnerBootstrapHandoff") < cleanup_mode.index(
        "Exit-TicketboxLifecycleLock"
    )
    assert "请先复制一次性绑定信息，并勾选确认后再完成安装" in finish_click
    prepare_flow = flow[flow.index("function PrepareToInstall") : flow.index("procedure CurStepChanged")]
    assert "OwnerHandoffExpected := False" in prepare_flow
    assert "owner-bootstrap.txt" not in prepare_flow
    postinstall = flow[flow.index("procedure CurStepChanged") : flow.index("procedure DeinitializeSetup")]
    service_install = postinstall.index("'Ticketbox service installation'")
    current_pending = postinstall.index(
        "OwnerHandoffExpected := HasCurrentOwnerHandoffPendingArtifact()"
    )
    assert service_install < current_pending
    assert " -TargetPgMajor {#TargetPgMajor}" in installer
    assert "[int]$TargetPgMajor" in prepare
    assert "[int]$TargetPgMajor = 0" in install
    assert 'Join-Path $PgData "PG_VERSION"' in prepare
    prepare_calls = list(
        re.finditer(
            r"ExpandConstant\('\{tmp\}\\prepare_bundled_upgrade\.ps1'\)",
            flow,
        )
    )
    assert len(prepare_calls) == 5
    for call in prepare_calls[1:]:
        args_start = flow.rfind("Args :=\n", 0, call.start())
        assert args_start >= 0
        assert " -TargetPgMajor {#TargetPgMajor}" in flow[args_start : call.start()]
    assert flow.count(" -TargetPgMajor {#TargetPgMajor}") == len(prepare_calls) + 1
    stale_start = prepare.index("$staleReceipt = Read-TicketboxLifecycleReceipt")
    stale_branch = prepare[
        stale_start : prepare.index(
            "Initialize-TicketboxInstalledReleaseConfiguration",
            stale_start,
        )
    ]
    assert stale_branch.count("return") == 2
    assert "AllowCancelDuringInstall=no" in installer
    assert "DisableDirPage=yes" in installer
    assert "UsePreviousAppDir=no" in installer
    assert "PowerShellExecutable()" in installer
    assert "CanRunPowerShell(PowerShellPath: String)" in installer
    assert "FindMachinePowerShell7()" in installer
    assert "Microsoft\\PowerShellCore\\InstalledVersions" in installer
    assert "HasValidMicrosoftSignature" in installer
    assert "{localappdata}\\Microsoft\\WindowsApps\\pwsh.exe" not in installer
    assert "{sys}\\WindowsPowerShell\\v1.0\\powershell.exe" in installer
    assert "CompareText(PowerShellPath, WindowsPowerShellExecutable())" in installer
    assert "AcquireLifecycleLock" in installer
    assert "CreateFileW@kernel32.dll" in installer
    assert "CreateMutexW@kernel32.dll" not in installer
    assert "{commoncf64}\\Ticketbox" in installer
    assert "function InitializeUninstall(): Boolean" in installer
    assert "installer-lifecycle.owner" in installer
    assert "GetCurrentProcessId@kernel32.dll" in installer
    assert "SaveStringToFile(" in installer
    assert installer.count(" -InstallerLockOwnerProcessId ") == 8
    assert "InstallerLockHeld" not in installer
    assert "Pos(#0, Value)" in installer
    assert '"prepare_bundled_upgrade.ps1" = @(' in installer
    assert '"install_bundled_services.ps1" = @(' in installer
    assert '"uninstall_bundled_services.ps1" = @(' in installer
    assert "Child script resolution mismatch." in installer
    assert "Child parameter is not allowlisted:" in installer
    assert "Duplicate child parameter:" in installer
    prepare_start = installer.index("function PrepareToInstall")
    port_check = installer.index("Result := FreshInstallPortError();", prepare_start)
    extract_preflight = installer.index("ExtractTemporaryFile('prepare_bundled_upgrade.ps1')", prepare_start)
    assert port_check < extract_preflight
    assert "StopServiceIfPresent" not in installer
    assert "Sleep(30000)" not in installer
    assert uninstall.index("Save-TicketboxUninstallPgRecoveryIfRequired") < uninstall.index(
        'Write-Step "停止并删除 PostgreSQL 服务"'
    )
    assert 'if ($mode -eq "repair_install")' in prepare
    assert 'elseif ($mode -ne "preserved_data_reinstall")' in prepare
    topology = prepare[prepare.index("$usingRecoveryPgService") :]
    verify_installed_tools = topology.index("Save-TicketboxPgRecoveryToolset")
    persist_capture = topology.index("Write-TicketboxLifecycleReceipt")
    register_recovery = topology.index("Register-TicketboxRecoveryPgService")
    dump_database = topology.index("Invoke-TicketboxPgDumpCustom")
    persist_backup = topology.index("Set-TicketboxLifecycleReceiptPrepared")
    assert verify_installed_tools < persist_capture < register_recovery < dump_database < persist_backup
    assert "-SourcePgHome $InstalledPgHome" in topology
    assert "-BuildManifestPath $InstalledBuildManifestPath" in topology
    assert "Assert-TicketboxPgRecoveryToolset -ExpectedMajor $TargetPgMajor" in prepare
    assert prepare.index("Register-TicketboxRecoveryPgService") < prepare.index(
        "Invoke-TicketboxPgDumpCustom"
    )
    assert prepare.index("Invoke-TicketboxPgDumpCustom") < prepare.rindex(
        "Remove-TicketboxRecoveryPgServiceIfExists"
    )

    registry_lines = [line for line in installer.splitlines() if 'Root: HKLM; Subkey: "Software\\Ticketbox"' in line]
    preserved_names = {"DataRoot", "BackendPort", "PgPort", "BackendServiceName", "PgServiceName"}
    for name in preserved_names:
        line = next(line for line in registry_lines if f'ValueName: "{name}"' in line)
        assert "uninsdeletevalue" not in line


def test_preserved_data_reinstall_defers_verified_backup_until_target_tools_exist() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    install = _read("install_bundled_services.ps1")
    database = _read("windows_bundled_database.ps1")

    preserved_branch = prepare[
        prepare.index('if ($mode -eq "preserved_data_reinstall")') :
        prepare.index('elseif ($mode -ne "fresh_install")')
    ]
    assert "Assert-TicketboxLegacyPreservedDataLayout" in preserved_branch
    assert "Get-TicketboxLocalDatabaseConnection" in preserved_branch
    assert "Assert-TicketboxRegisteredDataRootBinding" not in preserved_branch
    captured = prepare.index('-PreparationStage "captured"')
    deferred_return = prepare.index("if ($deferredPreservedBackup)", captured)
    persist_deferred = prepare.index("Set-TicketboxLifecycleReceiptDeferredBackup", deferred_return)
    acl_mutation = prepare.index("Repair-TicketboxPreflightInstallAcl", deferred_return)
    assert captured < deferred_return < persist_deferred < acl_mutation

    flow = _read("ticketbox-installer-flow.isph")
    install_boundary = flow.index("if CurStep = ssInstall")
    persist_copy_boundary = flow.index("-MarkProgramFilesInstalledBackupPending", install_boundary)
    memory_copy_boundary = flow.index("LifecycleFilesMayBeReplaced := True", persist_copy_boundary)
    assert install_boundary < persist_copy_boundary < memory_copy_boundary

    service_phase = install.index("if ($DeferredPreservedDataBackup)")
    cleanup_wal = install.index(
        "Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending",
        service_phase,
    )
    register_service = install.index("Register-TicketboxDeferredPreservedPgService", cleanup_wal)
    backup = install.index("Invoke-TicketboxPreservedDataReinstallBackup", service_phase)
    remove_service = install.index("Remove-TicketboxDeferredPreservedPgServiceIfExists", backup)
    cleanup_complete = install.index("-CleanupPending $false", remove_service)
    receipt_files = install.index("Set-TicketboxLifecycleReceiptDeferredBackupCompleted", cleanup_complete)
    mutation = install.index("$mutationStarted = $true", receipt_files)
    data_root_acl = install.index("Initialize-TicketboxSecureDataRoot", mutation)
    initdb = install.index("Initialize-PgClusterIfNeeded", data_root_acl)
    assert cleanup_wal < register_service < backup < remove_service
    assert remove_service < cleanup_complete < receipt_files < mutation < data_root_acl < initdb
    assert "NT SERVICE\\$PgServiceName" in install[register_service - 1800 : backup]
    assert "Get-TicketboxDeferredBackupRoot" in install[register_service : backup + 600]
    assert "-ExpectedPgMajor $TargetPgMajor" in install[service_phase:backup]
    assert "-ExpectedPgMajor $ExpectedPgMajor" not in install[service_phase:backup]
    assert "ReleaseConfig.pg_major" not in install
    assert "ReleaseConfig.pg_major" not in database

    direct_backup = database[
        database.index("function Invoke-TicketboxPreservedDataReinstallBackup") :
        database.index("function Invoke-PreUpgradeBackupIfNeeded")
    ]
    assert "& $PgCtl" not in direct_backup
    assert "Start-Process" not in direct_backup
    assert "Wait-TicketboxServiceSettledState" in direct_backup
    assert "Assert-TicketboxServiceAccount" in direct_backup
    assert "Assert-TicketboxPgServiceCommand" in direct_backup
    assert "Assert-TicketboxConnectedPostgresDataRoot" in direct_backup
    assert "Invoke-TicketboxPgDumpCustom" in direct_backup
    assert "& $PgRestore --list" in direct_backup
    assert "Register-PgService" not in direct_backup
    assert "Initialize-PgClusterIfNeeded" not in direct_backup

    stale_cleanup = prepare[
        prepare.index("if ([bool]$staleReceipt.temporary_pg_service_cleanup_pending") :
        prepare.index("if ([bool]$staleReceipt.install_completed)")
    ]
    assert stale_cleanup.index("Remove-TicketboxDeferredPreservedPgServiceIfExists") < stale_cleanup.index(
        "-CleanupPending $false"
    )
    stale_recovery = prepare[
        prepare.index("$staleReceipt = Read-TicketboxLifecycleReceipt") :
        prepare.index("if ([bool]$staleReceipt.install_completed)")
    ]
    assert stale_recovery.index("Remove-TicketboxDeferredPreservedPgServiceIfExists") < stale_recovery.index(
        "Remove-TicketboxRecoveryPgServiceIfExists"
    )


def test_programdata_identity_is_the_locked_fail_closed_version_floor() -> None:
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")
    install = _read("install_bundled_services.ps1")
    safety = _read("windows_installation_safety.ps1")

    initialize = windows[
        windows.index("function InitializeSetup") : windows.index("function InitializeUninstall")
    ]
    acquire = initialize.index("AcquireLifecycleLock()")
    version_read = initialize.index("CheckBackendVersionFloor")
    release_on_failure = initialize.index("ReleaseLifecycleLock()", version_read)
    assert acquire < version_read < release_on_failure

    gate = windows[
        windows.index("function CheckBackendVersionFloor") : windows.index("function InitializeSetup")
    ]
    assert "TryGetPersistentBackendVersionFloor" in gate
    assert "HasPreservedPgData" in gate
    assert "可信 version floor 缺失或损坏" in gate
    legacy_adoption = gate[
        gate.index("else if HasPreservedPgData then") : gate.index(
            "if (not HasFormalVersion) and (not HasTrustedLegacyVersion) then"
        )
    ]
    assert "RegQueryStringValue(" in legacy_adoption
    assert "'DataRoot'" in legacy_adoption
    assert "CanonicalVersionGateInstallPath(RegisteredDataRoot)" in legacy_adoption
    assert "CanonicalVersionGateInstallPath(PreservedDataRoot)" in legacy_adoption
    assert "TryGetTrustedLegacyBackendVersion" in legacy_adoption
    assert "HasExistingInstall := True" in legacy_adoption
    assert "安装器已 fail closed" in legacy_adoption
    assert "CheckBackendVersionFloorForDataRoot" in flow
    prepare_to_install = flow[
        flow.index("function PrepareToInstall") : flow.index("procedure CurStepChanged")
    ]
    assert prepare_to_install.index("CheckBackendVersionFloorForDataRoot") < prepare_to_install.index(
        "ExtractTemporaryFile('prepare_bundled_upgrade.ps1')"
    )
    persistent_reader = windows[
        windows.index("function TryGetPersistentBackendVersionFloor") : windows.index(
            "function TicketboxLegacyUninstallKey"
        )
    ]
    assert "LoadStringsFromFile" in persistent_reader
    assert "HasProtectedPersistentIdentityAcl" in persistent_reader
    assert "BUILD_MANIFEST_SHA256" in persistent_reader
    assert "INSTALLATION_ID" in persistent_reader
    assert "DATA_ROOT" in persistent_reader
    assert "{#PgServiceName}" in persistent_reader
    assert "{#BackendServiceName}" in persistent_reader

    identity_writer = safety[
        safety.index("function Write-TicketboxPersistentInstallationIdentity") : safety.index(
            "function Assert-TicketboxRegisteredDataRootBinding"
        )
    ]
    assert "Write-TicketboxUtf8FileDurable" in identity_writer
    assert "Set-TicketboxExactFileAcl" in identity_writer
    assert "$script:TicketboxPersistentInstallationIdentityAclAccounts" in identity_writer
    assert "Get-TicketboxPortableFileSha256 $BuildManifestPath" in identity_writer
    assert "Compare-TicketboxNumericVersion" in identity_writer
    assert "[guid]::NewGuid()" in identity_writer

    persist_identity = install.rindex("Write-TicketboxPersistentInstallationIdentity")
    service_return = install.index('Write-Host "================ 安装完成', persist_identity)
    assert persist_identity < service_return
    post_install = flow[flow.index("if CurStep = ssPostInstall") : flow.index("procedure DeinitializeSetup")]
    service_install = post_install.index("'Ticketbox service installation'")
    lifecycle_commit = post_install.index("'Ticketbox installer lifecycle commit'", service_install)
    assert service_install < lifecycle_commit

    manifest_path = install.index('$InstalledBuildManifestPath = Join-Path $ScriptDir "BUILD_PROVENANCE.json"')
    manifest_validation = install.index("Read-TicketboxInstalledBuildManifest")
    operation_lock = install.index("$operationLock = Enter-TicketboxLifecycleLock")
    mutation = install.index("$mutationStarted = $true")
    assert manifest_path < manifest_validation < operation_lock < mutation
    assert "-ExpectedPgMajor $TargetPgMajor" in install[manifest_validation - 100 : manifest_validation + 220]


def test_owner_handoff_uses_utf8_aware_inno_loading() -> None:
    flow = _read("ticketbox-installer-flow.isph")
    loader = flow[
        flow.index("function LoadUtf8TextFile") : flow.index(
            "function HasCurrentOwnerHandoffPendingArtifact"
        )
    ]
    assert "LoadStringsFromFile" in loader
    assert "LoadStringFromFile" not in loader
    pending = flow[
        flow.index("function HasCurrentOwnerHandoffPendingArtifact") : flow.index(
            "procedure CurPageChanged"
        )
    ]
    finished = flow[
        flow.index("procedure CurPageChanged") : flow.index("function NextButtonClick")
    ]
    assert "LoadUtf8TextFile" in pending
    assert "LoadUtf8TextFile" in finished
    assert "AnsiString" not in pending + finished


def test_data_root_guard_releases_operation_lock_before_long_lived_lease() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    guard = prepare[
        prepare.index("if ($HoldDataRootMutationGuard)") :
        prepare.index("if ($PgPort -eq $BackendPort)")
    ]
    acquired = guard.index("$guardOperationLock = Enter-TicketboxLifecycleLock")
    released = guard.index("Exit-TicketboxLifecycleLock $guardOperationLock")
    waited = guard.index("Wait-TicketboxDirectoryMutationGuardLease")
    assert acquired < released < waited


def test_installer_never_bundles_local_runtime_data() -> None:
    installer = _read_installer()

    backend_source = next(
        line for line in installer.splitlines() if 'Source: "..\\dist\\ticketbox-backend\\*"' in line
    )
    assert 'Excludes: "ticketbox-data\\*"' in backend_source


def test_installer_version_only_comes_from_backend_source_of_truth() -> None:
    build = _read("build_inno_installer.ps1")
    installer = _read_installer()

    assert '[string]$Version =' not in build
    assert '$versionFile = Join-Path $BackendRoot "app\\version.py"' in build
    assert 'BACKEND_VERSION\\s*=\\s*"([^\"]+)"' in build
    assert 'return "0.0.0.0"' not in build
    assert '#define AppVersion "0.0.0-dev"' not in installer
    assert '#define AppVersionInfo "0.0.0.0"' not in installer
    assert "#error AppVersion must be injected by build_inno_installer.ps1" in installer
    assert '$ReleaseConfigPath = Join-Path $ScriptDir "windows-release-config.json"' in build
    assert '$ReleaseConfigScript = Join-Path $ScriptDir "windows_release_config.ps1"' in build
    assert 'Read-TicketboxWindowsReleaseConfig $ReleaseConfigPath' in build
    assert '"/DDefaultPgPort=$($releaseConfig.default_pg_port)"' in build
    assert "SelectInitialPort('TicketboxPgPort', ExistingPgPort, '5432', '5440')" not in installer

    powershell = shutil.which("powershell")
    assert powershell
    for version, expected in (
        ("1.3.0a1", "1.3.0.0"),
        ("1.3.0rc2", "1.3.0.0"),
        ("1.3.0-rc.2+build.7", "1.3.0.0"),
        ("1.3.0.9", "1.3.0.9"),
    ):
        result = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                PACKAGING / "build_inno_installer.ps1",
                "-VersionContractProbe",
                version,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
    rejected = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            PACKAGING / "build_inno_installer.ps1",
            "-VersionContractProbe",
            "release-latest",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert rejected.returncode != 0


def test_mutable_windows_runtime_policy_is_read_from_release_config() -> None:
    config = json.loads(_read("windows-release-config.json"))
    build = _read("build_inno_installer.ps1")
    install = _read("install_bundled_services.ps1")
    prepare = _read("prepare_bundled_upgrade.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")
    lifecycle = _read("windows_service_lifecycle.ps1")
    database = _read("windows_bundled_database.ps1")
    database_safety = _read("windows_database_safety.ps1")
    lifecycle_lock = _read("windows_lifecycle_lock.ps1")
    installer = _read_installer()

    for script in (build, install, prepare, uninstall):
        assert "Read-TicketboxWindowsReleaseConfig" in script
    assert '"/DStopTimeoutMs=' not in build
    assert '"/DRestartDelayMs=' not in build
    assert " -PgServiceName {#PgServiceName}" not in installer
    assert " -BackendServiceName {#BackendServiceName}" not in installer
    assert " -StopTimeoutMs {#StopTimeoutMs}" not in installer
    assert " -RestartDelayMs {#RestartDelayMs}" not in installer
    assert "[int]$TimeoutSeconds = 60" not in lifecycle
    assert "MAX_UPLOAD_SIZE_MB=" not in database
    assert "ENABLE_API_DOCS=" not in database
    assert "ALLOW_PUBLIC_ADMIN_API=" not in database
    assert "CLOUDFLARE_ACCESS_REQUIRED=" not in database
    assert "XPJ_EXTRA_LOOPBACK_HOSTS=127.0.0.1:${BackendPort}" in database
    assert '"-X", "-w"' in database
    assert "--no-psqlrc" in database_safety
    assert "--no-password" in database_safety
    assert "[System.IO.Path]::GetTempPath()" not in database
    assert "Set-TicketboxExactFileAcl" in database
    assert "Remove-TicketboxSensitiveFile $pwfile" in database
    assert "Remove-Item -LiteralPath $pwfile -Force -ErrorAction SilentlyContinue" not in database
    assert "System.Threading.Mutex" not in lifecycle
    assert "FileShare]::None" in lifecycle_lock
    assert "SpecialFolder]::CommonProgramFiles" in lifecycle_lock
    assert "Is64BitProcess" in lifecycle_lock

    for name in (
        "service_state_timeout_ms",
        "service_poll_interval_ms",
        "postgres_ready_timeout_ms",
        "postgres_ready_poll_interval_ms",
        "pre_upgrade_postgres_ready_timeout_ms",
        "pre_upgrade_postgres_ready_poll_interval_ms",
        "backend_ready_timeout_ms",
        "backend_ready_poll_interval_ms",
        "backend_health_request_timeout_ms",
        "bootstrap_request_timeout_ms",
        "secret_byte_count",
    ):
        assert name in config
        assert name in _read("windows_release_config.ps1")


def test_install_and_uninstall_share_fail_closed_service_ownership() -> None:
    install = _read("install_bundled_services.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")

    for script in (install, uninstall):
        assert ". $LifecycleScript" in script
        assert "Stop-TicketboxOwnedServiceIfExists" in script
        assert "Remove-TicketboxOwnedServiceIfExists" in script
        assert "Get-ExpectedServiceExecutable" in script
        assert "Assert-ExpectedServiceConfiguration" in script
    assert "停止服务 $Name 失败" not in install
    assert "停止服务 $Name 失败" not in uninstall
    assert "Assert-TicketboxPgScmProcessAgreement" in uninstall
    assert "Remove-TicketboxPgServiceIfExists" in uninstall
    assert "& $PgCtl status -D $PgData" in uninstall
    assert uninstall.index("Assert-TicketboxPgScmProcessAgreement") < uninstall.index(
        'Write-Step "停止并删除后端服务"'
    )
    assert "Start-Service -Name $PgServiceName" not in install
    assert "Start-Service -Name $BackendServiceName" not in install
    assert "Restart-Service -Name $BackendServiceName" not in install


def test_uninstall_preflights_marker_and_paths_before_mutation() -> None:
    install = _read("install_bundled_services.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")
    safety = _read("windows_installation_safety.ps1")

    assert "Write-TicketboxDataRootMarker" in safety
    assert "Invoke-IcaclsChecked" in install
    assert "Initialize-TicketboxSecureDataRoot" in install
    assert "Set-TicketboxExactDirectoryAcl" in install
    assert "Assert-TicketboxDataRootDeletionSafety" in uninstall
    assert "AllowProtectedMarkerWithoutRegistration" in safety
    assert "Assert-TicketboxExactFileAcl" in safety
    assert "$ExplicitDataRootProvided" in uninstall
    assert "Assert-TicketboxDataRootForDeletion" in uninstall
    preflight = uninstall.index("$safeRoot = Assert-UninstallInputs")
    first_remove = uninstall.index("Remove-ServiceIfExists $BackendServiceName")
    assert preflight < first_remove
    assert "ticketbox-data-root-v1" in safety
    assert "拒绝把非空目录收编" in safety
    assert "Assert-NoTicketboxReparsePoints" in safety
    assert "Assert-NoTicketboxAncestorReparsePoints" in safety
    assert "Get-TicketboxProtectedProfileRoots" in safety
    assert 'Invoke-TicketboxIcaclsChecked $Path @("/inheritance:r")' in safety
    assert 'Invoke-TicketboxIcaclsChecked $Path @("/grant:r"' in safety
    assert "RegisteredDataRoot" in safety
    assert 'GetFolderPath("Windows")' in safety
    assert "Remove-TicketboxDataRootExact `" in uninstall
    assert "-Path $safeRoot `" in uninstall
    assert "-OnRootHandleAcquired $finalDeletionGuard" in uninstall
    deletion_guard = uninstall[
        uninstall.index("$finalDeletionGuard = {") : uninstall.index(
            "Write-Ok \"数据目录已删除。\""
        )
    ]
    assert "Assert-TicketboxRuntimeProcessesStoppedForDataDeletion" in deletion_guard
    assert "Assert-TicketboxBackendPortStoppedForDataDeletion" in deletion_guard
    assert "Assert-TicketboxPgScmProcessAgreement" in deletion_guard
    assert "TicketboxExactTreeDeleteNativeMethods" in safety
    assert "SetFileInformationByHandle" in safety
    assert "FileShareRead," in safety
    assert "FileShareRead | FileShareWrite" not in safety
    assert "Remove-Item -LiteralPath $safeRoot -Recurse" not in uninstall


def test_delete_data_proves_runtime_stopped_when_service_or_registered_port_is_missing() -> None:
    uninstall = _read("uninstall_bundled_services.ps1")
    helper = uninstall[
        uninstall.index("function Assert-TicketboxMissingBackendServicePortStoppedForDataDeletion") : uninstall.index(
            "function Assert-UninstallInputs"
        )
    ]

    assert "$DeleteData" in helper
    assert "$InstallationIdentityCleanupIncomplete" in uninstall
    identity_cleanup = uninstall[
        uninstall.index("$PreservedIdentityNames = @(") : uninstall.index("$RegisteredDataRoot")
    ]
    assert identity_cleanup.index('"BackendPort"') < identity_cleanup.index('"DataRoot"')
    assert "Service-Exists $BackendServiceName" in helper
    assert "Assert-TicketboxRuntimeProcessesStoppedForDataDeletion" in helper
    assert "if ($BackendPort -gt 0)" in helper
    assert "Assert-TicketboxBackendPortStoppedForDataDeletion" in helper
    assert 'elseif (Test-Path -LiteralPath (Join-Path $AppData ".env") -PathType Leaf)' in uninstall
    assert "($InstallationIdentityAlreadyRemoved -or $InstallationIdentityCleanupIncomplete) -and" in uninstall
    assert "[string]::IsNullOrWhiteSpace($DataRoot)" in uninstall
    assert "$DeleteData -and" in uninstall
    assert "($ExplicitDataRootProvided -or $RegisteredDataRoot.Trim().Length -gt 0)" in uninstall
    port_helper = uninstall[
        uninstall.index("function Assert-TicketboxBackendPortStoppedForDataDeletion") : uninstall.index(
            "function Remove-TicketboxPgServiceIfExists"
        )
    ]
    assert "Get-TicketboxListeningProcessIds $BackendPort" in port_helper
    assert "$listeners.Count -gt 0" in port_helper
    preflight = uninstall[
        uninstall.index("function Assert-UninstallInputs") : uninstall.index(
            "function Remove-TicketboxPreservedInstallationIdentity"
        )
    ]
    assert "Assert-TicketboxMissingBackendServicePortStoppedForDataDeletion" in preflight
    assert uninstall.index("$safeRoot = Assert-UninstallInputs") < uninstall.index(
        "Remove-ServiceIfExists $BackendServiceName"
    )

    receipt_validation = uninstall.index("Get-TicketboxCompletedLifecycleReceiptForDataDeletion")
    first_service_cleanup = uninstall.index("Remove-ServiceIfExists $BackendServiceName")
    receipt_removal = uninstall.rindex("Remove-TicketboxCompletedLifecycleReceipt")
    recovery_cleanup = uninstall.index("Remove-TicketboxPgRecoveryToolset -ExpectedMajor $preservedPgMajor")
    assert receipt_validation < first_service_cleanup < recovery_cleanup < receipt_removal
    assert "Read-TicketboxCompletedLifecycleReceipt" in uninstall
    assert '"InstallDir"' in identity_cleanup
    for binding in (
        "-ExpectedPgPort $RegisteredPgPortNumber",
        "-ExpectedBackendPort $BackendPort",
        "-ExpectedPgServiceName $RegisteredPgServiceName",
        "-ExpectedBackendServiceName $RegisteredBackendServiceName",
    ):
        assert binding in uninstall


def test_inno_acl_and_post_child_failure_compensation_mutations() -> None:
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")

    harden = windows[
        windows.index("function HardenLifecycleLockPath") : windows.index(
            "function AcquireLifecycleLock"
        )
    ]
    reset = harden.index("RunLifecycleIcacls(TargetPath, '/reset')")
    remove_inheritance = harden.index("RunLifecycleIcacls(TargetPath, '/inheritance:r')")
    exact_grant = harden.index("RunLifecycleIcacls(TargetPath, GrantArguments)")
    assert reset < exact_grant < remove_inheritance
    assert '*S-1-5-18' in harden
    assert '*S-1-5-32-544' in harden

    runner = windows[
        windows.index("function RunPowerShellChecked") : windows.index(
            "function StartDataRootMutationGuard"
        )
    ]
    child_success = runner.index("LastPowerShellChildSucceeded := ResultCode = 0")
    commit_branch = runner.index("if CompareText(Context, 'Ticketbox installer lifecycle commit') = 0")
    post_child_hardening = runner.index("if not HardenLifecycleLockPath(LogPath, False)")
    assert child_success < commit_branch < post_child_hardening
    assert "Result := True;" in runner[commit_branch:post_child_hardening]

    prepare = flow[
        flow.index("function PrepareToInstall") : flow.index("procedure CurStepChanged")
    ]
    failed_call = prepare.index("if not RunPowerShellChecked")
    record_prepared = prepare.index("if LastPowerShellChildSucceeded then", failed_call)
    assert failed_call < record_prepared
    assert "LifecyclePrepared := True" in prepare[record_prepared:]

    deinitialize = flow[
        flow.index("procedure DeinitializeSetup") : flow.index(
            "procedure CurUninstallStepChanged"
        )
    ]
    assert "if LifecyclePrepared and (not LifecycleInstallCompleted)" in deinitialize
    assert "if LifecycleFilesMayBeReplaced then" in deinitialize
    assert "Args := Args + ' -FilesReplaced'" in deinitialize

    commit = flow[
        flow.index("'Ticketbox installer lifecycle commit'") : flow.index(
            "procedure DeinitializeSetup"
        )
    ]
    report_commit_failure = commit.index("RaiseException")
    record_completed = commit.index("LifecycleInstallCompleted := True")
    assert report_commit_failure < record_completed
    assert "if LastPowerShellChildSucceeded then" not in commit
    assert "DeleteFile(ExpandConstant('{commoncf64}\\Ticketbox\\installer-lifecycle-receipt.json'))" not in deinitialize


def test_installer_rejects_wizard_silent_before_mutation_and_holds_data_root_guard() -> None:
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")

    initialize = windows[
        windows.index("function InitializeSetup") : windows.index("function InitializeUninstall")
    ]
    assert initialize.index("if WizardSilent then") < initialize.index("AcquireLifecycleLock()")
    assert "无人值守安装合同" in initialize

    prepare = flow[flow.index("function PrepareToInstall") : flow.index("procedure CurStepChanged")]
    guard_start = prepare.index("StartDataRootMutationGuard")
    pre_copy = prepare.index("'Ticketbox pre-upgrade backup and service preparation'")
    assert guard_start < pre_copy
    assert "AssertDataRootMutationGuardActive()" in prepare[guard_start:pre_copy]

    postinstall = flow[flow.index("procedure CurStepChanged") : flow.index("procedure DeinitializeSetup")]
    assert postinstall.index("AssertDataRootMutationGuardActive()") < postinstall.index(
        "LifecycleFilesMayBeReplaced := True"
    )
    assert postinstall.count("AssertDataRootMutationGuardActive()") >= 3

    deinitialize = flow[
        flow.index("procedure DeinitializeSetup") : flow.index("procedure CurUninstallStepChanged")
    ]
    assert deinitialize.index("ReleaseDataRootMutationGuard()") < deinitialize.index(
        "ReleaseLifecycleLock()"
    )
    holder = _read("prepare_bundled_upgrade.ps1")
    assert "Wait-TicketboxDirectoryMutationGuardLease" in holder
    safety = _read("windows_installation_safety.ps1")
    guard = safety[
        safety.index("function Enter-TicketboxDirectoryMutationGuard") : safety.index(
            "function Initialize-TicketboxDurableFileNativeMethods"
        )
    ]
    assert "0x02200000" in guard
    assert "0x3" in guard
    assert "FileShareDelete" not in guard


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Inno argv contract")
def test_inno_quote_roundtrips_command_line_to_argvw_and_rejects_unsafe_text(
    tmp_path: Path,
) -> None:
    import ctypes
    from ctypes import wintypes

    windows = _read("ticketbox-installer-windows.isph")
    quote_function = windows[
        windows.index("function Quote") : windows.index("function WindowsPowerShellExecutable")
    ]
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6/ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6/ISCC.exe",
    )
    iscc = next((candidate for candidate in candidates if candidate.is_file()), None)
    assert iscc is not None, "Inno Setup 6 compiler is required"

    output_path = tmp_path / "quoted-arguments.txt"
    source = tmp_path / "quote-contract.iss"
    source.write_text(
        """
[Setup]
AppName=Ticketbox Quote Contract
AppVersion=1.0
DefaultDirName={tmp}\\TicketboxQuoteContract
PrivilegesRequired=lowest
Uninstallable=no
OutputDir=.
OutputBaseFilename=quote-contract

[Code]
"""
        + quote_function
        + """
function InitializeSetup(): Boolean;
var
  OutputText: String;
  QuoteRejected: Boolean;
  NewlineRejected: Boolean;
begin
  OutputText := Quote('C:\\Ticketbox\\') + #13#10 +
    Quote('C:\\Ticketbox Data\\') + #13#10 +
    Quote('') + #13#10;
  QuoteRejected := False;
  try
    Quote('unsafe"argument');
  except
    QuoteRejected := True;
  end;
  NewlineRejected := False;
  try
    Quote('unsafe' + #10 + 'argument');
  except
    NewlineRejected := True;
  end;
  if (not QuoteRejected) or (not NewlineRejected) then
    RaiseException('unsafe argument was accepted');
  if not SaveStringToFile(ExpandConstant('{param:OutputPath|}'), OutputText, False) then
    RaiseException('could not save quote contract output');
  Result := False;
end;
""",
        encoding="utf-8-sig",
    )
    compile_result = subprocess.run(
        [iscc, source],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    installer = tmp_path / "quote-contract.exe"
    run_result = subprocess.run(
        [installer, "/VERYSILENT", f"/OutputPath={output_path}"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    assert output_path.is_file(), run_result.stdout + run_result.stderr

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    expected = ["C:\\Ticketbox\\", "C:\\Ticketbox Data\\", ""]
    for command_line, expected_argument in zip(
        output_path.read_text(encoding="utf-8-sig").splitlines(), expected, strict=True
    ):
        argc = ctypes.c_int()
        argv = shell32.CommandLineToArgvW(f"helper.exe {command_line}", ctypes.byref(argc))
        assert argv
        try:
            assert argc.value == 2
            assert argv[1] == expected_argument
        finally:
            kernel32.LocalFree(argv)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DataRoot handle lease contract")
def test_data_root_guard_lease_blocks_cross_process_root_and_ancestor_rename(
    tmp_path: Path,
) -> None:
    safety = str(PACKAGING / "windows_installation_safety.ps1").replace("'", "''")
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"

    for index, engine in enumerate(engines):
        protocol = tmp_path / f"lease-{index}"
        phase_parent = protocol / "mutable-parent"
        data_root = phase_parent / "data-root"
        moved_root = phase_parent / "data-root-moved"
        moved_parent = protocol / "mutable-parent-moved"
        ready = protocol / "guard.ready"
        release = protocol / "guard.release"
        protocol.mkdir()
        harness = protocol / "hold-guard.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
function Assert-TicketboxProtectedDirectoryAcl([string]$Path) {{ }}
function Assert-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}}
Wait-TicketboxDirectoryMutationGuardLease `
    -Path '{str(data_root).replace("'", "''")}' `
    -ReadyPath '{str(ready).replace("'", "''")}' `
    -ReleasePath '{str(release).replace("'", "''")}' `
    -OwnerProcessId {os.getpid()}
""",
            encoding="utf-8-sig",
        )
        process = subprocess.Popen(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.is_file() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready.is_file(), process.communicate(timeout=5)
            assert data_root.is_dir()
            with pytest.raises(OSError):
                data_root.rename(moved_root)
            with pytest.raises(OSError):
                phase_parent.rename(moved_parent)
            release.write_bytes(
                f"STATE=release\r\nOWNER_PID={os.getpid()}\r\n".encode()
            )
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, f"{engine}:\n{stdout}\n{stderr}"
            phase_parent.rename(moved_parent)
            moved_parent.rename(phase_parent)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


def test_windows_safety_helpers_execute_in_available_powershells(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell behavior contract")
    assert_pg_recovery_toolset_behavior(tmp_path)

    lifecycle = PACKAGING / "windows_service_lifecycle.ps1"
    safety = PACKAGING / "windows_installation_safety.ps1"
    lifecycle_lock = PACKAGING / "windows_lifecycle_lock.ps1"
    database_safety = PACKAGING / "windows_database_safety.ps1"
    release_config_script = PACKAGING / "windows_release_config.ps1"
    uninstall = _read("uninstall_bundled_services.ps1")
    process_guard = uninstall[
        uninstall.index("function Assert-TicketboxRuntimeProcessesStoppedForDataDeletion") : uninstall.index(
            "function Assert-TicketboxBackendPortStoppedForDataDeletion"
        )
    ]
    base = ROOT / "backend" / "build" / f"installer-safety-{uuid.uuid4().hex}"
    data_root = base / "ticketbox-data"
    install_dir = base / "ticketbox-program"
    data_root.mkdir(parents=True)
    install_dir.mkdir()
    dynamic_config_path = base / "windows-release-config.json"
    dynamic_config = json.loads(_read("windows-release-config.json"))
    dynamic_config["service_state_timeout_ms"] += 137
    dynamic_config_path.write_text(json.dumps(dynamic_config, ensure_ascii=False), encoding="utf-8")
    installed_config_path = base / "windows-release-config-installed.json"
    installed_config = dict(dynamic_config)
    installed_config["stop_timeout_ms"] += 111
    installed_config["restart_delay_ms"] += 222
    installed_config_path.write_text(json.dumps(installed_config, ensure_ascii=False), encoding="utf-8")
    changed_identity_config_path = base / "windows-release-config-changed-identity.json"
    changed_identity_config = dict(dynamic_config)
    changed_identity_config["backend_service_name"] += "V2"
    changed_identity_config_path.write_text(
        json.dumps(changed_identity_config, ensure_ascii=False),
        encoding="utf-8",
    )
    conflicting_service_config_path = base / "windows-release-config-conflicting-services.json"
    conflicting_service_config = dict(dynamic_config)
    conflicting_service_config["backend_service_name"] = conflicting_service_config["pg_service_name"]
    conflicting_service_config_path.write_text(
        json.dumps(conflicting_service_config, ensure_ascii=False),
        encoding="utf-8",
    )

    def literal(path: Path) -> str:
        return str(path).replace("'", "''")

    command = f"""
$ErrorActionPreference = 'Stop'
. '{literal(lifecycle)}'
. '{literal(safety)}'
. '{literal(lifecycle_lock)}'
. '{literal(database_safety)}'
. '{literal(release_config_script)}'
$BackendExe = 'C:\\Ticketbox\\program\\ticketbox-backend.exe'
$ShawlExe = 'C:\\Ticketbox\\shawl\\shawl.exe'
$PgBin = 'C:\\Ticketbox\\pg\\bin'
$PgCtl = Join-Path $PgBin 'pg_ctl.exe'
{process_guard}
$rejected = $false
try {{
    Assert-TicketboxRuntimeProcessesStoppedForDataDeletion -ProcessReader {{
        [pscustomobject]@{{ Name = 'ticketbox-backend.exe'; ExecutablePath = $BackendExe; ProcessId = 4101 }}
    }}
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'exact Ticketbox process path was accepted before data deletion' }}
$rejected = $false
try {{
    Assert-TicketboxRuntimeProcessesStoppedForDataDeletion -ProcessReader {{
        [pscustomobject]@{{ Name = 'postgres.exe'; ExecutablePath = $null; ProcessId = 4102 }}
    }}
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'unreadable same-name process was accepted before data deletion' }}
Assert-TicketboxRuntimeProcessesStoppedForDataDeletion -ProcessReader {{
    [pscustomobject]@{{ Name = 'postgres.exe'; ExecutablePath = 'C:\\OtherPg\\postgres.exe'; ProcessId = 4103 }}
}}
$rejected = $false
try {{ Assert-TicketboxRuntimeProcessesStoppedForDataDeletion -ProcessReader {{ throw 'enumeration failed' }} }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'process enumeration failure did not fail closed' }}
$dynamicConfig = Read-TicketboxWindowsReleaseConfig '{literal(dynamic_config_path)}'
if ($dynamicConfig.service_state_timeout_ms -ne {dynamic_config["service_state_timeout_ms"]}) {{ throw 'release policy was not read dynamically' }}
$installedConfig = Read-TicketboxWindowsReleaseConfig '{literal(installed_config_path)}'
Assert-TicketboxReleaseIdentityCompatible -InstalledConfig $installedConfig -TargetConfig $dynamicConfig
$changedIdentityConfig = Read-TicketboxWindowsReleaseConfig '{literal(changed_identity_config_path)}'
$rejected = $false
try {{ Assert-TicketboxReleaseIdentityCompatible -InstalledConfig $installedConfig -TargetConfig $changedIdentityConfig }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'release identity changed without migration' }}
$rejected = $false
try {{ Read-TicketboxWindowsReleaseConfig '{literal(conflicting_service_config_path)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'conflicting service names were accepted' }}
$localUrl = Assert-TicketboxLocalDatabaseUrl -DatabaseUrl 'postgresql+psycopg://ticketbox:secret@127.0.0.1:5432/ticketbox' -PgPort 5432
if ($localUrl -ne 'postgresql://ticketbox:secret@127.0.0.1:5432/ticketbox') {{ throw 'local DB URL rejected' }}
$connection = Get-TicketboxLocalDatabaseConnection -DatabaseUrl $localUrl -PgPort 5432 -ExpectedDatabase ticketbox -ExpectedRole ticketbox
if ($connection.DatabaseUrl -match 'secret' -or $connection.Password -ne 'secret') {{ throw 'database password was not isolated' }}
$rejected = $false
try {{ Assert-TicketboxLocalDatabaseUrl -DatabaseUrl 'postgresql://ticketbox:secret@example.com:5432/ticketbox' -PgPort 5432 | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'external DB URL accepted' }}
$rejected = $false
try {{ Assert-TicketboxLocalDatabaseUrl -DatabaseUrl 'postgresql://ticketbox:secret@127.0.0.1:5432/ticketbox?hostaddr=203.0.113.7' -PgPort 5432 | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'libpq target override accepted' }}
$rejected = $false
try {{ Get-TicketboxLocalDatabaseConnection -DatabaseUrl 'postgresql://ticketbox:secret@127.0.0.1:5432/postgres' -PgPort 5432 -ExpectedDatabase ticketbox -ExpectedRole ticketbox | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'wrong application database accepted' }}
$rejected = $false
try {{ Get-TicketboxLocalDatabaseConnection -DatabaseUrl 'postgresql://postgres:secret@127.0.0.1:5432/ticketbox' -PgPort 5432 -ExpectedDatabase ticketbox -ExpectedRole ticketbox | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'wrong application role accepted' }}
$rejected = $false
try {{ Get-TicketboxLocalDatabaseConnection -DatabaseUrl 'postgresql://ticketbox:@127.0.0.1:5432/ticketbox' -PgPort 5432 -ExpectedDatabase ticketbox -ExpectedRole ticketbox | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'empty application password accepted' }}
$quoted = ConvertTo-TicketboxServiceExecutablePath '"C:\\Program Files\\Ticketbox\\shawl.exe" run'
if ($quoted -ne 'C:\\Program Files\\Ticketbox\\shawl.exe') {{ throw 'quoted parse failed' }}
$rejected = $false
try {{ ConvertTo-TicketboxServiceExecutablePath 'C:\\Program Files\\Ticketbox\\shawl.exe run' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'unquoted service path was accepted' }}
$dataArg = Get-TicketboxCommandArgumentValue '"C:\\Ticketbox\\pg_ctl.exe" runservice -N "TicketboxPg" -D "D:\\Ticketbox Data\\pgdata" -w' '-D'
if ($dataArg -ne 'D:\\Ticketbox Data\\pgdata') {{ throw 'service argument parse failed' }}
$rejected = $false
try {{ Get-TicketboxCommandArgumentValue '"C:\\Ticketbox\\pg_ctl.exe" runservice -D "D:\\one" -D "D:\\two"' '-D' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'duplicate service argument accepted' }}
$script:testServiceDependencies = @()
function Get-TicketboxServiceDependencies([string]$Name) {{ return $script:testServiceDependencies }}
$script:testServiceImagePath = '"C:\\Ticketbox\\pg_ctl.exe" runservice -N "TicketboxPg" -D "D:\\Ticketbox Data\\pgdata" -w'
function Get-TicketboxServiceImagePath([string]$Name) {{ return $script:testServiceImagePath }}
Assert-TicketboxPgServiceCommand -Name TicketboxPg -ExpectedExecutable 'C:\\Ticketbox\\pg_ctl.exe' -ExpectedServiceName TicketboxPg -ExpectedDataRoot 'D:\\Ticketbox Data\\pgdata'
$script:testServiceDependencies = @('UnexpectedPg')
$rejected = $false
try {{ Assert-TicketboxPgServiceCommand -Name TicketboxPg -ExpectedExecutable 'C:\\Ticketbox\\pg_ctl.exe' -ExpectedServiceName TicketboxPg -ExpectedDataRoot 'D:\\Ticketbox Data\\pgdata' }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'PostgreSQL service dependency was accepted' }}
$script:testServiceDependencies = @()
$script:testServiceImagePath = '"C:\\Ticketbox\\pg_ctl.exe" runservice -N "TicketboxPg" -D "D:\\Ticketbox Data\\pgdata" -w -o "-D D:\\Other"'
$rejected = $false
try {{ Assert-TicketboxPgServiceCommand -Name TicketboxPg -ExpectedExecutable 'C:\\Ticketbox\\pg_ctl.exe' -ExpectedServiceName TicketboxPg -ExpectedDataRoot 'D:\\Ticketbox Data\\pgdata' }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'PostgreSQL option smuggling accepted' }}
$script:testServiceDependencies = @('TicketboxPg')
$script:testServiceImagePath = '"C:\\Ticketbox\\shawl.exe" run --name TicketboxBackend --stop-timeout 25000 --restart --kill-process-tree --restart-delay 5000 --cwd "D:\\Ticketbox Data\\app" --log-dir "D:\\Ticketbox Data\\app\\logs" --env "TICKETBOX_DATA_DIR=D:\\Ticketbox Data\\app" --env "PG_DUMP_PATH=C:\\Ticketbox\\pg_dump.exe" --env "PG_RESTORE_PATH=C:\\Ticketbox\\pg_restore.exe" --env "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH=D:\\Ticketbox Data\\bootstrap-exposure-recovery-pending" -- "C:\\Ticketbox\\backend.exe"'
$shawlArgs = @{{
    Name = 'TicketboxBackend'; ExpectedExecutable = 'C:\\Ticketbox\\shawl.exe'; ExpectedServiceName = 'TicketboxBackend'
    ExpectedCwd = 'D:\\Ticketbox Data\\app'; ExpectedPayload = 'C:\\Ticketbox\\backend.exe'; ExpectedDependency = 'TicketboxPg'
    ExpectedLogDir = 'D:\\Ticketbox Data\\app\\logs'; ExpectedPgDumpPath = 'C:\\Ticketbox\\pg_dump.exe'
    ExpectedPgRestorePath = 'C:\\Ticketbox\\pg_restore.exe'; ExpectedBootstrapRecoveryGuardPath = 'D:\\Ticketbox Data\\bootstrap-exposure-recovery-pending'
    ExpectedStopTimeoutMs = 25000; ExpectedRestartDelayMs = 5000
}}
Assert-TicketboxShawlServiceCommand @shawlArgs
$validShawlImagePath = $script:testServiceImagePath
$script:testServiceImagePath = $validShawlImagePath.Replace(' --kill-process-tree', '')
$rejected = $false
try {{ Assert-TicketboxShawlServiceCommand @shawlArgs }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'Shawl command without process-tree termination was accepted' }}
$script:testServiceImagePath = $validShawlImagePath
$script:testServiceDependencies = @('UnexpectedPg')
$rejected = $false
try {{ Assert-TicketboxShawlServiceCommand @shawlArgs }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'wrong SCM dependency accepted' }}
$script:testServiceDependencies = @('TicketboxPg')
$script:testServiceImagePath = $script:testServiceImagePath.Replace(' -- "C:\\Ticketbox\\backend.exe"', ' --path-prepend "D:\\Other" -- "C:\\Ticketbox\\backend.exe"')
$rejected = $false
try {{ Assert-TicketboxShawlServiceCommand @shawlArgs }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'Shawl option smuggling accepted' }}
$testLockPath = Join-Path '{literal(base)}' 'lifecycle.lock'
$operationLock = Enter-TicketboxExclusiveFileLock $testLockPath
try {{
    $enginePath = (Get-Process -Id $PID).Path
    $childCommand = '. ''{literal(lifecycle_lock)}''; try {{ $m = Enter-TicketboxExclusiveFileLock ''{literal(base / "lifecycle.lock")}''; $m.Dispose(); exit 9 }} catch {{ exit 0 }}'
    & $enginePath -NoLogo -NoProfile -ExecutionPolicy Bypass -Command $childCommand
    if ($LASTEXITCODE -ne 0) {{ throw 'cross-process lifecycle lock did not fail busy' }}
}}
finally {{ Exit-TicketboxLifecycleLock $operationLock }}
$queue = [System.Collections.Generic.Queue[string]]::new()
@('startpending', 'running') | ForEach-Object {{ $queue.Enqueue($_) }}
$state = Wait-TicketboxServiceSettledState -Name Demo -TimeoutMilliseconds 1000 -PollMilliseconds 1 -StateReader {{ param($Name) $queue.Dequeue() }} -SleepAction {{ param($Ms) }}
if ($state -ne 'running') {{ throw 'settled-state wait failed' }}
Initialize-TicketboxDataRootMarker -DataRoot '{literal(data_root)}' -InstallDir '{literal(install_dir)}'
$safe = Assert-TicketboxDataRootDeletionSafety -DataRoot '{literal(data_root)}' -RegisteredDataRoot '{literal(data_root)}' -InstallDir '{literal(install_dir)}'
if ($safe -ne [System.IO.Path]::GetFullPath('{literal(data_root)}')) {{ throw 'safe root mismatch' }}
$rejected = $false
try {{ Assert-TicketboxDataRootDeletionSafety -DataRoot '{literal(data_root)}' -RegisteredDataRoot '' -InstallDir '{literal(install_dir)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'missing registration was accepted without explicit recovery mode' }}
$originalMarkerAclAssertion = ${{function:Assert-TicketboxExactFileAcl}}
$script:protectedMarkerAclChecked = $false
try {{
    function Assert-TicketboxExactFileAcl {{
        param([string]$Path, [string[]]$Accounts, [string]$OwnerAccount)
        if ($Path -ne (Get-TicketboxDataRootMarkerPath '{literal(data_root)}')) {{ throw 'wrong marker ACL path' }}
        if (($Accounts -join ',') -ne 'SYSTEM,BUILTIN\\Administrators' -or $OwnerAccount -ne 'SYSTEM') {{ throw 'wrong marker ACL contract' }}
        $script:protectedMarkerAclChecked = $true
    }}
    $safe = Assert-TicketboxDataRootDeletionSafety `
        -DataRoot '{literal(data_root)}' `
        -RegisteredDataRoot '' `
        -InstallDir '{literal(install_dir)}' `
        -AllowProtectedMarkerWithoutRegistration
    if ($safe -ne [System.IO.Path]::GetFullPath('{literal(data_root)}')) {{ throw 'protected marker recovery root mismatch' }}
    if (-not $script:protectedMarkerAclChecked) {{ throw 'protected marker ACL was not checked' }}
}}
finally {{ Set-Item -Path Function:\\Assert-TicketboxExactFileAcl -Value $originalMarkerAclAssertion }}
$junctionTarget = Join-Path '{literal(base)}' 'junction-target'
$junctionPath = Join-Path '{literal(base)}' 'junction-parent'
New-Item -ItemType Directory -Force -Path $junctionTarget | Out-Null
& cmd.exe /d /c "mklink /J `"$junctionPath`" `"$junctionTarget`"" | Out-Null
if ($LASTEXITCODE -eq 0) {{
    try {{
        $rejected = $false
        try {{ Assert-NoTicketboxAncestorReparsePoints (Join-Path $junctionPath 'child') }} catch {{ $rejected = $true }}
        if (-not $rejected) {{ throw 'ancestor junction was accepted' }}
    }}
    finally {{ [System.IO.Directory]::Delete($junctionPath) }}
}}
& icacls.exe '{literal(data_root)}' /grant '*S-1-1-0:(OI)(CI)R' | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw 'failed to seed stale explicit ACL' }}
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$descendant = Join-Path '{literal(data_root)}' 'stale-child.txt'
Set-Content -LiteralPath $descendant -Value 'test'
& icacls.exe $descendant /grant '*S-1-1-0:R' | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw 'failed to seed stale descendant ACL' }}
Set-TicketboxExactDirectoryAcl -Path '{literal(data_root)}' -Accounts @($currentAccount) -ReadExecuteAccounts @('BUILTIN\\Users') -OwnerAccount $currentAccount -Recurse
$worldSid = New-Object Security.Principal.SecurityIdentifier('S-1-1-0')
foreach ($aclPath in @('{literal(data_root)}', $descendant)) {{
    foreach ($rule in (Get-TicketboxPathAcl $aclPath).Access) {{
        if ($rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $worldSid.Value) {{ throw 'stale explicit ACL survived' }}
    }}
}}
$usersSid = (New-Object Security.Principal.NTAccount('BUILTIN\\Users')).Translate([Security.Principal.SecurityIdentifier]).Value
$rootUsersRules = @((Get-TicketboxPathAcl '{literal(data_root)}').Access | Where-Object {{
    $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $usersSid
}})
if ($rootUsersRules.Count -eq 0) {{ throw 'root ReadExecute account missing' }}
foreach ($rule in $rootUsersRules) {{
    $forbidden = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    if ($rule.InheritanceFlags -ne [Security.AccessControl.InheritanceFlags]::None -or ($rule.FileSystemRights -band $forbidden) -ne 0) {{
        throw 'root ReadExecute account can mutate or inherit into sibling trees'
    }}
}}
$descendantUsersRules = @((Get-TicketboxPathAcl $descendant).Access | Where-Object {{
    $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $usersSid
}})
if ($descendantUsersRules.Count -ne 0) {{ throw 'root ReadExecute account inherited into child tree' }}
$installAclRoot = Join-Path '{literal(base)}' 'install-acl-root'
$installAclChild = Join-Path $installAclRoot 'program\\backend.exe'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $installAclChild) | Out-Null
Set-Content -LiteralPath $installAclChild -Value 'binary'
Set-TicketboxExactDirectoryAcl `
    -Path $installAclRoot `
    -Accounts @($currentAccount) `
    -InheritableReadExecuteAccounts @('BUILTIN\\Users') `
    -OwnerAccount $currentAccount `
    -Recurse
$inheritedUsersRules = @((Get-TicketboxPathAcl $installAclChild).Access | Where-Object {{
    $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $usersSid
}})
if ($inheritedUsersRules.Count -eq 0) {{ throw 'program-tree ReadExecute was removed recursively' }}
foreach ($rule in $inheritedUsersRules) {{
    $forbidden = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete
    if (-not $rule.IsInherited -or ($rule.FileSystemRights -band $forbidden) -ne 0) {{
        throw 'program-tree ReadExecute ACL is not inherited least privilege'
    }}
}}
$secretFile = Join-Path '{literal(data_root)}' 'secret.txt'
Set-Content -LiteralPath $secretFile -Value 'secret'
Set-TicketboxExactFileAcl -Path $secretFile -Accounts @($currentAccount) -OwnerAccount $currentAccount
$secretAcl = Get-TicketboxPathAcl $secretFile
if (-not $secretAcl.AreAccessRulesProtected) {{ throw 'secret file still inherits ACLs' }}
$guardRoot = Join-Path '{literal(base)}' 'guarded-root'
$guardMoved = Join-Path '{literal(base)}' 'guarded-root-moved'
New-Item -ItemType Directory -Force -Path $guardRoot | Out-Null
$guard = Enter-TicketboxDirectoryMutationGuard $guardRoot
$renameBlocked = $false
try {{ Move-Item -LiteralPath $guardRoot -Destination $guardMoved -ErrorAction Stop }}
catch {{ $renameBlocked = $true }}
finally {{ $guard.Dispose() }}
if (-not $renameBlocked) {{ throw 'directory mutation guard allowed root replacement' }}
Move-Item -LiteralPath $guardRoot -Destination $guardMoved -ErrorAction Stop
Move-Item -LiteralPath $guardMoved -Destination $guardRoot -ErrorAction Stop
$guardParent = Join-Path '{literal(base)}' 'guarded-parent'
$guardChild = Join-Path $guardParent 'child'
$guardParentMoved = Join-Path '{literal(base)}' 'guarded-parent-moved'
New-Item -ItemType Directory -Force -Path $guardChild | Out-Null
$guard = Enter-TicketboxDirectoryMutationGuard $guardChild
$ancestorRenameBlocked = $false
try {{ Move-Item -LiteralPath $guardParent -Destination $guardParentMoved -ErrorAction Stop }}
catch {{ $ancestorRenameBlocked = $true }}
finally {{ $guard.Dispose() }}
if (-not $ancestorRenameBlocked) {{ throw 'directory guard allowed ancestor substitution' }}
$durablePath = Join-Path '{literal(base)}' ("durable-state-{{0}}.json" -f $PID)
Write-TicketboxUtf8FileDurable -Path $durablePath -Text 'first'
Write-TicketboxUtf8FileDurable -Path $durablePath -Text 'second' -ReplaceExisting
if ([System.IO.File]::ReadAllText($durablePath) -cne 'second') {{ throw 'durable file replacement failed' }}
$deleteRoot = Join-Path '{literal(base)}' 'exact-delete-root'
$deleteMoved = Join-Path '{literal(base)}' 'exact-delete-moved'
New-Item -ItemType Directory -Force -Path (Join-Path $deleteRoot 'nested') | Out-Null
Set-Content -LiteralPath (Join-Path $deleteRoot 'nested\\payload.txt') -Value 'delete-me'
$script:exactDeleteRenameBlocked = $false
Remove-TicketboxDataRootExact -Path $deleteRoot -OnRootHandleAcquired {{
    param($GuardedPath)
    try {{ Move-Item -LiteralPath $GuardedPath -Destination $deleteMoved -ErrorAction Stop }}
    catch {{ $script:exactDeleteRenameBlocked = $true }}
}}
if (-not $script:exactDeleteRenameBlocked) {{ throw 'exact deletion did not hold the target directory handle' }}
if ((Test-Path -LiteralPath $deleteRoot) -or (Test-Path -LiteralPath $deleteMoved)) {{
    throw 'exact deletion left or redirected the target tree'
}}
$outsideDeleteTarget = Join-Path '{literal(base)}' 'exact-delete-outside'
$reparseDeleteRoot = Join-Path '{literal(base)}' 'exact-delete-reparse-root'
$reparseDeleteChild = Join-Path $reparseDeleteRoot 'linked-child'
New-Item -ItemType Directory -Force -Path $outsideDeleteTarget, $reparseDeleteRoot | Out-Null
Set-Content -LiteralPath (Join-Path $outsideDeleteTarget 'keep.txt') -Value 'keep'
& cmd.exe /d /c "mklink /J `"$reparseDeleteChild`" `"$outsideDeleteTarget`"" | Out-Null
if ($LASTEXITCODE -eq 0) {{
    $rejected = $false
    try {{ Remove-TicketboxDataRootExact -Path $reparseDeleteRoot }} catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw 'exact deletion followed a descendant reparse point' }}
    if (-not (Test-Path -LiteralPath (Join-Path $outsideDeleteTarget 'keep.txt') -PathType Leaf)) {{
        throw 'exact deletion escaped through a reparse point'
    }}
    [System.IO.Directory]::Delete($reparseDeleteChild)
    Remove-TicketboxDataRootExact -Path $reparseDeleteRoot
}}
$rejected = $false
try {{ Assert-TicketboxDataRootDeletionSafety -DataRoot 'C:\\Windows' -RegisteredDataRoot 'C:\\Windows' -InstallDir '{literal(install_dir)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'Windows directory was accepted' }}
$rejected = $false
try {{ Assert-TicketboxDataRootDomain -DataRoot $env:USERPROFILE -InstallDir '{literal(install_dir)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'user profile data root was accepted' }}
$rejected = $false
try {{ Assert-TicketboxDataRootDomain -DataRoot '\\\\localhost\\C$\\Ticketbox' -InstallDir '{literal(install_dir)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'UNC data root was accepted' }}
Assert-TicketboxRegisteredDataRootBinding `
    -DataRoot '{literal(data_root)}' `
    -RegistryReader {{ return '{literal(data_root)}' }}
$rejected = $false
try {{
    Assert-TicketboxRegisteredDataRootBinding `
        -DataRoot '{literal(data_root)}' `
        -RegistryReader {{ return '{literal(base / "other-data")}' }}
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'mismatched machine data-root binding was accepted' }}
$adoptionRoot = Join-Path '{literal(base)}' 'unrelated-data'
New-Item -ItemType Directory -Force -Path $adoptionRoot | Out-Null
Set-Content -LiteralPath (Join-Path $adoptionRoot 'family-photo.txt') -Value 'keep'
$rejected = $false
try {{ Initialize-TicketboxDataRootMarker -DataRoot $adoptionRoot -InstallDir '{literal(install_dir)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'non-empty unrelated directory was adopted' }}
function Get-TicketboxDataRootDriveType([string]$CanonicalPath) {{
    return [System.IO.DriveType]::Network
}}
$rejected = $false
try {{ Assert-TicketboxDataRootDomain -DataRoot '{literal(data_root)}' -InstallDir '{literal(install_dir)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'mapped network drive data root was accepted' }}
"""
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    behavior_script = base / "installer-safety-behavior.ps1"
    behavior_script.write_text(command, encoding="utf-8-sig")
    try:
        for engine in engines:
            result = subprocess.run(
                [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", behavior_script],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_installer_input_gate_requires_all_safety_scripts() -> None:
    build = _read("build_inno_installer.ps1")

    assert '$SafetyScript = Join-Path $ScriptDir "windows_installation_safety.ps1"' in build
    assert 'Assert-File $SafetyScript "Windows 安装安全脚本"' in build
    assert '$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"' in build
    assert 'Assert-File $LockScript "Windows 生命周期锁脚本"' in build
    assert '$DatabaseSafetyScript = Join-Path $ScriptDir "windows_database_safety.ps1"' in build
    assert 'Assert-File $DatabaseSafetyScript "Windows 数据库安全脚本"' in build
    assert "Assert-TicketboxLocalDatabaseUrl" in _read("windows_database_safety.ps1")
    assert "Assert-TicketboxLocalDatabaseUrl" not in _read("windows_installation_safety.ps1")


def test_installer_input_gate_requires_lifecycle_scripts() -> None:
    build = _read("build_inno_installer.ps1")

    assert '$PrepareScript = Join-Path $ScriptDir "prepare_bundled_upgrade.ps1"' in build
    assert '$ServiceContractScript = Join-Path $ScriptDir "windows_service_contract.ps1"' in build
    assert '$LifecycleScript = Join-Path $ScriptDir "windows_service_lifecycle.ps1"' in build
    assert '$DatabaseScript = Join-Path $ScriptDir "windows_bundled_database.ps1"' in build
    assert '$BackendBootstrapScript = Join-Path $ScriptDir "windows_backend_bootstrap.ps1"' in build
    assert '$ReleaseConfigScript = Join-Path $ScriptDir "windows_release_config.ps1"' in build
    assert 'Assert-File $PrepareScript "升级前预检脚本"' in build
    assert 'Assert-File $ServiceContractScript "Windows 服务命令契约脚本"' in build
    assert 'Assert-File $LifecycleScript "Windows 服务生命周期脚本"' in build
    assert 'Assert-File $BackendBootstrapScript "Windows 后端就绪/bootstrap 脚本"' in build
