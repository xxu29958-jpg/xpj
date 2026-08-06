from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def test_fresh_install_recovery_receipt_operation_rebind_is_narrow_and_cross_engine(
    tmp_path: Path,
) -> None:
    receipt_script = PACKAGING / "windows_lifecycle_receipt.ps1"
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"receipt-fresh-install-recovery-rebind-{index}.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(receipt_script)}'
$script:writes = 0
$script:lastOperation = ''
function Write-TicketboxLifecycleReceipt {{
    $script:writes += 1
    for ($index = 0; $index -lt $args.Count - 1; $index++) {{
        if ([string]$args[$index] -ceq '-C07InstallationOperationId') {{
            $script:lastOperation = [string]$args[$index + 1]
        }}
    }}
}}
function Close-TicketboxLifecycleBackupGuard {{ param($Receipt) }}
$oldOperation = '11111111-1111-1111-1111-111111111111'
$newOperation = '22222222-2222-2222-2222-222222222222'
$receipt = [pscustomobject]@{{
    mode = 'fresh_install'
    install_dir = 'C:\\Program Files\\Ticketbox'
    data_root = 'C:\\ProgramData\\Ticketbox'
    pg_port = 5440
    backend_port = 8001
    installed_release_config = [pscustomobject]@{{}}
    target_backend_version_floor = '1.2.0'
    previous_pg_state = 'absent'
    previous_backend_state = 'absent'
    previous_pg_start_policy = 'absent'
    previous_backend_start_policy = 'absent'
    backup_required = $false
    backup_completed = $false
    preparation_stage = 'files_may_have_been_replaced'
    backup_path = ''
    backup_sha256 = ''
    backup_byte_length = 0
    files_may_have_been_replaced = $true
    install_completed = $false
    temporary_pg_service_cleanup_pending = $false
    c07_installation_operation_id = $oldOperation
    c07_production_authority_sha256 = ''
    c07_runtime_projection_sha256 = ''
}}
Set-TicketboxLifecycleReceiptC07InstallationOperation `
    -Path 'unused' `
    -Receipt $receipt `
    -InstallerOwnerProcessId 1234 `
    -OperationId $newOperation `
    -AllowFreshInstallRecoveryRebind
if ($script:writes -ne 1 -or $script:lastOperation -cne $newOperation) {{
    throw 'safe fresh-install recovery receipt operation was not rebound'
}}
$mutations = @(
    [pscustomobject]@{{ Property = 'mode'; Bad = 'preserved_data_reinstall'; Good = 'fresh_install' }},
    [pscustomobject]@{{ Property = 'previous_pg_state'; Bad = 'stopped'; Good = 'absent' }},
    [pscustomobject]@{{ Property = 'previous_backend_state'; Bad = 'stopped'; Good = 'absent' }},
    [pscustomobject]@{{ Property = 'previous_pg_start_policy'; Bad = 'disabled'; Good = 'absent' }},
    [pscustomobject]@{{ Property = 'previous_backend_start_policy'; Bad = 'disabled'; Good = 'absent' }},
    [pscustomobject]@{{ Property = 'preparation_stage'; Bad = 'prepared'; Good = 'files_may_have_been_replaced' }},
    [pscustomobject]@{{ Property = 'files_may_have_been_replaced'; Bad = $false; Good = $true }},
    [pscustomobject]@{{ Property = 'backup_required'; Bad = $true; Good = $false }},
    [pscustomobject]@{{ Property = 'backup_completed'; Bad = $true; Good = $false }},
    [pscustomobject]@{{ Property = 'backup_path'; Bad = 'C:\\protected\\backup.dump'; Good = '' }},
    [pscustomobject]@{{ Property = 'backup_sha256'; Bad = ('A' * 64); Good = '' }},
    [pscustomobject]@{{ Property = 'backup_byte_length'; Bad = 1; Good = 0 }},
    [pscustomobject]@{{ Property = 'install_completed'; Bad = $true; Good = $false }},
    [pscustomobject]@{{ Property = 'temporary_pg_service_cleanup_pending'; Bad = $true; Good = $false }},
    [pscustomobject]@{{ Property = 'c07_production_authority_sha256'; Bad = ('B' * 64); Good = '' }},
    [pscustomobject]@{{ Property = 'c07_runtime_projection_sha256'; Bad = ('C' * 64); Good = '' }}
)
foreach ($mutation in $mutations) {{
    $receipt.($mutation.Property) = $mutation.Bad
    $rejected = $false
    try {{
        Set-TicketboxLifecycleReceiptC07InstallationOperation `
            -Path 'unused' `
            -Receipt $receipt `
            -InstallerOwnerProcessId 1234 `
            -OperationId '33333333-3333-3333-3333-333333333333' `
            -AllowFreshInstallRecoveryRebind
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected -or $script:writes -ne 1) {{
        throw "receipt mutation $($mutation.Property) was rebound"
    }}
    $receipt.($mutation.Property) = $mutation.Good
}}
$rejected = $false
try {{
    Set-TicketboxLifecycleReceiptC07InstallationOperation `
        -Path 'unused' `
        -Receipt $receipt `
        -InstallerOwnerProcessId 1234 `
        -OperationId '33333333-3333-3333-3333-333333333333' `
        -SuccessorIntent ([pscustomobject]@{{ Payload = [pscustomobject]@{{}} }}) `
        -AllowFreshInstallRecoveryRebind
}}
catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 1) {{
    throw 'fresh-install recovery accepted a successor intent'
}}
$receipt.c07_installation_operation_id = 'not-a-guid'
$rejected = $false
try {{
    Set-TicketboxLifecycleReceiptC07InstallationOperation `
        -Path 'unused' `
        -Receipt $receipt `
        -InstallerOwnerProcessId 1234 `
        -OperationId '33333333-3333-3333-3333-333333333333' `
        -AllowFreshInstallRecoveryRebind
}}
catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 1) {{
    throw 'malformed existing receipt operation was rebound'
}}
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
    assert '"ticketbox-windows-lifecycle-receipt-v8"' in receipt
    assert '"ticketbox-windows-lifecycle-receipt-v7"' in receipt
    assert "target_backend_version_floor" in receipt
    assert "Read-TicketboxCompatibleLifecycleReceipt" in receipt
    assert "ConvertTo-TicketboxCurrentLifecycleReceipt" in receipt
    assert "ReplaceVerifiedLegacyReceipt" in receipt
    assert "AllowLegacyV7WithoutTargetVersionFloor" in receipt
    assert "Set-TicketboxLifecycleReceiptTargetVersionFloor" in receipt
    assert "Set-TicketboxLifecycleReceiptC07InstallationOperation" in receipt
    assert "c07_installation_operation_id" in receipt
    assert "Promote-TicketboxPendingInstallationIdentity" in receipt
    assert "ExpectedOperationId" in receipt
    assert "Assert-TicketboxProtectedLifecycleReceipt" in receipt
    assert "Write-TicketboxProtectedUtf8FileDurable" in receipt
    receipt_writer = receipt[
        receipt.index("function Write-TicketboxLifecycleReceipt") : receipt.index(
            "function Read-TicketboxLifecycleReceipt"
        )
    ]
    assert "Write-TicketboxProtectedUtf8FileDurable" in receipt_writer
    assert "安装生命周期回执目标版本下限不能回退" in receipt_writer
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
    assert "backup_sha256" in receipt
    assert "backup_byte_length" in receipt
    assert "Assert-TicketboxLifecycleBackupEvidence" in receipt
    marker_reader = receipt[
        receipt.index("function Read-TicketboxInstallerRecoveryMarker") :
        receipt.index("function Remove-TicketboxInstallerRecoveryMarker")
    ]
    marker_writer = receipt[
        receipt.index("function Write-TicketboxInstallerRecoveryMarker") : receipt.index(
            "function Ensure-TicketboxInstallerRecoveryMarkerAfterFailure"
        )
    ]
    assert "Write-TicketboxProtectedUtf8FileDurable" in marker_writer
    assert "-FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts" in marker_writer
    assert "ReplaceExisting" not in marker_writer
    assert "Read-TicketboxInstallerRecoveryMarker" in marker_writer
    assert "Assert-TicketboxProtectedDirectoryAcl" in marker_reader
    assert "ConvertFrom-Json" in marker_reader
    assert "[System.IO.File]::WriteAllText" not in marker_writer


def test_initdb_one_shot_receipt_state_machine_and_recovery_contract(
    tmp_path: Path,
) -> None:
    receipt_text = _read("windows_lifecycle_receipt.ps1")
    install = _read("install_bundled_services.ps1")
    prepare = _read("prepare_bundled_upgrade.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")
    assert '"ticketbox-windows-initdb-service-receipt-v1"' in receipt_text
    for phase in (
        "intent_written",
        "registered",
        "start_authorized",
        "initdb_succeeded",
        "converted_to_pgctl",
    ):
        assert f'"{phase}"' in receipt_text
    assert "function Remove-TicketboxAbortedInitdbServiceReceipt" in receipt_text
    assert "Invoke-TicketboxServiceOwnedInitdb" in install
    assert "Invoke-TicketboxInterruptedInitdbServiceRecovery" in prepare
    assert "Invoke-TicketboxInitdbServiceUninstallRecovery" in uninstall
    operation_lock = prepare.index("$operationLock =")
    recovery_call = prepare.index(
        "Invoke-TicketboxInterruptedInitdbServiceRecovery", operation_lock
    )
    target_major_gate = prepare.index("Assert-TicketboxTargetPgMajor", operation_lock)
    installed_config = prepare.index(
        "\n    Initialize-TicketboxInstalledReleaseConfiguration\n", operation_lock
    )
    assert installed_config < recovery_call < target_major_gate
    uninstall_entry = uninstall.index('$deleteDataRetryAuthority =')
    uninstall_recovery = uninstall.index(
        "Invoke-TicketboxInitdbServiceUninstallRecovery", uninstall_entry
    )
    completed_receipt = uninstall.index(
        "Get-TicketboxCompletedLifecycleReceiptForUninstall", uninstall_recovery
    )
    assert uninstall_recovery < completed_receipt

    receipt_script = PACKAGING / "windows_lifecycle_receipt.ps1"
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"initdb-receipt-state-{index}.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(receipt_script)}'
$script:writes = @()
$script:removes = 0
function Write-TicketboxInitdbServiceReceipt {{
    param($Path,$InstallDir,$DataRoot,$ServiceName,$ImagePath,$PgMajor,$StopTimeoutMs,$InstallerOwnerProcessId,$Phase,$CreatedAtUtc,[switch]$ReplaceExisting)
    $script:writes += [string]$Phase
}}
function Assert-TicketboxInitdbServiceReceiptPath {{ param($Path) return $Path }}
function Remove-TicketboxProtectedUtf8Artifact {{
    param($Path,$FullControlAccounts,$OwnerAccount)
    $script:removes += 1
}}
$receipt = [pscustomobject]@{{
    phase = 'intent_written'
    install_dir = 'C:\\Program Files\\Ticketbox'
    data_root = 'C:\\ProgramData\\Ticketbox'
    service_name = 'TicketboxPg'
    image_path = 'exact-image-path'
    pg_major = 17
    stop_timeout_ms = 25000
    created_at_utc = '2026-08-05T00:00:00.0000000+00:00'
}}
foreach ($next in @('registered','start_authorized','initdb_succeeded','converted_to_pgctl')) {{
    Set-TicketboxInitdbServiceReceiptPhase `
        -Path 'unused' `
        -Receipt $receipt `
        -InstallerOwnerProcessId 4242 `
        -Phase $next
    $receipt.phase = $next
}}
if (($script:writes -join ',') -cne 'registered,start_authorized,initdb_succeeded,converted_to_pgctl') {{
    throw 'initdb receipt phase sequence drifted'
}}
$skipRejected = $false
$receipt.phase = 'intent_written'
try {{
    Set-TicketboxInitdbServiceReceiptPhase `
        -Path 'unused' `
        -Receipt $receipt `
        -InstallerOwnerProcessId 4242 `
        -Phase 'initdb_succeeded'
}}
catch {{ $skipRejected = $true }}
if (-not $skipRejected) {{ throw 'initdb receipt accepted a skipped phase' }}
$receipt.phase = 'start_authorized'
Remove-TicketboxAbortedInitdbServiceReceipt -Path 'unused' -Receipt $receipt
if ($script:removes -ne 1) {{ throw 'aborted initdb receipt was not retired' }}
$receipt.phase = 'converted_to_pgctl'
$convertedAbortRejected = $false
try {{ Remove-TicketboxAbortedInitdbServiceReceipt -Path 'unused' -Receipt $receipt }}
catch {{ $convertedAbortRejected = $true }}
if (-not $convertedAbortRejected -or $script:removes -ne 1) {{
    throw 'converted initdb receipt was accepted by abort retirement'
}}
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_initdb_recovery_reader_uses_protected_receipt_release_values(
    tmp_path: Path,
) -> None:
    receipt_script = PACKAGING / "windows_lifecycle_receipt.ps1"
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"initdb-bound-recovery-{index}.ps1"
        harness.write_text(
            rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(receipt_script)}'
$script:envelope = [ordered]@{{
    schema = 'ticketbox-windows-initdb-service-receipt-v1'
    pg_major = 16
    stop_timeout_ms = 17000
}} | ConvertTo-Json -Compress
$script:strictReads = 0
function Assert-TicketboxInitdbServiceReceiptPath {{ param($Path); return $Path }}
function Assert-TicketboxProtectedLifecycleReceipt {{ param($Path) }}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path,$FullControlAccounts,$OwnerAccount,$MaximumBytes)
    return [pscustomobject]@{{ Text = $script:envelope }}
}}
function Read-TicketboxInitdbServiceReceipt {{
    param($Path,$InstallDir,$DataRoot,$ServiceName,$PgMajor,$StopTimeoutMs,$InstallerOwnerProcessId,[switch]$AllowPreviousInstallerOwnerProcessId)
    $script:strictReads += 1
    return [pscustomobject]@{{
        pg_major = $PgMajor
        stop_timeout_ms = $StopTimeoutMs
        previous_owner_allowed = [bool]$AllowPreviousInstallerOwnerProcessId
    }}
}}
$bound = Read-TicketboxBoundInitdbServiceReceipt `
    -Path 'receipt.json' `
    -InstallDir 'C:\Program Files\Ticketbox' `
    -DataRoot 'C:\ProgramData\Ticketbox' `
    -ServiceName 'TicketboxPg' `
    -InstallerOwnerProcessId 9001 `
    -AllowPreviousInstallerOwnerProcessId
if ($bound.pg_major -ne 16 -or $bound.stop_timeout_ms -ne 17000 -or
    -not $bound.previous_owner_allowed -or $script:strictReads -ne 1) {{
    throw 'recovery reader substituted current target release values'
}}
$script:envelope = [ordered]@{{ pg_major = 17; stop_timeout_ms = 999 }} |
    ConvertTo-Json -Compress
$invalidRejected = $false
try {{
    Read-TicketboxBoundInitdbServiceReceipt `
        -Path 'receipt.json' `
        -InstallDir 'C:\Program Files\Ticketbox' `
        -DataRoot 'C:\ProgramData\Ticketbox' `
        -ServiceName 'TicketboxPg' `
        -InstallerOwnerProcessId 9001 | Out-Null
}}
catch {{ $invalidRejected = $true }}
if (-not $invalidRejected -or $script:strictReads -ne 1) {{
    throw 'invalid self-described recovery values reached the strict reader'
}}
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_aborted_fresh_install_uninstall_authority_is_narrow_and_post_cleanup(
    tmp_path: Path,
) -> None:
    receipt_script = PACKAGING / "windows_lifecycle_receipt.ps1"
    uninstall = _read("uninstall_bundled_services.ps1")
    recovery = uninstall.index("Invoke-TicketboxInitdbServiceUninstallRecovery")
    main_receipt = uninstall.index(
        "Get-TicketboxCompletedLifecycleReceiptForUninstall", recovery
    )
    validate = uninstall.index("$safeRoot = Assert-UninstallInputs", main_receipt)
    service_cleanup = uninstall.index(
        "Remove-ServiceIfExists $BackendServiceName", validate
    )
    receipt_retire = uninstall.index(
        "Remove-TicketboxAbortedFreshInstallLifecycleReceipt", service_cleanup
    )
    assert recovery < main_receipt < validate < service_cleanup < receipt_retire
    assert "Write-TicketboxAbortedFreshInstallDeleteDataIntent" in uninstall
    assert 'authority_kind = "aborted_fresh_install"' in _read(
        "windows_lifecycle_receipt.ps1"
    )

    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"aborted-fresh-authority-{index}.ps1"
        harness.write_text(
            rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(receipt_script)}'
