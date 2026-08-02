from __future__ import annotations

import ctypes
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
from _powershell_contract import powershell_contract_engines

ROOT = Path(__file__).resolve().parents[3]
PACKAGING = ROOT / "backend" / "packaging"


class _WindowsFileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def _windows_process_creation_filetime_parts(process_id: int) -> tuple[int, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_WindowsFileTime),
        ctypes.POINTER(_WindowsFileTime),
        ctypes.POINTER(_WindowsFileTime),
        ctypes.POINTER(_WindowsFileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x1000, False, process_id)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    creation = _WindowsFileTime()
    exit_time = _WindowsFileTime()
    kernel_time = _WindowsFileTime()
    user_time = _WindowsFileTime()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return creation.high, creation.low
    finally:
        kernel32.CloseHandle(handle)


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def _start_exclusive_file_lock(
    engine: str,
    tmp_path: Path,
    name: str,
    lock_path: Path,
) -> tuple[subprocess.Popen[str], Path]:
    ready_path = tmp_path / f"{name}.ready"
    release_path = tmp_path / f"{name}.release"
    script = tmp_path / f"{name}.ps1"
    script.write_text(
        f"""
$ErrorActionPreference = 'Stop'
$stream = [System.IO.File]::Open(
    '{str(lock_path).replace("'", "''")}',
    [System.IO.FileMode]::OpenOrCreate,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::None
)
try {{
    [System.IO.File]::WriteAllText('{str(ready_path).replace("'", "''")}', 'ready')
    while (-not (Test-Path -LiteralPath '{str(release_path).replace("'", "''")}')) {{
        Start-Sleep -Milliseconds 50
    }}
}}
finally {{ $stream.Dispose() }}
""",
        encoding="utf-8-sig",
    )
    process = subprocess.Popen(
        [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.monotonic() + 10
    while not ready_path.is_file() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if not ready_path.is_file():
        stdout, stderr = process.communicate(timeout=5)
        pytest.fail(f"{engine} did not acquire {name}:\n{stdout}\n{stderr}")
    return process, release_path


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
        "hold_installer_lifecycle_lock.ps1",
        "hold_data_root_mutation_guard.ps1",
        "windows_database_safety.ps1",
        "windows_pg_recovery_tools.ps1",
        "windows_release_config.ps1",
        "windows-release-config.json",
    )
    for name in pre_copy_dependencies:
        assert f'Source: "{name}"; Flags: dontcopy noencryption' in installer
        assert f"'{name}'," in installer
    prepare_source = _read("prepare_bundled_upgrade.ps1")
    prepare_sibling_imports = set(
        re.findall(
            r'Join-Path \$ScriptDir "([A-Za-z0-9_-]+\.ps1)"',
            prepare_source,
        )
    )
    installer_lines = installer.splitlines()
    for name in prepare_sibling_imports:
        assert any(
            "Source:" in line
            and name in line
            and "Flags: dontcopy noencryption" in line
            for line in installer_lines
        ), f"prepare sibling is missing from protected pre-copy sources: {name}"
        assert f"'{name}'," in installer, (
            f"prepare sibling is not staged into the protected bootstrap bundle: {name}"
        )
    for name in (
        "windows_backend_build_provenance.ps1",
        "windows_build_provenance.ps1",
    ):
        assert f"'{name}'," in installer
    assert (PACKAGING / "hold_installer_lifecycle_lock.ps1").read_bytes().startswith(
        b"\xef\xbb\xbf"
    )
    assert (PACKAGING / "hold_data_root_mutation_guard.ps1").read_bytes().startswith(
        b"\xef\xbb\xbf"
    )

    installed_dependencies = pre_copy_dependencies + (
        "windows_bundled_database.ps1",
        "windows_c07_database.ps1",
        "windows_c07_superuser_recovery.ps1",
        "windows_c07_heartbeat_authority.ps1",
        "windows_c07_lifecycle.ps1",
        "windows_c07_heartbeat_helper.ps1",
        "windows_c07_failure_summary.ps1",
        "windows_c07_recovery_generation.ps1",
        "windows_c07_packaged_migration.ps1",
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
    assert installer.index("'windows_build_provenance.ps1',") < installer.index(
        "'windows_backend_build_provenance.ps1',"
    )

    prepare = prepare_source
    install = _read("install_bundled_services.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")
    bootstrap = _read("windows_backend_bootstrap.ps1")
    receipt = _read("windows_lifecycle_receipt.ps1")
    for variable in (
        "$C07DatabaseScript",
        "$C07SuperuserRecoveryScript",
        "$C07LifecycleScript",
        "$C07FailureSummaryScript",
        "$C07RecoveryGenerationScript",
        "$C07PackagedMigrationScript",
    ):
        assert f". {variable}" in install
    assert "$C07HeartbeatAuthorityScript = Join-Path `" in install
    assert '"windows_c07_heartbeat_authority.ps1"' in install
    assert (
        "Test-Path -LiteralPath $C07HeartbeatAuthorityScript -PathType Leaf"
        in install
    )
    assert ". $C07HeartbeatAuthorityScript" not in install
    assert "$C07HeartbeatHelperScript = Join-Path `" in install
    assert '"windows_c07_heartbeat_helper.ps1"' in install
    assert "Test-Path -LiteralPath $C07HeartbeatHelperScript -PathType Leaf" in install
    assert ". $C07HeartbeatHelperScript" not in install
    assert '$C07MigrationHelper = Join-Path $ProgramDir "ticketbox-c07-migrator.exe"' in install
    assert "function Invoke-TicketboxC07InstalledMigrationAction" in install
    assert "function Invoke-TicketboxC07InstalledFreshSourceBootstrapAction" in install
    assert "function Invoke-TicketboxInstalledManagedSchemaUpgrade" in install
    assert "Enable-TicketboxC07MigratorForManagedSchemaUpgrade" in install
    assert "Invoke-TicketboxC07RecoveredSuperuserAction" in install
    assert 'Write-Step "收敛 release schema 到 frozen head"' in install
    assert 'Assert-File $C07MigrationHelper "ticketbox-c07-migrator.exe"' in install
    for script in (prepare, install, uninstall):
        assert ". $ReleaseConfigScript" in script
        assert ". $LifecycleScript" in script
        assert ". $SafetyScript" in script
        assert ". $LockScript" in script
    for script in (prepare, install, uninstall):
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
    windows = _read("ticketbox-installer-windows.isph")
    lifecycle_lock = _read("windows_lifecycle_lock.ps1")
    assert "LifecycleInstallerStatePath('owner-bootstrap.txt')" in flow
    assert "LifecycleInstallerStatePath('owner-handoff-pending')" in flow
    assert "AddBackslash(LifecycleInstallerStateDirectory) + FileName" in windows
    assert "'installer-state\\' + FileName" not in windows
    assert '"INSTALLER_STATE=$(Join-Path $lockRoot $script:TicketboxInstallerStateDirectoryName)' in lifecycle_lock
    acquire_lock = windows[
        windows.index("function AcquireLifecycleLock") : windows.index(
            "procedure ReleaseLifecycleLock"
        )
    ]
    assert "FileExists(LifecycleLockHolderReadyPath)" not in acquire_lock[
        : acquire_lock.index("Params :=")
    ]
    holder_launch = acquire_lock.index("if not Exec(")
    root_validation_poll = acquire_lock.index(
        "if FileExists(LifecycleLockRootValidatedPath)", holder_launch
    )
    root_validation_accept = acquire_lock.index("RootValidated := True", root_validation_poll)
    machine_ready_poll = acquire_lock.index(
        "FileExists(LifecycleLockHolderReadyPath)", holder_launch
    )
    assert holder_launch < root_validation_poll < root_validation_accept < machine_ready_poll
    assert "FileExists(LifecycleLockHolderReadyPath)" not in acquire_lock[
        holder_launch:root_validation_accept
    ]
    holder = lifecycle_lock[
        lifecycle_lock.index("function Wait-TicketboxExternalInstallerLifecycleLock") :
        lifecycle_lock.index("function Enter-TicketboxLifecycleLock")
    ]
    assert holder.index("Initialize-TicketboxLifecycleLockDirectory") < holder.index(
        "Test-Path -LiteralPath $readyFullPath"
    )
    assert holder.index("Test-Path -LiteralPath $readyFullPath") < holder.index(
        '"STATE=root_validated$([Environment]::NewLine)"'
    )
    assert holder.index('"STATE=root_validated$([Environment]::NewLine)"') < holder.index(
        "$lockPath = Join-Path $lockRoot"
    )
    assert holder.index("$operationLockPath = Join-Path $lockRoot") < holder.index(
        "Test-TicketboxExclusiveFileLockHeld -Path $operationLockPath"
    )
    assert "function Get-TicketboxInstallerStateDirectory" in lifecycle_lock
    assert "$script:TicketboxInstallerStateDirectoryName" in lifecycle_lock
    lock_provider = lifecycle_lock[
        lifecycle_lock.index("function Get-TicketboxLifecycleLockPath") : lifecycle_lock.index(
            "function Get-TicketboxLifecycleLockOwnerPath"
        )
    ]
    assert "Initialize-TicketboxLifecycleLockDirectory" in lock_provider
    assert "Set-TicketboxExactDirectoryAcl" not in lock_provider
    lock_initializer = lifecycle_lock[
        lifecycle_lock.index("function Initialize-TicketboxLifecycleLockDirectory") : lifecycle_lock.index(
            "function Get-TicketboxLifecycleLockPath"
        )
    ]
    assert "Assert-TicketboxProtectedDirectoryAcl" in lock_initializer
    assert "Initialize-TicketboxProtectedDirectoryAtomically" in lock_initializer
    assert "Enter-TicketboxDirectoryMutationGuard" in lock_initializer
    assert "Set-TicketboxExactDirectoryAcl" not in lock_initializer
    acquire_lock = windows[
        windows.index("function AcquireLifecycleLock") : windows.index(
            "procedure ReleaseLifecycleLock"
        )
    ]
    assert "-InstallerOwnerProcessId " in acquire_lock
    assert "-ExpectedLockDirectory " in acquire_lock
    assert "-RootValidatedPath " in acquire_lock
    assert "-ReadyPath " in acquire_lock
    assert "-ReleasePath " in acquire_lock
    assert "CreateFile(" not in acquire_lock
    assert "ForceDirectories(" not in acquire_lock
    assert "HardenLifecycleLockPath(" not in acquire_lock
    assert "SaveStringToFile(LifecycleLockOwnerPath" not in acquire_lock
    enter_lock = lifecycle_lock[
        lifecycle_lock.index("function Enter-TicketboxLifecycleLock") : lifecycle_lock.index(
            "function Exit-TicketboxLifecycleLock"
        )
    ]
    external_branch = enter_lock[
        enter_lock.index("if ($ExternalOwnerProcessId -gt 0)") : enter_lock.index("else {")
    ]
    assert external_branch.index("Enter-TicketboxProtectedExclusiveFileLock") < external_branch.index(
        "Assert-TicketboxExternalLifecycleLock"
    )
    assert "Set-TicketboxExactFileAcl" not in external_branch
    data_root_holder = _read("hold_data_root_mutation_guard.ps1")
    assert "-RetainWhileLockPath (Get-TicketboxLifecycleOperationLockPath)" in data_root_holder
    holder = _read("hold_installer_lifecycle_lock.ps1")
    assert holder.index("Get-TicketboxParentProcessId") < holder.index(
        "Wait-TicketboxExternalInstallerLifecycleLock"
    )
    assert "Test-TicketboxPathEquals $ExpectedLockDirectory $expectedRoot" in holder
    assert "\\app\\owner-bootstrap.txt" not in flow
    assert "\\app\\owner-handoff-pending" not in flow
    assert "SelectedDataRoot() + '\\installer-state" not in flow
    finished_page = flow[flow.index("procedure CurPageChanged") : flow.index("function NextButtonClick")]
    finish_click = flow[flow.index("function NextButtonClick") : flow.index("function PrepareToInstall")]
    assert "OwnerHandoffMemo.Visible := True" in finished_page
    assert "OwnerHandoffConfirmation.Visible := True" in finished_page
    assert "Android 绑定前须先在管理器中完成手机连接配置" in finished_page
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
    cleanup_start = install.index("if ($CompleteOwnerHandoffOnly)")
    cleanup_end = install.index("$operationLock = Enter-TicketboxLifecycleLock", cleanup_start)
    cleanup_mode = install[cleanup_start:cleanup_end]
    assert cleanup_mode.index("Enter-TicketboxLifecycleLock") < cleanup_mode.index(
        "Complete-TicketboxOwnerBootstrapHandoff"
    )
    assert cleanup_mode.index("Complete-TicketboxOwnerBootstrapHandoff") < cleanup_mode.index(
        "Exit-TicketboxLifecycleLock"
    )
    assert "请先复制一次性绑定信息，并勾选确认后再完成安装" in finish_click
    bootstrap = _read("windows_backend_bootstrap.ps1")
    assert "Android pairing code (requires a configured server URL)" in bootstrap
    assert "configure the phone connection, then use or regenerate this code" in bootstrap
    assert "$InstallerState = Get-TicketboxInstallerStateDirectory" in install
    assert "$InstallerState = Get-TicketboxInstallerStateDirectory" in prepare
    assert '$RecoveryRequiredPath = Join-Path $InstallerState "installer-recovery-required.json"' in install
    state_initialization = install[
        install.index("function Initialize-TicketboxInstallerStateArtifacts") : install.index(
            "function Assert-PortAvailableForMissingServices"
        )
    ]
    assert state_initialization.index("$LegacyRecoveryRequiredPath") < state_initialization.index(
        "Move-TicketboxLegacyOwnerHandoffArtifacts"
    )
    compensation = install[
        install.index("function Invoke-TicketboxInstallFailureCompensation") : install.index(
            'Write-Host "=== 小票夹 Inno 安装器服务配置 ==="'
        )
    ]
    assert "Ensure-TicketboxInstallerRecoveryMarkerAfterFailure" in compensation
    recovery_compensation = receipt[
        receipt.index("function Ensure-TicketboxInstallerRecoveryMarkerAfterFailure") : receipt.index(
            "function Close-TicketboxLifecycleBackupGuard"
        )
    ]
    reconcile = recovery_compensation.index("Move-TicketboxLegacyInstallerStateArtifact")
    preserve = recovery_compensation.index("Read-TicketboxInstallerRecoveryMarker", reconcile)
    create = recovery_compensation.index("Write-TicketboxInstallerRecoveryMarker", preserve)
    assert reconcile < preserve < create
    owner_migration = bootstrap[
        bootstrap.index("function Move-TicketboxLegacyOwnerHandoffArtifacts") : bootstrap.index(
            "function Read-TicketboxOwnerHandoffRecord"
        )
    ]
    preflight = owner_migration.index("Read-TicketboxProtectedUtf8Artifact")
    retain_source = owner_migration.index("-RetainLegacySource")
    bind_pending = owner_migration.index("Write-TicketboxOwnerHandoffPendingMarker")
    retire_source = owner_migration.index("Remove-TicketboxProtectedUtf8Artifact")
    assert preflight < retain_source < bind_pending < retire_source
    assert "Initialize-TicketboxInstallerStateArtifacts" not in cleanup_mode
    assert cleanup_mode.index("Assert-TicketboxDataRootMarker") < cleanup_mode.index(
        "Assert-TicketboxProtectedDirectoryAcl"
    )
    assert "完成页清理不迁移 legacy owner handoff" in cleanup_mode
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
    assert " -TargetBackendVersion {#AppVersion}" in flow
    assert "[int]$TargetPgMajor" in prepare
    assert "[int]$TargetPgMajor = 0" in install
    assert "[Parameter(Mandatory = $true)][string]$TargetBackendVersion" in prepare
    assert "[Parameter(Mandatory = $true)][string]$TargetBackendVersion" in install
    assert 'Join-Path $PgData "PG_VERSION"' in prepare
    prepare_calls = list(
        re.finditer(
            r"LifecycleBootstrapFilePath\('prepare_bundled_upgrade\.ps1'\)",
            flow,
        )
    )
    assert len(prepare_calls) == 4
    for call in prepare_calls:
        args_start = flow.rfind("Args :=\n", 0, call.start())
        assert args_start >= 0
        assert " -TargetPgMajor {#TargetPgMajor}" in flow[args_start : call.start()]
        assert " -TargetBackendVersion {#AppVersion}" in flow[args_start : call.start()]
    install_calls = list(
        re.finditer(r"(?<!un)install_bundled_services\.ps1'\)", flow)
    )
    assert len(install_calls) == 2
    for call in install_calls:
        args_start = flow.rfind("Args :=\n", 0, call.start())
        assert args_start >= 0
        assert " -TargetBackendVersion {#AppVersion}" in flow[args_start : call.start()]
    stale_start = prepare.index("$staleReceipt = Read-TicketboxCompatibleLifecycleReceipt")
    stale_branch = prepare[
        stale_start : prepare.index(
            "Initialize-TicketboxInstalledReleaseConfiguration",
            stale_start,
        )
    ]
    assert stale_branch.count("return") == 2
    assert "AllowCancelDuringInstall=no" in installer
    assert "CloseApplications=yes" in installer
    assert "RestartManagerSupport" not in installer
    assert "RestartApplications=no" in installer
    assert "DisableDirPage=yes" in installer
    assert "UsePreviousAppDir=no" in installer
    assert "function FindAutomaticPort(" in flow
    assert "procedure ResolveInstallationPorts();" in flow
    assert "function ShouldSkipPage(PageID: Integer): Boolean;" in flow
    assert "AdvancedPortSettings.Checked := AdvancedPortsRequested();" in flow
    assert "PageID = PortPage.ID" in flow
    assert "not ManualPortSettingsEnabled()" in flow
    assert "普通用户保持默认即可；如果本机已有 PostgreSQL" not in flow
    assert flow.index("ResolveInstallationPorts();", flow.index("function FreshInstallPortError")) < flow.index(
        "Result := PortConflictMessage();",
        flow.index("function FreshInstallPortError"),
    )
    assert "PowerShellExecutable()" in installer
    assert "IsSupportedPowerShell7Host(PowerShellPath: String)" in installer
    assert "FindMachinePowerShell7()" in installer
    assert "Microsoft\\PowerShellCore\\InstalledVersions" in installer
    assert "HasValidMicrosoftSignature" in installer
    assert "{localappdata}\\Microsoft\\WindowsApps\\pwsh.exe" not in installer
    assert "{sys}\\WindowsPowerShell\\v1.0\\powershell.exe" in installer
    assert "CompareText(PowerShellPath, WindowsPowerShellExecutable())" in installer
    assert "AcquireLifecycleLock" in installer
    assert "LockDirectory + '\\installer-lifecycle-'" in installer
    assert "ExpandConstant('{tmp}\\ticketbox-lifecycle-lock-')" not in installer
    assert "NONCE=" in installer
    assert "IsLowerHexLifecycleNonce" in installer
    assert "HardenLifecycleLockPath(ReleaseTempPath, False)" in installer
    assert installer.count("AssertLifecycleLockActive();") >= 8
    assert installer.count("CreateFileW@kernel32.dll") == 1
    source_lease = windows[
        windows.index("function AcquireInstallerSourceLease") : windows.index(
            "function StartManagerMaintenanceGate"
        )
    ]
    assert source_lease.count("CreateFileForLease(") == 1
    assert "CreateFileForLease(" not in acquire_lock
    assert "hold_installer_lifecycle_lock.ps1" in installer
    assert "OpenProcess(" in installer
    assert "GetProcessTimes(" in installer
    assert "OpenVerifiedProcessIdentityHandle(" in installer
    assert "LifecycleLockHolderProcessId := LongWord(ResultCode)" not in installer
    assert "DataRootGuardProcessId := LongWord(ResultCode)" not in installer
    assert "HOLDER_PID=" in installer
    assert "HOLDER_STARTED_FILETIME_HIGH=" in installer
    assert "HOLDER_STARTED_FILETIME_LOW=" in installer
    assert "-InstallerOwnerStartedFileTimeHigh" in installer
    assert "-InstallerOwnerStartedFileTimeLow" in installer
    assert "INSTALLER_STATE=" in installer
    assert "ValidateLifecycleLockBootstrapFiles" in installer
    assert "GetSHA256OfFile" in installer
    assert "Ticketbox-Installer-Bootstrap-" in installer
    assert "CopyFile(ExtractedPath, ProtectedPath, True)" in installer
    assert "ExpandConstant('{tmp}\\ticketbox-run-installer-child-logged.ps1')" not in installer
    assert "AddBackslash(LifecycleLockBootstrapDirectory)" in installer
    assert "ValidateLoggedPowerShellRunner" in installer
    assert "Quote(LifecycleBootstrapFilePath('windows-release-config.json'))" in installer
    assert "Quote(ExpandConstant('{tmp}\\windows-release-config.json'))" not in installer
    assert "if not FileExists(ExpandConstant('{tmp}\\hold_installer_lifecycle_lock.ps1'))" not in installer
    assert "CreateMutexW@kernel32.dll" not in installer
    assert "ReleaseMutex@kernel32.dll" not in installer
    assert "{commoncf64}\\Ticketbox" in installer
    assert "function InitializeUninstall(): Boolean" in installer
    assert "installer-lifecycle.owner" in installer
    assert "GetCurrentProcessId@kernel32.dll" in installer
    assert "SaveStringToFile(" in installer
    assert installer.count(" -InstallerLockOwnerProcessId ") == 8
    assert "InstallerLockHeld" not in installer
    assert "Pos(#0, Value)" in installer
    assert '"prepare_bundled_upgrade.ps1" = @(' in installer
    assert '"hold_data_root_mutation_guard.ps1" = @(' in installer
    assert '"install_bundled_services.ps1" = @(' in installer
    assert '"uninstall_bundled_services.ps1" = @(' in installer
    assert "Child script resolution mismatch." in installer
    assert "Child parameter is not allowlisted:" in installer
    assert "Duplicate child parameter:" in installer
    prepare_start = installer.index("function PrepareToInstall")
    port_check = installer.index("Result := FreshInstallPortError();", prepare_start)
    protected_bundle_preflight = installer.index(
        "if not ValidateLifecycleLockBootstrapFiles()",
        prepare_start,
    )
    assert port_check < protected_bundle_preflight
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
    assert "Get-TicketboxPreparedApplicationDatabaseConnection" in preserved_branch
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

    copy_boundary = prepare[
        prepare.index("if ($MarkProgramFilesInstalledBackupPending)") : prepare.index(
            "if ($RecoverPreparedInstall)"
        )
    ]
    stage_persistence = min(
        copy_boundary.index("Set-TicketboxLifecycleReceiptProgramFilesInstalledBackupPending"),
        copy_boundary.index("Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced"),
    )
    ratchet = copy_boundary.index("Set-TicketboxLifecycleReceiptTargetVersionFloor")
    durable_verify = copy_boundary.index(
        "Compare-TicketboxLifecycleVersions",
        ratchet,
    )
    boundary_return = copy_boundary.rindex("return")
    assert stage_persistence < ratchet < durable_verify < boundary_return
    assert "-CurrentTargetBackendVersion $TargetBackendVersion" in copy_boundary
    assert "-TargetBackendVersionFloor $TargetBackendVersion" in copy_boundary

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
    data_root_authority = install.index("Initialize-TicketboxDataRootMarker", receipt_files)
    mutation = install.index("$mutationStarted = $true", data_root_authority)
    backend_stop = install.index("Stop-ServiceIfExists", mutation)
    recursive_acl = install.index("Initialize-TicketboxSecureDataRoot", backend_stop)
    initdb = install.index("Initialize-PgClusterIfNeeded", recursive_acl)
    assert cleanup_wal < register_service < backup < remove_service
    assert remove_service < cleanup_complete < receipt_files < data_root_authority
    assert data_root_authority < mutation < backend_stop < recursive_acl < initdb
    deferred_service_contract = install[
        install.index("function Register-TicketboxDeferredPreservedPgService") : backup
    ]
    assert "NT SERVICE\\$PgServiceName" in deferred_service_contract
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
    assert "Invoke-TicketboxPgRestoreList" in direct_backup
    assert "Register-PgService" not in direct_backup
    assert "Initialize-PgClusterIfNeeded" not in direct_backup

    prepared_recovery = prepare[
        prepare.index("if ($RecoverPreparedInstall)") :
        prepare.index("if ($CommitCompletedInstall)")
    ]
    cleanup_obligation = prepared_recovery[
        prepared_recovery.index("if ([bool]$receipt.temporary_pg_service_cleanup_pending") :
        prepared_recovery.index("Remove-TicketboxRecoveryPgServiceIfExists")
    ]
    assert cleanup_obligation.index("Remove-TicketboxDeferredPreservedPgServiceIfExists") < cleanup_obligation.index(
        "-CleanupPending $false"
    )
    stale_start = prepare.index("$staleReceipt = Read-TicketboxCompatibleLifecycleReceipt")
    stale_dispatch = prepare[
        stale_start : prepare.index(
            "Initialize-TicketboxInstalledReleaseConfiguration",
            stale_start,
        )
    ]
    completed_branch = stale_dispatch[
        stale_dispatch.index("if ([bool]$staleReceipt.install_completed)") :
        stale_dispatch.index('elseif ([string]$staleReceipt.preparation_stage -in @(')
    ]
    captured_branch = stale_dispatch[
        stale_dispatch.index('elseif ([string]$staleReceipt.preparation_stage -in @(') :
        stale_dispatch.index(
            'elseif ([string]$staleReceipt.preparation_stage -eq "program_files_installed_backup_pending")'
        )
    ]
    backup_pending_branch = stale_dispatch[
        stale_dispatch.index(
            'elseif ([string]$staleReceipt.preparation_stage -eq "program_files_installed_backup_pending")'
        ) : stale_dispatch.index("else {", stale_dispatch.index("program_files_installed_backup_pending"))
    ]
    post_copy_branch = stale_dispatch[
        stale_dispatch.index("else {", stale_dispatch.index("program_files_installed_backup_pending")) :
    ]
    assert completed_branch.index("Assert-TicketboxPreparedServiceContracts") < completed_branch.index(
        "ConvertTo-TicketboxCurrentLifecycleReceipt"
    )
    assert captured_branch.index("Remove-TicketboxRecoveryPgServiceIfExists") < captured_branch.index(
        "Assert-TicketboxPreparedServiceContracts"
    ) < captured_branch.index(
        "Invoke-TicketboxPreparedInstallRecovery"
    ) < captured_branch.index("Remove-TicketboxLifecycleReceipt")
    assert "ConvertTo-TicketboxCurrentLifecycleReceipt" not in captured_branch
    for branch in (completed_branch, post_copy_branch):
        assert branch.index("Remove-TicketboxRecoveryPgServiceIfExists") < branch.index(
            "Assert-TicketboxPreparedServiceContracts"
        ) < branch.index(
            "ConvertTo-TicketboxCurrentLifecycleReceipt"
        )
    assert backup_pending_branch.index("Remove-TicketboxRecoveryPgServiceIfExists") < backup_pending_branch.index(
        "Remove-TicketboxDeferredPreservedPgServiceIfExists"
    ) < backup_pending_branch.index(
        "Assert-TicketboxPreparedServiceContracts"
    ) < backup_pending_branch.index(
        "ConvertTo-TicketboxCurrentLifecycleReceipt"
    ) < backup_pending_branch.index("Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending")


def test_programdata_identity_is_the_locked_fail_closed_version_floor() -> None:
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")
    install = _read("install_bundled_services.ps1")
    safety = _read("windows_installation_safety.ps1")
    receipt = _read("windows_lifecycle_receipt.ps1")

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
        "ValidateLifecycleLockBootstrapFiles()"
    )
    persistent_gate = gate[
        gate.index("if HasPersistentIdentity then") : gate.index("else if HasPreservedPgData then")
    ]
    assert "'DataRoot'" in persistent_gate
    assert "'BackendVersion'" in persistent_gate
    assert "CompareSupportedNumericVersions(" in persistent_gate
    assert "if VersionComparison > 0 then" in persistent_gate
    cur_step = flow[
        flow.index("procedure CurStepChanged") : flow.index("procedure DeinitializeSetup")
    ]
    recovered = cur_step.index("PreparationFailure := PrepareAuthoritativePayloadReplacement()")
    version_recheck = cur_step.index("CheckBackendVersionFloorForDataRoot", recovered)
    payload_copy = cur_step.index("AssertDataRootMutationGuardActive()", version_recheck)
    assert recovered < version_recheck < payload_copy
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

    release_candidate = safety[
        safety.index("function Get-TicketboxInstallationReleaseCandidate") : safety.index(
            "function Assert-TicketboxInstallationIdentityBaseMatches"
        )
    ]
    assert 'Join-Path $canonicalInstallDir "installer\\BUILD_PROVENANCE.json"' in release_candidate
    assert "Read-TicketboxInstalledBuildManifest $expectedManifestPath" in release_candidate
    assert "Open-TicketboxC07VerifiedMigrationHelperLease" in release_candidate
    assert "-ExpectedSize $helperEvidence.Size" in release_candidate
    assert "-ExpectedSha256 $helperEvidence.Sha256" in release_candidate
    assert "Get-TicketboxPortableFileSha256 $expectedManifestPath" in release_candidate
    assert "BackendVersionFloor = [string]$buildManifest.BackendVersion" in release_candidate

    identity_matcher = safety[
        safety.index("function Assert-TicketboxInstallationIdentityBaseMatches") : safety.index(
            "function Test-TicketboxInstallationIdentityReleaseMatches"
        )
    ]
    assert "Compare-TicketboxNumericVersion" in identity_matcher

    identity_state_writer = safety[
        safety.index("function Write-TicketboxInstallationIdentityState") : safety.index(
            "function Initialize-TicketboxPendingInstallationIdentity"
        )
    ]
    assert "Write-TicketboxProtectedUtf8FileDurable" in identity_state_writer
    assert "$script:TicketboxPersistentInstallationIdentityAclAccounts" in identity_state_writer
    assert "$script:TicketboxPersistentInstallationIdentityOwnerAccount" in identity_state_writer
    assert 'Read-TicketboxPersistentInstallationIdentity `' in identity_state_writer
    assert '$persisted.State -cne $State' in identity_state_writer

    identity_initializer = safety[
        safety.index("function Initialize-TicketboxPendingInstallationIdentity") : safety.index(
            "function Promote-TicketboxPendingInstallationIdentity"
        )
    ]
    assert "[guid]::NewGuid()" in identity_initializer
    pending_write = identity_initializer.index("Write-TicketboxInstallationIdentityState")
    assert pending_write < identity_initializer.index('-State "PENDING"', pending_write)

    identity_promoter = safety[
        safety.index("function Promote-TicketboxPendingInstallationIdentity") : safety.index(
            "function Write-TicketboxPersistentInstallationIdentity"
        )
    ]
    assert "([guid]$ExpectedOperationId).ToString(\"D\")" in identity_promoter
    ready_write = identity_promoter.index("Write-TicketboxInstallationIdentityState")
    ready_state = identity_promoter.index('-State "READY"', ready_write)
    pending_retire = identity_promoter.index("Remove-TicketboxProtectedUtf8Artifact", ready_state)
    assert ready_write < ready_state < pending_retire

    identity_writer = safety[
        safety.index("function Write-TicketboxPersistentInstallationIdentity") : safety.index(
            "function Assert-TicketboxRegisteredDataRootBinding"
        )
    ]
    initialize_pending = identity_writer.index("Initialize-TicketboxPendingInstallationIdentity")
    promote_pending = identity_writer.index("Promote-TicketboxPendingInstallationIdentity")
    assert initialize_pending < promote_pending
    assert "-ExpectedOperationId $pending.OperationId" in identity_writer

    transaction = receipt[
        receipt.index("function Complete-TicketboxInstalledLifecycleTransaction") : receipt.index(
            "function Set-TicketboxLifecycleReceiptInstallerOwner"
        )
    ]
    ready_artifact_guard = transaction.index("Assert-TicketboxC07CommitReadyArtifacts")
    persist_identity = transaction.index("Promote-TicketboxPendingInstallationIdentity")
    commit_receipt = transaction.index("Set-TicketboxLifecycleReceiptInstallCompleted")
    retire_latch = transaction.index("Remove-TicketboxInstallerRecoveryMarker")
    assert ready_artifact_guard < persist_identity < commit_receipt < retire_latch
    receipt_guard = install.index('if ($InstallerLockOwnerProcessId -le 0)')
    operation_lock = install.index("$operationLock = Enter-TicketboxLifecycleLock")
    assert receipt_guard < operation_lock
    assert "正式安装或升级只能由持有生命周期锁和回执的 Inno 安装器调用" in install
    assert 'if ($InstallerLockOwnerProcessId -eq 0)' not in install
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


def test_data_root_guard_hands_off_operation_lock_only_after_durable_ready() -> None:
    guard = _read("hold_data_root_mutation_guard.ps1")
    assert "windows_release_config.ps1" not in guard
    assert "windows_service_lifecycle.ps1" not in guard
    assert "windows_lifecycle_receipt.ps1" not in guard
    acquired = guard.index("Lock = Enter-TicketboxLifecycleLock")
    waited = guard.index("Wait-TicketboxDirectoryMutationGuardLease")
    assert acquired < waited
    assert "-InstallDir $InstallDir" in guard[waited:]
    assert "-OwnerIdentity $guardOperationState.Lock.ExternalOwnerIdentity" in guard[waited:]
    assert "-OnLeaseReady $releaseGuardStartupLease" in guard[waited:]
    assert "& $releaseGuardStartupLease" in guard
    startup_release = guard.rindex("& $releaseGuardStartupLease")
    owner_handle = guard.index("Open-TicketboxVerifiedProcessIdentityHandle")
    acknowledge = guard.rindex("Write-TicketboxDataRootGuardStoppedAcknowledgement")
    assert owner_handle < startup_release < acknowledge
    acknowledgement = guard[
        guard.index("function Write-TicketboxDataRootGuardStoppedAcknowledgement") :
        guard.rindex("Assert-TicketboxDataRootGuardAdministrator")
    ]
    assert acknowledgement.index("Test-TicketboxProcessIdentityHandleExited") < acknowledgement.index(
        '"STATE=stopped$([Environment]::NewLine)"'
    )
    assert "-ReplaceExisting" in acknowledgement
    assert '$guardExitReason -cne "control"' in guard
    assert "Read-TicketboxProtectedUtf8Artifact" in guard
    assert "Assert-TicketboxDataRootGuardRecoveryControl" in guard
    assert '"confirmed_inactive"' in guard
    recovery = guard[
        guard.index("function Assert-TicketboxDataRootGuardRecoveryControl") :
        guard.index("function Write-TicketboxDataRootGuardStoppedAcknowledgement")
    ]
    assert "Get-TicketboxPathEntryKindNoFollow" in recovery
    assert "Get-TicketboxProcessIdentity" in recovery
    assert "Test-TicketboxProcessIdentityEquals" in recovery
    assert "holder 仍以原进程身份存活" in recovery

    safety = _read("windows_installation_safety.ps1")
    lease = safety[
        safety.index("function Wait-TicketboxDirectoryMutationGuardLease") : safety.index(
            "function Test-TicketboxExclusiveFileLockHeld"
        )
    ]
    guard_implementation = safety[
        safety.index("function Enter-TicketboxDirectoryMutationGuard") : safety.index(
            "function Initialize-TicketboxDurableFileNativeMethods"
        )
    ]
    before_create_callback = guard_implementation.index("& $OnBeforeFirstDirectoryCreation")
    protected_directory_create = guard_implementation.index(
        "Initialize-TicketboxProtectedDirectoryAtomically"
    )
    assert before_create_callback < protected_directory_create
    assert "$creationCallbackInvoked = $false" in guard_implementation
    assert "$creationCallbackInvoked = $true" in guard_implementation
    assert "GetVolumeNameForVolumeMountPoint" in safety
    assert "DATA_VOLUME_UTF8_B64=" in safety
    assert "DataVolumeIdentity" in safety

    provisioning_callback = lease.index("$publishProvisioningIntent = {")
    provisioning_write = lease.index(
        "Write-TicketboxProtectedUtf8FileDurable",
        provisioning_callback,
    )
    guard_enter = lease.index("$guard = Enter-TicketboxDirectoryMutationGuard")
    callback_binding = lease.index(
        "-OnBeforeFirstDirectoryCreation $publishProvisioningIntent",
        guard_enter,
    )
    ready_text = lease.index("$readyText =")
    ready = lease.index("Write-TicketboxProtectedUtf8FileDurable", ready_text)
    ready_readback = lease.index("$persistedReady = Read-TicketboxProtectedUtf8Artifact")
    handoff = lease.index("& $OnLeaseReady")
    long_lived_wait = lease.index("while ($true)", handoff)
    secure_create = lease.index("$dataRootCreated")
    marker = lease.index("Write-TicketboxDataRootMarker", secure_create)
    marker_volume_binding = lease.index(
        "-DataVolumeIdentity $provisioningState.ExpectedVolumeIdentity",
        marker,
    )
    marker_readback = lease.index("Assert-TicketboxProtectedDataRootMarker", marker)
    provisioning_retire = lease.index(
        "Remove-TicketboxDirectoryGuardCoordinationArtifacts",
        marker,
    )
    reject_preexisting = lease.index("预先存在的空 DataRoot", marker)
    assert (
        provisioning_callback
        < provisioning_write
        < guard_enter
        < callback_binding
        < secure_create
        < marker
        < marker_volume_binding
        < marker_readback
        < provisioning_retire
        < reject_preexisting
        < ready
        < ready_readback
        < handoff
        < long_lived_wait
    )
    assert "Open-TicketboxVerifiedProcessIdentityHandle" in lease
    assert "Test-TicketboxProcessIdentityHandleExited" in lease
    assert '"STATE=abort$([Environment]::NewLine)"' in lease
    assert 'return "control"' in lease
    assert 'return "owner_exit"' in lease
    assert "$ownerProcess.Refresh()" not in lease

    lifecycle = _read("windows_lifecycle_lock.ps1")
    assert "SafeWaitHandle OpenProcess" in lifecycle
    assert "GetProcessTimes" in lifecycle
    assert "WaitForSingleObject" in lifecycle
    assert "$ownerProcess.Refresh()" not in lifecycle

    windows = _read("ticketbox-installer-windows.isph")
    start_guard = windows[
        windows.index("function StartDataRootMutationGuard") : windows.index(
            "procedure AssertDataRootMutationGuardActive"
        )
    ]
    assert "finally" in start_guard
    assert "AbortDataRootMutationGuardStartup()" in start_guard
    abort_guard = windows[
        windows.index("function AbortDataRootMutationGuardStartup") : windows.index(
            "function StartDataRootMutationGuard"
        )
    ]
    assert abort_guard.count("DataRootGuardStoppedAcknowledged()") >= 2
    assert "ConfirmDataRootGuardStoppedAfterControlFailure()" in abort_guard
    assert "RunPowerShellChecked(" in windows[
        windows.index("function ConfirmDataRootGuardStoppedAfterControlFailure") :
        windows.index("function AbortDataRootMutationGuardStartup")
    ]
    release_guard = windows[
        windows.index("procedure ReleaseDataRootMutationGuard") :
    ]
    assert "if DataRootGuardStoppedAcknowledged() then" in release_guard
    assert "if WaitForDataRootGuardStoppedAcknowledgement() then" in release_guard
    assert "if ConfirmDataRootGuardStoppedAfterControlFailure() then" in release_guard
    assert "if not WaitForDataRootGuardStoppedAcknowledgement()" not in release_guard

    flow = _read("ticketbox-installer-flow.isph")
    preflight_start = flow.index("if not RunPowerShellChecked(")
    preflight_failure = flow[
        preflight_start : flow.index("升级前备份或服务检查失败", preflight_start)
    ]
    assert "ReleaseDataRootMutationGuard();" in preflight_failure


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
    assert "Result := (Value <> '') and (Length(Value) <= 5);" in installer
    assert "if (Length(Value) > 1) and (Value[1] = '0') then" in installer

    accepted = (
        ("1.3.0", "1.3.0.0"),
        ("1.3.0.9", "1.3.0.9"),
        ("0.2.3", "0.2.3.0"),
        ("65535.0.0", "65535.0.0.0"),
    )
    rejected_versions = (
        "1.3.0a1",
        "1.3.0rc2",
        "1.3.0-rc.2+build.7",
        "release-latest",
        "01.2.3",
        "1.02.3",
        "1.2.3.04",
        "000000.2.3",
        "65536.0.0",
    )
    for powershell in powershell_contract_engines():
        for version, expected in accepted:
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
                encoding="utf-8-sig",
                errors="replace",
                timeout=15,
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == expected
        for version in rejected_versions:
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
                    version,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8-sig",
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
    assert config["owner_recovery_channel"] == "managed_host"
    assert '"TICKETBOX_OWNER_RECOVERY_CHANNEL=$OwnerRecoveryChannel"' in _read(
        "windows_service_contract.ps1"
    )
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
    assert "--lock-wait-timeout=30000" in database_safety
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
        "database_tool_timeout_ms",
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
    assert "Invoke-TicketboxBoundedNativeProcess" in uninstall
    assert "& $PgCtl status -D $PgData" not in uninstall
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
    assert '$script:TicketboxDataRootMarkerSchema = "ticketbox-data-root-v2"' in safety
    assert '$script:TicketboxLegacyDataRootMarkerSchema = "ticketbox-data-root-v1"' in safety
    assert "data_volume_identity" in safety
    assert "拒绝把 markerless 非空目录收编为小票夹数据根" in safety
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
    pre_open_guard = uninstall[
        uninstall.index('Write-Step "删除数据目录 $safeRoot"') : uninstall.index(
            "$finalDeletionGuard = {"
        )
    ]
    intent_revalidation = pre_open_guard.index("Read-TicketboxDeleteDataIntent")
    runtime_revalidation = pre_open_guard.index(
        "Assert-TicketboxRuntimeProcessesStoppedForDataDeletion",
        intent_revalidation,
    )
    assert intent_revalidation < runtime_revalidation
    assert "Assert-TicketboxBackendPortStoppedForDataDeletion" in pre_open_guard
    assert "Assert-TicketboxPgScmProcessAgreement" in pre_open_guard
    assert "GetDirectoryIdentity" in deletion_guard
    assert "ReadExactUtf8File" in deletion_guard
    assert "InspectEntry" in deletion_guard
    assert "Assert-TicketboxDataRootForDeletion" not in deletion_guard
    assert "Read-TicketboxDeleteDataIntent" not in deletion_guard
    assert "Assert-TicketboxRuntimeProcessesStoppedForDataDeletion" not in deletion_guard
    assert "Assert-TicketboxBackendPortStoppedForDataDeletion" not in deletion_guard
    assert "Assert-TicketboxPgScmProcessAgreement" not in deletion_guard
    assert "TicketboxExactTreeDeleteNativeMethods" in safety
    assert "SetFileInformationByHandle" in safety
    delete_open = safety[
        safety.index("private static SafeFileHandle OpenExact") : safety.index(
            "private static FILE_ATTRIBUTE_TAG_INFO ReadAttributes"
        )
    ]
    assert "FileShareRead," in delete_open
    assert "FileShareRead | FileShareWrite" not in delete_open
    no_follow_inspection = safety[
        safety.index("public static int InspectEntry") : safety.index(
            "private static void DeleteOpenedNode"
        )
    ]
    assert "FileShareRead | FileShareWrite | FileShareDelete" in no_follow_inspection
    assert "Remove-Item -LiteralPath $safeRoot -Recurse" not in uninstall


    retain_branch = uninstall[
        uninstall.index("else {", uninstall.index("if ($DeleteData) {", first_remove)) : uninstall.index(
            'Write-Host "=== 卸载脚本完成 ==="'
        )
    ]
    projection_cleanup = uninstall.index(
        "Remove-TicketboxInstallerRuntimeProjectionForUninstall", preflight
    )
    installer_state_staging = uninstall.index(
        "Remove-TicketboxInstallerStateStagingAfterRuntimeProjection", projection_cleanup
    )
    pg_recovery = uninstall.index(
        "Save-TicketboxUninstallPgRecoveryIfRequired", projection_cleanup
    )
    remove_backend = uninstall.index("Remove-ServiceIfExists $BackendServiceName", projection_cleanup)
    retire_completed_receipt = uninstall.index(
        "Remove-TicketboxCompletedLifecycleReceipt", remove_backend
    )
    assert (
        projection_cleanup
        < installer_state_staging
        < pg_recovery
        < remove_backend
        < retire_completed_receipt
    )
    assert "Remove-TicketboxCompletedLifecycleReceipt" in retain_branch
    assert "Remove-TicketboxPreservedInstallationIdentity" not in retain_branch
    assert "Remove-TicketboxPgRecoveryToolset" not in retain_branch


@pytest.mark.skipif(sys.platform != "win32", reason="Windows exact delete callback")
def test_uninstall_exact_delete_callback_runs_under_both_powershell_engines(
    tmp_path: Path,
) -> None:
    uninstall = _read("uninstall_bundled_services.ps1")
    remove_helper = uninstall[
        uninstall.index("function Remove-TicketboxDataRootForUninstall") : uninstall.index(
            "function Get-TicketboxInstallerStateDataDeletionSnapshot"
        )
    ]
    safety_path = PACKAGING / "windows_installation_safety.ps1"

    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"delete-root-{index}"
        root.mkdir()
        marker = root / ".ticketbox-data-root.json"
        marker.write_text("marker-authority\n", encoding="utf-8")
        payload = root / "payload.txt"
        payload.write_text("delete-me", encoding="utf-8")
        intent = tmp_path / f"delete-intent-{index}.json"
        intent.write_text("intent-authority\n", encoding="utf-8")
        harness = tmp_path / f"delete-callback-{index}.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{str(safety_path).replace("'", "''")}'
$script:DeleteDataIntentValidated = $true
$script:TicketboxDataRootMarkerName = '.ticketbox-data-root.json'
$DeleteDataIntentPath = '{str(intent).replace("'", "''")}'
$InstallDir = 'C:\\Program Files\\Ticketbox'
$script:runtimeChecks = 0
function Write-Step {{ param([string]$Message) }}
function Write-Ok {{ param([string]$Message) }}
function Assert-TicketboxDataRootForDeletion {{
    param([string]$CandidateRoot)
    return [IO.Path]::GetFullPath($CandidateRoot)
}}
function Read-TicketboxDeleteDataIntent {{
    param($Path, $InstallDir, $DataRoot)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{
        throw 'missing intent'
    }}
}}
function Assert-TicketboxRuntimeProcessesStoppedForDataDeletion {{
    $script:runtimeChecks++
}}
function Assert-TicketboxBackendPortStoppedForDataDeletion {{
    $script:runtimeChecks++
}}
function Assert-TicketboxPgScmProcessAgreement {{
    $script:runtimeChecks++
}}
{remove_helper}
Remove-TicketboxDataRootForUninstall '{str(root).replace("'", "''")}'
if (Test-Path -LiteralPath '{str(root).replace("'", "''")}') {{
    throw 'exact delete left the data root'
}}
if ($script:runtimeChecks -ne 3) {{
    throw 'pre-open runtime proofs did not execute exactly once'
}}
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


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
    assert '"BackendVersion"' not in identity_cleanup
    remove_identity = uninstall[
        uninstall.index("function Remove-TicketboxPreservedInstallationIdentity") : uninstall.index(
            "function Remove-TicketboxDataRootForUninstall"
        )
    ]
    assert 'if ($DeleteData)' in remove_identity
    assert '$identityNamesToRemove += "BackendVersion"' in remove_identity
    assert "foreach ($name in $identityNamesToRemove)" in remove_identity
    retry_cleanup = uninstall[
        uninstall.index("if ($InstallationIdentityAlreadyRemoved") : uninstall.index(
            "$safeRoot = Assert-UninstallInputs"
        )
    ]
    assert "if ($InstallationIdentityCleanupIncomplete -or $DeleteData)" in retry_cleanup
    assert "Remove-TicketboxPreservedInstallationIdentity" in retry_cleanup
    assert "Service-Exists $BackendServiceName" in helper
    assert "Assert-TicketboxRuntimeProcessesStoppedForDataDeletion" in helper
    assert "if ($BackendPort -gt 0)" in helper
    assert "Assert-TicketboxBackendPortStoppedForDataDeletion" in helper
    assert 'elseif (Test-Path -LiteralPath (Join-Path $AppData ".env") -PathType Leaf)' in uninstall
    assert "($InstallationIdentityAlreadyRemoved -or $InstallationIdentityCleanupIncomplete) -and" in uninstall
    assert "[string]::IsNullOrWhiteSpace($DataRoot)" in uninstall
    assert "$DeleteData -and" in uninstall
    assert "$deleteDataRetryAuthority -ceq \"resolved\"" in uninstall
    assert "Resolve-TicketboxDeleteDataRetryAuthority" in uninstall
    assert "Read-TicketboxDeleteDataIntent `" in uninstall
    assert "Set-TicketboxUninstallDataRoot ([string]$intent.data_root)" in uninstall
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
    first_service_cleanup = uninstall.index("Remove-ServiceIfExists $BackendServiceName")
    state_preflight = uninstall.index("Assert-TicketboxInstallerStateForDataDeletion", uninstall.index("$safeRoot"))
    data_deletion = uninstall.rindex("Remove-TicketboxDataRootForUninstall $safeRoot")
    state_cleanup = uninstall.rindex("Remove-TicketboxInstallerStateAfterDataDeletion")
    identity_removal = uninstall.rindex("Remove-TicketboxPreservedInstallationIdentity")
    recovery_cleanup = uninstall.index("-ExpectedMajor $preservedPgMajor", data_deletion)
    assert (
        state_preflight
        < first_service_cleanup
        < data_deletion
        < recovery_cleanup
        < identity_removal
        < state_cleanup
    )

    receipt_validation = uninstall.index("Get-TicketboxCompletedLifecycleReceiptForUninstall")
    receipt_removal = uninstall.index(
        "Remove-TicketboxCompletedLifecycleReceipt", first_service_cleanup
    )
    assert receipt_validation < first_service_cleanup < receipt_removal < recovery_cleanup < identity_removal
    retry_delete = retry_cleanup.index("Remove-TicketboxDataRootForUninstall $DataRoot")
    retry_tools = retry_cleanup.index("-ExpectedMajor 0", retry_delete)
    retry_identity = retry_cleanup.index("Remove-TicketboxPreservedInstallationIdentity")
    retry_state = retry_cleanup.index("Remove-TicketboxInstallerStateAfterDataDeletion")
    assert retry_delete < retry_tools < retry_identity < retry_state
    assert uninstall.count("-DeleteDataIntentValidated:$script:DeleteDataIntentValidated") == 2
    assert "Read-TicketboxCompletedLifecycleReceipt" in uninstall
    assert '"InstallDir"' in identity_cleanup
    for binding in (
        "-ExpectedPgPort $RegisteredPgPortNumber",
        "-ExpectedBackendPort $BackendPort",
        "-ExpectedPgServiceName $RegisteredPgServiceName",
        "-ExpectedBackendServiceName $RegisteredBackendServiceName",
    ):
        assert binding in uninstall


