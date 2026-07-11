from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def test_receipt_replaces_caller_controlled_backup_bypass() -> None:
    install = _read("install_bundled_services.ps1")
    prepare = _read("prepare_bundled_upgrade.ps1")
    flow = _read("ticketbox-installer-flow.isph")
    receipt = _read("windows_lifecycle_receipt.ps1")

    assert "[switch]$SkipPreUpgradeBackup" not in install
    assert "SkipPreUpgradeBackup" not in flow
    assert "直接运行安装脚本不能提交或伪造 Inno 生命周期回执" in install
    assert "$PreUpgradeBackupAlreadyCompleted = [bool]$lifecycleReceipt.backup_completed" in install
    assert "InstallerOwnerProcessId" in receipt
    assert "Assert-TicketboxProtectedLifecycleReceipt" in receipt
    assert "Set-TicketboxExactFileAcl" in receipt
    receipt_writer = receipt[
        receipt.index("function Write-TicketboxLifecycleReceipt") : receipt.index(
            "function Read-TicketboxLifecycleReceipt"
        )
    ]
    assert "Write-TicketboxUtf8FileDurable" in receipt_writer
    assert "[System.IO.File]::WriteAllText" not in receipt_writer
    assert "Write-TicketboxLifecycleReceipt" in prepare
    assert "files_may_have_been_replaced" in receipt
    assert "AllowPreviousInstallerOwnerProcessId" in receipt
    assert "Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced" in receipt
    assert "Set-TicketboxLifecycleReceiptInstallCompleted" in receipt
    assert "Set-TicketboxLifecycleReceiptInstallerOwner" in receipt
    assert "Set-TicketboxLifecycleReceiptDeferredBackup" in receipt
    assert "Set-TicketboxLifecycleReceiptProgramFilesInstalledBackupPending" in receipt
    assert "Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending" in receipt
    assert "Set-TicketboxLifecycleReceiptDeferredBackupCompleted" in receipt
    assert "temporary_pg_service_cleanup_pending" in receipt
    assert "temporary_pg_service_name" in receipt
    assert "temporary_pg_service_account" in receipt
    assert "temporary_pg_service_data_root" in receipt
    assert "Remove-TicketboxCompletedLifecycleReceipt" in receipt
    assert "拒绝静默覆盖旧的运行态或备份证据" in receipt
    assert 'recovery_action = "rerun_installer_repair"' in receipt


def test_completed_stale_receipt_cannot_reuse_previous_backup_mutation() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    install = _read("install_bundled_services.ps1")
    flow = _read("ticketbox-installer-flow.isph")

    stale_start = prepare.index("$staleReceipt = Read-TicketboxLifecycleReceipt")
    completed_check = prepare.index("if ([bool]$staleReceipt.install_completed)", stale_start)
    invalidate = prepare.index("Remove-TicketboxCompletedLifecycleReceipt", completed_check)
    initialize_current = prepare.index("Initialize-TicketboxInstalledReleaseConfiguration", invalidate)
    reset_backup = prepare.index("$backupCompleted = $false", initialize_current)
    write_new_receipt = prepare.index("Write-TicketboxLifecycleReceipt", reset_backup)
    completed_branch = prepare[
        completed_check : prepare.index(
            'elseif ([string]$staleReceipt.preparation_stage -in @(',
            completed_check,
        )
    ]

    assert completed_check < invalidate < initialize_current < reset_backup < write_new_receipt
    assert "backup_completed" not in completed_branch
    assert "return" not in completed_branch
    assert "Set-TicketboxLifecycleReceiptInstallCompleted" not in install
    receipt_read = install.index("Read-TicketboxLifecycleReceipt")
    prepared_transition = install.index('if ([string]$lifecycleReceipt.preparation_stage -eq "prepared")')
    repair_resume = install.index(
        'elseif ([string]$lifecycleReceipt.preparation_stage -ne "files_may_have_been_replaced")'
    )
    assert receipt_read < prepared_transition < repair_resume
    post_install = flow.index("if CurStep = ssPostInstall")
    service_install = flow.index("if not RunPowerShellChecked", post_install)
    durable_commit = flow.index("Ticketbox installer lifecycle commit", service_install)
    host_commit = flow.index("LifecycleInstallCompleted := True", durable_commit)
    assert service_install < durable_commit < host_commit
    assert "-CommitCompletedInstall" in flow[service_install:host_commit]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL and PowerShell contract")