$valid = [pscustomobject]@{{
    mode = 'fresh_install'
    preparation_stage = 'files_may_have_been_replaced'
    install_completed = $false
    files_may_have_been_replaced = $true
    previous_pg_state = 'absent'
    previous_backend_state = 'absent'
    previous_pg_start_policy = 'absent'
    previous_backend_start_policy = 'absent'
    backup_required = $false
    backup_completed = $false
    temporary_pg_service_cleanup_pending = $false
}}
Assert-TicketboxAbortedFreshInstallLifecycleReceipt $valid
$poisons = @(
    @('mode','upgrade'),
    @('preparation_stage','prepared'),
    @('install_completed',$true),
    @('files_may_have_been_replaced',$false),
    @('previous_pg_state','stopped'),
    @('previous_backend_start_policy','manual'),
    @('backup_required',$true),
    @('temporary_pg_service_cleanup_pending',$true)
)
foreach ($poison in $poisons) {{
    $name = [string]$poison[0]
    $old = $valid.$name
    $valid.$name = $poison[1]
    $rejected = $false
    try {{ Assert-TicketboxAbortedFreshInstallLifecycleReceipt $valid }}
    catch {{ $rejected = $true }}
    $valid.$name = $old
    if (-not $rejected) {{ throw "aborted authority accepted poison: $name" }}
}}
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_runtime_recovery_projection_blocks_traffic_until_commit() -> None:
    install = _read("install_bundled_services.ps1")
    prepare = _read("prepare_bundled_upgrade.ps1")
    receipt = _read("windows_lifecycle_receipt.ps1")
    service_contract = _read("windows_service_contract.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")

    runtime_guard = receipt[
        receipt.index("function Assert-TicketboxInstallerRuntimeRecoveryGuardPath") : receipt.index(
            "function Complete-TicketboxInstalledLifecycleTransaction"
        )
    ]
    assert "Get-TicketboxInstallerRuntimeRecoveryGuardPath" in receipt
    assert "Get-TicketboxInstallerRuntimeStateDirectory" in receipt
    assert "CommonApplicationData" in receipt
    assert '"TicketboxRuntimeState"' in receipt
    assert "Test-TicketboxPathWithin $runtimeStateDirectory $DataRoot" in runtime_guard
    assert "Initialize-TicketboxProtectedDirectoryAtomically" in runtime_guard
    assert '"installer-runtime-recovery-pending"' in receipt
    assert 'state = "installer_transaction_pending"' in runtime_guard
    assert '-ReadExecuteAccounts @("NT SERVICE\\$BackendServiceName")' in runtime_guard
    assert "ReplaceExisting" not in runtime_guard

    transaction = receipt[
        receipt.index("function Complete-TicketboxInstalledLifecycleTransaction") : receipt.index(
            "function Set-TicketboxLifecycleReceiptInstallerOwner"
        )
    ]
    retire_recovery_tools = transaction.index("Remove-TicketboxPgRecoveryToolset")
    promote_services = transaction.index("Enable-TicketboxInstalledServicesAutoStart")
    retire_machine_latch = transaction.index("Remove-TicketboxInstallerRecoveryMarker")
    retire_runtime_projection = transaction.index(
        "Remove-TicketboxInstallerRuntimeRecoveryGuard"
    )
    assert retire_recovery_tools < promote_services < retire_machine_latch < retire_runtime_projection

    mutation = install[install.index("$mutationStarted = $true") :]
    register_backend = mutation.index("Register-BackendService")
    write_projection = mutation.index("Write-TicketboxInstallerRuntimeRecoveryGuard")
    enable_backend = mutation.index("Set-TicketboxOwnedServiceDemandStartIfExists")
    bootstrap_recovery = install.index("Resolve-TicketboxBootstrapExposureRecoveryIntent")
    backend_start = install.index('Write-Step "启动后端服务"')
    assert register_backend < write_projection < enable_backend
    assert install.index("Write-TicketboxInstallerRuntimeRecoveryGuard") < bootstrap_recovery < backend_start
    assert "Remove-TicketboxInstallerRecoveryMarker" not in install
    assert "Remove-TicketboxInstallerRuntimeRecoveryGuard" not in install
    assert "Remove-TicketboxPgRecoveryToolset" not in install
    assert "Enable-TicketboxInstalledServicesAutoStart" not in install

    assert "ExpectedInstallerRecoveryGuardPath" in prepare
    assert "-AllowMissingInstallerRecoveryGuard `" in prepare
    assert "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH" in service_contract

    uninstall_projection = uninstall[
        uninstall.index("function Remove-TicketboxInstallerRuntimeProjectionForUninstall") : uninstall.index(
            "function Assert-UninstallInputs"
        )
    ]
    disable_backend = uninstall_projection.index("Disable-TicketboxOwnedServiceIfExists")
    remove_projection = uninstall_projection.index("Remove-TicketboxInstallerRuntimeRecoveryGuard")
    remove_runtime_state = uninstall_projection.index(
        "Remove-TicketboxInstallerRuntimeStateDirectoryIfEmpty"
    )
    remove_service = uninstall.index('Write-Step "停止并删除后端服务"')
    invoke_projection_cleanup = uninstall.index(
        "Remove-TicketboxInstallerRuntimeProjectionForUninstall",
        uninstall.index("$safeRoot = Assert-UninstallInputs"),
    )
    assert disable_backend < remove_projection < remove_runtime_state
    assert invoke_projection_cleanup < remove_service


def test_completed_stale_receipt_cannot_reuse_previous_backup_mutation() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    install = _read("install_bundled_services.ps1")
    flow = _read("ticketbox-installer-flow.isph")

    stale_start = prepare.index("$staleReceipt = Read-TicketboxCompatibleLifecycleReceipt")
    completed_check = prepare.index("if ([bool]$staleReceipt.install_completed)", stale_start)
    resume_commit = prepare.index("Complete-TicketboxInstalledLifecycleTransaction", completed_check)
    invalidate = prepare.index("Remove-TicketboxCompletedLifecycleReceipt", resume_commit)
    initialize_current = prepare.index(
        "\n    Initialize-TicketboxInstalledReleaseConfiguration\n"
    )
    reset_backup = prepare.index("$backupCompleted = $false", invalidate)
    write_new_receipt = prepare.index("Write-TicketboxLifecycleReceipt", reset_backup)
    completed_branch = prepare[
        completed_check : prepare.index(
            'elseif ([string]$staleReceipt.preparation_stage -in @(',
            completed_check,
        )
    ]

    assert initialize_current < completed_check < resume_commit < invalidate < reset_backup < write_new_receipt
    assert "Set-TicketboxLifecycleReceiptInstallerOwner" in completed_branch
    assert "Complete-TicketboxInstalledLifecycleTransaction" in completed_branch
    assert completed_branch.index("Assert-TicketboxPreparedServiceContracts") < completed_branch.index(
        "ConvertTo-TicketboxCurrentLifecycleReceipt"
    )
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
    final_data_root_lease_check = flow.index("AssertDataRootMutationGuardActive();", durable_commit)
    host_commit = flow.index("LifecycleInstallCompleted := True", durable_commit)
    assert service_install < durable_commit < final_data_root_lease_check < host_commit
    assert "-CommitCompletedInstall" in flow[service_install:host_commit]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows lifecycle commit contract")