@pytest.mark.skipif(sys.platform != "win32", reason="Windows delete-data receipt contract")
def test_delete_data_requires_completed_receipt_or_bound_retry_intent(tmp_path: Path) -> None:
    uninstall = _read("uninstall_bundled_services.ps1")
    lifecycle_receipt = _read("windows_lifecycle_receipt.ps1")
    installation_safety = _read("windows_installation_safety.ps1")
    win32_path_init = installation_safety[
        installation_safety.index("function Initialize-TicketboxWin32FilePathMethods") : installation_safety.index(
            "function Initialize-TicketboxDirectoryGuardNativeMethods"
        )
    ]
    exact_entry_init = installation_safety[
        installation_safety.index("function Initialize-TicketboxExactTreeDeleteNativeMethods") : installation_safety.index(
            "function Remove-TicketboxTreeExact"
        )
    ]
    no_follow_entry_kind = installation_safety[
        installation_safety.index("function Get-TicketboxPathEntryKindNoFollow") : installation_safety.index(
            "function Assert-NoTicketboxAncestorReparsePoints"
        )
    ]
    helper = uninstall[
        uninstall.index("function Get-TicketboxCompletedLifecycleReceiptForUninstall") : uninstall.index(
            "function Remove-TicketboxPreservedInstallationIdentity"
        )
    ]
    runtime_projection_helper = uninstall[
        uninstall.index("function Remove-TicketboxInstallerRuntimeProjectionForUninstall") : uninstall.index(
            "function Assert-UninstallInputs"
        )
    ].replace(
        "function Remove-TicketboxInstallerRuntimeProjectionForUninstall",
        "function Invoke-TicketboxProductionRuntimeProjectionRemoval",
        1,
    )
    remove_identity_helper = uninstall[
        uninstall.index("function Remove-TicketboxPreservedInstallationIdentity") : uninstall.index(
            "function Remove-TicketboxDataRootForUninstall"
        )
    ].replace(
        "function Remove-TicketboxPreservedInstallationIdentity",
        "function Invoke-TicketboxProductionIdentityRemoval",
        1,
    )
    set_data_root_helper = uninstall[
        uninstall.index("function Set-TicketboxUninstallDataRoot") : uninstall.index(
            "Set-TicketboxUninstallDataRoot $DataRoot"
        )
    ]
    retry_authority_helper = uninstall[
        uninstall.index("function Get-TicketboxInstallerStateDataDeletionSnapshot") : uninstall.index(
            'Write-Host "=== \u5c0f\u7968\u5939\u670d\u52a1\u5378\u8f7d ==="'
        )
    ]
    retry_entrypoint = uninstall[
        uninstall.index("$deleteDataRetryAuthority = Resolve-TicketboxDeleteDataRetryAuthority") : uninstall.index(
            "$safeRoot = Assert-UninstallInputs"
        )
    ]
    read_intent_helper = lifecycle_receipt[
        lifecycle_receipt.index("function Read-TicketboxDeleteDataIntent") : lifecycle_receipt.index(
            "function Write-TicketboxDeleteDataIntent"
        )
    ]
    remove_completed_receipt_helper = lifecycle_receipt[
        lifecycle_receipt.index("function Remove-TicketboxCompletedLifecycleReceipt") : lifecycle_receipt.index(
            "function Read-TicketboxInstallerRecoveryMarker"
        )
    ]
    runtime_shape_helper = lifecycle_receipt[
        lifecycle_receipt.index("function Get-TicketboxInstallerRuntimeStateShape") : lifecycle_receipt.index(
            "function Assert-TicketboxInstallerRuntimeRecoveryGuardPath"
        )
    ]
    receipt_path = tmp_path / "installer-lifecycle-receipt.json"
    installer_state = tmp_path / "installer-state"
    intent_path = installer_state / "delete-data-in-progress.json"
    resolved_data_root = tmp_path / "resolved-data"
    runtime_state_path = tmp_path / "runtime-state-projection"
    registry_path = f"HKCU:\\Software\\Ticketbox\\InstallerTests\\{tmp_path.name}"
    harness = tmp_path / "delete-data-receipt-authority.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
