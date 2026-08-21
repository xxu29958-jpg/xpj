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
BACKUP = PACKAGING / "windows_dataset_backup.ps1"
GENERATION_CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"


def test_backup_owner_passes_structured_barrier_and_inspects_before_request_retirement() -> None:
    backup = BACKUP.read_text(encoding="utf-8-sig")
    launch = (PACKAGING / "launch.py").read_text(encoding="utf-8")

    for field in (
        "--expected-current-sha256",
        "--expected-dataset-id",
        "--expected-restore-epoch",
        "--expected-schema-revision",
    ):
        assert field in backup
        assert field in launch
    assert "PayloadSha256" in powershell_function(
        backup,
        "Get-TicketboxInstalledBackupBarrier",
    )
    inspection = backup.rindex("Invoke-TicketboxInstalledDatasetBackupInspection")
    validation = backup.rindex("Assert-TicketboxInstalledCompleteBackupResult")
    retirement = backup.rindex("Remove-TicketboxInstalledDatasetBackupRequest")
    assert inspection < validation < retirement


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
    parser = runpy.run_path(str(PACKAGING / "launch.py"))[
        "_parse_complete_dataset_backup_args"
    ]
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