def test_install_commit_retires_recovery_latch_only_after_durable_authorities(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "install-commit-order.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_lifecycle_receipt.ps1')}'
$runtimeState = Get-TicketboxInstallerRuntimeStateDirectory '{_literal(tmp_path)}'
if ($runtimeState -cne '{_literal(tmp_path / "TicketboxRuntimeState")}') {{
    throw "runtime-state provider returned $runtimeState"
}}
$script:stage = 'files_may_have_been_replaced'
$script:events = New-Object System.Collections.Generic.List[string]
function Read-TicketboxLifecycleReceipt {{
    param($Path, $InstallDir, $DataRoot, $PgPort, $BackendPort, $TargetReleaseConfig, $CurrentTargetBackendVersion, $InstallerOwnerProcessId)
    [void]$script:events.Add('read')
    return [pscustomobject]@{{
        preparation_stage = $script:stage
        c07_installation_operation_id = '11111111-1111-1111-1111-111111111111'
        c07_production_authority_sha256 = ('A' * 64)
        c07_runtime_projection_sha256 = ('B' * 64)
    }}
}}
function Assert-TicketboxC07CommitReadyArtifacts {{
    param($ExpectedOperationId, $BackendServiceName, $ExpectedProductionAuthoritySha256, $ExpectedRuntimeProjectionSha256)
    if ($ExpectedOperationId -cne '11111111-1111-1111-1111-111111111111' -or
        $BackendServiceName -cne 'TicketboxBackend' -or
        $ExpectedProductionAuthoritySha256 -cne ('A' * 64) -or
        $ExpectedRuntimeProjectionSha256 -cne ('B' * 64)) {{
        throw 'unexpected C07 READY commit evidence'
    }}
    [void]$script:events.Add('ready')
    if ($script:failReady) {{ throw 'injected READY evidence drift' }}
}}
function Promote-TicketboxPendingInstallationIdentity {{
    param($DataRoot, $InstallDir, $PgPort, $BackendPort, $PgServiceName, $BackendServiceName, $BuildManifestPath, $ExpectedOperationId)
    if ($ExpectedOperationId -cne '11111111-1111-1111-1111-111111111111') {{
        throw "unexpected installation operation id $ExpectedOperationId"
    }}
    [void]$script:events.Add('identity')
}}
function Set-TicketboxLifecycleReceiptInstallCompleted {{
    param($Path, $Receipt, $InstallerOwnerProcessId)
    [void]$script:events.Add('receipt')
    $script:stage = 'install_completed'
}}
function Assert-TicketboxCompletedLifecycleReceipt {{
    param($Receipt)
    if ($Receipt.preparation_stage -cne 'install_completed') {{ throw 'receipt was not complete' }}
    [void]$script:events.Add('assert')
}}
function Remove-TicketboxPgRecoveryToolset {{
    param($ExpectedMajor, [switch]$DeleteDataIntentValidated, [switch]$InstallCommitValidated)
    if (-not $InstallCommitValidated -or $DeleteDataIntentValidated) {{
        throw 'commit used the wrong recovery-tool deletion authority'
    }}
    [void]$script:events.Add('tools')
    if ($script:failToolCleanup) {{ throw 'injected recovery-tool cleanup failure' }}
}}
function Enable-TicketboxInstalledServicesAutoStart {{
    param($InstallDir, $TargetReleaseConfig)
    [void]$script:events.Add('autostart')
    if ($script:failPromotion) {{ throw 'injected service promotion failure' }}
}}
function Remove-TicketboxInstallerRecoveryMarker {{
    param($Path, $InstallDir, $DataRoot)
    [void]$script:events.Add('latch')
}}
function Remove-TicketboxInstallerRuntimeRecoveryGuard {{
    param($Path, $InstallDir, $DataRoot, $BackendServiceName)
    [void]$script:events.Add('runtime')
}}
$config = [pscustomobject]@{{ pg_service_name = 'TicketboxPg'; backend_service_name = 'TicketboxBackend' }}
$arguments = @{{
    Path = 'receipt.json'; InstallDir = 'program'; DataRoot = 'data'; PgPort = 5432; BackendPort = 8000
    TargetReleaseConfig = $config; TargetBackendVersion = '1.3.0'; InstallerOwnerProcessId = $PID; BuildManifestPath = 'manifest.json'
    RecoveryRequiredPath = 'installer-recovery-required.json'
    RuntimeRecoveryGuardPath = 'installer-runtime-recovery-pending'
}}
Complete-TicketboxInstalledLifecycleTransaction @arguments
if (($script:events -join ',') -cne 'read,ready,identity,receipt,read,assert,tools,autostart,latch,runtime') {{
    throw "first commit order was $($script:events -join ',')"
}}
$script:events.Clear()
Complete-TicketboxInstalledLifecycleTransaction @arguments
if (($script:events -join ',') -cne 'read,ready,identity,assert,tools,autostart,latch,runtime') {{
    throw "retry commit was not idempotent: $($script:events -join ',')"
}}
$script:events.Clear()
$script:failReady = $true
$readyDriftRejected = $false
try {{ Complete-TicketboxInstalledLifecycleTransaction @arguments }}
catch {{ $readyDriftRejected = $true }}
if (-not $readyDriftRejected -or ($script:events -contains 'identity')) {{
    throw 'commit promoted identity after C07 READY evidence drift'
}}
$script:events.Clear()
$script:failReady = $false
$script:failToolCleanup = $true
$toolCleanupRejected = $false
try {{ Complete-TicketboxInstalledLifecycleTransaction @arguments }}
catch {{ $toolCleanupRejected = $true }}
if (-not $toolCleanupRejected -or
    ($script:events -contains 'autostart') -or
    ($script:events -contains 'latch') -or
    ($script:events -contains 'runtime')) {{
    throw 'commit advanced after recovery-tool cleanup failure'
}}
$script:events.Clear()
$script:failToolCleanup = $false
$script:failPromotion = $true
$promotionRejected = $false
try {{ Complete-TicketboxInstalledLifecycleTransaction @arguments }}
catch {{ $promotionRejected = $true }}
if (-not $promotionRejected -or
    ($script:events -contains 'latch') -or
    ($script:events -contains 'runtime')) {{
    throw 'recovery latch retired after service promotion failure'
}}
$script:events.Clear()
$script:failPromotion = $false
Complete-TicketboxInstalledLifecycleTransaction @arguments
if (($script:events -join ',') -cne 'read,ready,identity,assert,tools,autostart,latch,runtime') {{
    throw "promotion retry did not converge: $($script:events -join ',')"
}}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows recovery compensation contract")
def test_failure_compensation_converges_dual_latch_without_replacing_authority(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "recovery-compensation.ps1"
    legacy_path = _literal(tmp_path / "legacy-recovery.json")
    current_path = _literal(tmp_path / "installer-state" / "recovery.json")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_lifecycle_receipt.ps1')}'
$script:events = New-Object System.Collections.Generic.List[string]
function Initialize-TicketboxInstallerStateDirectory {{
    param($Path)
    [void]$script:events.Add('init')
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}}
function Move-TicketboxLegacyInstallerStateArtifact {{
    param($LegacyPath, $CurrentPath)
    [void]$script:events.Add('move')
    if (-not (Test-Path -LiteralPath $LegacyPath -PathType Leaf)) {{ return }}
    if (Test-Path -LiteralPath $CurrentPath -PathType Leaf) {{
        if ([System.IO.File]::ReadAllText($LegacyPath) -cne [System.IO.File]::ReadAllText($CurrentPath)) {{
            throw 'dual latch conflict'
        }}
        Remove-Item -LiteralPath $LegacyPath -Force
        return
    }}
    Move-Item -LiteralPath $LegacyPath -Destination $CurrentPath
}}
function Read-TicketboxInstallerRecoveryMarker {{
    param($Path, $InstallDir, $DataRoot)
    [void]$script:events.Add('read')
    return [pscustomobject]@{{ reason = [System.IO.File]::ReadAllText($Path) }}
}}
function Write-TicketboxInstallerRecoveryMarker {{
    param($Path, $InstallDir, $DataRoot, $Reason)
    [void]$script:events.Add('write')
    [System.IO.File]::WriteAllText($Path, $Reason)
}}
$installerState = Split-Path -Parent '{current_path}'
New-Item -ItemType Directory -Path $installerState -Force | Out-Null
[System.IO.File]::WriteAllText('{legacy_path}', 'original-latch')
[System.IO.File]::WriteAllText('{current_path}', 'original-latch')
Ensure-TicketboxInstallerRecoveryMarkerAfterFailure `
    -InstallerStatePath $installerState `
    -LegacyPath '{legacy_path}' `
    -CurrentPath '{current_path}' `
    -InstallDir 'program' `
    -DataRoot 'data' `
    -Reason 'new failure must not replace authority'
if (($script:events -join ',') -cne 'init,move,read' -or
    (Test-Path -LiteralPath '{legacy_path}') -or
    [System.IO.File]::ReadAllText('{current_path}') -cne 'original-latch') {{
    throw 'dual-location latch was replaced instead of converged and preserved'
}}
$script:events.Clear()
Remove-Item -LiteralPath '{current_path}' -Force
Ensure-TicketboxInstallerRecoveryMarkerAfterFailure `
    -InstallerStatePath $installerState `
    -LegacyPath '{legacy_path}' `
    -CurrentPath '{current_path}' `
    -InstallDir 'program' `
    -DataRoot 'data' `
    -Reason 'first-latch'
if (($script:events -join ',') -cne 'init,move,write' -or
    [System.IO.File]::ReadAllText('{current_path}') -cne 'first-latch') {{
    throw 'absent latch was not created exactly once'
}}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        (tmp_path / "legacy-recovery.json").unlink(missing_ok=True)
        shutil.rmtree(tmp_path / "installer-state", ignore_errors=True)
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows delete-data intent contract")
def test_delete_data_intent_is_bound_to_a_completed_receipt_before_retirement(
    tmp_path: Path,
) -> None:
    runtime_base = PACKAGING.parent / "build" / f"runtime-state-cleanup-{uuid.uuid4().hex}"
    uninstall = (PACKAGING / "uninstall_bundled_services.ps1").read_text(encoding="utf-8-sig")
    uninstall_projection = uninstall[
        uninstall.index("function Remove-TicketboxInstallerRuntimeProjectionForUninstall") :
        uninstall.index("function Assert-UninstallInputs")
    ]
    harness = tmp_path / "delete-data-intent.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_installation_safety.ps1')}'
. '{_literal(PACKAGING / 'windows_lifecycle_receipt.ps1')}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxLifecycleReceiptAclAccounts = @($currentAccount)
$script:TicketboxLifecycleReceiptOwnerAccount = $currentAccount
$machineRoot = '{_literal(tmp_path / 'machine')}'
$installerState = Join-Path $machineRoot 'installer-state'
$intentPath = Join-Path $installerState 'delete-data-in-progress.json'
$receiptPath = '{_literal(tmp_path / 'installer-lifecycle-receipt.json')}'
$installDir = '{_literal(tmp_path / 'program')}'
$dataRoot = '{_literal(tmp_path / 'data')}'
New-Item -ItemType Directory -Path $machineRoot, $installDir, $dataRoot -Force | Out-Null
Set-TicketboxExactDirectoryAcl `
    -Path $machineRoot `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Write-TicketboxProtectedUtf8FileDurable `
    -Path $receiptPath `
    -Text 'completed receipt evidence' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
function Assert-TicketboxCompletedLifecycleReceipt {{
    param($Receipt)
    if (-not [bool]$Receipt.install_completed) {{ throw 'receipt is not completed' }}
}}
function Assert-TicketboxProtectedLifecycleReceipt {{
    param($Path)
    Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
$receipt = [pscustomobject]@{{ install_completed = $true }}
$first = Write-TicketboxDeleteDataIntent `
    -Path $intentPath `
    -CompletedReceiptPath $receiptPath `
    -CompletedReceipt $receipt `
    -InstallDir $installDir `
    -DataRoot $dataRoot
$firstBytes = [System.IO.File]::ReadAllBytes($intentPath)
$second = Write-TicketboxDeleteDataIntent `
    -Path $intentPath `
    -CompletedReceiptPath $receiptPath `
    -CompletedReceipt $receipt `
    -InstallDir $installDir `
    -DataRoot $dataRoot
if (-not (Test-TicketboxByteArrayEquals $firstBytes ([System.IO.File]::ReadAllBytes($intentPath)))) {{
    throw 'delete-data intent was replaced instead of reused for the same receipt'
}}
Remove-Item -LiteralPath $receiptPath -Force
$resumed = Read-TicketboxDeleteDataIntent `
    -Path $intentPath `
    -InstallDir $installDir `
    -DataRoot $dataRoot
if ($resumed.completed_receipt_sha256 -cne $first.completed_receipt_sha256 -or
    $second.completed_receipt_sha256 -cne $first.completed_receipt_sha256) {{
    throw 'delete-data intent lost completed receipt binding across retry'
}}
$unboundRetry = Read-TicketboxDeleteDataIntent `
    -Path $intentPath `
    -InstallDir $installDir
if (-not (Test-TicketboxPathEquals ([string]$unboundRetry.data_root) $dataRoot)) {{
    throw 'protected delete-data intent could not recover its bound DataRoot after registry retirement'
}}
$crossBindingRejected = $false
try {{
    Read-TicketboxDeleteDataIntent `
        -Path $intentPath `
        -InstallDir $installDir `
        -DataRoot '{_literal(tmp_path / 'other-data')}' | Out-Null
}}
catch {{ $crossBindingRejected = $true }}
if (-not $crossBindingRejected) {{ throw 'delete-data intent accepted another data root' }}
$runtimeStateDirectory = '{_literal(tmp_path / 'runtime-state')}'
function Get-TicketboxInstallerRuntimeStateDirectory {{ return $runtimeStateDirectory }}
{uninstall_projection}
$runtimeDataRoot = '{_literal(runtime_base / 'runtime-data')}'
$runtimeInstallDir = '{_literal(runtime_base / 'runtime-program')}'
New-Item -ItemType Directory -Path $runtimeDataRoot, $runtimeInstallDir -Force | Out-Null
Initialize-TicketboxDataRootMarker `
    -DataRoot $runtimeDataRoot `
    -InstallDir $runtimeInstallDir `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Initialize-TicketboxInstallerRuntimeStateDirectory `
    -DataRoot $runtimeDataRoot `
    -BackendServiceName 'EventLog' | Out-Null
$runtimeGuardPath = Get-TicketboxInstallerRuntimeRecoveryGuardPath
Write-TicketboxInstallerRuntimeRecoveryGuard `
    -Path $runtimeGuardPath `
    -InstallDir $runtimeInstallDir `
    -DataRoot $runtimeDataRoot `
    -BackendServiceName 'EventLog'
Remove-TicketboxInstallerRuntimeRecoveryGuard `
    -Path $runtimeGuardPath `
    -InstallDir $runtimeInstallDir `
    -DataRoot $runtimeDataRoot `
    -BackendServiceName 'EventLog'
Remove-TicketboxInstallerRuntimeStateDirectoryIfEmpty `
    -DataRoot $runtimeDataRoot `
    -BackendServiceName 'EventLog'
if (Test-Path -LiteralPath $runtimeStateDirectory) {{
    throw 'uninstall runtime-state cleanup left an empty machine projection directory'
}}
$BackendServiceName = 'MissingTicketboxBackend'
$DataRoot = $runtimeDataRoot
$InstallDir = $runtimeInstallDir
$InstallerRuntimeRecoveryGuardPath = Get-TicketboxInstallerRuntimeRecoveryGuardPath
function Service-Exists([string]$Name) {{ return $false }}
[System.IO.File]::WriteAllText($runtimeStateDirectory, 'malformed runtime-state path')
$fileShapedStateRejected = $false
try {{ Remove-TicketboxInstallerRuntimeProjectionForUninstall }}
catch {{ $fileShapedStateRejected = $true }}
if (-not $fileShapedStateRejected) {{
    throw 'file-shaped runtime-state path was treated as absent during uninstall'
}}
Remove-Item -LiteralPath $runtimeStateDirectory -Force
New-Item -ItemType Directory -Path $runtimeStateDirectory | Out-Null
New-Item -ItemType Directory -Path $InstallerRuntimeRecoveryGuardPath | Out-Null
$directoryShapedGuardRejected = $false
try {{ Remove-TicketboxInstallerRuntimeProjectionForUninstall }}
catch {{ $directoryShapedGuardRejected = $true }}
if (-not $directoryShapedGuardRejected) {{
    throw 'directory-shaped runtime guard was treated as absent during uninstall'
}}
Remove-Item -LiteralPath $runtimeStateDirectory -Recurse -Force
$danglingTarget = '{_literal(tmp_path / 'runtime-state-dangling-target')}'
New-Item -ItemType Directory -Path $danglingTarget | Out-Null
New-Item -ItemType Junction -Path $runtimeStateDirectory -Target $danglingTarget | Out-Null
[System.IO.Directory]::Delete($danglingTarget)
$danglingRuntimeStateRejected = $false
try {{ Remove-TicketboxInstallerRuntimeProjectionForUninstall }}
catch {{ $danglingRuntimeStateRejected = $true }}
if (-not $danglingRuntimeStateRejected) {{
    throw 'dangling runtime-state reparse was treated as absent during uninstall'
}}
[System.IO.Directory]::Delete($runtimeStateDirectory)
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        shutil.rmtree(tmp_path / "machine", ignore_errors=True)
        shutil.rmtree(tmp_path / "runtime-state", ignore_errors=True)
        shutil.rmtree(runtime_base, ignore_errors=True)
        (tmp_path / "installer-lifecycle-receipt.json").unlink(missing_ok=True)
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
    shutil.rmtree(runtime_base, ignore_errors=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL and PowerShell contract")
def test_persistent_installation_identity_roundtrips_and_rejects_floor_rollback(
    tmp_path: Path,
) -> None:
    engines = powershell_contract_engines()

    for index, engine in enumerate(engines):
        root = tmp_path / f"identity-{index}"
        data_root = root / "data"
        install_dir = root / "program"
        data_root.mkdir(parents=True)
        helper_payload = b"c07-migration-helper-fixture"
        helper_dir = install_dir / "program" / "ticketbox-backend"
        helper_dir.mkdir(parents=True)
        helper = helper_dir / "ticketbox-c07-migrator.exe"
        helper.write_bytes(helper_payload)
        manifest = install_dir / "installer" / "BUILD_PROVENANCE.json"
        manifest.parent.mkdir()
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "artifact_type": "ticketbox-windows-installer-inputs",
                    "build_mode": "installer-build",
                    "backend": {
                        "version": "7.8.9",
                        "c07_migration_helper": {
                            "path": helper.name,
                            "size": len(helper_payload),
                            "sha256": hashlib.sha256(helper_payload).hexdigest(),
                        },
                    },
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
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(data_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
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
    operation_lock = prepare.index("$operationLock = Enter-TicketboxLifecycleLock")
    main_execution = prepare[operation_lock:]
    admin_gate = main_execution.index("Assert-Admin")
    owner_gate = main_execution.index(
        "if ($InstallerLockOwnerProcessId -le 0)", admin_gate
    )
    early_marker_repair = main_execution.index(
        "Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded `", owner_gate
    )
    mark_branch = main_execution.index(
        "if ($MarkProgramFilesInstalledBackupPending)", early_marker_repair
    )
    recover_branch_start = main_execution.index("if ($RecoverPreparedInstall)", mark_branch)
    commit_branch = main_execution.index("if ($CommitCompletedInstall)", recover_branch_start)
    stale_receipt_branch = main_execution.index(
        "if (Test-Path -LiteralPath $LifecycleReceiptPath -PathType Leaf)",
        commit_branch,
    )
    assert (
        admin_gate
        < owner_gate
        < early_marker_repair
        < mark_branch
        < recover_branch_start
        < commit_branch
        < stale_receipt_branch
    )
    receipt_reads = [
        match.start()
        for match in re.finditer(
            r"Read-Ticketbox[A-Za-z]*LifecycleReceipt", main_execution
        )
    ]
    assert receipt_reads
    assert all(early_marker_repair < receipt_read for receipt_read in receipt_reads)
    authority_call = prepare.rindex("Assert-TicketboxPreparedDataRootAuthorityGate `")
    preserved_mode = prepare.index('if ($mode -eq "preserved_data_reinstall")', authority_call)
    preserved_layout = prepare.index("Assert-TicketboxLegacyPreservedDataLayout", preserved_mode)
    existing_mode = prepare.index('elseif ($mode -ne "fresh_install")', authority_call)
    machine_binding = prepare.index("Assert-TicketboxRegisteredDataRootBinding", existing_mode)
    legacy_marker = prepare.index("Initialize-TicketboxDataRootMarker", machine_binding)
    pg_service_contract = prepare.index(
        "Assert-ExpectedServiceConfiguration -Name $PgServiceName",
        authority_call,
    )
    backend_service_contract = prepare.index(
        "Assert-ExpectedServiceConfiguration -Name $BackendServiceName",
        authority_call,
    )
    recovery_service_cleanup = prepare.index(
        "Remove-TicketboxRecoveryPgServiceIfExists",
        authority_call,
    )
    acl_mutation = prepare.index("Repair-TicketboxPreflightInstallAcl", authority_call)
    receipt_mutation = prepare.index("Write-TicketboxLifecycleReceipt `", authority_call)
    assert authority_call < preserved_mode < preserved_layout < legacy_marker
    assert authority_call < existing_mode < machine_binding < legacy_marker
    assert pg_service_contract < legacy_marker
    assert backend_service_contract < legacy_marker
    assert authority_call < recovery_service_cleanup < acl_mutation
    assert authority_call < receipt_mutation
    assert "fresh install 只接受 holder 已发布权威 marker" in prepare
    authority_gate = prepare[
        prepare.index("function Assert-TicketboxPreparedDataRootAuthorityGate") : prepare.index(
            "function Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded"
        )
    ]
    root_authority = authority_gate.index(
        "Repair-TicketboxRecoverableDataRootMarkerAcl"
    )
    marker_authority = authority_gate.index("Assert-TicketboxProtectedDataRootMarker")
    assert root_authority < marker_authority
    assert "-AllowLegacyV1" in authority_gate
    assert "独立隔离恢复/导入流程" in authority_gate
    assert "AllowMarkerlessLegacyAdoption" not in prepare
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
        prepare.index("function Assert-TicketboxPreparedServiceRuntimeCommand") : prepare.index(
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows stale receipt ACL recovery contract")
def test_stale_fresh_receipt_repairs_inherited_marker_before_receipt_read_and_recovery(
    tmp_path: Path,
) -> None:
    config = json.loads(_read("windows-release-config.json"))
    prepare = _read("prepare_bundled_upgrade.ps1")
    early_marker_repair = prepare[
        prepare.index("function Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded") :
        prepare.index("Set-TicketboxInstalledReleaseConfiguration -Config $InstalledReleaseConfig")
    ]
    prepared_recovery = prepare[
        prepare.index("function Invoke-TicketboxPreparedInstallRecovery") :
        prepare.index("if ($PgPort -eq $BackendPort)")
    ]

    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"stale-fresh-recovery-{index}"
        data_root = root / "data"
        install_dir = root / "program"
        machine_state = root / "machine-state"
        receipt_path = machine_state / "installer-lifecycle-receipt.json"
        config_path = root / "release.json"
        root.mkdir()
        data_root.mkdir()
        install_dir.mkdir()
        machine_state.mkdir()
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        harness = root / "stale-fresh-recovery.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_installation_safety.ps1')}'
. '{_literal(PACKAGING / 'windows_release_config.ps1')}'
. '{_literal(PACKAGING / 'windows_lifecycle_receipt.ps1')}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxLifecycleReceiptAclAccounts = @($currentAccount)
$script:TicketboxLifecycleReceiptOwnerAccount = $currentAccount
function Get-TicketboxLifecycleLockPath {{
    return '{_literal(machine_state / "installer-lifecycle.lock")}'
}}
function Assert-TicketboxDataRootDomain {{
    param([string]$DataRoot, [string]$InstallDir)
    return ConvertTo-TicketboxWin32CanonicalPath $DataRoot
}}
function Get-TestAclFingerprint([string]$Path) {{
    $acl = Get-TicketboxPathAcl $Path
    $rules = @($acl.Access | ForEach-Object {{
        [string]::Join(':', @(
            $_.IdentityReference.Value,
            [string]$_.AccessControlType,
            [string][int64]$_.FileSystemRights,
            [string]$_.InheritanceFlags,
            [string]$_.PropagationFlags,
            [string]$_.IsInherited
        ))
    }} | Sort-Object)
    return [string]::Join('|', @(
        $acl.Owner,
        [string]$acl.AreAccessRulesProtected,
        ($rules -join ',')
    ))
}}
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(data_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Write-TicketboxDataRootMarker `
    -DataRoot '{_literal(data_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(machine_state)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$config = Read-TicketboxWindowsReleaseConfig '{_literal(config_path)}'
$previousOwner = if ($PID -lt [int]::MaxValue) {{ $PID + 1 }} else {{ $PID - 1 }}
Write-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -Mode fresh_install `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -InstalledReleaseConfig $config `
    -TargetBackendVersionFloor 1.2.0 `
    -InstallerOwnerProcessId $previousOwner `
    -PreviousPgState absent `
    -PreviousBackendState absent `
    -PreviousPgStartPolicy absent `
    -PreviousBackendStartPolicy absent `
    -BackupRequired $false `
    -BackupCompleted $false `
    -PreparationStage captured
$receiptBytesBefore = [Convert]::ToBase64String(
    [IO.File]::ReadAllBytes('{_literal(receipt_path)}')
)
$receiptAclBefore = Get-TestAclFingerprint '{_literal(receipt_path)}'
$receiptWriteTimeBefore =
    (Get-Item -LiteralPath '{_literal(receipt_path)}' -Force).LastWriteTimeUtc.Ticks
$markerPath = Get-TicketboxDataRootMarkerPath '{_literal(data_root)}'
$markerBytesBefore = [Convert]::ToBase64String([IO.File]::ReadAllBytes($markerPath))
$markerWriteTimeBefore = (Get-Item -LiteralPath $markerPath -Force).LastWriteTimeUtc.Ticks
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(data_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -Recurse
$residualAcl = Get-TicketboxPathAcl $markerPath
if (
    $residualAcl.AreAccessRulesProtected -or
    @($residualAcl.Access | Where-Object {{ -not $_.IsInherited }}).Count -ne 0
) {{
    throw 'test did not reproduce the stale fresh marker residual'
}}
{early_marker_repair}
Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded `
    -DataRoot '{_literal(data_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$staleReceipt = Read-TicketboxCompatibleLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.2.0 `
    -InstallerOwnerProcessId $PID `
    -AllowPreviousInstallerOwnerProcessId
if (
    [string]$staleReceipt.mode -cne 'fresh_install' -or
    [string]$staleReceipt.preparation_stage -cne 'captured' -or
    [int]$staleReceipt.installer_owner_process_id -ne $previousOwner
) {{
    throw 'stale fresh receipt was not read with its original authority'
}}
$DataRoot = '{_literal(data_root)}'
$InstallDir = '{_literal(install_dir)}'
$script:recoveryReached = $false
function Restore-PreviousServiceState {{
    param(
        [bool]$BackendWasRunning,
        [bool]$PgWasRunning,
        [string]$BackendStartPolicy,
        [string]$PgStartPolicy
    )
    if (
        $BackendWasRunning -or $PgWasRunning -or
        $BackendStartPolicy -cne 'absent' -or $PgStartPolicy -cne 'absent'
    ) {{
        throw 'fresh stale receipt changed absent service state'
    }}
    $script:recoveryReached = $true
}}
{prepared_recovery}
Invoke-TicketboxPreparedInstallRecovery `
    -Receipt $staleReceipt `
    -ProgramFilesWereReplaced $false
$markerAclAfter = Get-TicketboxPathAcl $markerPath
if (
    -not $script:recoveryReached -or
    -not $markerAclAfter.AreAccessRulesProtected -or
    @($markerAclAfter.Access | Where-Object {{ $_.IsInherited }}).Count -ne 0 -or
    [Convert]::ToBase64String([IO.File]::ReadAllBytes($markerPath)) -cne
        $markerBytesBefore -or
    (Get-Item -LiteralPath $markerPath -Force).LastWriteTimeUtc.Ticks -ne
        $markerWriteTimeBefore -or
    [Convert]::ToBase64String([IO.File]::ReadAllBytes('{_literal(receipt_path)}')) -cne
        $receiptBytesBefore -or
    (Get-TestAclFingerprint '{_literal(receipt_path)}') -cne $receiptAclBefore -or
    (Get-Item -LiteralPath '{_literal(receipt_path)}' -Force).LastWriteTimeUtc.Ticks -ne
        $receiptWriteTimeBefore
) {{
    throw 'early repair did not preserve receipt and marker authority through recovery'
}}
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows recovery marker authority contract")
def test_recovery_marker_refuses_to_create_installer_state_without_data_root_authority(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    install_dir = tmp_path / "program"
    untrusted_fresh_root = tmp_path / "untrusted-fresh"
    forged_root_acl = tmp_path / "forged-root-acl"
    forged_marker_acl = tmp_path / "forged-marker-acl"
    legacy_v1_root = tmp_path / "legacy-v1-root"
    wrong_volume_root = tmp_path / "wrong-volume-root"
    runtime_binding_parent = tmp_path / "runtime-binding-parent"
    trusted_fresh_root = tmp_path / "trusted-fresh"
    recoverable_fresh_root = tmp_path / "recoverable-fresh"
    machine_state_root = tmp_path / "machine-lifecycle"
    marker_path = machine_state_root / "installer-state" / "installer-recovery-required.json"
    data_root.mkdir()
    install_dir.mkdir()
    untrusted_fresh_root.mkdir()
    (untrusted_fresh_root / "unknown.txt").write_text("untrusted", encoding="utf-8")
    forged_root_acl.mkdir()
    (forged_root_acl / "unknown.txt").write_text("untrusted", encoding="utf-8")
    forged_marker_acl.mkdir()
    (forged_marker_acl / "unknown.txt").write_text("untrusted", encoding="utf-8")
    legacy_v1_root.mkdir()
    wrong_volume_root.mkdir()
    runtime_binding_parent.mkdir()
    trusted_fresh_root.mkdir()
    recoverable_fresh_root.mkdir()
    machine_state_root.mkdir()
    prepare = _read("prepare_bundled_upgrade.ps1")
    authority_gate = prepare[
        prepare.index("function Assert-TicketboxPreparedDataRootAuthorityGate") : prepare.index(
            "function Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded"
        )
    ]
    early_marker_repair = prepare[
        prepare.index("function Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded") :
        prepare.index("Set-TicketboxInstalledReleaseConfiguration -Config $InstalledReleaseConfig")
    ]
    recovery_initializer = prepare[
        prepare.index("function Initialize-TicketboxRecoveryStateArtifact") : prepare.index(
            "function Assert-TicketboxPgStoppedForFailSafeRecovery"
        )
    ]
    wrong_volume_identity = r"\\?\Volume{00000000-0000-0000-0000-000000000000}" + "\\"
    harness = tmp_path / "marker-authority.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_installation_safety.ps1')}'
. '{_literal(PACKAGING / 'windows_lifecycle_receipt.ps1')}'
{authority_gate}
{early_marker_repair}
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxLifecycleReceiptAclAccounts = @($currentAccount)
$script:TicketboxLifecycleReceiptOwnerAccount = $currentAccount
function Get-TicketboxTestAclFingerprint([string]$Path) {{
    $acl = Get-TicketboxPathAcl $Path
    $rules = @($acl.Access | ForEach-Object {{
        [string]::Join(':', @(
            $_.IdentityReference.Value,
            [string]$_.AccessControlType,
            [string][int64]$_.FileSystemRights,
            [string]$_.InheritanceFlags,
            [string]$_.PropagationFlags,
            [string]$_.IsInherited
        ))
    }} | Sort-Object)
    return [string]::Join('|', @(
        $acl.Owner,
        [string]$acl.AreAccessRulesProtected,
        ($rules -join ',')
    ))
}}
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(machine_state_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(recoverable_fresh_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Write-TicketboxDataRootMarker `
    -DataRoot '{_literal(recoverable_fresh_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$recoverableMarker = Get-TicketboxDataRootMarkerPath '{_literal(recoverable_fresh_root)}'
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(recoverable_fresh_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -Recurse
$recoverableBeforeAcl = Get-TicketboxPathAcl $recoverableMarker
if (
    $recoverableBeforeAcl.AreAccessRulesProtected -or
    @($recoverableBeforeAcl.Access | Where-Object {{ -not $_.IsInherited }}).Count -ne 0
) {{
    throw 'test did not reproduce the trusted recursive-reset marker residual'
}}
$recoverableBytesBefore = [Convert]::ToBase64String(
    [IO.File]::ReadAllBytes($recoverableMarker)
)
$recoverableWriteTimeBefore =
    (Get-Item -LiteralPath $recoverableMarker -Force).LastWriteTimeUtc.Ticks
$recoverableRootSddlBefore = Get-TicketboxTestAclFingerprint `
    '{_literal(recoverable_fresh_root)}'
$recoverableEntriesBefore = @(
    Get-ChildItem -LiteralPath '{_literal(recoverable_fresh_root)}' -Force |
        ForEach-Object {{ $_.Name }} |
        Sort-Object
) -join '|'
Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded `
    -DataRoot '{_literal(recoverable_fresh_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Assert-TicketboxPreparedDataRootAuthorityGate `
    -Mode 'fresh_install' `
    -DataRoot '{_literal(recoverable_fresh_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$recoverableAfterAcl = Get-TicketboxPathAcl $recoverableMarker
if (
    -not $recoverableAfterAcl.AreAccessRulesProtected -or
    @($recoverableAfterAcl.Access | Where-Object {{ $_.IsInherited }}).Count -ne 0 -or
    [Convert]::ToBase64String([IO.File]::ReadAllBytes($recoverableMarker)) -cne
        $recoverableBytesBefore -or
    (Get-Item -LiteralPath $recoverableMarker -Force).LastWriteTimeUtc.Ticks -ne
        $recoverableWriteTimeBefore -or
    (Get-TicketboxTestAclFingerprint '{_literal(recoverable_fresh_root)}') -cne
        $recoverableRootSddlBefore -or
    (@(Get-ChildItem -LiteralPath '{_literal(recoverable_fresh_root)}' -Force |
        ForEach-Object {{ $_.Name }} | Sort-Object) -join '|') -cne
        $recoverableEntriesBefore
) {{
    throw 'fresh gate did not narrowly and idempotently repair only the marker ACL'
}}
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(legacy_v1_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$legacyMarkerText = Get-TicketboxDataRootMarkerText `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -LegacyV1
Write-TicketboxProtectedUtf8FileDurable `
    -Path (Get-TicketboxDataRootMarkerPath '{_literal(legacy_v1_root)}') `
    -Text $legacyMarkerText `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$legacyFreshRejected = $false
try {{
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode 'fresh_install' `
        -DataRoot '{_literal(legacy_v1_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $legacyFreshRejected = $true }}
if (-not $legacyFreshRejected) {{ throw 'fresh install accepted a legacy v1 marker' }}
Assert-TicketboxDataRootMarker `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -AllowLegacyV1
function Get-TicketboxProtectedProfileRoots {{ return @() }}
Initialize-TicketboxDataRootMarker `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -AllowLegacyV1Migration `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$migratedMarker = Get-Content `
    -LiteralPath (Get-TicketboxDataRootMarkerPath '{_literal(legacy_v1_root)}') `
    -Encoding UTF8 `
    -Raw | ConvertFrom-Json
if (
    $migratedMarker.schema -cne 'ticketbox-data-root-v2' -or
    $migratedMarker.data_volume_identity -cne
        (Get-TicketboxVolumeIdentityForPath '{_literal(legacy_v1_root)}')
) {{
    throw 'legacy marker was not atomically migrated to the current volume-bound schema'
}}
Assert-TicketboxPreparedDataRootAuthorityGate `
    -Mode 'fresh_install' `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$interruptedBindingDirectory = Get-TicketboxRuntimeDataBindingDirectory `
    '{_literal(runtime_binding_parent)}'
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path $interruptedBindingDirectory `
    -FullControlAccounts @($currentAccount) `
    -InheritableReadExecuteAccounts @('BUILTIN\\Users') `
    -OwnerAccount $currentAccount | Out-Null
if (Test-Path -LiteralPath (Get-TicketboxRuntimeDataRootPath '{_literal(runtime_binding_parent)}')) {{
    throw 'runtime binding provisioning probe unexpectedly created the junction'
}}
$runtimeBinding = Initialize-TicketboxRuntimeDataBinding `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -ServiceReadExecuteAccounts @('BUILTIN\\Users') `
    -CommonApplicationData '{_literal(runtime_binding_parent)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
if (
    -not (Test-TicketboxPathEquals $runtimeBinding.RuntimeAppData (Join-Path $runtimeBinding.RuntimeDataRoot 'app')) -or
    $runtimeBinding.DataVolumeIdentity -cne
        (Get-TicketboxVolumeIdentityForPath '{_literal(legacy_v1_root)}')
) {{
    throw 'runtime binding did not project the v2 marker volume'
}}
$wrongRuntimeTarget = Get-TicketboxVolumeBoundDataRootPath `
    -DataRoot '{_literal(wrong_volume_root)}' `
    -DataVolumeIdentity (Get-TicketboxVolumeIdentityForPath '{_literal(wrong_volume_root)}')
[System.IO.Directory]::Delete($runtimeBinding.RuntimeDataRoot)
New-Item `
    -ItemType Junction `
    -Path $runtimeBinding.RuntimeDataRoot `
    -Target $wrongRuntimeTarget | Out-Null
$retargetRejected = $false
try {{
    Read-TicketboxRuntimeDataBinding `
        -DataRoot '{_literal(legacy_v1_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -ServiceReadExecuteAccounts @('BUILTIN\\Users') `
        -CommonApplicationData '{_literal(runtime_binding_parent)}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
catch {{ $retargetRejected = $true }}
if (-not $retargetRejected) {{ throw 'retargeted runtime DataRoot junction was accepted' }}
[System.IO.Directory]::Delete($runtimeBinding.RuntimeDataRoot)
$runtimeBinding = Initialize-TicketboxRuntimeDataBinding `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -ServiceReadExecuteAccounts @('BUILTIN\\Users') `
    -CommonApplicationData '{_literal(runtime_binding_parent)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Remove-TicketboxRuntimeDataBinding `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -ServiceReadExecuteAccounts @('BUILTIN\\Users') `
    -CommonApplicationData '{_literal(runtime_binding_parent)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
if (
    (Test-Path -LiteralPath $runtimeBinding.BindingDirectory) -or
    -not (Test-Path -LiteralPath '{_literal(legacy_v1_root)}' -PathType Container)
) {{
    throw 'runtime binding retirement removed the target or left machine state'
}}
$runtimeBinding = Initialize-TicketboxRuntimeDataBinding `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -ServiceReadExecuteAccounts @('BUILTIN\\Users') `
    -CommonApplicationData '{_literal(runtime_binding_parent)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
[System.IO.Directory]::Delete($runtimeBinding.RuntimeDataRoot)
Remove-TicketboxRuntimeDataBinding `
    -DataRoot '{_literal(legacy_v1_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -ServiceReadExecuteAccounts @('BUILTIN\\Users') `
    -CommonApplicationData '{_literal(runtime_binding_parent)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
if (
    (Test-Path -LiteralPath $runtimeBinding.BindingDirectory) -or
    -not (Test-Path -LiteralPath '{_literal(legacy_v1_root)}' -PathType Container)
) {{
    throw 'interrupted runtime binding retirement was not reentrant'
}}
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(wrong_volume_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$wrongVolumeMarkerText = Get-TicketboxDataRootMarkerText `
    -DataRoot '{_literal(wrong_volume_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataVolumeIdentity '{_literal(wrong_volume_identity)}'
Write-TicketboxProtectedUtf8FileDurable `
    -Path (Get-TicketboxDataRootMarkerPath '{_literal(wrong_volume_root)}') `
    -Text $wrongVolumeMarkerText `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$wrongVolumeRejected = $false
try {{
    Assert-TicketboxProtectedDataRootMarker `
        -DataRoot '{_literal(wrong_volume_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $wrongVolumeRejected = $true }}
if (-not $wrongVolumeRejected) {{ throw 'volume-bound marker was accepted on another volume' }}
$freshRejected = $false
try {{
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode 'fresh_install' `
        -DataRoot '{_literal(untrusted_fresh_root)}' `
        -InstallDir '{_literal(install_dir)}'
}}
catch {{
    if ($_.Exception.Message -cne 'fresh install 只接受 holder 已发布权威 marker 的新 DataRoot；拒绝收编非空 markerless 目录。') {{ throw }}
    $freshRejected = $true
}}
if (-not $freshRejected) {{ throw 'markerless non-empty fresh DataRoot was accepted' }}
$markerlessRepairRejected = $false
try {{
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode 'repair_install' `
        -DataRoot '{_literal(untrusted_fresh_root)}' `
        -InstallDir '{_literal(install_dir)}'
}}
catch {{
    if ($_.Exception.Message -cne '既有 DataRoot 缺少 v1/v2 marker；普通安装器拒绝重新铸造权威，请使用独立隔离恢复/导入流程。') {{ throw }}
    $markerlessRepairRejected = $true
}}
if (-not $markerlessRepairRejected) {{
    throw 'markerless repair minted authority on the currently mounted volume'
}}
$markerlessPreservedRejected = $false
try {{
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode 'preserved_data_reinstall' `
        -DataRoot '{_literal(untrusted_fresh_root)}' `
        -InstallDir '{_literal(install_dir)}'
}}
catch {{
    if ($_.Exception.Message -cne '既有 DataRoot 缺少 v1/v2 marker；普通安装器拒绝重新铸造权威，请使用独立隔离恢复/导入流程。') {{ throw }}
    $markerlessPreservedRejected = $true
}}
if (-not $markerlessPreservedRejected) {{
    throw 'markerless preserved reinstall minted authority from directory shape'
}}
$markerlessUpgradeRejected = $false
try {{
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode 'upgrade' `
        -DataRoot '{_literal(untrusted_fresh_root)}' `
        -InstallDir '{_literal(install_dir)}'
}}
catch {{
    if ($_.Exception.Message -cne '既有 DataRoot 缺少 v1/v2 marker；普通安装器拒绝重新铸造权威，请使用独立隔离恢复/导入流程。') {{ throw }}
    $markerlessUpgradeRejected = $true
}}
if (-not $markerlessUpgradeRejected) {{
    throw 'markerless upgrade minted authority from directory shape'
}}
Write-TicketboxDataRootMarker `
    -DataRoot '{_literal(forged_root_acl)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$forgedRootAclRejected = $false
try {{
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode 'fresh_install' `
        -DataRoot '{_literal(forged_root_acl)}' `
        -InstallDir '{_literal(install_dir)}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $forgedRootAclRejected = $true }}
if (-not $forgedRootAclRejected) {{ throw 'fresh DataRoot with untrusted root ACL was accepted' }}
$forgedMarkerPayload = [ordered]@{{
    schema = $script:TicketboxDataRootMarkerSchema
    data_root = [System.IO.Path]::GetFullPath('{_literal(forged_marker_acl)}')
    install_dir = [System.IO.Path]::GetFullPath('{_literal(install_dir)}')
}} | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText(
    (Get-TicketboxDataRootMarkerPath '{_literal(forged_marker_acl)}'),
    $forgedMarkerPayload,
    (New-Object System.Text.UTF8Encoding($false))
)
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(forged_marker_acl)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$forgedMarkerAclRejected = $false
try {{
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode 'fresh_install' `
        -DataRoot '{_literal(forged_marker_acl)}' `
        -InstallDir '{_literal(install_dir)}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $forgedMarkerAclRejected = $true }}
if (-not $forgedMarkerAclRejected) {{ throw 'fresh DataRoot with untrusted marker ACL was accepted' }}
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(trusted_fresh_root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Write-TicketboxDataRootMarker `
    -DataRoot '{_literal(trusted_fresh_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Assert-TicketboxPreparedDataRootAuthorityGate `
    -Mode 'fresh_install' `
    -DataRoot '{_literal(trusted_fresh_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$rejected = $false
try {{
    Write-TicketboxInstallerRecoveryMarker `
        -Path '{_literal(marker_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -Reason 'must fail before authority exists'
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'markerless data root was accepted' }}
if (Test-Path -LiteralPath '{_literal(machine_state_root / "installer-state")}') {{
    throw 'failed recovery write created installer-state before data-root authority'
}}

{recovery_initializer}
$DataRoot = '{_literal(data_root)}'
$InstallDir = '{_literal(install_dir)}'
$InstallerState = '{_literal(machine_state_root / "installer-state")}'
$LegacyRecoveryRequiredPath = Join-Path (Join-Path $DataRoot 'app') 'installer-recovery-required.json'
$script:OriginalInstallerStateInitializer = ${{function:Initialize-TicketboxInstallerStateDirectory}}
function Initialize-TicketboxInstallerStateDirectory {{
    param([Parameter(Mandatory = $true)][string]$Path)
    & $script:OriginalInstallerStateInitializer `
        -Path $Path `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
Initialize-TicketboxInstallerStateDirectory $InstallerState | Out-Null
Initialize-TicketboxRecoveryStateArtifact
Write-TicketboxProtectedUtf8FileDurable `
    -Path (Join-Path $InstallerState 'owner-handoff-pending') `
    -Text 'machine-state-without-data-root-authority' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$nonEmptyRejected = $false
try {{ Initialize-TicketboxRecoveryStateArtifact }}
catch {{ $nonEmptyRejected = $true }}
if (-not $nonEmptyRejected) {{
    throw 'non-empty machine installer-state was accepted without data-root authority'
}}
Remove-Item -LiteralPath $DataRoot -Force
$missingDataRootRejected = $false
try {{ Initialize-TicketboxRecoveryStateArtifact }}
catch {{ $missingDataRootRejected = $true }}
if (-not $missingDataRootRejected) {{
    throw 'non-empty machine installer-state was accepted without a data root'
}}
New-Item -ItemType Directory -Path $DataRoot | Out-Null
Remove-Item -LiteralPath (Join-Path $InstallerState 'owner-handoff-pending') -Force
New-Item -ItemType Directory -Path (Split-Path -Parent $LegacyRecoveryRequiredPath) -Force | Out-Null
New-Item -ItemType Directory -Path $LegacyRecoveryRequiredPath | Out-Null
$legacyNonFileRejected = $false
try {{ Initialize-TicketboxRecoveryStateArtifact }}
catch {{ $legacyNonFileRejected = $true }}
if (-not $legacyNonFileRejected) {{
    throw 'legacy non-file recovery state was treated as absent'
}}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        shutil.rmtree(machine_state_root / "installer-state", ignore_errors=True)
        shutil.rmtree(data_root / "app", ignore_errors=True)
        (forged_root_acl / ".ticketbox-data-root.json").unlink(missing_ok=True)
        (forged_marker_acl / ".ticketbox-data-root.json").unlink(missing_ok=True)
        (legacy_v1_root / ".ticketbox-data-root.json").unlink(missing_ok=True)
        (wrong_volume_root / ".ticketbox-data-root.json").unlink(missing_ok=True)
        (trusted_fresh_root / ".ticketbox-data-root.json").unlink(missing_ok=True)
        (recoverable_fresh_root / ".ticketbox-data-root.json").unlink(missing_ok=True)
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL and PowerShell contract")
def test_lifecycle_receipt_roundtrip_is_bound_to_install_inputs(tmp_path: Path) -> None:
    engines = powershell_contract_engines()
    config = json.loads(_read("windows-release-config.json"))

    for index, engine in enumerate(engines):
        root = tmp_path / f"receipt-{index}"
        data_root = Path(os.environ["PROGRAMDATA"]) / f"TicketboxReceiptTest-{uuid.uuid4().hex}"
        other_data_root = Path(os.environ["PROGRAMDATA"]) / f"TicketboxReceiptTest-{uuid.uuid4().hex}"
        install_dir = root / "program"
        backup_root = data_root / "installer-backups"
        data_root.mkdir(parents=True)
        other_data_root.mkdir(parents=True)
        backup_path = backup_root / "pre-upgrade.dump"
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
Set-TicketboxExactDirectoryAcl `
    -Path '{_literal(root)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Initialize-TicketboxDataRootMarker `
    -DataRoot '{_literal(data_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
New-Item -ItemType Directory -Path '{_literal(backup_root)}' | Out-Null
[System.IO.File]::WriteAllBytes(
    '{_literal(backup_path)}',
    [System.Text.Encoding]::UTF8.GetBytes('verified-backup')
)
$markerPath = '{_literal(root / "installer-state" / "installer-recovery-required.json")}'
Write-TicketboxInstallerRecoveryMarker `
    -Path $markerPath `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -Reason 'first reason'
$originalMarkerBytes = [System.IO.File]::ReadAllBytes($markerPath)
Initialize-TicketboxDataRootMarker `
    -DataRoot '{_literal(other_data_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$crossBindingRejected = $false
try {{
    Write-TicketboxInstallerRecoveryMarker -Path $markerPath -InstallDir '{_literal(install_dir)}' -DataRoot '{_literal(other_data_root)}' -Reason 'wrong installation'
}}
catch {{ $crossBindingRejected = $true }}
if (-not $crossBindingRejected) {{ throw 'machine recovery marker accepted another data-root binding' }}
$unchanged = Read-TicketboxInstallerRecoveryMarker -Path $markerPath -InstallDir '{_literal(install_dir)}' -DataRoot '{_literal(data_root)}' -ExpectedReason 'first reason'
Write-TicketboxInstallerRecoveryMarker `
    -Path $markerPath `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -Reason 'replacement reason'
Assert-TicketboxExactFileAcl `
    -Path $markerPath `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$marker = Get-Content -LiteralPath $markerPath -Encoding UTF8 -Raw | ConvertFrom-Json
if ($marker.reason -cne 'first reason' -or
    $marker.schema -cne 'ticketbox-installer-recovery-required-v1' -or
    -not $marker.files_may_have_been_replaced -or
    -not (Test-TicketboxByteArrayEquals $originalMarkerBytes ([System.IO.File]::ReadAllBytes($markerPath)))) {{
    throw 'recovery marker was replaced instead of preserving first-failure authority'
}}
if (@(Get-ChildItem -LiteralPath (Split-Path -Parent $markerPath) -Filter '.ticketbox-protected-*.tmp').Count -ne 0) {{
    throw 'recovery marker left a durable temporary file'
}}
Remove-TicketboxInstallerRecoveryMarker `
    -Path $markerPath `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}'
[System.IO.File]::WriteAllBytes($markerPath, [byte[]](0xC3, 0x28))
Set-TicketboxExactFileAcl `
    -Path $markerPath `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$invalidUtf8Rejected = $false
try {{
    Read-TicketboxInstallerRecoveryMarker `
        -Path $markerPath `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' | Out-Null
}}
catch {{ $invalidUtf8Rejected = $true }}
if (-not $invalidUtf8Rejected -or -not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {{
    throw 'invalid UTF-8 recovery marker was accepted or destroyed'
}}
Remove-Item -LiteralPath $markerPath -Force
Write-TicketboxProtectedUtf8FileDurable `
    -Path $markerPath `
    -Text ('x' * 16385) `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$oversizedRejected = $false
try {{
    Read-TicketboxInstallerRecoveryMarker `
        -Path $markerPath `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' | Out-Null
}}
catch {{ $oversizedRejected = $true }}
if (-not $oversizedRejected -or -not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {{
    throw 'oversized recovery marker was accepted or destroyed'
}}
Remove-Item -LiteralPath $markerPath -Force
New-Item -ItemType Directory -Path $markerPath | Out-Null
$nonFileRemoveRejected = $false
try {{
    Remove-TicketboxInstallerRecoveryMarker `
        -Path $markerPath `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}'
}}
catch {{ $nonFileRemoveRejected = $true }}
$nonFileWriteRejected = $false
try {{
    Write-TicketboxInstallerRecoveryMarker `
        -Path $markerPath `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -Reason 'must not replace a directory'
}}
catch {{ $nonFileWriteRejected = $true }}
if (-not $nonFileRemoveRejected -or -not $nonFileWriteRejected) {{
    throw 'non-file recovery marker was treated as absent'
}}
Remove-Item -LiteralPath $markerPath -Force
$danglingTarget = Join-Path '{_literal(root)}' 'dangling-recovery-target'
New-Item -ItemType Directory -Path $danglingTarget | Out-Null
New-Item -ItemType Junction -Path $markerPath -Target $danglingTarget | Out-Null
Remove-Item -LiteralPath $danglingTarget -Recurse -Force
$danglingRemoveRejected = $false
try {{
    Remove-TicketboxInstallerRecoveryMarker `
        -Path $markerPath `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}'
}}
catch {{ $danglingRemoveRejected = $true }}
$danglingWriteRejected = $false
try {{
    Write-TicketboxInstallerRecoveryMarker `
        -Path $markerPath `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -Reason 'must not follow dangling junction'
}}
catch {{ $danglingWriteRejected = $true }}
if (-not $danglingRemoveRejected -or -not $danglingWriteRejected -or
    (Get-TicketboxPathEntryKindNoFollow $markerPath) -cne 'Reparse') {{
    throw 'dangling recovery marker was treated as absent or mutated'
}}
[System.IO.Directory]::Delete($markerPath)
Set-TicketboxExactFileAcl `
    -Path '{_literal(backup_path)}' `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
function Set-TestBackupContent([string]$Text) {{
    [System.IO.File]::WriteAllBytes(
        '{_literal(backup_path)}',
        [System.Text.Encoding]::UTF8.GetBytes($Text)
    )
    Set-TicketboxExactFileAcl `
        -Path '{_literal(backup_path)}' `
        -Accounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
function Set-TestReceiptLegacyV7 {{
    $legacyReceipt = Get-Content `
        -LiteralPath '{_literal(receipt_path)}' `
        -Encoding UTF8 `
        -Raw | ConvertFrom-Json
    $legacyReceipt.schema = 'ticketbox-windows-lifecycle-receipt-v7'
    $legacyReceipt.PSObject.Properties.Remove('target_backend_version_floor')
    Write-TicketboxProtectedUtf8FileDurable `
        -Path '{_literal(receipt_path)}' `
        -Text ($legacyReceipt | ConvertTo-Json -Depth 20 -Compress) `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount `
        -ReplaceExisting
}}
function Convert-TestLegacyReceipt(
    [string]$ExpectedStage,
    [int]$InstallerOwnerProcessId,
    [switch]$AllowPreviousInstallerOwnerProcessId
) {{
    Set-TestReceiptLegacyV7
    $legacyBytes = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
    $implicitLegacyReadRejected = $false
    try {{
        Read-TicketboxLifecycleReceipt `
            -Path '{_literal(receipt_path)}' `
            -InstallDir '{_literal(install_dir)}' `
            -DataRoot '{_literal(data_root)}' `
            -PgPort 5544 `
            -BackendPort 8765 `
            -TargetReleaseConfig $config `
            -CurrentTargetBackendVersion 1.3.0 `
            -InstallerOwnerProcessId $InstallerOwnerProcessId `
            -AllowPreviousInstallerOwnerProcessId:$AllowPreviousInstallerOwnerProcessId | Out-Null
    }}
    catch {{ $implicitLegacyReadRejected = $true }}
    if (
        -not $implicitLegacyReadRejected -or
        -not (Test-TicketboxByteArrayEquals `
            $legacyBytes `
            ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))
    ) {{
        throw "legacy $ExpectedStage receipt was accepted without migration or mutated first"
    }}
    $compatibleReceipt = Read-TicketboxCompatibleLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.3.0 `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -AllowPreviousInstallerOwnerProcessId:$AllowPreviousInstallerOwnerProcessId
    if (
        [string]$compatibleReceipt.schema -cne 'ticketbox-windows-lifecycle-receipt-v7' -or
        [string]$compatibleReceipt.preparation_stage -cne $ExpectedStage -or
        -not (Test-TicketboxByteArrayEquals `
            $legacyBytes `
            ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))
    ) {{
        throw "legacy $ExpectedStage receipt was not classified without mutation"
    }}
    Close-TicketboxLifecycleBackupGuard $compatibleReceipt
    $migratedReceipt = ConvertTo-TicketboxCurrentLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.3.0 `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -AllowPreviousInstallerOwnerProcessId:$AllowPreviousInstallerOwnerProcessId
    if (
        [string]$migratedReceipt.schema -cne 'ticketbox-windows-lifecycle-receipt-v8' -or
        [string]$migratedReceipt.target_backend_version_floor -cne '1.3.0' -or
        [string]$migratedReceipt.preparation_stage -cne $ExpectedStage -or
        [int]$migratedReceipt.installer_owner_process_id -ne $InstallerOwnerProcessId
    ) {{
        throw "legacy $ExpectedStage receipt migration lost lifecycle authority"
    }}
    return $migratedReceipt
}}
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
foreach ($version in @('0.2.3', '65535.0.0')) {{
    $parsedVersion = ConvertTo-TicketboxLifecycleVersion $version
    if ([string]$parsedVersion.Canonical -cne $version) {{
        throw "supported lifecycle version changed identity: $version"
    }}
}}
foreach ($version in @('01.2.3', '1.02.3', '1.2.3.04', '000000.2.3', '65536.0.0')) {{
    $invalidVersionRejected = $false
    try {{ ConvertTo-TicketboxLifecycleVersion $version | Out-Null }}
    catch {{ $invalidVersionRejected = $true }}
    if (-not $invalidVersionRejected) {{
        throw "unsupported lifecycle version was accepted: $version"
    }}
}}
Write-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -Mode upgrade `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -InstalledReleaseConfig $config `
    -TargetBackendVersionFloor 1.3.0 `
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
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId $PID
$dataRootAuthority = Read-TicketboxProtectedDataRootMarker `
    -DataRoot '{_literal(data_root)}' `
    -InstallDir '{_literal(install_dir)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$capturedReceiptJson = Get-Content `
    -LiteralPath '{_literal(receipt_path)}' `
    -Encoding UTF8 `
    -Raw | ConvertFrom-Json
if (
    $capturedReceiptJson.schema -cne 'ticketbox-windows-lifecycle-receipt-v8' -or
    $capturedReceiptJson.target_backend_version_floor -cne '1.3.0' -or
    $capturedReceiptJson.data_volume_identity -cne $dataRootAuthority.DataVolumeIdentity
) {{
    throw 'lifecycle receipt did not durably bind the v2 DataRoot volume authority'
}}
$capturedReceiptText = Get-Content `
    -LiteralPath '{_literal(receipt_path)}' `
    -Encoding UTF8 `
    -Raw
Set-TestReceiptLegacyV7
$legacyCapturedText = Get-Content `
    -LiteralPath '{_literal(receipt_path)}' `
    -Encoding UTF8 `
    -Raw
$malformedLegacy = $legacyCapturedText | ConvertFrom-Json
$malformedLegacy.files_may_have_been_replaced = $true
Write-TicketboxProtectedUtf8FileDurable `
    -Path '{_literal(receipt_path)}' `
    -Text ($malformedLegacy | ConvertTo-Json -Depth 20 -Compress) `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
$malformedLegacyBytes = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
$malformedLegacyRejected = $false
try {{
    ConvertTo-TicketboxCurrentLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.3.0 `
        -InstallerOwnerProcessId $PID | Out-Null
}}
catch {{ $malformedLegacyRejected = $true }}
if (
    -not $malformedLegacyRejected -or
    -not (Test-TicketboxByteArrayEquals `
        $malformedLegacyBytes `
        ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))
) {{
    throw 'malformed legacy receipt was accepted or mutated before rejection'
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path '{_literal(receipt_path)}' `
    -Text $capturedReceiptText `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
$capturedReceipt = Convert-TestLegacyReceipt `
    -ExpectedStage captured `
    -InstallerOwnerProcessId $PID
$dataRootMarkerPath = Get-TicketboxDataRootMarkerPath '{_literal(data_root)}'
$dataRootMarkerText = Get-Content -LiteralPath $dataRootMarkerPath -Encoding UTF8 -Raw
$receiptBytesBeforeAuthorityFailure = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
Remove-Item -LiteralPath $dataRootMarkerPath -Force
$missingDataRootAuthorityRejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.3.0 `
        -InstallerOwnerProcessId $PID | Out-Null
}}
catch {{ $missingDataRootAuthorityRejected = $true }}
if (
    -not $missingDataRootAuthorityRejected -or
    -not (Test-TicketboxByteArrayEquals `
        $receiptBytesBeforeAuthorityFailure `
        ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))
) {{
    throw 'lifecycle receipt recovery accepted missing volume authority or mutated state first'
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path $dataRootMarkerPath `
    -Text $dataRootMarkerText `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$originalReceiptText = Get-Content -LiteralPath '{_literal(receipt_path)}' -Encoding UTF8 -Raw
$forgedReceipt = $originalReceiptText | ConvertFrom-Json
$forgedReceipt.data_volume_identity = '\\\\?\\Volume{{00000000-0000-0000-0000-000000000000}}\\'
Write-TicketboxProtectedUtf8FileDurable `
    -Path '{_literal(receipt_path)}' `
    -Text ($forgedReceipt | ConvertTo-Json -Depth 20 -Compress) `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
$forgedReceiptBytes = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
$wrongVolumeReceiptRejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.3.0 `
        -InstallerOwnerProcessId $PID | Out-Null
}}
catch {{ $wrongVolumeReceiptRejected = $true }}
if (
    -not $wrongVolumeReceiptRejected -or
    -not (Test-TicketboxByteArrayEquals `
        $forgedReceiptBytes `
        ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))
) {{
    throw 'lifecycle receipt accepted a forged volume or mutated it before rejection'
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path '{_literal(receipt_path)}' `
    -Text $originalReceiptText `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
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
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId $PID
if ($receipt.mode -ne 'upgrade' -or
    $receipt.target_backend_version_floor -cne '1.3.0' -or
    -not $receipt.backup_completed -or
    $receipt.backup_sha256 -cnotmatch '^[0-9A-F]{{64}}$' -or
    [long]$receipt.backup_byte_length -ne 15 -or
    $receipt.preparation_stage -ne 'prepared' -or
    $receipt.previous_pg_start_policy -ne 'delayed_auto' -or
    $receipt.previous_backend_start_policy -ne 'manual') {{
    throw 'receipt mode, policy, or backup changed'
}}
Close-TicketboxLifecycleBackupGuard $receipt
$receipt = Convert-TestLegacyReceipt `
    -ExpectedStage prepared `
    -InstallerOwnerProcessId $PID
if (-not $receipt.backup_completed -or
    $receipt.backup_sha256 -cnotmatch '^[0-9A-F]{{64}}$' -or
    [long]$receipt.backup_byte_length -ne 15 -or
    $receipt.previous_pg_start_policy -cne 'delayed_auto' -or
    $receipt.previous_backend_start_policy -cne 'manual') {{
    throw 'legacy prepared migration discarded backup or service policy evidence'
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
        -TargetBackendVersionFloor 1.3.0 `
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
        -CurrentTargetBackendVersion 1.3.0 `
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
Close-TicketboxLifecycleBackupGuard $receipt
$staleReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId ($PID + 1) `
    -AllowPreviousInstallerOwnerProcessId
$backupMutationBlocked = $false
try {{ Set-TestBackupContent 'tampered-backup' }}
catch {{ $backupMutationBlocked = $true }}
if (-not $backupMutationBlocked) {{
    throw 'validated backup was mutable between preflight and recovery transition'
}}
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
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId ($PID + 1)
if (-not $repairReceipt.files_may_have_been_replaced -or
    $repairReceipt.target_backend_version_floor -cne '1.3.0' -or
    $repairReceipt.previous_pg_state -ne 'running' -or
    $repairReceipt.previous_backend_state -ne 'running' -or
    $repairReceipt.previous_pg_start_policy -ne 'delayed_auto' -or
    $repairReceipt.previous_backend_start_policy -ne 'manual' -or
    -not $repairReceipt.backup_completed -or
    $repairReceipt.backup_path -ne [System.IO.Path]::GetFullPath('{_literal(backup_path)}') -or
    $repairReceipt.backup_sha256 -cne $receipt.backup_sha256 -or
    [long]$repairReceipt.backup_byte_length -ne [long]$receipt.backup_byte_length) {{
    throw 'repair rebind discarded previous state or backup evidence'
}}
Close-TicketboxLifecycleBackupGuard $repairReceipt
$repairReceipt = Convert-TestLegacyReceipt `
    -ExpectedStage files_may_have_been_replaced `
    -InstallerOwnerProcessId ($PID + 1)
if (-not $repairReceipt.files_may_have_been_replaced -or
    -not $repairReceipt.backup_completed -or
    $repairReceipt.backup_sha256 -cne $receipt.backup_sha256 -or
    [long]$repairReceipt.backup_byte_length -ne [long]$receipt.backup_byte_length) {{
    throw 'legacy post-copy migration discarded recovery or backup evidence'
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
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId ($PID + 2)
if ($repairReceipt.target_backend_version_floor -cne '1.3.0') {{
    throw 'installer-owner transition discarded the target version floor'
}}
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
        -CurrentTargetBackendVersion 1.3.0 `
        -InstallerOwnerProcessId ($PID + 2) | Out-Null
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'receipt accepted mismatched port' }}
Set-TicketboxLifecycleReceiptInstallCompleted `
    -Path '{_literal(receipt_path)}' `
    -Receipt $repairReceipt `
    -InstallerOwnerProcessId ($PID + 2)
$completedReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId ($PID + 2)
if (-not $completedReceipt.install_completed -or
    $completedReceipt.preparation_stage -ne 'install_completed' -or
    $completedReceipt.target_backend_version_floor -cne '1.3.0') {{
    throw 'completed receipt was not persisted'
}}
Set-TestReceiptLegacyV7
$legacyCompletedBytes = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
$legacyCompletedReceipt = Read-TicketboxCompletedLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -TargetReleaseConfig $config `
    -ExpectedPgPort 5544 `
    -ExpectedBackendPort 8765 `
    -ExpectedPgServiceName ([string]$config.pg_service_name) `
    -ExpectedBackendServiceName ([string]$config.backend_service_name)
if (-not $legacyCompletedReceipt.install_completed -or
    $legacyCompletedReceipt.preparation_stage -cne 'install_completed' -or
    -not (Test-TicketboxByteArrayEquals `
        $legacyCompletedBytes `
        ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))) {{
    throw 'read-only legacy completed receipt adoption mutated or lost authority'
}}
$completedReceipt = ConvertTo-TicketboxCurrentLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId ($PID + 3) `
    -AllowPreviousInstallerOwnerProcessId
if (-not $completedReceipt.install_completed -or
    $completedReceipt.preparation_stage -cne 'install_completed' -or
    $completedReceipt.target_backend_version_floor -cne '1.3.0' -or
    $completedReceipt.backup_sha256 -cne $legacyCompletedReceipt.backup_sha256 -or
    [long]$completedReceipt.backup_byte_length -ne
        [long]$legacyCompletedReceipt.backup_byte_length) {{
    throw 'legacy completed receipt migration discarded completion or backup evidence'
}}
$adoptedCompletedBytes = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
$adoptedDowngradeRejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.2.9 `
        -InstallerOwnerProcessId ($PID + 3) | Out-Null
}}
catch {{ $adoptedDowngradeRejected = $true }}
if (-not $adoptedDowngradeRejected -or
    -not (Test-TicketboxByteArrayEquals `
        $adoptedCompletedBytes `
        ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))) {{
    throw 'legacy adoption failed to establish a monotonic target version floor'
}}
Set-TestBackupContent 'completed-corruption'
$completedCorruptionRejected = $false
try {{
    Read-TicketboxCompletedLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -TargetReleaseConfig $config | Out-Null
}}
catch {{ $completedCorruptionRejected = $true }}
if (-not $completedCorruptionRejected) {{ throw 'completed receipt accepted corrupted backup evidence' }}
Set-TestBackupContent 'verified-backup'
$boundCompletedReceipt = Read-TicketboxCompletedLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -TargetReleaseConfig $config `
    -ExpectedPgPort 5544 `
    -ExpectedBackendPort 8765 `
    -ExpectedPgServiceName ([string]$config.pg_service_name) `
    -ExpectedBackendServiceName ([string]$config.backend_service_name)
Remove-Item -LiteralPath '{_literal(backup_path)}' -Force
$completedMissingBackupRejected = $false
try {{
    Read-TicketboxCompletedLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -TargetReleaseConfig $config | Out-Null
}}
catch {{ $completedMissingBackupRejected = $true }}
if (-not $completedMissingBackupRejected) {{ throw 'completed receipt accepted missing backup evidence' }}
Set-TestBackupContent 'verified-backup'
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
Write-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -Mode preserved_data_reinstall `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -InstalledReleaseConfig $config `
    -TargetBackendVersionFloor 1.3.0 `
    -InstallerOwnerProcessId $PID `
    -PreviousPgState absent `
    -PreviousBackendState absent `
    -PreviousPgStartPolicy absent `
    -PreviousBackendStartPolicy absent `
    -BackupRequired $true `
    -BackupCompleted $false `
    -PreparationStage captured
$deferredReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId $PID
Set-TicketboxLifecycleReceiptDeferredBackup `
    -Path '{_literal(receipt_path)}' `
    -Receipt $deferredReceipt `
    -InstallerOwnerProcessId $PID
$deferredReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId $PID
$deferredReceipt = Convert-TestLegacyReceipt `
    -ExpectedStage backup_deferred_until_program_files_installed `
    -InstallerOwnerProcessId $PID
if ($deferredReceipt.mode -cne 'preserved_data_reinstall' -or
    -not $deferredReceipt.backup_required -or
    $deferredReceipt.backup_completed -or
    $deferredReceipt.files_may_have_been_replaced) {{
    throw 'legacy deferred-backup migration changed its recovery boundary'
}}
Set-TicketboxLifecycleReceiptProgramFilesInstalledBackupPending `
    -Path '{_literal(receipt_path)}' `
    -Receipt $deferredReceipt `
    -InstallerOwnerProcessId $PID
$backupPendingReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId $PID
Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending `
    -Path '{_literal(receipt_path)}' `
    -Receipt $backupPendingReceipt `
    -InstallerOwnerProcessId $PID `
    -CleanupPending $true
$backupPendingReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId $PID
$backupPendingReceipt = Convert-TestLegacyReceipt `
    -ExpectedStage program_files_installed_backup_pending `
    -InstallerOwnerProcessId $PID
if (-not $backupPendingReceipt.files_may_have_been_replaced -or
    -not $backupPendingReceipt.temporary_pg_service_cleanup_pending -or
    $backupPendingReceipt.backup_completed) {{
    throw 'legacy backup-pending migration discarded copy or cleanup obligations'
}}
Remove-Item -LiteralPath '{_literal(receipt_path)}' -Force
Write-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -Mode repair_install `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -InstalledReleaseConfig $config `
    -TargetBackendVersionFloor 1.3.0 `
    -InstallerOwnerProcessId $PID `
    -PreviousPgState absent `
    -PreviousBackendState absent `
    -PreviousPgStartPolicy absent `
    -PreviousBackendStartPolicy absent `
    -BackupRequired $false `
    -BackupCompleted $false `
    -PreparationStage captured
$floorReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.3.0 `
    -InstallerOwnerProcessId $PID
$floorBytes = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
$olderTargetRejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.2.9 `
        -InstallerOwnerProcessId $PID | Out-Null
}}
catch {{ $olderTargetRejected = $true }}
if (-not $olderTargetRejected -or
    -not (Test-TicketboxByteArrayEquals $floorBytes ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))) {{
    throw 'older installer target was accepted or mutated the receipt before rejection'
}}
$newerReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.4.0 `
    -InstallerOwnerProcessId $PID
Set-TicketboxLifecycleReceiptTargetVersionFloor `
    -Path '{_literal(receipt_path)}' `
    -Receipt $newerReceipt `
    -InstallerOwnerProcessId $PID `
    -TargetBackendVersionFloor 1.4.0
$ratchetedReceipt = Read-TicketboxLifecycleReceipt `
    -Path '{_literal(receipt_path)}' `
    -InstallDir '{_literal(install_dir)}' `
    -DataRoot '{_literal(data_root)}' `
    -PgPort 5544 `
    -BackendPort 8765 `
    -TargetReleaseConfig $config `
    -CurrentTargetBackendVersion 1.4.0 `
    -InstallerOwnerProcessId $PID
if ($ratchetedReceipt.target_backend_version_floor -cne '1.4.0' -or
    $ratchetedReceipt.preparation_stage -cne 'captured') {{
    throw 'newer installer did not durably ratchet the target version floor'
}}
$previousTargetRejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.3.0 `
        -InstallerOwnerProcessId $PID | Out-Null
}}
catch {{ $previousTargetRejected = $true }}
if (-not $previousTargetRejected) {{
    throw 'previous installer target remained valid after receipt ratchet'
}}
$staleTransitionRejected = $false
try {{
    Set-TicketboxLifecycleReceiptPrepared `
        -Path '{_literal(receipt_path)}' `
        -Receipt $floorReceipt `
        -InstallerOwnerProcessId $PID `
        -BackupCompleted $false
}}
catch {{ $staleTransitionRejected = $true }}
if (-not $staleTransitionRejected) {{
    throw 'stale transition lowered the target version floor'
}}
$ratchetedJson = Get-Content -LiteralPath '{_literal(receipt_path)}' -Encoding UTF8 -Raw | ConvertFrom-Json
$ratchetedJson.target_backend_version_floor = '1.4.beta'
Write-TicketboxProtectedUtf8FileDurable `
    -Path '{_literal(receipt_path)}' `
    -Text ($ratchetedJson | ConvertTo-Json -Depth 20 -Compress) `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
$malformedBytes = [System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')
$malformedFloorRejected = $false
try {{
    Read-TicketboxLifecycleReceipt `
        -Path '{_literal(receipt_path)}' `
        -InstallDir '{_literal(install_dir)}' `
        -DataRoot '{_literal(data_root)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -TargetReleaseConfig $config `
        -CurrentTargetBackendVersion 1.4.0 `
        -InstallerOwnerProcessId $PID | Out-Null
}}
catch {{ $malformedFloorRejected = $true }}
if (-not $malformedFloorRejected -or
    -not (Test-TicketboxByteArrayEquals $malformedBytes ([System.IO.File]::ReadAllBytes('{_literal(receipt_path)}')))) {{
    throw 'malformed target version floor was accepted or mutated before rejection'
}}
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
        shutil.rmtree(data_root, ignore_errors=True)
        shutil.rmtree(other_data_root, ignore_errors=True)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