$DeleteData = $true
$LifecycleReceiptPath = '{str(receipt_path).replace("'", "''")}'
$DeleteDataIntentPath = '{str(intent_path).replace("'", "''")}'
$InstallerState = '{str(installer_state).replace("'", "''")}'
$OwnerBootstrapPath = Join-Path $InstallerState 'owner-bootstrap.txt'
$OwnerHandoffPendingPath = Join-Path $InstallerState 'owner-handoff-pending'
$RecoveryRequiredPath = Join-Path $InstallerState 'installer-recovery-required.json'
$InstallDir = 'C:\\Program Files\\Ticketbox'
$RegisteredInstallDir = $InstallDir
$DataRoot = 'C:\\ProgramData\\Ticketbox'
$ExplicitDataRootProvided = $false
$RegisteredDataRoot = ''
$InstallationIdentityAlreadyRemoved = $true
$InstallationIdentityCleanupIncomplete = $false
$ReleaseConfig = [pscustomobject]@{{}}
$RegisteredPgPortNumber = 5432
$BackendPort = 8000
$RegisteredPgServiceName = 'TicketboxPg'
$RegisteredBackendServiceName = 'TicketboxBackend'
$script:DeleteDataIntentValidated = $false
$script:TicketboxDeleteDataIntentSchema = 'ticketbox-delete-data-intent-v1'
$script:TicketboxLifecycleReceiptAclAccounts = @('SYSTEM', 'BUILTIN\\Administrators')
$script:TicketboxLifecycleReceiptOwnerAccount = 'SYSTEM'
$runtimeStateDirectory = '{str(runtime_state_path).replace("'", "''")}'
$regPath = '{registry_path.replace("'", "''")}'
$PreservedIdentityNames = @('InstallDir', 'DataRoot')
if (Test-Path -LiteralPath $regPath) {{ Remove-Item -LiteralPath $regPath -Recurse -Force }}
New-Item -Path $regPath -Force | Out-Null
function Test-TicketboxPathEquals {{
    param($Left, $Right)
    return [System.IO.Path]::GetFullPath($Left) -ceq [System.IO.Path]::GetFullPath($Right)
}}
function ConvertTo-TicketboxCanonicalPath {{
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}}
{win32_path_init}
function Get-TicketboxInstallerRuntimeStateDirectory {{ return $runtimeStateDirectory }}
function Get-TicketboxInstallerRuntimeRecoveryGuardPath {{ return Join-Path $runtimeStateDirectory 'installer-runtime-recovery-pending' }}
function Test-TicketboxPathWithin {{ param($Path, $Parent); return $false }}
function Assert-NoTicketboxAncestorReparsePoints {{ param($Path) }}
{exact_entry_init}
{no_follow_entry_kind}
function Assert-TicketboxProtectedDirectoryAcl {{ param($Path, $FullControlAccounts, $OwnerAccount) }}
function Remove-TicketboxProtectedStagingArtifacts {{ param($Path, $FullControlAccounts, $OwnerAccount) }}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $OwnerAccount, $MaximumBytes)
    return [pscustomobject]@{{ Text = [System.IO.File]::ReadAllText($Path) }}
}}
function Read-TicketboxCompletedLifecycleReceipt {{
    param($Path, $InstallDir, $DataRoot, $TargetReleaseConfig, $ExpectedPgPort, $ExpectedBackendPort, $ExpectedPgServiceName, $ExpectedBackendServiceName)
    return [pscustomobject]@{{ install_completed = $true }}
}}
function Assert-TicketboxCompletedLifecycleReceipt {{ param($Receipt) }}
function Assert-TicketboxLifecycleReceiptPath {{ param($Path); return [System.IO.Path]::GetFullPath($Path) }}
function Assert-TicketboxProtectedLifecycleReceipt {{ param($Path) }}
{remove_completed_receipt_helper}
{runtime_shape_helper}
{read_intent_helper}
{set_data_root_helper}
{helper}
{runtime_projection_helper}
{retry_authority_helper}
{remove_identity_helper}
function Write-ValidDeleteDataIntent([string]$IntentDataRoot) {{
    New-Item -ItemType Directory -Force -Path $InstallerState | Out-Null
    [ordered]@{{
        schema = 'ticketbox-delete-data-intent-v1'
        install_dir = $InstallDir
        data_root = $IntentDataRoot
        completed_receipt_sha256 = ('A' * 64)
        created_at_utc = '2026-07-13T00:00:00.0000000Z'
    }} | ConvertTo-Json | Set-Content -LiteralPath $DeleteDataIntentPath -Encoding UTF8
}}
$missingRejected = $false
try {{ Get-TicketboxCompletedLifecycleReceiptForUninstall | Out-Null }} catch {{ $missingRejected = $true }}
if (-not $missingRejected) {{ throw 'missing receipt without retry intent was accepted' }}
New-Item -ItemType Directory -Path $LifecycleReceiptPath | Out-Null
$directoryRejected = $false
try {{ Get-TicketboxCompletedLifecycleReceiptForUninstall | Out-Null }} catch {{ $directoryRejected = $true }}
if (-not $directoryRejected) {{ throw 'directory-shaped receipt was treated as absent' }}
Remove-Item -LiteralPath $LifecycleReceiptPath -Force
[System.IO.File]::WriteAllText($LifecycleReceiptPath, 'completed')
$completed = Get-TicketboxCompletedLifecycleReceiptForUninstall
if (-not [bool]$completed.install_completed -or $script:DeleteDataIntentValidated) {{
    throw 'regular completed receipt did not remain primary authority'
}}
Remove-Item -LiteralPath $LifecycleReceiptPath -Force
Write-ValidDeleteDataIntent $DataRoot
$resumed = Get-TicketboxCompletedLifecycleReceiptForUninstall
if ($null -ne $resumed -or -not $script:DeleteDataIntentValidated) {{
    throw 'receipt-retired retry did not require the bound delete-data intent'
}}
Remove-Item -LiteralPath $InstallerState -Recurse -Force

