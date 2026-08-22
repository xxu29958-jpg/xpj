from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
APP = PACKAGING.parent / "app"
BACKUP = PACKAGING / "windows_dataset_backup.ps1"
GENERATION_CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
INSTALLED_READER = PACKAGING / "windows_installed_dataset_reader.ps1"


def test_dataset_maintenance_cli_is_not_owned_by_backend_launch_host() -> None:
    launch = (PACKAGING / "launch.py").read_text(encoding="utf-8")
    cli_path = APP / "dataset_maintenance_cli.py"
    assert cli_path.is_file()
    cli = cli_path.read_text(encoding="utf-8")

    for function in (
        "_parse_complete_dataset_backup_args",
        "_parse_dataset_backup_inspection_args",
        "_parse_isolated_dataset_restore_args",
        "_parse_restored_originals_verification_args",
        "_run_complete_dataset_backup",
        "_run_dataset_backup_inspection",
        "_run_isolated_dataset_restore",
        "_run_restored_originals_verification",
    ):
        assert f"def {function}" in cli
        assert f"def {function}" not in launch
    assert "from app.dataset_maintenance_cli import" in launch
    assert launch.count("run_dataset_maintenance(arguments)") == 1


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
function Assert-TicketboxProtectedDirectoryAcl {{
    param($Path)
    $script:events += "dir:$Path"
}}
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
function Throw-TicketboxDatabaseGenerationOperationFailure {{
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
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-backup-tree-acl-operands.ps1",
    )


def test_backup_owner_passes_structured_barrier_and_inspects_before_request_retirement() -> None:
    backup = BACKUP.read_text(encoding="utf-8-sig")
    cli = (APP / "dataset_maintenance_cli.py").read_text(encoding="utf-8")

    for field in (
        "--expected-current-sha256",
        "--expected-dataset-id",
        "--expected-restore-epoch",
        "--expected-schema-revision",
    ):
        assert field in backup
        assert field in cli
    assert "PayloadSha256" in powershell_function(
        backup,
        "Get-TicketboxInstalledBackupBarrier",
    )
    inspection = backup.rindex("Invoke-TicketboxInstalledDatasetBackupInspection")
    validation = backup.rindex("Assert-TicketboxInstalledCompleteBackupResult")
    retirement = backup.rindex("Remove-TicketboxInstalledDatasetOperation")
    assert inspection < validation < retirement


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
def test_backup_owner_publishes_exact_read_only_inventory_acl(
    tmp_path: Path,
) -> None:
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
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-backup-inventory-acl.ps1",
    )

    backup = BACKUP.read_text(encoding="utf-8-sig")
    helper = backup.rindex("Invoke-TicketboxInstalledCompleteBackupHelper")
    protection = backup.rindex("Protect-TicketboxInstalledBackupInventory")
    inspection = backup.rindex("Invoke-TicketboxInstalledDatasetBackupInspection")
    assert helper < protection < inspection


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_installer_backup_acl_accounts_are_not_polluted_by_backend_service(
    tmp_path: Path,
) -> None:
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
function Protect-PostgresBootstrapRecoveryFileAfterAclNormalization {{ param($ParentFullControlAccounts) }}
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
Set-TicketboxAcl -IncludePgService $true -IncludeBackendService $true
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
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="installed-backup-acl-isolation.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_backup_owner_argv_is_accepted_by_the_real_frozen_cli_parser(
    tmp_path: Path,
) -> None:
    helper = powershell_function(
        BACKUP.read_text(encoding="utf-8-sig"),
        "Invoke-TicketboxInstalledCompleteBackupHelper",
    )
    argv_path = tmp_path / "complete-backup-argv.json"
    escaped_argv_path = str(argv_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxInstalledPostgresToolArtifact {{
    param($Subject, $Tool)
    if ($Tool -ceq 'PgDump') {{ return 'C:\\pg\\pg_dump.exe' }}
    return 'C:\\pg\\pg_restore.exe'
}}
function New-TicketboxPostgresqlLocalDatabaseUrl {{ param($Authority, $Database, $Role); return 'postgresql://local' }}
function Invoke-TicketboxWithPlainPostgresqlSecret {{ param($Secret, $Action); return (& $Action 'password') }}
function New-TicketboxProtectedPgPassFile {{ param($DatabaseUrl, $Password); return [pscustomobject]@{{ Path = 'C:\\state\\pgpass'; FullControlAccounts = @(); OwnerAccount = 'owner' }} }}
function Open-TicketboxVerifiedDatabaseMaintenanceHelperLease {{ param($Path, $ExpectedRelativePath, $ExpectedSize, $ExpectedSha256); return [pscustomobject]@{{ Path = $Path }} }}
function New-TicketboxDatabaseGenerationHelperChildEnvironment {{ param($PgPassFilePath); return @{{}} }}
function Invoke-TicketboxBoundedNativeProcess {{
    param($FilePath, $Arguments, $StandardInputText, $TimeoutMilliseconds, $Label, $ChildEnvironment)
    $script:capturedArgv = @($Arguments)
    return [pscustomobject]@{{
        ExitCode = 0
        StandardError = ''
        StandardOutput = '{{"schema":"ticketbox-complete-dataset-backup-result-v1","backup_id":"22222222-2222-4222-8222-222222222222","generation":"ticketbox-backup-22222222-2222-4222-8222-222222222222","dataset_id":"33333333-3333-4333-8333-333333333333","restore_epoch":4,"size_bytes":4096}}'
    }}
}}
function Get-TicketboxDatabaseGenerationJsonLine {{ param($StandardOutput, $Label); return $StandardOutput }}
function Assert-TicketboxDatabaseGenerationExactProperties {{ param($Value, $ExpectedNames, $Label) }}
function Assert-TicketboxDatabaseMaintenanceHelperLeaseUnchanged {{ param($Lease) }}
function Close-TicketboxDatabaseMaintenanceHelperLease {{ param($Lease) }}
function Remove-TicketboxProtectedPgPassArtifact {{ param($Path, $FullControlAccounts, $OwnerAccount) }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{ param($Primary, $Cleanup); if ($null -ne $Primary) {{ throw $Primary }} }}
{helper}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\\Ticketbox'; DataRoot = 'C:\\Data'; PgPort = 5432 }}
    Manifest = [pscustomobject]@{{
        Sha256 = ('a' * 64)
        DatabaseMaintenanceHelper = [pscustomobject]@{{ RelativePath = 'helper.exe'; Size = 1; Sha256 = ('d' * 64) }}
    }}
    Release = [pscustomobject]@{{ database_tool_timeout_ms = 1000 }}
}}
$authority = [pscustomobject]@{{ Credentials = [pscustomobject]@{{ BackupPassword = 'secret' }} }}
$request = [pscustomobject]@{{ Payload = [pscustomobject]@{{
    operation_id = '11111111-1111-4111-8111-111111111111'
    backup_id = '22222222-2222-4222-8222-222222222222'
    backup_kind = 'manual'
}} }}
$barrier = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        current_sha256 = ('c' * 64)
        dataset_id = '33333333-3333-4333-8333-333333333333'
        restore_epoch = 4
        schema_revision = '20260821_0001'
    }}
}}
[void](Invoke-TicketboxInstalledCompleteBackupHelper $subject $authority $request $barrier)
[IO.File]::WriteAllText(
    '{escaped_argv_path}',
    ($script:capturedArgv | ConvertTo-Json -Compress),
    (New-Object Text.UTF8Encoding($false))
)
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-backup-real-cli-argv.ps1",
    )
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    parser = runpy.run_path(str(APP / "dataset_maintenance_cli.py"))["_parse_complete_dataset_backup_args"]
    parsed = parser(argv)
    assert parsed.pg_dump_path == Path(r"C:\pg\pg_dump.exe")
    assert parsed.pg_restore_path == Path(r"C:\pg\pg_restore.exe")


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_python_and_powershell_writer_barrier_codecs_match(tmp_path: Path) -> None:
    payload = {
        "schema": "ticketbox-dataset-backup-writer-barrier-v1",
        "current_sha256": "c" * 64,
        "dataset_id": "33333333-3333-4333-8333-333333333333",
        "restore_epoch": 4,
        "schema_revision": "20260821_0001",
        "backend_service_state": "stopped",
        "other_client_session_count": 0,
    }
    expected = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    contract = GENERATION_CONTRACT.read_text(encoding="utf-8-sig")
    canonical = powershell_function(
        contract,
        "ConvertTo-TicketboxDatabaseGenerationCanonicalJson",
    )
    digest = powershell_function(
        contract,
        "Get-TicketboxDatabaseGenerationTextSha256",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{canonical}
{digest}
$payload = [ordered]@{{
    schema = 'ticketbox-dataset-backup-writer-barrier-v1'
    current_sha256 = ('c' * 64)
    dataset_id = '33333333-3333-4333-8333-333333333333'
    restore_epoch = 4
    schema_revision = '20260821_0001'
    backend_service_state = 'stopped'
    other_client_session_count = 0
}}
$actual = Get-TicketboxDatabaseGenerationTextSha256 (
    ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
)
if ($actual -cne '{expected}') {{ throw "writer barrier codec drifted: $actual" }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-backup-writer-barrier-codec.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_complete_backup_result_is_bound_to_request_barrier_and_inspection(
    tmp_path: Path,
) -> None:
    validator = powershell_function(
        BACKUP.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxInstalledCompleteBackupResult",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join "`n") -cne ($expected -join "`n")) {{ throw 'open contract' }}
}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw 'bad digest' }}
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); return 'barrier-json' }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ param($Value); return ('b' * 64) }}
{validator}
$operation = '11111111-1111-4111-8111-111111111111'
$backup = '22222222-2222-4222-8222-222222222222'
$dataset = '33333333-3333-4333-8333-333333333333'
$release = ('a' * 64)
$fence = ('b' * 64)
$subject = [pscustomobject]@{{ Manifest = [pscustomobject]@{{ Sha256 = $release }} }}
$request = [pscustomobject]@{{ Payload = [pscustomobject]@{{
    operation_id = $operation
    backup_id = $backup
    backup_kind = 'manual'
    current_sha256 = ('c' * 64)
    release_manifest_sha256 = $release
}} }}
$barrier = [pscustomobject]@{{
    PayloadSha256 = $fence
    Payload = [pscustomobject][ordered]@{{
        schema = 'ticketbox-dataset-backup-writer-barrier-v1'
        current_sha256 = ('c' * 64)
        dataset_id = $dataset
        restore_epoch = 4
        schema_revision = '20260821_0001'
        backend_service_state = 'stopped'
        other_client_session_count = 0
    }}
}}
$result = [pscustomobject][ordered]@{{
    schema = 'ticketbox-complete-dataset-backup-result-v1'
    backup_id = $backup
    generation = "ticketbox-backup-$backup"
    dataset_id = $dataset
    restore_epoch = 4
    size_bytes = 4096
}}
$evidence = [pscustomobject][ordered]@{{
    schema = 'ticketbox-complete-dataset-backup-inspection-v1'
    operation_id = $operation
    backup_id = $backup
    backup_kind = 'manual'
    generation = "ticketbox-backup-$backup"
    dataset_id = $dataset
    restore_epoch = 4
    schema_revision = '20260821_0001'
    release_id = $release
    writer_fence_sha256 = $fence
    manifest_sha256 = ('d' * 64)
    original_count = 1
}}
$inspection = [pscustomobject]@{{ Evidence = $evidence }}
[void](Assert-TicketboxInstalledCompleteBackupResult $subject $request $barrier $result $inspection)
foreach ($case in @(
    'result_dataset', 'result_epoch',
    'inspection_dataset', 'inspection_epoch',
    'operation', 'request_release', 'inspection_release', 'fence'
)) {{
    switch ($case) {{
        'result_dataset' {{ $result.dataset_id = '44444444-4444-4444-8444-444444444444' }}
        'result_epoch' {{ $result.restore_epoch = 5 }}
        'inspection_dataset' {{ $evidence.dataset_id = '44444444-4444-4444-8444-444444444444' }}
        'inspection_epoch' {{ $evidence.restore_epoch = 5 }}
        'operation' {{ $evidence.operation_id = '55555555-5555-4555-8555-555555555555' }}
        'request_release' {{ $request.Payload.release_manifest_sha256 = ('e' * 64) }}
        'inspection_release' {{ $evidence.release_id = ('e' * 64) }}
        'fence' {{ $evidence.writer_fence_sha256 = ('f' * 64) }}
    }}
    $rejected = $false
    try {{ Assert-TicketboxInstalledCompleteBackupResult $subject $request $barrier $result $inspection | Out-Null }} catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "$case mutation crossed backup result authority" }}
    $result.dataset_id = $dataset
    $result.restore_epoch = 4
    $evidence.dataset_id = $dataset
    $evidence.restore_epoch = 4
    $evidence.operation_id = $operation
    $request.Payload.release_manifest_sha256 = $release
    $evidence.release_id = $release
    $evidence.writer_fence_sha256 = $fence
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-backup-result-binding.ps1",
    )
