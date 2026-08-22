from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
BACKUP = PACKAGING / "windows_dataset_backup.ps1"
INSTALLED_READER = PACKAGING / "windows_installed_dataset_reader.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_backup_inspection_checks_each_exact_acl_operand_before_opening_helper(
    tmp_path: Path,
) -> None:
    inspection = powershell_function(
        INSTALLED_READER.read_text(encoding="utf-8-sig"),
        "Invoke-TicketboxInstalledDatasetBackupInspection",
    )
    root = str(tmp_path).replace("'", "''")
    generation = "ticketbox-backup-11111111-1111-4111-8111-111111111111"
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = @()
function Test-TicketboxPathEquals {{ param($Left, $Right); return $true }}
function Assert-TicketboxProtectedDirectoryAcl {{ param($Path); $script:events += "dir:$Path" }}
function Assert-NoTicketboxReparsePoints {{ param($Path) }}
function Get-ChildItem {{
    param($LiteralPath, [switch]$Force, [switch]$Recurse)
    return @(
        [pscustomobject]@{{ FullName = (Join-Path $LiteralPath 'originals'); Kind = 'Directory' }},
        [pscustomobject]@{{ FullName = (Join-Path $LiteralPath 'manifest.json'); Kind = 'File' }},
        [pscustomobject]@{{ FullName = (Join-Path $LiteralPath 'database.dump'); Kind = 'File' }}
    )
}}
function Get-TicketboxPathEntryKindNoFollow {{ param($Path); if ($Path.EndsWith('originals')) {{ return 'Directory' }}; return 'File' }}
function Assert-TicketboxExactFileAcl {{
    param($Path, $Accounts, $OwnerAccount)
    $script:events += "file:${{Path}}:$($Accounts -join ','):$OwnerAccount"
}}
function Open-TicketboxVerifiedDatabaseMaintenanceHelperLease {{ throw 'stop-after-acl' }}
function Throw-TicketboxOperationFailure {{
    param($Primary, $Cleanup)
    if ($null -ne $Primary) {{ throw $Primary }}
}}
{inspection}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ DataRoot = (Join-Path '{root}' 'data'); InstallDir = (Join-Path '{root}' 'install') }}
}}
$failed = $false
try {{ Invoke-TicketboxInstalledDatasetBackupInspection $subject '{generation}' | Out-Null }}
catch {{ if ($_.Exception.Message -ceq 'stop-after-acl') {{ $failed = $true }} else {{ throw }} }}
if (-not $failed) {{ throw 'inspection crossed the helper boundary' }}
$generationPath = Join-Path (Join-Path $subject.Identity.DataRoot 'backups') '{generation}'
$expected = @(
    "dir:$(Join-Path $subject.Identity.DataRoot 'backups')",
    "dir:$generationPath",
    "dir:$(Join-Path $generationPath 'originals')",
    "file:$(Join-Path $generationPath 'manifest.json'):SYSTEM,BUILTIN\Administrators:SYSTEM",
    "file:$(Join-Path $generationPath 'database.dump'):SYSTEM,BUILTIN\Administrators:SYSTEM"
)
if (($script:events -join '|') -cne ($expected -join '|')) {{
    throw "backup ACL operands drifted: $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(script, tmp_path, filename="dataset-backup-tree-acl-operands.ps1")


def test_backup_owner_reasserts_privileged_payload_acl_before_and_after_write() -> None:
    backup = BACKUP.read_text(encoding="utf-8-sig")
    request = backup.rindex("Start-TicketboxInstalledDatasetBackupOperation")
    stop = backup.index("Stop-TicketboxOwnedServiceIfExists", request)
    helper = backup.rindex("Invoke-TicketboxInstalledCompleteBackupHelper")
    inspection = backup.rindex("Invoke-TicketboxInstalledDatasetBackupInspection")
    validation = backup.rindex("Assert-TicketboxInstalledCompleteBackupResult")

    before_write = backup[request:stop]
    assert "Set-TicketboxExactDirectoryAcl" in before_write
    assert '-Accounts @("SYSTEM", "BUILTIN\\Administrators")' in before_write
    assert "-Recurse" in before_write

    after_write = backup[helper:validation]
    assert helper < inspection
    assert "Set-TicketboxExactDirectoryAcl" in after_write
    assert "-Path $generationPath" in after_write
    assert '-Accounts @("SYSTEM", "BUILTIN\\Administrators")' in after_write
    assert "-Recurse" in after_write
    assert "Get-ChildItem -LiteralPath $generationPath -Force -Recurse" in after_write
    assert "Set-TicketboxExactFileAcl" in after_write
    assert "BackendServiceName" not in before_write + after_write


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_backup_owner_publishes_exact_read_only_inventory_acl(tmp_path: Path) -> None:
    protector = powershell_function(
        BACKUP.read_text(encoding="utf-8-sig"),
        "Protect-TicketboxInstalledBackupInventory",
    )
    root = str(tmp_path).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = @()
function Set-TicketboxExactFileAcl {{
    param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount)
    $script:events += "set:${{Path}}:$($Accounts -join ','):$($ReadExecuteAccounts -join ','):${{OwnerAccount}}"
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount, $MaximumBytes)
    $script:events += "read:${{Path}}:$($FullControlAccounts -join ','):$($ReadExecuteAccounts -join ','):${{OwnerAccount}}:$MaximumBytes"
    return [pscustomobject]@{{ Text = '{{"schema":"ticketbox-complete-backup-inventory-v1","generations":[]}}' }}
}}
{protector}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{
        DataRoot = (Join-Path '{root}' 'data')
        BackendServiceName = 'ticketbox-backend'
    }}
}}
[void](Protect-TicketboxInstalledBackupInventory $subject)
$path = Join-Path $subject.Identity.DataRoot 'app\backup-inventory.json'
$expected = @(
    "set:${{path}}:SYSTEM,BUILTIN\Administrators:NT SERVICE\ticketbox-backend:SYSTEM",
    "read:${{path}}:SYSTEM,BUILTIN\Administrators:NT SERVICE\ticketbox-backend:SYSTEM:65536"
)
if (($script:events -join '|') -cne ($expected -join '|')) {{
    throw "inventory ACL publication drifted: $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(script, tmp_path, filename="dataset-backup-inventory-acl.ps1")

    backup = BACKUP.read_text(encoding="utf-8-sig")
    helper = backup.rindex("Invoke-TicketboxInstalledCompleteBackupHelper")
    protection = backup.rindex("Protect-TicketboxInstalledBackupInventory")
    inspection = backup.rindex("Invoke-TicketboxInstalledDatasetBackupInspection")
    assert helper < protection < inspection


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_installer_backup_acl_accounts_are_not_polluted_by_backend_service(tmp_path: Path) -> None:
    install = (PACKAGING / "install_bundled_services.ps1").read_text(encoding="utf-8-sig")
    start = install.index("function Set-TicketboxAcl(")
    end = install.index("\nfunction Initialize-TicketboxInstallerStateArtifacts", start)
    set_acl = install[start:end]
    root = str(tmp_path).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:calls = @()
function Write-Step {{ param($Message) }}
function Write-Ok {{ param($Message) }}
function Set-TicketboxExactDirectoryAcl {{
    param(
        [string]$Path, [string[]]$Accounts,
        [string[]]$ReadExecuteAccounts = @(), [string]$OwnerAccount,
        [switch]$Recurse
    )
    $script:calls += [pscustomobject]@{{
        Path = $Path
        Accounts = @($Accounts)
        ReadExecuteAccounts = @($ReadExecuteAccounts)
        OwnerAccount = $OwnerAccount
        Recurse = [bool]$Recurse
    }}
}}
function Set-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function Protect-PostgresBootstrapRecoveryFileAfterAclNormalization {{
    param($DataRoot, $AppData, $SecretByteCount, $ParentFullControlAccounts)
}}
function Initialize-TicketboxInstallerStateDirectory {{ param($Path) }}
function Get-TicketboxDataRootMarkerPath {{ param($DataRoot); return (Join-Path $DataRoot 'marker.json') }}
function Invoke-IcaclsChecked {{ param($Arguments) }}
{set_acl}
$DataRoot = Join-Path '{root}' 'data'
$PgData = Join-Path $DataRoot 'pgdata'
$AppData = Join-Path $DataRoot 'app'
$DefaultUploadRoot = Join-Path $AppData 'uploads'
$LogDir = Join-Path $AppData 'logs'
$RuntimeSettingsDir = Join-Path $AppData 'runtime-settings'
$BackupDir = Join-Path $DataRoot 'backups'
$InstallerState = Join-Path $DataRoot 'installer-state'
$BootstrapExposureRecoveryGuardPath = Join-Path $DataRoot 'absent-bootstrap'
$InstallerRuntimeRecoveryGuardPath = Join-Path $DataRoot 'absent-runtime'
$ProgramDir = Join-Path '{root}' 'program'
$PgHome = Join-Path '{root}' 'pg'
$PgServiceName = 'ticketbox-pg'
$BackendServiceName = 'ticketbox-backend'
Set-TicketboxAcl `
    -IncludePgService $true `
    -IncludeBackendService $true `
    -DataRoot $DataRoot `
    -AppData $AppData `
    -SecretByteCount 32
$backup = @($script:calls | Where-Object {{ $_.Path -ceq $BackupDir }})
if ($backup.Count -ne 1) {{ throw 'backup ACL call count drifted' }}
if (($backup[0].Accounts -join '|') -cne 'SYSTEM|BUILTIN\Administrators') {{
    throw 'backup ACL gained a runtime principal'
}}
if ($backup[0].ReadExecuteAccounts.Count -ne 0 -or -not $backup[0].Recurse) {{
    throw 'backup ACL lost its exact recursive contract'
}}
$app = @($script:calls | Where-Object {{ $_.Path -ceq $AppData }})
if (
    ($app[0].Accounts -join '|') -cne 'SYSTEM|BUILTIN\Administrators' -or
    ($app[0].ReadExecuteAccounts -join '|') -cne 'NT SERVICE\ticketbox-backend' -or
    $app[0].Recurse
) {{ throw 'app authority root still grants runtime replacement authority' }}
foreach ($writable in @($DefaultUploadRoot, $LogDir, $RuntimeSettingsDir)) {{
    $entry = @($script:calls | Where-Object {{ $_.Path -ceq $writable }})
    if (
        $entry.Count -ne 1 -or
        ($entry[0].Accounts -join '|') -cne
            'SYSTEM|BUILTIN\Administrators|NT SERVICE\ticketbox-backend' -or
        -not $entry[0].Recurse
    ) {{ throw "backend writable leaf ACL drifted: $writable" }}
}}
"""
    run_powershell_contract_script(script, tmp_path, filename="installed-backup-acl-isolation.ps1")