$script:DeleteDataIntentValidated = $false
$resolvedDataRoot = '{str(resolved_data_root).replace("'", "''")}'
Write-ValidDeleteDataIntent $resolvedDataRoot
$resolved = Resolve-TicketboxDeleteDataRetryAuthority
if ($resolved -cne 'resolved' -or -not $script:DeleteDataIntentValidated) {{
    throw 'identity-removed retry did not resolve its durable intent'
}}
if (-not (Test-TicketboxPathEquals $DataRoot $resolvedDataRoot) -or
    -not (Test-TicketboxPathEquals $PgData (Join-Path $resolvedDataRoot 'pgdata')) -or
    -not (Test-TicketboxPathEquals $AppData (Join-Path $resolvedDataRoot 'app'))) {{
    throw 'resolved intent did not rebind the complete uninstall data-root projection'
}}
Remove-Item -LiteralPath $InstallerState -Recurse -Force

New-Item -ItemType Directory -Path $InstallerState | Out-Null
$retired = Resolve-TicketboxDeleteDataRetryAuthority
if ($retired -cne 'retired' -or -not (Test-Path -LiteralPath $InstallerState -PathType Container)) {{
    throw 'read-only retry authority resolution mutated empty retired installer-state'
}}
Remove-TicketboxRetiredInstallerStateAfterRuntimeProjection
if (Test-Path -LiteralPath $InstallerState) {{ throw 'validated retired installer-state was not removed' }}

$InstallationIdentityAlreadyRemoved = $false
$InstallationIdentityCleanupIncomplete = $true
$script:DeleteDataIntentValidated = $false
Write-ValidDeleteDataIntent $resolvedDataRoot
$partial = Resolve-TicketboxDeleteDataRetryAuthority
if ($partial -cne 'resolved' -or -not $script:DeleteDataIntentValidated) {{
    throw 'partial identity removal did not use the same durable retry authority'
}}
Remove-Item -LiteralPath $InstallerState -Recurse -Force

$InstallationIdentityAlreadyRemoved = $true
$InstallationIdentityCleanupIncomplete = $false
New-Item -ItemType Directory -Path $InstallerState | Out-Null
[System.IO.File]::WriteAllText($OwnerBootstrapPath, 'orphaned state')
$missingIntentRejected = $false
try {{ Resolve-TicketboxDeleteDataRetryAuthority | Out-Null }} catch {{ $missingIntentRejected = $true }}
if (-not $missingIntentRejected -or -not (Test-Path -LiteralPath $OwnerBootstrapPath -PathType Leaf)) {{
    throw 'non-empty installer-state without delete intent was accepted or mutated'
}}
Remove-Item -LiteralPath $InstallerState -Recurse -Force

New-Item -ItemType Directory -Path $InstallerState | Out-Null
[System.IO.File]::WriteAllText($DeleteDataIntentPath, '{{ malformed json')
$script:DeleteDataIntentValidated = $false
$malformedIntentRejected = $false
try {{ Resolve-TicketboxDeleteDataRetryAuthority | Out-Null }} catch {{ $malformedIntentRejected = $true }}
if (-not $malformedIntentRejected -or $script:DeleteDataIntentValidated -or
    -not (Test-Path -LiteralPath $DeleteDataIntentPath -PathType Leaf)) {{
    throw 'malformed delete intent was accepted, marked valid, or destroyed'
}}
Remove-Item -LiteralPath $InstallerState -Recurse -Force

$script:DataRoot = 'C:\\ProgramData\\Ticketbox-placeholder'
$DataRoot = $script:DataRoot
$PgData = Join-Path $DataRoot 'pgdata'
$AppData = Join-Path $DataRoot 'app'
$script:DeleteDataIntentValidated = $false
Write-ValidDeleteDataIntent $resolvedDataRoot
$script:RetryEntrypointCalls = [System.Collections.Generic.List[string]]::new()
$ServiceWaitArguments = @{{}}
$BackendServiceName = 'TicketboxBackend'
$PgServiceName = 'TicketboxPg'
$BackendPort = 8000
$BackendExe = 'C:\\Program Files\\Ticketbox\\backend.exe'
$ShawlExe = 'C:\\Program Files\\Ticketbox\\shawl.exe'
$PgBin = 'C:\\Program Files\\Ticketbox\\pg\\bin'
$PgCtl = Join-Path $PgBin 'pg_ctl.exe'
function Set-TicketboxUninstallRuntimeServiceContract {{
    if (-not (Test-TicketboxPathEquals $DataRoot $resolvedDataRoot) -or
        ($RegisteredDataRoot.Trim().Length -eq 0 -and -not $script:DeleteDataIntentValidated)) {{
        throw 'runtime contract was configured before durable retry authority resolution'
    }}
    $script:RetryEntrypointCalls.Add('runtime-contract')
}}
function Service-Exists {{ return $false }}
function Wait-TicketboxBackendRuntimeStopped {{
    param($Name, $BackendPort, $ExpectedRuntimeExecutables)
    $script:RetryEntrypointCalls.Add("wait:$Name")
}}
function Remove-TicketboxUninstallRuntimeDataBindingIfPresent {{
    $script:RetryEntrypointCalls.Add('runtime-binding')
}}
function Remove-TicketboxInstallerRuntimeProjectionForUninstall {{
    $script:RetryEntrypointCalls.Add('runtime-projection')
    Invoke-TicketboxProductionRuntimeProjectionRemoval
}}
function Remove-TicketboxDataRootForUninstall {{
    param($Path)
    if (-not (Test-TicketboxPathEquals $Path $resolvedDataRoot)) {{
        throw 'retry entrypoint used the placeholder DataRoot'
    }}
    $script:RetryEntrypointCalls.Add('data-root')
}}
function Remove-TicketboxPgRecoveryToolset {{
    param($ExpectedMajor, [switch]$DeleteDataIntentValidated)
    if (-not $DeleteDataIntentValidated) {{ throw 'PG cleanup lost validated delete intent' }}
    $script:RetryEntrypointCalls.Add('pg-recovery')
}}
function Remove-TicketboxPreservedInstallationIdentity {{
    $script:RetryEntrypointCalls.Add('identity')
    Invoke-TicketboxProductionIdentityRemoval
}}
function Remove-TicketboxInstallerStateAfterDataDeletion {{
    $script:RetryEntrypointCalls.Add('installer-state')
}}
function Invoke-ProductionDeleteDataRetryEntrypoint {{
{retry_entrypoint}
}}
Invoke-ProductionDeleteDataRetryEntrypoint
$expectedCalls = @(
    'runtime-contract',
    'wait:TicketboxBackend',
    'wait:TicketboxPg',
    'runtime-projection',
    'runtime-binding',
    'data-root',
    'pg-recovery',
    'identity',
    'installer-state'
)
if ([string]::Join('|', $script:RetryEntrypointCalls) -cne [string]::Join('|', $expectedCalls)) {{
    throw "production retry entrypoint order mismatch: $($script:RetryEntrypointCalls -join '|')"
}}
Remove-Item -LiteralPath $InstallerState -Recurse -Force
$script:RetryEntrypointCalls.Clear()
New-Item -ItemType Directory -Path $InstallerState | Out-Null
[System.IO.File]::WriteAllText($runtimeStateDirectory, 'malformed runtime projection')
$projectionRejected = $false
try {{ Invoke-ProductionDeleteDataRetryEntrypoint }} catch {{
    $projectionRejected = $true
    $projectionError = $_.Exception.Message
}}
if (-not $projectionRejected -or -not (Test-Path -LiteralPath $InstallerState -PathType Container)) {{
    throw 'malformed runtime projection did not fail before preserving retired installer-state'
}}
if (-not $projectionError.StartsWith('machine runtime-state 路径不是可信普通目录')) {{
    throw "retired-state rejection came from the wrong boundary: $projectionError"
}}
if ($script:RetryEntrypointCalls -contains 'runtime-binding' -or
    $script:RetryEntrypointCalls -contains 'identity' -or
    $script:RetryEntrypointCalls -contains 'installer-state') {{
    throw 'runtime projection failure allowed downstream retry mutation'
}}
Remove-Item -LiteralPath $runtimeStateDirectory -Force
$script:RetryEntrypointCalls.Clear()
Invoke-ProductionDeleteDataRetryEntrypoint
if (Test-Path -LiteralPath $InstallerState) {{
    throw 'retired installer-state was not removed after runtime projection validation'
}}

Write-ValidDeleteDataIntent $resolvedDataRoot
$intentBytesBefore = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($DeleteDataIntentPath))
[System.IO.File]::WriteAllText($runtimeStateDirectory, 'malformed runtime projection')
$script:RetryEntrypointCalls.Clear()
$resolvedIntentRejected = $false
try {{ Invoke-ProductionDeleteDataRetryEntrypoint }} catch {{
    $resolvedIntentRejected = $true
    $resolvedIntentError = $_.Exception.Message
}}
$intentBytesAfter = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($DeleteDataIntentPath))
if (-not $resolvedIntentRejected -or $intentBytesAfter -cne $intentBytesBefore) {{
    throw 'runtime projection failure mutated the durable resolved delete intent'
}}
if (-not $resolvedIntentError.StartsWith('machine runtime-state 路径不是可信普通目录')) {{
    throw "resolved-intent rejection came from the wrong boundary: $resolvedIntentError"
}}
if ($script:RetryEntrypointCalls -contains 'runtime-binding' -or
    $script:RetryEntrypointCalls -contains 'identity' -or
    $script:RetryEntrypointCalls -contains 'installer-state') {{
    throw 'resolved-intent projection failure allowed downstream authority mutation'
}}
Remove-Item -LiteralPath $runtimeStateDirectory -Force
Remove-Item -LiteralPath $InstallerState -Recurse -Force

$InstallationIdentityAlreadyRemoved = $false
$InstallationIdentityCleanupIncomplete = $true
$RegisteredDataRoot = $resolvedDataRoot
Set-TicketboxUninstallDataRoot $resolvedDataRoot
$script:DeleteDataIntentValidated = $false
[System.IO.File]::WriteAllText($LifecycleReceiptPath, 'completed-receipt-sentinel')
New-ItemProperty -LiteralPath $regPath -Name InstallDir -Value 'partial-identity-sentinel' -PropertyType String -Force | Out-Null
$receiptBytesBefore = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($LifecycleReceiptPath))
$identityBefore = [string](Get-ItemPropertyValue -LiteralPath $regPath -Name InstallDir)
$script:RetryEntrypointCalls.Clear()
[System.IO.File]::WriteAllText($runtimeStateDirectory, 'malformed runtime projection')
$partialIdentityRejected = $false
try {{ Invoke-ProductionDeleteDataRetryEntrypoint }} catch {{
    $partialIdentityRejected = $true
    $partialIdentityError = $_.Exception.Message
}}
$receiptBytesAfter = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($LifecycleReceiptPath))
$identityAfter = [string](Get-ItemPropertyValue -LiteralPath $regPath -Name InstallDir)
if (-not $partialIdentityRejected -or $receiptBytesAfter -cne $receiptBytesBefore -or
    $identityAfter -cne $identityBefore) {{
    throw 'runtime projection failure mutated completed receipt or partial registry identity'
}}
if (-not $partialIdentityError.StartsWith('machine runtime-state 路径不是可信普通目录')) {{
    throw "partial-identity rejection came from the wrong boundary: $partialIdentityError"
}}
if ($script:RetryEntrypointCalls -contains 'runtime-binding' -or
    $script:RetryEntrypointCalls -contains 'identity' -or
    $script:RetryEntrypointCalls -contains 'installer-state') {{
    throw 'partial-identity projection failure allowed downstream authority mutation'
}}
Remove-Item -LiteralPath $runtimeStateDirectory -Force
Remove-Item -LiteralPath $LifecycleReceiptPath -Force
$InstallationIdentityAlreadyRemoved = $true
$InstallationIdentityCleanupIncomplete = $false
$RegisteredDataRoot = ''
$script:DeleteDataIntentValidated = $false
Write-ValidDeleteDataIntent $resolvedDataRoot
$danglingTarget = Join-Path (Split-Path -Parent $LifecycleReceiptPath) 'missing-receipt-target'
New-Item -ItemType Directory -Path $danglingTarget | Out-Null
& cmd.exe /d /c mklink /J $LifecycleReceiptPath $danglingTarget | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw 'failed to create dangling lifecycle receipt junction' }}
[System.IO.Directory]::Delete($danglingTarget)
$danglingReceiptRejected = $false
try {{ Resolve-TicketboxDeleteDataRetryAuthority | Out-Null }} catch {{ $danglingReceiptRejected = $true }}
if (-not $danglingReceiptRejected -or -not (Test-Path -LiteralPath $DeleteDataIntentPath -PathType Leaf)) {{
    throw 'dangling lifecycle receipt bypassed no-follow classification beside a valid intent'
}}
$DeleteData = $false
$retainReceiptRejected = $false
try {{ Get-TicketboxCompletedLifecycleReceiptForUninstall | Out-Null }} catch {{ $retainReceiptRejected = $true }}
if (-not $retainReceiptRejected) {{ throw 'retain-data uninstall treated dangling receipt as absent' }}
Remove-Item -LiteralPath $regPath -Recurse -Force
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        if receipt_path.is_dir():
            receipt_path.rmdir()
        else:
            receipt_path.unlink(missing_ok=True)
        shutil.rmtree(installer_state, ignore_errors=True)
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


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
        flow.index("function PrepareAuthoritativePayloadReplacement") : flow.index(
            "function PrepareToInstall"
        )
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


def test_installer_uses_protected_lifecycle_lock_as_sole_serial_authority() -> None:
    setup = _read("ticketbox-installer.iss")
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")

    assert "TicketboxLifecycleProcessMutex" not in setup
    assert "AppMutex=" not in setup
    assert "LifecycleProcessMutex" not in windows
    assert "CreateMutex(" not in windows
    assert "ReleaseMutex(" not in windows

    initialize = windows[
        windows.index("function InitializeSetup") : windows.index("function InitializeUninstall")
    ]
    silent_rejection = initialize.index("if WizardSilent then")
    holder_staging = initialize.index("PrepareSetupLifecycleLockHolderScripts()")
    authority_lock = initialize.index("AcquireLifecycleLock()")
    assert silent_rejection < holder_staging < authority_lock
    assert "无人值守安装合同" in initialize
    initialize_uninstall = windows[
        windows.index("function InitializeUninstall") : windows.index(
            "procedure DeinitializeUninstall"
        )
    ]
    assert initialize_uninstall.index("PrepareUninstallLifecycleLockHolderScript()") < (
        initialize_uninstall.index("AcquireLifecycleLock()")
    )
    deinitialize_uninstall = windows[
        windows.index("procedure DeinitializeUninstall") : windows.index(
            "function IsSupportedPowerShell7Host"
        )
    ]
    assert deinitialize_uninstall.count("ReleaseLifecycleLock()") == 1
    assert "LifecycleProcessMutex" not in deinitialize_uninstall

    prepare = flow[
        flow.index("function PrepareAuthoritativePayloadReplacement") : flow.index(
            "function PrepareToInstall"
        )
    ]
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
    assert "LifecycleProcessMutex" not in deinitialize
    holder = _read("hold_data_root_mutation_guard.ps1")
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