def test_persistent_installation_identity_roundtrips_and_rejects_floor_rollback(
    tmp_path: Path,
) -> None:
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"

    for index, engine in enumerate(engines):
        root = tmp_path / f"identity-{index}"
        data_root = root / "data"
        install_dir = root / "program"
        data_root.mkdir(parents=True)
        install_dir.mkdir()
        manifest = root / "BUILD_PROVENANCE.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "artifact_type": "ticketbox-windows-installer-inputs",
                    "build_mode": "installer-build",
                    "backend": {"version": "7.8.9"},
                    "postgresql": {"major": 17},
                    "compiler_defines": ["/DTargetPgMajor=17"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        harness = root / "identity-roundtrip.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_installation_safety.ps1')}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxPersistentInstallationIdentityAclAccounts = @($currentAccount)
$script:TicketboxPersistentInstallationIdentityOwnerAccount = $currentAccount
$validatedManifest = Read-TicketboxInstalledBuildManifest `
    -Path '{_literal(manifest)}' `
    -ExpectedPgMajor 17
if ($validatedManifest.BackendVersion -cne '7.8.9' -or $validatedManifest.PgMajor -ne 17) {{
    throw 'installed build manifest validation mismatch'
}}
$majorMismatchRejected = $false
try {{ Read-TicketboxInstalledBuildManifest -Path '{_literal(manifest)}' -ExpectedPgMajor 18 | Out-Null }}
catch {{ $majorMismatchRejected = $true }}
if (-not $majorMismatchRejected) {{ throw 'installed build manifest accepted mismatched PG major' }}
$first = Write-TicketboxPersistentInstallationIdentity `
    -DataRoot '{_literal(data_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -PgServiceName 'ConfiguredPg' `
    -BackendServiceName 'ConfiguredBackend' `
    -BuildManifestPath '{_literal(manifest)}'
$second = Write-TicketboxPersistentInstallationIdentity `
    -DataRoot '{_literal(data_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -PgServiceName 'ConfiguredPg' `
    -BackendServiceName 'ConfiguredBackend' `
    -BuildManifestPath '{_literal(manifest)}'
if ($first.BackendVersionFloor -cne '7.8.9' -or
    $first.InstallationId -cne $second.InstallationId -or
    $first.BuildManifestSha256 -cnotmatch '^[0-9A-F]{{64}}$' -or
    $first.PgServiceName -cne 'ConfiguredPg' -or
    $first.BackendServiceName -cne 'ConfiguredBackend') {{
    throw 'persistent installation identity roundtrip mismatch'
}}
$rollbackManifest = Get-Content -LiteralPath '{_literal(manifest)}' -Encoding UTF8 -Raw | ConvertFrom-Json
$rollbackManifest.backend.version = '7.8.8'
$rollbackManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath '{_literal(manifest)}' -Encoding UTF8
$rollbackRejected = $false
try {{
    Write-TicketboxPersistentInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -PgServiceName 'ConfiguredPg' `
        -BackendServiceName 'ConfiguredBackend' `
        -BuildManifestPath '{_literal(manifest)}' | Out-Null
}}
catch {{ $rollbackRejected = $true }}
if (-not $rollbackRejected) {{ throw 'persistent version floor rollback was accepted' }}
$identityPath = Get-TicketboxPersistentInstallationIdentityPath '{_literal(data_root)}'
Set-Content -LiteralPath $identityPath -Encoding UTF8 -Value 'broken'
$corruptionRejected = $false
try {{ Read-TicketboxPersistentInstallationIdentity '{_literal(data_root)}' | Out-Null }}
catch {{ $corruptionRejected = $true }}
if (-not $corruptionRejected) {{ throw 'corrupt persistent installation identity was accepted' }}
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
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_stale_recovery_validates_exact_service_contract_before_mutation() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    existing_mode = prepare.index('if ($mode -ne "fresh_install")')
    machine_binding = prepare.index("Assert-TicketboxRegisteredDataRootBinding", existing_mode)
    legacy_marker = prepare.index("Initialize-TicketboxDataRootMarker", machine_binding)
    assert existing_mode < machine_binding < legacy_marker
    contract_guard = prepare[
        prepare.index("function Assert-TicketboxPreparedServiceContracts") : prepare.index(
            "function Test-PgDataProcessReady"
        )
    ]
    assert "Assert-ExpectedServiceConfiguration `" in contract_guard
    assert "-Name $PgServiceName" in contract_guard
    assert "-Name $BackendServiceName" in contract_guard
    assert contract_guard.count("Assert-TicketboxRuntimeAbsent `") == 2
    assert "-RuntimePort $PgPort" in contract_guard
    assert "-ExpectedRuntimeExecutables @($PgCtl" in contract_guard
    assert "-RuntimePort $BackendPort" in contract_guard
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in contract_guard

    exact_contract = prepare[
        prepare.index("function Assert-ExpectedServiceConfiguration") : prepare.index(
            "function Assert-TicketboxPreparedServiceContracts"
        )
    ]
    assert "Assert-TicketboxServiceAccount" in exact_contract
    assert "Assert-TicketboxPgServiceCommand" in exact_contract
    assert "Assert-TicketboxShawlServiceCommand" in exact_contract

    recover_start = prepare.index("if ($RecoverPreparedInstall)")
    recover_end = prepare.index("return", recover_start)
    recover_branch = prepare[recover_start:recover_end]
    stale_start = prepare.index("if ([bool]$staleReceipt.install_completed)")
    stale_end = prepare.index("return", stale_start)
    stale_branch = prepare[stale_start:stale_end]
    for recovery in (recover_branch, stale_branch):
        guard = recovery.index("Assert-TicketboxPreparedServiceContracts")
        mutation = recovery.index("Invoke-TicketboxPreparedInstallRecovery")
        assert guard < mutation
        assert "-AllowRepairableAccount" not in recovery


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL and PowerShell contract")
def test_lifecycle_receipt_roundtrip_is_bound_to_install_inputs(tmp_path: Path) -> None:
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    config = json.loads(_read("windows-release-config.json"))

    for index, engine in enumerate(engines):
        root = tmp_path / f"receipt-{index}"
        data_root = root / "data"
        install_dir = root / "program"
        backup_root = data_root / "installer-backups"
        backup_root.mkdir(parents=True)
        backup_path = backup_root / "pre-upgrade.dump"
        backup_path.write_bytes(b"verified-backup")
        install_dir.mkdir(parents=True)
        receipt_path = root / "installer-lifecycle-receipt.json"
        config_path = root / "release.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        harness = root / "receipt-behavior.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_installation_safety.ps1')}'
. '{_literal(PACKAGING / 'windows_release_config.ps1')}'
. '{_literal(PACKAGING / 'windows_lifecycle_receipt.ps1')}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxLifecycleReceiptAclAccounts = @($currentAccount)
$script:TicketboxLifecycleReceiptOwnerAccount = $currentAccount
function Get-TicketboxLifecycleLockPath {{ return '{_literal(root / "installer-lifecycle.lock")}' }}
Set-TicketboxExactFileAcl `
    -Path '{_literal(backup_path)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$freshMode = Get-TicketboxPreparedInstallMode $false $false $false $false $false
$preservedMode = Get-TicketboxPreparedInstallMode $false $false $true $true $false
$repairMode = Get-TicketboxPreparedInstallMode $true $false $true $true $false
$upgradeMode = Get-TicketboxPreparedInstallMode $true $true $true $true $false
$partialBootstrapMode = Get-TicketboxPreparedInstallMode $false $false $false $false $true
if ($freshMode -ne 'fresh_install' -or
    $preservedMode -ne 'preserved_data_reinstall' -or
    $repairMode -ne 'repair_install' -or
    $upgradeMode -ne 'upgrade' -or
    $partialBootstrapMode -ne 'repair_install') {{
    throw 'prepared install mode classification failed'
}}
$rejectedMode = $false
try {{ Get-TicketboxPreparedInstallMode $false $false $true $false $false | Out-Null }}
catch {{ $rejectedMode = $true }}
if (-not $rejectedMode) {{ throw 'unrecoverable partial data was accepted' }}
$config = Read-TicketboxWindowsReleaseConfig '{_literal(config_path)}'
Write-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -Mode upgrade `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -InstalledReleaseConfig $config `
    -InstallerOwnerProcessId $PID `
    -PreviousPgState running `
    -PreviousBackendState running `
    -PreviousPgStartPolicy delayed_auto `
    -PreviousBackendStartPolicy manual `
    -BackupRequired $true `
    -BackupCompleted $false `
    -PreparationStage captured
$capturedReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -InstallerOwnerProcessId $PID
Set-TicketboxLifecycleReceiptPrepared `
    -Path '{_literal(receipt_path)}' `
    -Receipt $capturedReceipt `
    -InstallerOwnerProcessId $PID `
    -BackupCompleted $true `
    -BackupPath '{_literal(backup_path)}'
$receipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -InstallerOwnerProcessId $PID
if ($receipt.mode -ne 'upgrade' -or
    -not $receipt.backup_completed -or
    $receipt.preparation_stage -ne 'prepared' -or
    $receipt.previous_pg_start_policy -ne 'delayed_auto' -or
    $receipt.previous_backend_start_policy -ne 'manual') {{
    throw 'receipt mode, policy, or backup changed'
}}
$overwriteRejected = $false
try {{
    Write-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -Mode fresh_install `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -InstalledReleaseConfig $config `
        -InstallerOwnerProcessId $PID `
        -PreviousPgState absent `
        -PreviousBackendState absent `
        -PreviousPgStartPolicy absent `
        -PreviousBackendStartPolicy absent `
        -BackupRequired $false `
        -BackupCompleted $false `
        -PreparationStage captured
}}
catch {{ $overwriteRejected = $true }}
if (-not $overwriteRejected) {{ throw 'existing receipt was silently overwritten' }}
$oldOwnerRejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -InstallerOwnerProcessId ($PID + 1) | Out-Null
}}
catch {{ $oldOwnerRejected = $true }}
if (-not $oldOwnerRejected) {{ throw 'receipt accepted a different installer owner without recovery mode' }}
$invalidTransitionRejected = $false
try {{
    Set-TicketboxLifecycleReceiptInstallCompleted `
        -Path '{_literal(receipt_path)}' `
        -Receipt $receipt `
        -InstallerOwnerProcessId $PID
}}
catch {{ $invalidTransitionRejected = $true }}
if (-not $invalidTransitionRejected) {{ throw 'prepared receipt skipped the files-replaced stage' }}
$staleReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -InstallerOwnerProcessId ($PID + 1) `
    -AllowPreviousInstallerOwnerProcessId
Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced `
    -Path '{_literal(receipt_path)}' `
    -Receipt $staleReceipt `
    -InstallerOwnerProcessId ($PID + 1)
$repairReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -InstallerOwnerProcessId ($PID + 1)
if (-not $repairReceipt.files_may_have_been_replaced -or
    $repairReceipt.previous_pg_state -ne 'running' -or
    $repairReceipt.previous_backend_state -ne 'running' -or
    $repairReceipt.previous_pg_start_policy -ne 'delayed_auto' -or
    $repairReceipt.previous_backend_start_policy -ne 'manual' -or
    -not $repairReceipt.backup_completed -or
    $repairReceipt.backup_path -ne [System.IO.Path]::GetFullPath('{_literal(backup_path)}')) {{
    throw 'repair rebind discarded previous state or backup evidence'
}}
Set-TicketboxLifecycleReceiptInstallerOwner `
    -Path '{_literal(receipt_path)}' `
    -Receipt $repairReceipt `
    -InstallerOwnerProcessId ($PID + 2)
$repairReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -InstallerOwnerProcessId ($PID + 2)
$duplicateTransitionRejected = $false
try {{
    Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced `
        -Path '{_literal(receipt_path)}' `
        -Receipt $repairReceipt `
        -InstallerOwnerProcessId ($PID + 2)
}}
catch {{ $duplicateTransitionRejected = $true }}
if (-not $duplicateTransitionRejected) {{ throw 'files-replaced transition was replayed' }}
$rejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5545 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -InstallerOwnerProcessId ($PID + 2) | Out-Null
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'receipt accepted mismatched port' }}
Set-TicketboxLifecycleReceiptInstallCompleted `
    -Path '{_literal(receipt_path)}' `
    -Receipt $repairReceipt `
    -InstallerOwnerProcessId ($PID + 2)
Remove-Item -LiteralPath '{_literal(backup_path)}' -Force
$completedReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -InstallerOwnerProcessId ($PID + 2)
if (-not $completedReceipt.install_completed -or $completedReceipt.preparation_stage -ne 'install_completed') {{
    throw 'completed receipt was not persisted'
}}
$boundCompletedReceipt = Read-TicketboxCompletedLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -TargetReleaseConfig $config `
    -ExpectedPgPort 5544 `
    -ExpectedBackendPort 8765 `
    -ExpectedPgServiceName ([string]$config.pg_service_name) `
    -ExpectedBackendServiceName ([string]$config.backend_service_name)
$incompleteRemovalRejected = $false
try {{
    Remove-TicketboxCompletedLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -Receipt $repairReceipt
}}
catch {{ $incompleteRemovalRejected = $true }}
if (-not $incompleteRemovalRejected) {{ throw 'incomplete receipt was removed' }}
Remove-TicketboxCompletedLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -Receipt $boundCompletedReceipt
if (Test-Path -LiteralPath '{_literal(receipt_path)}') {{ throw 'completed receipt survived invalidation' }}
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
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