def test_manager_maintenance_gate_spans_setup_and_uninstall_payload_mutation() -> None:
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")

    assert "ManagerMaintenanceRegistryPath = 'Software\\Ticketbox'" in windows
    assert "ManagerMaintenanceRegistryValue = 'MaintenanceOwner'" in windows
    assert "ManagerMaintenanceRecordSchema = 'ticketbox-manager-maintenance-v1'" in windows
    assert "Global\\TicketboxManagerMaintenance" not in windows
    gate_start = windows[
        windows.index("function StartManagerMaintenanceGate") : windows.index(
            "function ManagerMaintenanceGateActive"
        )
    ]
    assert "BuildManagerMaintenanceOwnerRecord()" in gate_start
    assert "RegWriteStringValue(" in gate_start
    assert "RegQueryStringValue(" in gate_start
    assert "LifecycleLockOwnerProcessId" in gate_start

    prepare = flow[flow.index("function PrepareToInstall") : flow.index("procedure CurStepChanged")]
    assert "StartManagerMaintenanceGate()" in prepare
    assert "StartDataRootMutationGuard" not in prepare
    assert "'Ticketbox pre-upgrade backup and service preparation'" not in prepare

    install = flow[flow.index("procedure CurStepChanged") : flow.index("procedure DeinitializeSetup")]
    assert install.count("AssertManagerMaintenanceGateActive()") >= 2
    assert install.index("PrepareAuthoritativePayloadReplacement()") < install.index(
        "'Ticketbox program-files copy boundary'"
    )
    after_close_applications = flow[
        flow.index("function PrepareAuthoritativePayloadReplacement") : flow.index(
            "function PrepareToInstall"
        )
    ]
    assert after_close_applications.index("StartDataRootMutationGuard") < (
        after_close_applications.index(
            "'Ticketbox pre-upgrade backup and service preparation'"
        )
    )
    finish = flow[flow.index("function NextButtonClick") : flow.index("function PrepareToInstall")]
    assert "ReleaseManagerMaintenanceGate()" in finish

    setup_deinitialize = flow[
        flow.index("procedure DeinitializeSetup") : flow.index("procedure CurUninstallStepChanged")
    ]
    assert setup_deinitialize.index("ReleaseDataRootMutationGuard()") < (
        setup_deinitialize.index("ReleaseLifecycleLock()")
    )
    assert setup_deinitialize.index("ReleaseLifecycleLock()") < setup_deinitialize.index(
        "CloseInstallerSourceLease()"
    )
    assert setup_deinitialize.index("CloseInstallerSourceLease()") < (
        setup_deinitialize.index("CloseManagerMaintenanceGate()")
    )
    uninstall_initialize = windows[
        windows.index("function InitializeUninstall") : windows.index(
            "procedure DeinitializeUninstall"
        )
    ]
    assert uninstall_initialize.index("AcquireLifecycleLock()") < (
        uninstall_initialize.index("StartManagerMaintenanceGate()")
    )
    uninstall = flow[flow.index("procedure CurUninstallStepChanged") :]
    assert uninstall.index("AssertManagerMaintenanceGateActive()") < uninstall.index(
        "'Ticketbox service uninstall'"
    )
    uninstall_deinitialize = windows[
        windows.index("procedure DeinitializeUninstall") : windows.index(
            "function IsSupportedPowerShell7Host"
        )
    ]
    assert uninstall_deinitialize.index("ReleaseLifecycleLock()") < (
        uninstall_deinitialize.index("CloseManagerMaintenanceGate()")
    )


def test_installer_source_lease_stays_owned_until_setup_deinitializes() -> None:
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")

    acquire = windows[
        windows.index("function AcquireInstallerSourceLease") : windows.index(
            "function StartManagerMaintenanceGate"
        )
    ]
    assert "ExpandConstant('{srcexe}')" in acquire
    assert "GenericRead" in acquire
    assert "FileShareRead" in acquire
    assert "Handoff" not in acquire
    assert "CreateFileForLease(" in acquire

    initialize = windows[
        windows.index("function InitializeSetup") : windows.index("function InitializeUninstall")
    ]
    assert initialize.index("AcquireInstallerSourceLease()") < initialize.index("if WizardSilent then")
    assert initialize.index("AcquireInstallerSourceLease()") < initialize.index(
        "AcquireLifecycleLock()"
    )
    deinitialize = flow[
        flow.index("procedure DeinitializeSetup") : flow.index("procedure CurUninstallStepChanged")
    ]
    assert deinitialize.index("ReleaseLifecycleLock()") < deinitialize.index(
        "CloseInstallerSourceLease()"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Inno compiler contract")
def test_manager_maintenance_gate_compiles_with_full_installer_code(tmp_path: Path) -> None:
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6/ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6/ISCC.exe",
    )
    iscc = next((candidate for candidate in candidates if candidate.is_file()), None)
    assert iscc is not None, "Inno Setup 6 compiler is required"

    digest = "a" * 64
    defines = {
        "AppName": "Ticketbox Contract",
        "AppVersion": "0.1.0",
        "AppVersionInfo": "0.1.0.0",
        "TicketboxAppIdGuid": "C97812CE-7486-41D0-AB68-7558A916F6E3",
        "PgServiceName": "TicketboxPgContract",
        "BackendServiceName": "TicketboxBackendContract",
        "DefaultPgPort": "5432",
        "FallbackPgPort": "15432",
        "DefaultBackendPort": "8000",
        "FallbackBackendPort": "18000",
        "TargetPgMajor": "17",
        "LifecycleSafetyScriptSha256": digest,
        "LifecycleLockScriptSha256": digest,
        "LifecycleHolderScriptSha256": digest,
        "DataRootGuardScriptSha256": digest,
        "PrepareScriptSha256": digest,
        "ServiceContractScriptSha256": digest,
        "ServiceLifecycleScriptSha256": digest,
        "LifecycleReceiptScriptSha256": digest,
        "DatabaseSafetyScriptSha256": digest,
        "PgRecoveryToolsScriptSha256": digest,
        "ReleaseConfigScriptSha256": digest,
        "ReleaseConfigJsonSha256": digest,
        "BuildProvenanceScriptSha256": digest,
        "BackendBuildProvenanceScriptSha256": digest,
    }
    preprocessor = "\n".join(f'#define {name} "{value}"' for name, value in defines.items())
    source = tmp_path / "manager-maintenance-contract.iss"
    source.write_text(
        preprocessor
        + """
[Setup]
AppName=Ticketbox Manager Maintenance Contract
AppVersion=0.1.0
DefaultDirName={tmp}\\TicketboxManagerMaintenanceContract
PrivilegesRequired=admin
Uninstallable=no
OutputDir=.
OutputBaseFilename=manager-maintenance-contract

[Code]
"""
        + f'#include "{PACKAGING / "ticketbox-installer-windows.isph"}"\n'
        + f'#include "{PACKAGING / "ticketbox-installer-flow.isph"}"\n',
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [iscc, source],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    windows = _read("ticketbox-installer-windows.isph")
    registry_path = rf"Software\TicketboxContract\{uuid.uuid4().hex}"
    windows_prefix = windows[: windows.index("function ProcessHandleMatchesStartedFileTime")]
    windows_prefix = windows_prefix.replace(
        "ManagerMaintenanceRegistryPath = 'Software\\Ticketbox';",
        f"ManagerMaintenanceRegistryPath = '{registry_path}';",
    ).replace("HKLM64", "HKCU")
    gate_source = tmp_path / "manager-maintenance-runtime-contract.iss"
    gate_output = tmp_path / "manager-maintenance-runtime-contract.txt"
    gate_ready = tmp_path / "manager-maintenance-runtime-contract.ready"
    gate_release = tmp_path / "manager-maintenance-runtime-contract.release"
    gate_source.write_text(
        preprocessor
        + """
[Setup]
AppName=Ticketbox Manager Maintenance Runtime Contract
AppVersion=0.1.0
DefaultDirName={tmp}\\TicketboxManagerMaintenanceRuntimeContract
PrivilegesRequired=lowest
Uninstallable=no
OutputDir=.
OutputBaseFilename=manager-maintenance-runtime-contract

[Code]
"""
        + windows_prefix
        + """
function InitializeSetup(): Boolean;
var
  Attempts: Integer;
  ProcessHandle: LongWord;
begin
  ManagerMaintenanceOwnerRecord := '';
  LifecycleLockOwnerProcessId := GetCurrentProcessId();
  ProcessHandle := OpenProcess(
    ProcessSynchronize or ProcessQueryLimitedInformation,
    False,
    LifecycleLockOwnerProcessId);
  if not IsProcessHandleRunning(ProcessHandle) then
    RaiseException('could not open maintenance owner process');
  if not ReadProcessStartedFileTime(
    ProcessHandle,
    LifecycleLockOwnerStartedFileTimeHigh,
    LifecycleLockOwnerStartedFileTimeLow) then
    RaiseException('could not read maintenance owner creation time');
  CloseHandle(ProcessHandle);
  if not StartManagerMaintenanceGate() then
    RaiseException('could not start maintenance gate');
  if not ManagerMaintenanceGateActive() then
    RaiseException('maintenance gate was not initially active');
  if not ManagerMaintenanceGateActive() then
    RaiseException('maintenance gate was not manual-reset');
  if not SaveStringToFile(
    ExpandConstant('{param:ReadyPath|}'),
    'ready',
    False) then
    RaiseException('could not save maintenance gate ready state');
  Attempts := 0;
  while (not FileExists(ExpandConstant('{param:ReleasePath|}'))) and
    (Attempts < 200) do begin
    Sleep(50);
    Attempts := Attempts + 1;
  end;
  if not FileExists(ExpandConstant('{param:ReleasePath|}')) then
    RaiseException('maintenance gate release timed out');
  if not ReleaseManagerMaintenanceGate() then
    RaiseException('could not release maintenance gate');
  if ManagerMaintenanceGateActive() then
    RaiseException('maintenance gate remained active after release');
  if not SaveStringToFile(
    ExpandConstant('{param:OutputPath|}'),
    'ok',
    False) then
    RaiseException('could not save maintenance gate result');
  Result := False;
end;
""",
        encoding="utf-8-sig",
    )
    gate_compile = subprocess.run(
        [iscc, gate_source],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert gate_compile.returncode == 0, gate_compile.stdout + gate_compile.stderr

    def manager_gate_requested() -> bool:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "import winreg; "
                "from backend_manager.maintenance_gate import "
                "manager_maintenance_requested, _read_registry_record; "
                "reader=lambda: _read_registry_record(root=winreg.HKEY_CURRENT_USER, registry_path=sys.argv[2]); "
                "print('true' if manager_maintenance_requested(record_reader=reader) else 'false')",
                str(ROOT / "desktop"),
                registry_path,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        assert probe.stdout.strip() in {"true", "false"}
        return probe.stdout.strip() == "true"

    gate_process = subprocess.Popen(
        [
            tmp_path / "manager-maintenance-runtime-contract.exe",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            f"/OutputPath={gate_output}",
            f"/ReadyPath={gate_ready}",
            f"/ReleasePath={gate_release}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    gate_stdout = gate_stderr = ""
    try:
        deadline = time.monotonic() + 10
        while not gate_ready.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert gate_ready.is_file(), "Inno producer did not publish the maintenance gate"
        assert manager_gate_requested() is True
        assert manager_gate_requested() is True
        gate_release.write_text("release", encoding="utf-8")
        gate_stdout, gate_stderr = gate_process.communicate(timeout=20)
    finally:
        gate_release.write_text("release", encoding="utf-8")
        if gate_process.poll() is None:
            try:
                gate_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                gate_process.kill()
                gate_process.communicate()
    assert gate_output.is_file(), gate_stdout + gate_stderr
    assert gate_output.read_text(encoding="utf-8-sig") == "ok"
    assert manager_gate_requested() is False

    gate_ready.unlink()
    gate_release.unlink()
    gate_output.unlink()
    crashed_process = subprocess.Popen(
        [
            tmp_path / "manager-maintenance-runtime-contract.exe",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            f"/OutputPath={gate_output}",
            f"/ReadyPath={gate_ready}",
            f"/ReleasePath={gate_release}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.monotonic() + 10
    while not gate_ready.is_file() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert gate_ready.is_file(), "Inno producer did not publish the crash marker"
    assert manager_gate_requested() is True
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
        owner_record, _ = winreg.QueryValueEx(key, "MaintenanceOwner")
    owner_process_id = int(owner_record.split("|")[1])
    assert owner_process_id not in {0, os.getpid()}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_bool
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    owner_handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, owner_process_id)
    assert owner_handle
    try:
        assert kernel32.TerminateProcess(owner_handle, 1)
        assert kernel32.WaitForSingleObject(owner_handle, 5000) == 0
    finally:
        kernel32.CloseHandle(owner_handle)
    crashed_process.communicate(timeout=10)
    assert manager_gate_requested() is False

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        registry_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.DeleteValue(key, "MaintenanceOwner")

    flow = _read("ticketbox-installer-flow.isph")
    selection_contract = flow[
        flow.index("function TryAvailablePort") : flow.index(
            "procedure ResolveInstallationPorts"
        )
    ]
    selection_source = tmp_path / "automatic-port-selection-contract.iss"
    selection_output = tmp_path / "automatic-port-selection.txt"
    selection_source.write_text(
        """
[Setup]
AppName=Ticketbox Automatic Port Selection Contract
AppVersion=0.1.0
DefaultDirName={tmp}\\TicketboxAutomaticPortSelectionContract
PrivilegesRequired=lowest
Uninstallable=no
OutputDir=.
OutputBaseFilename=automatic-port-selection-contract

[Code]
var
  PortProbeFailed: Boolean;

function IsValidPort(Port: String): Boolean;
var
  PortNumber: Integer;
begin
  PortNumber := StrToIntDef(Trim(Port), -1);
  Result := (PortNumber >= 1) and (PortNumber <= 65535);
end;

function IsPortListening(Port: String): Boolean;
begin
  Result :=
    (Port = '5432') or (Port = '5440') or
    (Port = '8000') or (Port = '8001');
end;
"""
        + selection_contract
        + """
function InitializeSetup(): Boolean;
var
  PgPort: String;
  BackendPort: String;
begin
  PortProbeFailed := False;
  if not FindAutomaticPort('5432', '5440', '', PgPort) then
    RaiseException('PostgreSQL automatic selection failed');
  if not FindAutomaticPort('8000', '8001', PgPort, BackendPort) then
    RaiseException('backend automatic selection failed');
  if not SaveStringToFile(
    ExpandConstant('{param:OutputPath|}'),
    PgPort + #13#10 + BackendPort + #13#10,
    False) then
    RaiseException('could not save automatic selection result');
  Result := False;
end;
""",
        encoding="utf-8-sig",
    )
    selection_compile = subprocess.run(
        [iscc, selection_source],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert selection_compile.returncode == 0, selection_compile.stdout + selection_compile.stderr
    selection_run = subprocess.run(
        [
            tmp_path / "automatic-port-selection-contract.exe",
            "/VERYSILENT",
            f"/OutputPath={selection_output}",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    assert selection_output.read_text(encoding="utf-8-sig").splitlines() == ["5441", "8002"], (
        selection_run.stdout + selection_run.stderr
    )


def test_powershell7_selector_requires_core_v7_x64_and_is_deterministic() -> None:
    windows = _read("ticketbox-installer-windows.isph")
    probe = windows[
        windows.index("function IsSupportedPowerShell7Host") : windows.index(
            "function IsProtectedProgramFilesPath"
        )
    ]
    assert "$PSVersionTable.PSEdition -ceq ''Core''" in probe
    assert "$PSVersionTable.PSVersion.Major -ge 7" in probe
    assert "[Environment]::Is64BitProcess" in probe
    assert "exit 0" in probe and "exit 1" in probe

    selector = windows[
        windows.index("function FindMachinePowerShell7") : windows.index(
            "function PowerShellExecutable"
        )
    ]
    assert "HasValidMicrosoftSignature(Candidate)" in selector
    assert "IsSupportedPowerShell7Host(Candidate)" in selector
    assert "CompareText(ExpandFileName(Candidate), ExpandFileName(Result)) < 0" in selector
    selected_branch = selector[selector.index("Result := Candidate;") :]
    assert "exit;" not in selected_branch


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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows lifecycle lock holder contract")
def test_external_lifecycle_lock_holder_keeps_authority_until_release(
    tmp_path: Path,
) -> None:
    for engine_index, engine in enumerate(powershell_contract_engines()):
        for case in ("valid", "forged", "active-operation", "owner-identity-mismatch"):
            lock_root = tmp_path / f"machine-lifecycle-{engine_index}-{case}"
            validation_root = tmp_path / f"lifecycle-bootstrap-{engine_index}-{case}"
            root_validated_path = validation_root / "root-validated.ready"
            ready_path = lock_root / "lifecycle.ready"
            release_path = lock_root / "lifecycle.release"
            owner_path = lock_root / "installer-lifecycle.owner"
            owner_started_high, owner_started_low = _windows_process_creation_filetime_parts(
                os.getpid()
            )
            owner_high_argument = (
                (owner_started_high + 1) & 0xFFFFFFFF
                if case == "owner-identity-mismatch"
                else owner_started_high
            )
            harness = tmp_path / f"hold-lifecycle-lock-{engine_index}-{case}.ps1"
            harness.write_text(
                f"""
$ErrorActionPreference = 'Stop'
. '{str(PACKAGING / 'windows_installation_safety.ps1').replace("'", "''")}'
. '{str(PACKAGING / 'windows_lifecycle_lock.ps1').replace("'", "''")}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{str(validation_root).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
$expectedOwnerIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
    -ProcessId {os.getpid()} `
    -StartedFileTimeHigh {owner_high_argument} `
    -StartedFileTimeLow {owner_started_low}
$ownerHandleLease = Open-TicketboxVerifiedProcessIdentityHandle `
    -ProcessId {os.getpid()} `
    -ExpectedIdentity $expectedOwnerIdentity
try {{
    Wait-TicketboxExternalInstallerLifecycleLock `
        -LockDirectory '{str(lock_root).replace("'", "''")}' `
        -RootValidatedPath '{str(root_validated_path).replace("'", "''")}' `
        -ReadyPath '{str(ready_path).replace("'", "''")}' `
        -ReleasePath '{str(release_path).replace("'", "''")}' `
        -OwnerProcessId {os.getpid()} `
        -OwnerStartedFileTimeHigh {owner_high_argument} `
        -OwnerStartedFileTimeLow {owner_started_low} `
        -OwnerProcessHandleLease $ownerHandleLease `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
finally {{
    try {{
        if (Test-Path -LiteralPath '{str(root_validated_path).replace("'", "''")}' -PathType Leaf) {{
            Remove-TicketboxProtectedUtf8Artifact `
                -Path '{str(root_validated_path).replace("'", "''")}' `
                -FullControlAccounts @($currentAccount) `
                -OwnerAccount $currentAccount
        }}
    }}
    finally {{
        Close-TicketboxProcessIdentityHandle $ownerHandleLease
    }}
}}
""",
                encoding="utf-8-sig",
            )
            process = subprocess.Popen(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    harness,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if case == "owner-identity-mismatch":
                stdout, stderr = process.communicate(timeout=15)
                assert process.returncode != 0
                assert "创建时间" in stderr
                assert not owner_path.exists()
                assert not ready_path.exists()
                continue
            deadline = time.monotonic() + 20
            while (
                not root_validated_path.is_file()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if not root_validated_path.is_file():
                stdout, stderr = process.communicate(timeout=5)
                pytest.fail(f"{engine} holder never validated its root:\n{stdout}\n{stderr}")
            assert root_validated_path.read_text(encoding="utf-8") == (
                f"STATE=root_validated\nOWNER_PID={os.getpid()}\n"
            )
            while (
                not ready_path.is_file()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if not ready_path.is_file():
                stdout, stderr = process.communicate(timeout=5)
                pytest.fail(f"{engine} holder never became ready:\n{stdout}\n{stderr}")
            assert process.poll() is None
            ready_text = ready_path.read_text(encoding="utf-8")
            match = re.fullmatch(
                rf"STATE=holding\nOWNER_PID={os.getpid()}\nHOLDER_PID=(\d+)\n"
                rf"HOLDER_STARTED_FILETIME_HIGH=(\d+)\n"
                rf"HOLDER_STARTED_FILETIME_LOW=(\d+)\n"
                rf"INSTALLER_STATE=(.+)\nNONCE=([0-9a-f]{{64}})\n",
                ready_text,
            )
            assert match is not None, ready_text
            assert int(match.group(1)) == process.pid
            assert (int(match.group(2)), int(match.group(3))) == (
                _windows_process_creation_filetime_parts(process.pid)
            )
            assert Path(match.group(4)) == lock_root / "installer-state"
            assert owner_path.read_text(encoding="utf-8") == (
                "SCHEMA=ticketbox-lifecycle-owner-v2\n"
                f"OWNER_PID={os.getpid()}\n"
                f"OWNER_STARTED_FILETIME_HIGH={owner_started_high}\n"
                f"OWNER_STARTED_FILETIME_LOW={owner_started_low}\n"
            )
            nonce = match.group(5)
            if case == "forged":
                nonce = "0" * 64 if nonce != "0" * 64 else "1" * 64
            activity_process = None
            activity_release = None
            if case == "active-operation":
                activity_process, activity_release = _start_exclusive_file_lock(
                    engine,
                    tmp_path,
                    f"lifecycle-activity-{engine_index}",
                    lock_root / "installer-operation.lock",
                )
            writer = tmp_path / f"write-release-{engine_index}-{case}.ps1"
            writer.write_text(
                f"""
$ErrorActionPreference = 'Stop'
. '{str(PACKAGING / 'windows_installation_safety.ps1').replace("'", "''")}'
. '{str(PACKAGING / 'windows_lifecycle_lock.ps1').replace("'", "''")}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$releaseText =
    "STATE=release$([Environment]::NewLine)" +
    "OWNER_PID={os.getpid()}$([Environment]::NewLine)" +
    "NONCE={nonce}$([Environment]::NewLine)"
Write-TicketboxLifecycleCoordinationArtifact `
    -Path '{str(release_path).replace("'", "''")}' `
    -Text $releaseText `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
""",
                encoding="utf-8-sig",
            )
            writer_result = subprocess.run(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    writer,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            assert writer_result.returncode == 0, writer_result.stderr
            if activity_process is not None:
                time.sleep(0.3)
                assert process.poll() is None
                assert ready_path.is_file()
                assert activity_release is not None
                activity_release.write_text("release", encoding="utf-8")
                activity_stdout, activity_stderr = activity_process.communicate(timeout=10)
                assert activity_process.returncode == 0, (
                    f"{engine}:\n{activity_stdout}\n{activity_stderr}"
                )
            stdout, stderr = process.communicate(timeout=15)
            if case in {"valid", "active-operation"}:
                assert process.returncode == 0, f"{engine}:\n{stdout}\n{stderr}"
            else:
                assert process.returncode != 0
                assert "release IPC" in stderr
            assert not owner_path.exists()
            assert not root_validated_path.exists()
            assert not ready_path.exists()
            assert not release_path.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DataRoot guard contract")
def test_data_root_guard_authenticates_holder_and_cleans_ipc_after_owner_death(
    tmp_path: Path,
) -> None:
    safety = str(PACKAGING / "windows_installation_safety.ps1").replace("'", "''")
    lifecycle = str(PACKAGING / "windows_lifecycle_lock.ps1").replace("'", "''")
    for engine_index, engine in enumerate(powershell_contract_engines()):
        for case in ("release", "abort", "owner-death", "owner-death-active-operation"):
            ipc_root = tmp_path / f"data-root-ipc-{engine_index}-{case}"
            guarded_root = tmp_path / f"guarded-data-{engine_index}-{case}"
            guard_install_dir = tmp_path / f"guarded-program-{engine_index}-{case}"
            ready_path = ipc_root / "guard.ready"
            release_path = ipc_root / "guard.release"
            activity_lock_path = ipc_root / "installer-operation.lock"
            acl_probe = tmp_path / f"runtime-state-acl-{engine_index}"
            owner = None
            owner_pid = os.getpid()
            if case.startswith("owner-death"):
                owner = subprocess.Popen(
                    [engine, "-NoLogo", "-NoProfile", "-Command", "Start-Sleep -Seconds 30"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                owner_pid = owner.pid
            acl_probe_contract = ""
            if case == "release":
                acl_probe_contract = fr"""
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{str(acl_probe).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -ReadExecuteAccounts @('BUILTIN\Users') `
    -OwnerAccount $currentAccount | Out-Null
Assert-TicketboxProtectedDirectoryAcl `
    -Path '{str(acl_probe).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -ReadExecuteAccounts @('BUILTIN\Users') `
    -OwnerAccount $currentAccount
"""
            harness = tmp_path / f"hold-data-root-{engine_index}-{case}.ps1"
            harness.write_text(
                f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
. '{lifecycle}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
{acl_probe_contract}
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{str(ipc_root).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
$startupLeaseState = [pscustomobject]@{{
    Lock = [System.IO.File]::Open(
        '{str(activity_lock_path).replace("'", "''")}',
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
}}
$ownerIdentity = Get-TicketboxProcessIdentity -ProcessId {owner_pid}
$releaseStartupLease = {{
    param([bool]$RequireReady)
    if ($null -ne $startupLeaseState.Lock) {{
        if ($RequireReady -and -not (Test-Path -LiteralPath '{str(ready_path).replace("'", "''")}' -PathType Leaf)) {{
            throw 'startup operation lease was released before durable ready publication'
        }}
        $startupLeaseState.Lock.Dispose()
        $startupLeaseState.Lock = $null
    }}
}}
$handoffStartupLease = {{ & $releaseStartupLease $true }}
try {{
    Wait-TicketboxDirectoryMutationGuardLease `
        -Path '{str(guarded_root).replace("'", "''")}' `
        -InstallDir '{str(guard_install_dir).replace("'", "''")}' `
        -ReadyPath '{str(ready_path).replace("'", "''")}' `
        -ReleasePath '{str(release_path).replace("'", "''")}' `
        -OwnerProcessId {owner_pid} `
        -OwnerIdentity $ownerIdentity `
        -OnLeaseReady $handoffStartupLease `
        -RetainWhileLockPath '{str(activity_lock_path).replace("'", "''")}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
finally {{ & $releaseStartupLease $false }}
""",
                encoding="utf-8-sig",
            )
            process = subprocess.Popen(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    harness,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            deadline = time.monotonic() + 20
            while (
                not ready_path.is_file()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if not ready_path.is_file():
                stdout, stderr = process.communicate(timeout=5)
                if owner is not None and owner.poll() is None:
                    owner.terminate()
                pytest.fail(f"{engine} DataRoot guard never became ready:\n{stdout}\n{stderr}")

            ready_text = ready_path.read_text(encoding="utf-8")
            match = re.fullmatch(
                rf"STATE=holding\nOWNER_PID={owner_pid}\nHOLDER_PID=(\d+)\n"
                rf"HOLDER_STARTED_FILETIME_HIGH=(\d+)\n"
                rf"HOLDER_STARTED_FILETIME_LOW=(\d+)\n"
                rf"NONCE=([0-9a-f]{{64}})\n",
                ready_text,
            )
            assert match is not None, ready_text
            assert int(match.group(1)) == process.pid
            assert (int(match.group(2)), int(match.group(3))) == (
                _windows_process_creation_filetime_parts(process.pid)
            )
            nonce = match.group(4)
            activity_process = None
            activity_release = None
            if case == "owner-death-active-operation":
                activity_process, activity_release = _start_exclusive_file_lock(
                    engine,
                    tmp_path,
                    f"data-root-activity-{engine_index}",
                    activity_lock_path,
                )

            if case in {"release", "abort"}:
                control_text = (
                    '"STATE=release$([Environment]::NewLine)" +\n'
                    f'    "OWNER_PID={owner_pid}$([Environment]::NewLine)" +\n'
                    f'    "NONCE={nonce}$([Environment]::NewLine)"'
                    if case == "release"
                    else '"STATE=abort$([Environment]::NewLine)" +\n'
                    f'    "OWNER_PID={owner_pid}$([Environment]::NewLine)"'
                )
                writer = tmp_path / f"release-data-root-{engine_index}.ps1"
                writer.write_text(
                    f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$releaseText =
    {control_text}
Write-TicketboxProtectedUtf8FileDurable `
    -Path '{str(release_path).replace("'", "''")}' `
    -Text $releaseText `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
""",
                    encoding="utf-8-sig",
                )
                writer_result = subprocess.run(
                    [
                        engine,
                        "-NoLogo",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        writer,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
                assert writer_result.returncode == 0, writer_result.stderr
            else:
                (release_path.parent / f"{release_path.name}.tmp").write_text(
                    "partial",
                    encoding="utf-8",
                )
                assert owner is not None
                owner.terminate()
                owner.wait(timeout=10)
                if activity_process is not None:
                    time.sleep(0.3)
                    assert process.poll() is None
                    assert ready_path.is_file()
                    assert activity_release is not None
                    activity_release.write_text("release", encoding="utf-8")
                    activity_stdout, activity_stderr = activity_process.communicate(timeout=10)
                    assert activity_process.returncode == 0, (
                        f"{engine}:\n{activity_stdout}\n{activity_stderr}"
                    )

            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, f"{engine}:\n{stdout}\n{stderr}"
            assert not ready_path.exists()
            assert not release_path.exists()
            assert not Path(f"{release_path}.tmp").exists()
            marker = guarded_root / ".ticketbox-data-root.json"
            assert marker.is_file()
            marker_value = json.loads(marker.read_text(encoding="utf-8"))
            assert marker_value["schema"] == "ticketbox-data-root-v2"
            assert Path(marker_value["data_root"]) == guarded_root
            assert Path(marker_value["install_dir"]) == guard_install_dir
            assert re.fullmatch(
                r"\\\\\?\\VOLUME\{[0-9A-F-]{36}\}\\",
                marker_value["data_volume_identity"],
            )
            assert not (ipc_root / "data-root-provisioning-pending").exists()

        untrusted_root = tmp_path / f"guarded-data-{engine_index}-preexisting-empty"
        untrusted_root.mkdir()
        ipc_root = tmp_path / f"data-root-ipc-{engine_index}-preexisting-empty"
        ready_path = ipc_root / "guard.ready"
        release_path = ipc_root / "guard.release"
        reject_harness = tmp_path / f"hold-data-root-{engine_index}-preexisting-empty.ps1"
        reject_harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
. '{lifecycle}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{str(ipc_root).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
Wait-TicketboxDirectoryMutationGuardLease `
    -Path '{str(untrusted_root).replace("'", "''")}' `
    -InstallDir '{str(tmp_path / f"guarded-program-{engine_index}-preexisting-empty").replace("'", "''")}' `
    -ReadyPath '{str(ready_path).replace("'", "''")}' `
    -ReleasePath '{str(release_path).replace("'", "''")}' `
    -OwnerProcessId {os.getpid()} `
    -OwnerIdentity (Get-TicketboxProcessIdentity -ProcessId {os.getpid()}) `
    -OnLeaseReady {{ }} `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
""",
            encoding="utf-8-sig",
        )
        rejected = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", reject_harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert rejected.returncode != 0
        assert "预先存在的空 DataRoot" in rejected.stderr
        assert not ready_path.exists()
        assert not (untrusted_root / ".ticketbox-data-root.json").exists()

        junction_target = tmp_path / f"guarded-data-{engine_index}-junction-target"
        junction_parent = tmp_path / f"guarded-data-{engine_index}-junction-parent"
        junction_leaf = junction_parent / "missing-child"
        junction_ipc_root = tmp_path / f"data-root-ipc-{engine_index}-junction-parent"
        junction_ready_path = junction_ipc_root / "guard.ready"
        junction_release_path = junction_ipc_root / "guard.release"
        junction_intent_path = junction_ipc_root / "data-root-provisioning-pending"
        junction_harness = tmp_path / f"hold-data-root-{engine_index}-junction-parent.ps1"
        junction_harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
. '{lifecycle}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{str(junction_ipc_root).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
New-Item -ItemType Directory -Path '{str(junction_target).replace("'", "''")}' | Out-Null
New-Item `
    -ItemType Junction `
    -Path '{str(junction_parent).replace("'", "''")}' `
    -Target '{str(junction_target).replace("'", "''")}' | Out-Null
try {{
    $rejected = $false
    try {{
        Wait-TicketboxDirectoryMutationGuardLease `
            -Path '{str(junction_leaf).replace("'", "''")}' `
            -InstallDir '{str(tmp_path / f"guarded-program-{engine_index}-junction-parent").replace("'", "''")}' `
            -ReadyPath '{str(junction_ready_path).replace("'", "''")}' `
            -ReleasePath '{str(junction_release_path).replace("'", "''")}' `
            -OwnerProcessId {os.getpid()} `
            -OwnerIdentity (Get-TicketboxProcessIdentity -ProcessId {os.getpid()}) `
            -OnLeaseReady {{ throw 'junction-backed DataRoot unexpectedly became ready' }} `
            -FullControlAccounts @($currentAccount) `
            -OwnerAccount $currentAccount
    }}
    catch {{
        if ($_.Exception.Message -cnotmatch '重解析点') {{ throw }}
        $rejected = $true
    }}
    if (-not $rejected) {{ throw 'junction-backed DataRoot was accepted' }}
    if (Test-Path -LiteralPath '{str(junction_intent_path).replace("'", "''")}') {{
        throw 'rejected ancestor published a provisioning intent'
    }}
    if (Test-Path -LiteralPath '{str(junction_target / "missing-child").replace("'", "''")}') {{
        throw 'rejected ancestor created content through the junction'
    }}
}}
finally {{
    if (Test-Path -LiteralPath '{str(junction_parent).replace("'", "''")}') {{
        [System.IO.Directory]::Delete('{str(junction_parent).replace("'", "''")}')
    }}
}}
""",
            encoding="utf-8-sig",
        )
        junction_result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                junction_harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert junction_result.returncode == 0, (
            junction_result.stdout + junction_result.stderr
        )
        assert not junction_intent_path.exists()

        retarget_ipc_root = tmp_path / f"data-root-ipc-{engine_index}-retarget"
        abandoned_root = tmp_path / f"guarded-data-{engine_index}-abandoned"
        abandoned_install_dir = tmp_path / f"guarded-program-{engine_index}-abandoned"
        retargeted_root = tmp_path / f"guarded-data-{engine_index}-retargeted"
        retargeted_install_dir = tmp_path / f"guarded-program-{engine_index}-retargeted"
        retarget_ready_path = retarget_ipc_root / "guard.ready"
        retarget_release_path = retarget_ipc_root / "guard.release"
        retarget_intent_path = retarget_ipc_root / "data-root-provisioning-pending"
        retarget_harness = tmp_path / f"hold-data-root-{engine_index}-retarget.ps1"
        retarget_harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
. '{lifecycle}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{str(retarget_ipc_root).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
$abandonedIntent = Get-TicketboxDataRootProvisioningIntentText `
    -DataRoot '{str(abandoned_root).replace("'", "''")}' `
    -InstallDir '{str(abandoned_install_dir).replace("'", "''")}'
Write-TicketboxProtectedUtf8FileDurable `
    -Path '{str(retarget_intent_path).replace("'", "''")}' `
    -Text $abandonedIntent `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$ownerIdentity = Get-TicketboxProcessIdentity -ProcessId {os.getpid()}
$script:originalVolumeIdentityProvider = ${{function:Get-TicketboxVolumeIdentityForPath}}
try {{
    function Get-TicketboxVolumeIdentityForPath {{
        param([string]$Path)
        if (Test-TicketboxPathEquals $Path '{str(abandoned_root).replace("'", "''")}') {{
            return '\\\\?\\Volume{{00000000-0000-0000-0000-000000000000}}\\'
        }}
        return & $script:originalVolumeIdentityProvider $Path
    }}
    $replacementVolumeRejected = $false
    try {{
        Wait-TicketboxDirectoryMutationGuardLease `
            -Path '{str(abandoned_root).replace("'", "''")}' `
            -InstallDir '{str(abandoned_install_dir).replace("'", "''")}' `
            -ReadyPath '{str(retarget_ready_path).replace("'", "''")}' `
            -ReleasePath '{str(retarget_release_path).replace("'", "''")}' `
            -OwnerProcessId {os.getpid()} `
            -OwnerIdentity $ownerIdentity `
            -OnLeaseReady {{ throw 'replacement volume unexpectedly became ready' }} `
            -FullControlAccounts @($currentAccount) `
            -OwnerAccount $currentAccount
    }}
    catch {{
        if ($_.Exception.Message -cnotmatch '原卷当前不可用或已被替换') {{ throw }}
        $replacementVolumeRejected = $true
    }}
    if (-not $replacementVolumeRejected) {{ throw 'replacement volume reused the old drive letter' }}
    $preservedAbandonedIntent = Read-TicketboxDataRootProvisioningIntent `
        -Path '{str(retarget_intent_path).replace("'", "''")}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
    if (-not (Test-TicketboxPathEquals $preservedAbandonedIntent.DataRoot '{str(abandoned_root).replace("'", "''")}')) {{
        throw 'replacement-volume rejection changed the original intent'
    }}
}}
finally {{
    Set-Item `
        -LiteralPath Function:\\Get-TicketboxVolumeIdentityForPath `
        -Value $script:originalVolumeIdentityProvider
}}
$differentPathRejected = $false
try {{
    Wait-TicketboxDirectoryMutationGuardLease `
        -Path '{str(retargeted_root).replace("'", "''")}' `
        -InstallDir '{str(retargeted_install_dir).replace("'", "''")}' `
        -ReadyPath '{str(retarget_ready_path).replace("'", "''")}' `
        -ReleasePath '{str(retarget_release_path).replace("'", "''")}' `
        -OwnerProcessId {os.getpid()} `
        -OwnerIdentity $ownerIdentity `
        -OnLeaseReady {{ throw 'different path unexpectedly became ready' }} `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{
    if ($_.Exception.Message -cnotmatch '固定绑定') {{ throw }}
    $differentPathRejected = $true
}}
if (-not $differentPathRejected) {{ throw 'provisioning intent was automatically retargeted' }}
if (Test-Path -LiteralPath '{str(retargeted_root).replace("'", "''")}') {{
    throw 'rejected different path was created'
}}
$script:retargetReadyPath = '{str(retarget_ready_path).replace("'", "''")}'
$script:retargetReleasePath = '{str(retarget_release_path).replace("'", "''")}'
$script:retargetCurrentAccount = $currentAccount
$script:retargetOwnerProcessId = {os.getpid()}
$releaseRetargetedGuard = {{
    $readyArtifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $script:retargetReadyPath `
        -FullControlAccounts @($script:retargetCurrentAccount) `
        -OwnerAccount $script:retargetCurrentAccount `
        -MaximumBytes 512
    $nonceLines = @($readyArtifact.Text -split "`r?`n" | Where-Object {{ $_.StartsWith('NONCE=') }})
    if ($nonceLines.Count -ne 1) {{ throw 'retarget ready artifact lacks one nonce' }}
    $releaseText =
        "STATE=release$([Environment]::NewLine)" +
        "OWNER_PID=$script:retargetOwnerProcessId$([Environment]::NewLine)" +
        "NONCE=$($nonceLines[0].Substring(6))$([Environment]::NewLine)"
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $script:retargetReleasePath `
        -Text $releaseText `
        -FullControlAccounts @($script:retargetCurrentAccount) `
        -OwnerAccount $script:retargetCurrentAccount
}}
Wait-TicketboxDirectoryMutationGuardLease `
    -Path '{str(abandoned_root).replace("'", "''")}' `
    -InstallDir '{str(abandoned_install_dir).replace("'", "''")}' `
    -ReadyPath '{str(retarget_ready_path).replace("'", "''")}' `
    -ReleasePath '{str(retarget_release_path).replace("'", "''")}' `
    -OwnerProcessId {os.getpid()} `
    -OwnerIdentity $ownerIdentity `
    -OnLeaseReady $releaseRetargetedGuard `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
if (Test-Path -LiteralPath '{str(retarget_intent_path).replace("'", "''")}') {{
    throw 'same-path retry did not retire the provisioning intent'
}}
Assert-TicketboxProtectedDataRootMarker `
    -DataRoot '{str(abandoned_root).replace("'", "''")}' `
    -InstallDir '{str(abandoned_install_dir).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
""",
            encoding="utf-8-sig",
        )
        retarget_result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                retarget_harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert retarget_result.returncode == 0, (
            retarget_result.stdout + retarget_result.stderr
        )

        retry_ipc_root = tmp_path / f"data-root-ipc-{engine_index}-provisioning-retry"
        retry_guarded_root = tmp_path / f"guarded-data-{engine_index}-provisioning-retry"
        retry_alternate_root = tmp_path / f"guarded-data-{engine_index}-unsafe-retarget"
        retry_install_dir = tmp_path / f"guarded-program-{engine_index}-provisioning-retry"
        retry_ready_path = retry_ipc_root / "guard.ready"
        retry_release_path = retry_ipc_root / "guard.release"
        retry_intent_path = retry_ipc_root / "data-root-provisioning-pending"
        retry_harness = tmp_path / f"hold-data-root-{engine_index}-provisioning-retry.ps1"
        retry_harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
. '{lifecycle}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{str(retry_ipc_root).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
$ownerIdentity = Get-TicketboxProcessIdentity -ProcessId {os.getpid()}
function Write-TicketboxDataRootMarker {{
    param(
        [string]$DataRoot,
        [string]$InstallDir,
        [string]$DataVolumeIdentity,
        [string[]]$FullControlAccounts,
        [string]$OwnerAccount
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $DataRoot '.ticketbox-durable-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.tmp'),
        'partial marker staging'
    )
    throw 'injected marker persistence failure'
}}
$firstAttemptFailed = $false
try {{
    Wait-TicketboxDirectoryMutationGuardLease `
        -Path '{str(retry_guarded_root).replace("'", "''")}' `
        -InstallDir '{str(retry_install_dir).replace("'", "''")}' `
        -ReadyPath '{str(retry_ready_path).replace("'", "''")}' `
        -ReleasePath '{str(retry_release_path).replace("'", "''")}' `
        -OwnerProcessId {os.getpid()} `
        -OwnerIdentity $ownerIdentity `
        -OnLeaseReady {{ throw 'first attempt unexpectedly reached ready' }} `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{
    if ($_.Exception.Message -cnotmatch 'injected marker persistence failure') {{ throw }}
    $firstAttemptFailed = $true
}}
if (-not $firstAttemptFailed) {{ throw 'first marker failure was not observed' }}
if (-not (Test-Path -LiteralPath '{str(retry_intent_path).replace("'", "''")}' -PathType Leaf)) {{
    throw 'failed provisioning attempt did not preserve durable intent'
}}
if (-not (Test-Path -LiteralPath '{str(retry_guarded_root).replace("'", "''")}' -PathType Container)) {{
    throw 'failed provisioning attempt did not leave the created protected root'
}}
if (Test-Path -LiteralPath '{str(retry_guarded_root / ".ticketbox-data-root.json").replace("'", "''")}') {{
    throw 'failed marker write unexpectedly published authority'
}}
if (-not (Test-Path -LiteralPath '{str(retry_guarded_root / ".ticketbox-durable-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.tmp").replace("'", "''")}' -PathType Leaf)) {{
    throw 'injected marker staging artifact was not preserved'
}}
$unsafeRetargetRejected = $false
try {{
    Wait-TicketboxDirectoryMutationGuardLease `
        -Path '{str(retry_alternate_root).replace("'", "''")}' `
        -InstallDir '{str(retry_install_dir).replace("'", "''")}' `
        -ReadyPath '{str(retry_ready_path).replace("'", "''")}' `
        -ReleasePath '{str(retry_release_path).replace("'", "''")}' `
        -OwnerProcessId {os.getpid()} `
        -OwnerIdentity $ownerIdentity `
        -OnLeaseReady {{ throw 'unsafe retarget unexpectedly became ready' }} `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{
    if ($_.Exception.Message -cnotmatch '固定绑定') {{ throw }}
    $unsafeRetargetRejected = $true
}}
if (-not $unsafeRetargetRejected) {{ throw 'existing partial DataRoot was retargeted' }}
$preservedIntent = Read-TicketboxDataRootProvisioningIntent `
    -Path '{str(retry_intent_path).replace("'", "''")}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
if (-not (Test-TicketboxPathEquals $preservedIntent.DataRoot '{str(retry_guarded_root).replace("'", "''")}')) {{
    throw 'rejected retarget replaced the original provisioning intent'
}}

. '{safety}'
$script:retryReadyPath = '{str(retry_ready_path).replace("'", "''")}'
$script:retryReleasePath = '{str(retry_release_path).replace("'", "''")}'
$script:retryCurrentAccount = $currentAccount
$script:retryOwnerProcessId = {os.getpid()}
$releaseAfterReady = {{
    $readyArtifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $script:retryReadyPath `
        -FullControlAccounts @($script:retryCurrentAccount) `
        -OwnerAccount $script:retryCurrentAccount `
        -MaximumBytes 512
    $nonceLines = @($readyArtifact.Text -split "`r?`n" | Where-Object {{ $_.StartsWith('NONCE=') }})
    if ($nonceLines.Count -ne 1) {{ throw 'retry ready artifact lacks one nonce' }}
    $nonce = $nonceLines[0].Substring(6)
    $releaseText =
        "STATE=release$([Environment]::NewLine)" +
        "OWNER_PID=$script:retryOwnerProcessId$([Environment]::NewLine)" +
        "NONCE=$nonce$([Environment]::NewLine)"
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $script:retryReleasePath `
        -Text $releaseText `
        -FullControlAccounts @($script:retryCurrentAccount) `
        -OwnerAccount $script:retryCurrentAccount
}}
Wait-TicketboxDirectoryMutationGuardLease `
    -Path '{str(retry_guarded_root).replace("'", "''")}' `
    -InstallDir '{str(retry_install_dir).replace("'", "''")}' `
    -ReadyPath '{str(retry_ready_path).replace("'", "''")}' `
    -ReleasePath '{str(retry_release_path).replace("'", "''")}' `
    -OwnerProcessId {os.getpid()} `
    -OwnerIdentity $ownerIdentity `
    -OnLeaseReady $releaseAfterReady `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
if (Test-Path -LiteralPath '{str(retry_intent_path).replace("'", "''")}') {{
    throw 'successful retry did not retire provisioning intent'
}}
if (Test-Path -LiteralPath '{str(retry_guarded_root / ".ticketbox-durable-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.tmp").replace("'", "''")}') {{
    throw 'successful retry did not retire marker staging artifact'
}}
Assert-TicketboxDataRootMarker `
    -DataRoot '{str(retry_guarded_root).replace("'", "''")}' `
    -InstallDir '{str(retry_install_dir).replace("'", "''")}'
""",
            encoding="utf-8-sig",
        )
        retry_result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", retry_harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert retry_result.returncode == 0, retry_result.stdout + retry_result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows holder entrypoint contract")
def test_holder_entrypoint_independently_rejects_wrong_parent_and_non_authoritative_root(
    tmp_path: Path,
) -> None:
    holder = PACKAGING / "hold_installer_lifecycle_lock.ps1"
    authoritative_root = Path(os.environ["COMMONPROGRAMFILES"]) / "Ticketbox"
    owner_started_high, owner_started_low = _windows_process_creation_filetime_parts(os.getpid())
    for engine in powershell_contract_engines():
        wrong_parent = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                holder,
                "-InstallerOwnerProcessId",
                "2147483647",
                "-InstallerOwnerStartedFileTimeHigh",
                "0",
                "-InstallerOwnerStartedFileTimeLow",
                "0",
                "-ExpectedLockDirectory",
                str(authoritative_root),
                "-RootValidatedPath",
                str(tmp_path / "wrong-parent-root-validated.ready"),
                "-ReadyPath",
                str(authoritative_root / "wrong-parent.ready"),
                "-ReleasePath",
                str(authoritative_root / "wrong-parent.release"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert wrong_parent.returncode != 0
        assert "生命周期锁 holder 不是当前安装器的直接子进程" in wrong_parent.stderr

        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                holder,
                "-InstallerOwnerProcessId",
                str(os.getpid()),
                "-InstallerOwnerStartedFileTimeHigh",
                str(owner_started_high),
                "-InstallerOwnerStartedFileTimeLow",
                str(owner_started_low),
                "-ExpectedLockDirectory",
                str(tmp_path / "not-common-program-files"),
                "-RootValidatedPath",
                str(tmp_path / "entry-root-validated.ready"),
                "-ReadyPath",
                str(tmp_path / "entry.ready"),
                "-ReleasePath",
                str(tmp_path / "entry.release"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert result.returncode != 0
        assert "Inno 与 PowerShell 解析出的机器生命周期根不一致" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows exact deletion contract")
def test_exact_deletion_defers_data_root_authority_marker_and_retries_only_empty_root(
    tmp_path: Path,
) -> None:
    safety = str(PACKAGING / "windows_installation_safety.ps1").replace("'", "''")
    for index, engine in enumerate(powershell_contract_engines()):
        base = ROOT / "backend" / "build" / f"exact-delete-{uuid.uuid4().hex}-{index}"
        data_root = base / "data"
        install_dir = base / "program"
        markerless_empty = base / "markerless-empty"
        markerless_nonempty = base / "markerless-nonempty"
        harness = tmp_path / f"exact-delete-{index}.ps1"

        def literal(path: Path) -> str:
            return str(path).replace("'", "''")

        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{safety}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
New-Item -ItemType Directory -Force -Path '{literal(data_root)}', '{literal(install_dir)}' | Out-Null
Initialize-TicketboxDataRootMarker `
    -DataRoot '{literal(data_root)}' `
    -InstallDir '{literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$markerPath = Get-TicketboxDataRootMarkerPath '{literal(data_root)}'
Set-Content -LiteralPath (Join-Path '{literal(data_root)}' 'payload.txt') -Value 'payload'
$markerLease = [System.IO.File]::Open(
    $markerPath,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::Read
)
$interrupted = $false
try {{
    try {{
        Remove-TicketboxDataRootExact `
            -Path '{literal(data_root)}' `
            -DeferredRootLeafName $script:TicketboxDataRootMarkerName
    }}
    catch {{ $interrupted = $true }}
}}
finally {{ $markerLease.Dispose() }}
if (-not $interrupted) {{ throw 'locked authority marker did not interrupt exact deletion' }}
$remaining = @(Get-ChildItem -LiteralPath '{literal(data_root)}' -Force)
if ($remaining.Count -ne 1 -or $remaining[0].Name -cne $script:TicketboxDataRootMarkerName) {{
    throw "data-root authority marker was not deleted last: $($remaining.Name -join ',')"
}}
Assert-TicketboxDataRootDeletionSafety `
    -DataRoot '{literal(data_root)}' `
    -RegisteredDataRoot '{literal(data_root)}' `
    -InstallDir '{literal(install_dir)}' | Out-Null
Remove-TicketboxDataRootExact `
    -Path '{literal(data_root)}' `
    -DeferredRootLeafName $script:TicketboxDataRootMarkerName
if (Test-Path -LiteralPath '{literal(data_root)}') {{ throw 'deferred data-root retry did not converge' }}
New-Item -ItemType Directory -Path '{literal(markerless_empty)}' | Out-Null
$missingMarkerRejected = $false
try {{
    Assert-TicketboxDataRootDeletionSafety `
        -DataRoot '{literal(markerless_empty)}' `
        -RegisteredDataRoot '{literal(markerless_empty)}' `
        -InstallDir '{literal(install_dir)}' | Out-Null
}}
catch {{ $missingMarkerRejected = $true }}
if (-not $missingMarkerRejected) {{ throw 'markerless root was accepted without retry authority' }}
Assert-TicketboxDataRootDeletionSafety `
    -DataRoot '{literal(markerless_empty)}' `
    -RegisteredDataRoot '{literal(markerless_empty)}' `
    -InstallDir '{literal(install_dir)}' `
    -AllowMarkerlessEmptyRoot | Out-Null
Remove-TicketboxDataRootExact -Path '{literal(markerless_empty)}'
New-Item -ItemType Directory -Path '{literal(markerless_nonempty)}' | Out-Null
Set-Content -LiteralPath (Join-Path '{literal(markerless_nonempty)}' 'unknown.txt') -Value 'keep'
$nonemptyRejected = $false
try {{
    Assert-TicketboxDataRootDeletionSafety `
        -DataRoot '{literal(markerless_nonempty)}' `
        -RegisteredDataRoot '{literal(markerless_nonempty)}' `
        -InstallDir '{literal(install_dir)}' `
        -AllowMarkerlessEmptyRoot | Out-Null
}}
catch {{ $nonemptyRejected = $true }}
if (-not $nonemptyRejected) {{ throw 'markerless non-empty root was accepted as deletion continuation' }}
Remove-TicketboxDataRootExact -Path '{literal(markerless_nonempty)}'
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        shutil.rmtree(base, ignore_errors=True)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DataRoot handle lease contract")
def test_data_root_guard_lease_blocks_cross_process_root_and_ancestor_rename(
    tmp_path: Path,
) -> None:
    safety = str(PACKAGING / "windows_installation_safety.ps1").replace("'", "''")
    lifecycle = str(PACKAGING / "windows_lifecycle_lock.ps1").replace("'", "''")
    engines = powershell_contract_engines()

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
. '{lifecycle}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
function Assert-TicketboxProtectedDirectoryAcl {{
    param($Path, $FullControlAccounts, $OwnerAccount)
}}
function Assert-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}}
Wait-TicketboxDirectoryMutationGuardLease `
    -Path '{str(data_root).replace("'", "''")}' `
    -InstallDir '{str(protocol / "program").replace("'", "''")}' `
    -ReadyPath '{str(ready).replace("'", "''")}' `
    -ReleasePath '{str(release).replace("'", "''")}' `
    -OwnerProcessId {os.getpid()} `
    -OwnerIdentity (Get-TicketboxProcessIdentity -ProcessId {os.getpid()}) `
    -OnLeaseReady {{ }} `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
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
            ready_match = re.fullmatch(
                rf"STATE=holding\nOWNER_PID={os.getpid()}\nHOLDER_PID=(\d+)\n"
                rf"HOLDER_STARTED_FILETIME_HIGH=(\d+)\n"
                rf"HOLDER_STARTED_FILETIME_LOW=(\d+)\n"
                rf"NONCE=([0-9a-f]{{64}})\n",
                ready.read_text(encoding="utf-8"),
            )
            assert ready_match is not None
            assert int(ready_match.group(1)) == process.pid
            assert (int(ready_match.group(2)), int(ready_match.group(3))) == (
                _windows_process_creation_filetime_parts(process.pid)
            )
            release.write_bytes(
                (
                    f"STATE=release\r\nOWNER_PID={os.getpid()}\r\n"
                    f"NONCE={ready_match.group(4)}\r\n"
                ).encode()
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
    lifecycle_receipt = PACKAGING / "windows_lifecycle_receipt.ps1"
    backend_bootstrap = PACKAGING / "windows_backend_bootstrap.ps1"
    database_safety = PACKAGING / "windows_database_safety.ps1"
    release_config_script = PACKAGING / "windows_release_config.ps1"
    uninstall = _read("uninstall_bundled_services.ps1")
    process_guard = uninstall[
        uninstall.index("function Assert-TicketboxRuntimeProcessesStoppedForDataDeletion") : uninstall.index(
            "function Assert-TicketboxBackendPortStoppedForDataDeletion"
        )
    ]
    installer_state_cleanup = uninstall[
        uninstall.index("function Get-TicketboxInstallerStateDataDeletionSnapshot") : uninstall.index(
            'Write-Host "=== 小票夹服务卸载 ==="'
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
    missing_owner_channel_config_path = base / "windows-release-config-missing-owner-channel.json"
    missing_owner_channel_config = dict(dynamic_config)
    missing_owner_channel_config.pop("owner_recovery_channel")
    missing_owner_channel_config_path.write_text(
        json.dumps(missing_owner_channel_config, ensure_ascii=False),
        encoding="utf-8",
    )
    invalid_owner_channel_config_path = base / "windows-release-config-invalid-owner-channel.json"
    invalid_owner_channel_config = dict(dynamic_config)
    invalid_owner_channel_config["owner_recovery_channel"] = "MANAGED_HOST"
    invalid_owner_channel_config_path.write_text(
        json.dumps(invalid_owner_channel_config, ensure_ascii=False),
        encoding="utf-8",
    )

    def literal(path: Path) -> str:
        return str(path).replace("'", "''")

    command = f"""
$ErrorActionPreference = 'Stop'
. '{literal(lifecycle)}'
. '{literal(safety)}'
. '{literal(lifecycle_lock)}'
. '{literal(lifecycle_receipt)}'
. '{literal(backend_bootstrap)}'
. '{literal(database_safety)}'
. '{literal(release_config_script)}'
$BackendExe = 'C:\\Ticketbox\\program\\ticketbox-backend.exe'
$ShawlExe = 'C:\\Ticketbox\\shawl\\shawl.exe'
$PgBin = 'C:\\Ticketbox\\pg\\bin'
$PgCtl = Join-Path $PgBin 'pg_ctl.exe'
{process_guard}
{installer_state_cleanup}
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
$rejected = $false
try {{ Read-TicketboxWindowsReleaseConfig '{literal(missing_owner_channel_config_path)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'current release config without owner recovery capability was accepted' }}
$legacyConfig = Read-TicketboxWindowsReleaseConfig `
    '{literal(missing_owner_channel_config_path)}' `
    -AllowLegacyMissingOwnerRecoveryChannel
if ($legacyConfig.owner_recovery_channel -cne 'managed_host') {{ throw 'legacy Windows capability was not normalized' }}
$rejected = $false
try {{ Read-TicketboxWindowsReleaseConfig '{literal(invalid_owner_channel_config_path)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'non-canonical owner recovery capability was accepted in Windows release config' }}
$localUrl = Assert-TicketboxLocalDatabaseUrl -DatabaseUrl 'postgresql+psycopg://ticketbox:secret@127.0.0.1:5432/ticketbox' -PgPort 5432
if ($localUrl -ne 'postgresql://ticketbox:secret@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256') {{ throw 'local DB URL was not hardened' }}
$connection = Get-TicketboxLocalDatabaseConnection -DatabaseUrl $localUrl -PgPort 5432 -ExpectedDatabase ticketbox -ExpectedRole ticketbox
if ($connection.DatabaseUrl -match 'secret' -or $connection.Password -ne 'secret' -or $connection.DatabaseUrl -notmatch 'require_auth=scram-sha-256') {{ throw 'database password or authentication contract was not isolated' }}
$rejected = $false
try {{ Assert-TicketboxLocalDatabaseUrl -DatabaseUrl 'postgresql://ticketbox:secret@example.com:5432/ticketbox' -PgPort 5432 | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'external DB URL accepted' }}
$rejected = $false
try {{ Assert-TicketboxLocalDatabaseUrl -DatabaseUrl 'postgresql://ticketbox:secret@127.0.0.1:5432/ticketbox?hostaddr=203.0.113.7' -PgPort 5432 | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'libpq target override accepted' }}
$rejected = $false
try {{ Assert-TicketboxLocalDatabaseUrl -DatabaseUrl 'postgresql://ticketbox:secret@127.0.0.1:5432/ticketbox?require_auth=none' -PgPort 5432 | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'libpq authentication downgrade accepted' }}
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
$script:testServiceImagePath = '"C:\\Ticketbox\\shawl.exe" run --name TicketboxBackend --stop-timeout 25000 --restart --kill-process-tree --restart-delay 5000 --cwd "D:\\Ticketbox Data\\app" --log-dir "D:\\Ticketbox Data\\app\\logs" --env "TICKETBOX_DATA_DIR=D:\\Ticketbox Data\\app" --env "PG_DUMP_PATH=C:\\Ticketbox\\pg_dump.exe" --env "PG_RESTORE_PATH=C:\\Ticketbox\\pg_restore.exe" --env "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH=D:\\Ticketbox Data\\bootstrap-exposure-recovery-pending" --env "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH=D:\\Ticketbox Data\\installer-runtime-recovery-pending" --env "TICKETBOX_DATA_ROOT_MARKER_PATH=C:\\ProgramData\\TicketboxRuntimeBinding\\data-root\\.ticketbox-data-root.json" --env "TICKETBOX_DATA_VOLUME_IDENTITY=\\\\?\\VOLUME{{01234567-89AB-CDEF-0123-456789ABCDEF}}\\\\" --env "TICKETBOX_OWNER_RECOVERY_CHANNEL=managed_host" -- "C:\\Ticketbox\\backend.exe"'
$shawlArgs = @{{
    Name = 'TicketboxBackend'; ExpectedExecutable = 'C:\\Ticketbox\\shawl.exe'; ExpectedServiceName = 'TicketboxBackend'
    ExpectedCwd = 'D:\\Ticketbox Data\\app'; ExpectedPayload = 'C:\\Ticketbox\\backend.exe'; ExpectedDependency = 'TicketboxPg'
    ExpectedLogDir = 'D:\\Ticketbox Data\\app\\logs'; ExpectedPgDumpPath = 'C:\\Ticketbox\\pg_dump.exe'
    ExpectedPgRestorePath = 'C:\\Ticketbox\\pg_restore.exe'; ExpectedBootstrapRecoveryGuardPath = 'D:\\Ticketbox Data\\bootstrap-exposure-recovery-pending'
    ExpectedInstallerRecoveryGuardPath = 'D:\\Ticketbox Data\\installer-runtime-recovery-pending'
    ExpectedDataRootMarkerPath = 'C:\\ProgramData\\TicketboxRuntimeBinding\\data-root\\.ticketbox-data-root.json'
    ExpectedDataVolumeIdentity = '\\\\?\\VOLUME{{01234567-89AB-CDEF-0123-456789ABCDEF}}\\'
    ExpectedOwnerRecoveryChannel = 'managed_host'
    ExpectedStopTimeoutMs = 25000; ExpectedRestartDelayMs = 5000
}}
Assert-TicketboxShawlServiceCommand @shawlArgs
$validShawlImagePath = $script:testServiceImagePath
$legacyShawlImagePath = $validShawlImagePath.Replace(' --env "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH=D:\\Ticketbox Data\\installer-runtime-recovery-pending"', '')
$script:testServiceImagePath = $legacyShawlImagePath
$rejected = $false
try {{ Assert-TicketboxShawlServiceCommand @shawlArgs }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'legacy Shawl command bypassed the explicit compatibility switch' }}
$shawlArgs.AllowMissingInstallerRecoveryGuard = $true
Assert-TicketboxShawlServiceCommand @shawlArgs
$shawlArgs.Remove('AllowMissingInstallerRecoveryGuard')
$legacyRuntimeImagePath = $validShawlImagePath.Replace(
    ' --env "TICKETBOX_DATA_ROOT_MARKER_PATH=C:\\ProgramData\\TicketboxRuntimeBinding\\data-root\\.ticketbox-data-root.json"',
    ''
)
$legacyRuntimeImagePath = $legacyRuntimeImagePath.Replace(
    ' --env "TICKETBOX_DATA_VOLUME_IDENTITY=\\\\?\\VOLUME{{01234567-89AB-CDEF-0123-456789ABCDEF}}\\\\"',
    ''
)
$script:testServiceImagePath = $legacyRuntimeImagePath
$rejected = $false
try {{ Assert-TicketboxShawlServiceCommand @shawlArgs }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'legacy runtime path bypassed the explicit compatibility switch' }}
$shawlArgs.AllowMissingRuntimeDataAuthority = $true
Assert-TicketboxShawlServiceCommand @shawlArgs
$shawlArgs.Remove('AllowMissingRuntimeDataAuthority')
$legacyOwnerRecoveryImagePath = $validShawlImagePath.Replace(
    ' --env "TICKETBOX_OWNER_RECOVERY_CHANNEL=managed_host"',
    ''
)
$script:testServiceImagePath = $legacyOwnerRecoveryImagePath
$rejected = $false
try {{ Assert-TicketboxShawlServiceCommand @shawlArgs }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'missing owner recovery capability bypassed the compatibility switch' }}
$shawlArgs.AllowMissingOwnerRecoveryChannel = $true
Assert-TicketboxShawlServiceCommand @shawlArgs
$shawlArgs.Remove('AllowMissingOwnerRecoveryChannel')
$script:testServiceImagePath = $validShawlImagePath.Replace(
    'TICKETBOX_OWNER_RECOVERY_CHANNEL=managed_host',
    'TICKETBOX_OWNER_RECOVERY_CHANNEL=operator'
)
$rejected = $false
try {{ Assert-TicketboxShawlServiceCommand @shawlArgs }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'wrong owner recovery capability was accepted' }}
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
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$protectedLockRoot = Join-Path '{literal(base)}' 'protected-lock-root'
$malformedLockTarget = Join-Path '{literal(base)}' 'malformed-lock-target'
$malformedOperationLock = Join-Path $protectedLockRoot 'installer-operation.lock'
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path $protectedLockRoot `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
New-Item -ItemType Directory -Path $malformedLockTarget -Force | Out-Null
New-Item -ItemType Junction -Path $malformedOperationLock -Target $malformedLockTarget | Out-Null
if (-not (Test-TicketboxExclusiveFileLockHeld -Path $malformedOperationLock)) {{
    throw 'malformed operation lock was treated as safely absent'
}}
$rejected = $false
try {{
    $malformedLease = Enter-TicketboxProtectedExclusiveFileLock `
        -Path $malformedOperationLock `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
    $malformedLease.Dispose()
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'operation lock reparse point was followed' }}
if (-not (Test-Path -LiteralPath $malformedLockTarget -PathType Container)) {{
    throw 'operation lock rejection touched the reparse target'
}}
[System.IO.Directory]::Delete($malformedOperationLock)
$originalNoFollowClassifier = ${{function:Get-TicketboxPathEntryKindNoFollow}}
try {{
    Set-Item -LiteralPath Function:Get-TicketboxPathEntryKindNoFollow -Value {{
        param([string]$Path)
        throw 'simulated sharing violation during no-follow classification'
    }}
    if (-not (Test-TicketboxExclusiveFileLockHeld -Path $malformedOperationLock)) {{
        throw 'indeterminate operation lock classification was treated as absent'
    }}
}}
finally {{
    Set-Item -LiteralPath Function:Get-TicketboxPathEntryKindNoFollow -Value $originalNoFollowClassifier
}}
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
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Initialize-TicketboxDataRootMarker `
    -DataRoot '{literal(data_root)}' `
    -InstallDir '{literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$safe = Assert-TicketboxDataRootDeletionSafety -DataRoot '{literal(data_root)}' -RegisteredDataRoot '{literal(data_root)}' -InstallDir '{literal(install_dir)}'
if ($safe -ne [System.IO.Path]::GetFullPath('{literal(data_root)}')) {{ throw 'safe root mismatch' }}
$rejected = $false
try {{ Assert-TicketboxDataRootDeletionSafety -DataRoot '{literal(data_root)}' -RegisteredDataRoot '' -InstallDir '{literal(install_dir)}' | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'missing registration was accepted without explicit recovery mode' }}
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxLifecycleReceiptAclAccounts = @($currentAccount)
$script:TicketboxLifecycleReceiptOwnerAccount = $currentAccount
$DataRoot = Join-Path '{literal(base)}' 'state-data'
$InstallDir = Join-Path '{literal(base)}' 'state-program'
$machineRoot = Join-Path '{literal(base)}' 'state-machine'
$InstallerState = Join-Path $machineRoot 'installer-state'
$OwnerBootstrapPath = Join-Path $InstallerState 'owner-bootstrap.txt'
$OwnerHandoffPendingPath = Join-Path $InstallerState 'owner-handoff-pending'
$RecoveryRequiredPath = Join-Path $InstallerState 'installer-recovery-required.json'
$DeleteDataIntentPath = Join-Path $InstallerState 'delete-data-in-progress.json'
New-Item -ItemType Directory -Path $DataRoot, $InstallDir, $machineRoot -Force | Out-Null
Set-TicketboxExactDirectoryAcl `
    -Path $machineRoot `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Initialize-TicketboxDataRootMarker `
    -DataRoot $DataRoot `
    -InstallDir $InstallDir `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Initialize-TicketboxInstallerStateDirectory `
    -Path $InstallerState `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
function Read-TicketboxOwnerHandoffArtifact([string]$Path) {{
    Assert-TicketboxProtectedDirectoryAcl `
        -Path (Split-Path -Parent $Path) `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
    Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount `
        -MaximumBytes 16384
}}
function Assert-TicketboxOwnerHandoffArtifact([string]$Path) {{
    Read-TicketboxOwnerHandoffArtifact $Path | Out-Null
}}
$credential = 'owner-credential-for-delete-data'
$credentialHash = Get-TicketboxOwnerHandoffTextSha256 $credential
$ownerStarted = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString(
    'yyyy-MM-ddTHH:mm:ss.fffffffZ',
    [System.Globalization.CultureInfo]::InvariantCulture
)
$handoff = [string]::Join([Environment]::NewLine, @(
    'SCHEMA=ticketbox-owner-handoff-v2',
    'STATE=pending',
    "GENERATION=$([Guid]::NewGuid().ToString('D'))",
    "INSTALLATION_ID=$(Get-TicketboxOwnerHandoffInstallationId)",
    "CREDENTIAL_SHA256=$credentialHash",
    "INSTALLER_OWNER_PID=$PID",
    "INSTALLER_OWNER_STARTED_UTC=$ownerStarted"
)) + [Environment]::NewLine
Write-TicketboxProtectedUtf8FileDurable `
    -Path $OwnerBootstrapPath `
    -Text $credential `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Write-TicketboxProtectedUtf8FileDurable `
    -Path $OwnerHandoffPendingPath `
    -Text $handoff `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
[System.IO.File]::WriteAllBytes($OwnerHandoffPendingPath, [byte[]](0xC3, 0x28))
$invalidOwnerMarkerRejected = $false
try {{ Read-TicketboxOwnerHandoffRecord | Out-Null }} catch {{ $invalidOwnerMarkerRejected = $true }}
if (-not $invalidOwnerMarkerRejected -or
    -not (Test-Path -LiteralPath $OwnerHandoffPendingPath -PathType Leaf)) {{
    throw 'invalid UTF-8 owner marker was accepted or destroyed'
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path $OwnerHandoffPendingPath `
    -Text $handoff `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
Write-TicketboxProtectedUtf8FileDurable `
    -Path $OwnerBootstrapPath `
    -Text ('x' * 16385) `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
$oversizedCredentialRejected = $false
try {{
    $ownerRecord = Read-TicketboxOwnerHandoffRecord
    Assert-TicketboxOwnerHandoffCredential $ownerRecord
}}
catch {{ $oversizedCredentialRejected = $true }}
if (-not $oversizedCredentialRejected -or
    -not (Test-Path -LiteralPath $OwnerBootstrapPath -PathType Leaf)) {{
    throw 'oversized owner credential was accepted or destroyed'
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path $OwnerBootstrapPath `
    -Text $credential `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
Write-TicketboxInstallerRecoveryMarker `
    -Path $RecoveryRequiredPath `
    -InstallDir $InstallDir `
    -DataRoot $DataRoot `
    -Reason 'delete-data retirement test'
Assert-TicketboxInstallerStateForDataDeletion
$unknownState = Join-Path $InstallerState 'unknown-state.txt'
Write-TicketboxProtectedUtf8FileDurable `
    -Path $unknownState `
    -Text 'unknown' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$unknownRejected = $false
try {{ Assert-TicketboxInstallerStateForDataDeletion }} catch {{ $unknownRejected = $true }}
if (-not $unknownRejected) {{ throw 'unknown installer state was accepted for data deletion' }}
Remove-TicketboxProtectedUtf8Artifact `
    -Path $unknownState `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Assert-TicketboxInstallerStateForDataDeletion
$danglingChildTarget = Join-Path $machineRoot 'dangling-child-target'
Remove-TicketboxProtectedUtf8Artifact `
    -Path $OwnerHandoffPendingPath `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
New-Item -ItemType Directory -Path $danglingChildTarget | Out-Null
New-Item -ItemType Junction -Path $OwnerHandoffPendingPath -Target $danglingChildTarget | Out-Null
Remove-Item -LiteralPath $danglingChildTarget -Recurse -Force
$danglingChildRejected = $false
try {{ Assert-TicketboxInstallerStateForDataDeletion }}
catch {{
    if ($_.Exception.Message -notlike 'installer-state 已知状态不是普通文件*') {{ throw }}
    $danglingChildRejected = $true
}}
if (-not $danglingChildRejected) {{ throw 'dangling known installer-state child was accepted' }}
[System.IO.Directory]::Delete($OwnerHandoffPendingPath)
Write-TicketboxProtectedUtf8FileDurable `
    -Path $OwnerHandoffPendingPath `
    -Text $handoff `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Remove-TicketboxProtectedUtf8Artifact `
    -Path $OwnerHandoffPendingPath `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$unboundCredentialRejected = $false
try {{ Assert-TicketboxInstallerStateForDataDeletion }} catch {{ $unboundCredentialRejected = $true }}
if (-not $unboundCredentialRejected -or
    -not (Test-Path -LiteralPath $OwnerBootstrapPath -PathType Leaf)) {{
    throw 'unbound current owner credential was accepted or destroyed before data deletion'
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path $OwnerHandoffPendingPath `
    -Text $handoff `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Assert-TicketboxInstallerStateForDataDeletion
Remove-TicketboxDataRootExact -Path $DataRoot
Remove-TicketboxInstallerStateAfterDataDeletion
if ((Test-Path -LiteralPath $DataRoot) -or (Test-Path -LiteralPath $InstallerState)) {{
    throw 'delete-data retirement left data or installer state behind'
}}
$danglingStateTarget = Join-Path $machineRoot 'dangling-state-target'
New-Item -ItemType Directory -Path $danglingStateTarget | Out-Null
New-Item -ItemType Junction -Path $InstallerState -Target $danglingStateTarget | Out-Null
Remove-Item -LiteralPath $danglingStateTarget -Recurse -Force
$danglingStateRejected = $false
try {{ Assert-TicketboxInstallerStateForDataDeletion }}
catch {{
    if ($_.Exception.Message -notlike 'installer-state 不是普通目录*') {{ throw }}
    $danglingStateRejected = $true
}}
if (-not $danglingStateRejected) {{ throw 'dangling installer-state root was accepted' }}
[System.IO.Directory]::Delete($InstallerState)
$DataRoot = '{literal(data_root)}'
$InstallDir = '{literal(install_dir)}'
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
    engines = powershell_contract_engines()
    behavior_script = base / "installer-safety-behavior.ps1"
    behavior_script.write_text(command, encoding="utf-8-sig")
    try:
        for engine in engines:
            shutil.rmtree(data_root, ignore_errors=True)
            data_root.mkdir()
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

    assert '$DataRootGuardScript = Join-Path $ScriptDir "hold_data_root_mutation_guard.ps1"' in build
    assert '$PrepareScript = Join-Path $ScriptDir "prepare_bundled_upgrade.ps1"' in build
    assert '$ServiceContractScript = Join-Path $ScriptDir "windows_service_contract.ps1"' in build
    assert '$LifecycleScript = Join-Path $ScriptDir "windows_service_lifecycle.ps1"' in build
    assert '$DatabaseScript = Join-Path $ScriptDir "windows_bundled_database.ps1"' in build
    assert (
        '$C07HeartbeatAuthorityScript = Join-Path $ScriptDir '
        '"windows_c07_heartbeat_authority.ps1"'
    ) in build
    assert (
        '$C07HeartbeatHelperScript = Join-Path $ScriptDir '
        '"windows_c07_heartbeat_helper.ps1"'
    ) in build
    assert '$BackendBootstrapScript = Join-Path $ScriptDir "windows_backend_bootstrap.ps1"' in build
    assert '$ReleaseConfigScript = Join-Path $ScriptDir "windows_release_config.ps1"' in build
    assert 'Assert-File $DataRootGuardScript "Windows DataRoot guard holder 脚本"' in build
    assert 'Assert-File $PrepareScript "升级前预检脚本"' in build
    assert 'Assert-File $ServiceContractScript "Windows 服务命令契约脚本"' in build
    assert 'Assert-File $LifecycleScript "Windows 服务生命周期脚本"' in build
    assert (
        'Assert-File $C07HeartbeatAuthorityScript '
        '"Windows C07 shared heartbeat authority module"'
    ) in build
    assert (
        'Assert-File $C07HeartbeatHelperScript '
        '"Windows C07 durable heartbeat helper"'
    ) in build
    assert 'Assert-File $BackendBootstrapScript "Windows 后端就绪/bootstrap 脚本"' in build
