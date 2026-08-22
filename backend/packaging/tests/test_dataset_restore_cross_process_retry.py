from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
)

PACKAGING = Path(__file__).resolve().parents[1]
RESTORE = PACKAGING / "windows_dataset_restore.ps1"
DATASET_OPERATION = PACKAGING / "windows_installed_dataset_operation.ps1"
RESTORE_ARTIFACTS = PACKAGING / "windows_installed_dataset_restore_artifacts.ps1"

RESTORE_DEPENDENCIES = (
    "windows_installation_safety.ps1",
    "windows_lifecycle_lock.ps1",
    "windows_deadline_budget.ps1",
    "windows_release_config.ps1",
    "windows_service_lifecycle.ps1",
    "windows_database_safety.ps1",
    "windows_pg_recovery_tools.ps1",
    "windows_postgresql_credentials.ps1",
    "windows_postgresql_database_command.ps1",
    "windows_backend_health.ps1",
    "windows_database_generation.ps1",
    "windows_installed_dataset_reader.ps1",
    "windows_installed_dataset_operation.ps1",
    "windows_installed_dataset_restore_artifacts.ps1",
    "windows_installed_dataset_restore_verification.ps1",
    "windows_dataset_restore_filesystem.ps1",
    "windows_dataset_restore_reducer.ps1",
    "windows_dataset_restore_database.ps1",
    "windows_dataset_restore_runtime.ps1",
    "windows_postgresql_candidate_cluster.ps1",
    "windows_postgresql_candidate_initdb.ps1",
    "windows_postgresql_candidate_runtime.ps1",
    "windows_bundled_database.ps1",
)
RESTORE_CONTRACT_PATHS = tuple(PACKAGING / name for name in RESTORE_DEPENDENCIES)


def _restore_contract() -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in RESTORE_CONTRACT_PATHS)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_cross_process_retry_republishes_verified_candidate_without_new_bootstrap(
    tmp_path: Path,
) -> None:
    entrypoint = tmp_path / "windows_dataset_restore.ps1"
    entrypoint.write_text(RESTORE.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    for name in RESTORE_DEPENDENCIES:
        (tmp_path / name).write_text("", encoding="utf-8-sig")

    operation_source = DATASET_OPERATION.read_text(encoding="utf-8-sig")
    reducer_source = (PACKAGING / "windows_dataset_restore_reducer.ps1").read_text(encoding="utf-8-sig")
    classifier = powershell_function(
        operation_source,
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    assert_operation = powershell_function(
        operation_source,
        "Assert-TicketboxInstalledDatasetOperation",
    )
    reducer = powershell_function(
        reducer_source,
        "Resolve-TicketboxInstalledDatasetRestoreNextAction",
    )
    stubs = f"""
$successor = '22222222-2222-4222-8222-222222222222'
$attempt = '11111111-1111-4111-8111-111111111111'
$predecessorSha = ('a' * 64)
$requestSha = ('b' * 64)
$installation = '66666666-6666-4666-8666-666666666666'
$predecessorOperation = '33333333-3333-4333-8333-333333333333'
$targetRevision = '20260821_0001'
$global:testIntent = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successor
        source_request_sha256 = $requestSha
        expected_predecessor_sha256 = $predecessorSha
        projection_contract_sha256 = ('d' * 64)
    }}
}}
$global:testCurrent = [pscustomobject]@{{
    PayloadSha256 = $predecessorSha
    Payload = [pscustomobject]@{{ operation_id = $predecessorOperation }}
}}
$global:testRequest = [pscustomobject]@{{
    PayloadSha256 = $requestSha
    Payload = [pscustomobject]@{{
        schema = 'ticketbox-installed-dataset-operation-v1'
        operation_kind = 'restore'
        operation_id = $attempt
        installation_id = $installation
        backup_generation = 'ticketbox-backup-44444444-4444-4444-8444-444444444444'
        backup_manifest_sha256 = ('e' * 64)
        release_manifest_sha256 = ('f' * 64)
        backup_id = '44444444-4444-4444-8444-444444444444'
        dataset_id = '55555555-5555-4555-8555-555555555555'
        backup_restore_epoch = 0
        target_revision = $targetRevision
        active_dataset_id = '55555555-5555-4555-8555-555555555555'
        active_restore_epoch = 0
        current_sha256 = $predecessorSha
        predecessor_intent_sha256 = ('9' * 64)
        predecessor_intent_payload = [pscustomobject]@{{
            schema = 'ticketbox-database-generation-intent-v2'
            operation_id = $predecessorOperation
            installation_id = $installation
            projection_contract_sha256 = ('d' * 64)
        }}
        predecessor_current_payload = [pscustomobject]@{{
            schema = 'ticketbox-current-database-generation-v1'
            operation_id = $predecessorOperation
            installation_id = $installation
            intent_sha256 = ('9' * 64)
            committed_revision = $targetRevision
        }}
        restart_backend = $true
    }}
}}
$global:testSource = [pscustomobject]@{{ PayloadSha256 = ('1' * 64); Payload = [pscustomobject]@{{}} }}
$global:testVerification = [pscustomobject]@{{ Kind = 'candidate-verification'; Payload = [pscustomobject]@{{}} }}
function Get-TicketboxDatabaseGenerationExecutionDependencyPaths {{ return @() }}
function Enter-TicketboxLifecycleLock {{ return [pscustomobject]@{{ token = 'lock' }} }}
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Get-TicketboxInstallerStateDirectory {{ return 'C:\\installer-state' }}
function Get-TicketboxDatabaseGenerationStateRoot {{ param($InstallerState); return 'C:\\state' }}
function Assert-TicketboxInstalledDatasetSubject {{
    param($DataRoot)
    return [pscustomobject]@{{
        Identity = [pscustomobject]@{{
            DataRoot = $DataRoot; InstallDir = 'C:\\Ticketbox'; PgPort = 15432
            PgServiceName = 'ticketbox-pg'; BackendServiceName = 'ticketbox-backend'
            BackendPort = 8123; BackendVersionFloor = '1.0.0'
        }}
        Release = [pscustomobject]@{{ secret_byte_count = 32 }}
        Manifest = [pscustomobject]@{{ Sha256 = ('f' * 64) }}
    }}
}}
function Assert-TicketboxInstalledDatasetServiceAuthority {{ param($Subject) }}
function Read-TicketboxDatabaseGenerationActiveIntent {{ param($StateRoot); return $global:testIntent }}
function Read-TicketboxDatabaseGenerationCurrent {{ return $global:testCurrent }}
function Read-TicketboxInstalledDatasetOperation {{
    param($StateRoot, $ExpectedOperationKind, [switch]$AllowAbsent)
    return $global:testRequest
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{
        throw "$Label properties are not closed"
    }}
}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "$Label digest invalid" }}
}}
function Get-TicketboxDatabaseGenerationPayloadProperties {{
    param($Kind)
    if ($Kind -ceq 'intent') {{
        return @('schema', 'operation_id', 'installation_id', 'projection_contract_sha256')
    }}
    if ($Kind -ceq 'current') {{
        return @('schema', 'operation_id', 'installation_id', 'intent_sha256', 'committed_revision')
    }}
    throw "unexpected payload kind: $Kind"
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); return [string]$Value.schema }}
function Get-TicketboxDatabaseGenerationTextSha256 {{
    param($Value)
    if ($Value -ceq 'ticketbox-database-generation-intent-v2') {{ return ('9' * 64) }}
    if ($Value -ceq 'ticketbox-current-database-generation-v1') {{ return $predecessorSha }}
    throw "unexpected hash subject: $Value"
}}
function Read-TicketboxInstalledDatasetRestoreResult {{ return $null }}
function Invoke-TicketboxInstalledDatasetBackupInspection {{
    return [pscustomobject]@{{ Evidence = [pscustomobject]@{{
        manifest_sha256 = ('e' * 64)
    }} }}
}}
function Assert-TicketboxInstalledPostgresToolArtifact {{ param($Subject, $Tool) }}
function New-TicketboxInstalledDatabaseGenerationContracts {{
    return [pscustomobject]@{{ Program = @{{}}; Host = @{{}}; Projection = @{{}} }}
}}
function Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 {{ return ('d' * 64) }}
function Get-TicketboxInstalledDatasetRestorePaths {{
    return [pscustomobject]@{{ operation_id = $successor }}
}}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    param($StateRoot, $OperationId, $Kind, [switch]$AllowAbsent)
    switch ($Kind) {{
        'restored-source' {{ return $global:testSource }}
        'candidate-verification' {{ return $global:testVerification }}
        'runtime-verification' {{ return $null }}
        default {{ throw "unexpected artifact: $Kind" }}
    }}
}}
function Assert-TicketboxInstalledDatasetCandidateVerification {{ return $global:testVerification }}
function Resolve-TicketboxInstalledDatasetRestorePhysicalState {{ return 'candidate_ready' }}
function Stop-TicketboxInstalledDatasetWriters {{ param($Subject) }}
function Get-OrCreatePostgresBootstrapRecoveryState {{ throw 'retry created a second bootstrap authority' }}
function New-TicketboxDatabaseGenerationCredentials {{ throw 'retry created new transient credentials' }}
function Start-TicketboxPostgresqlRestoreCandidateService {{ throw 'verified candidate was reopened' }}
function Initialize-TicketboxPostgresqlRestoreCandidateDatabase {{ throw 'verified candidate was reinitialized' }}
function Invoke-TicketboxInstalledDatasetRestoreHelper {{ throw 'verified backup was restored twice' }}
function New-TicketboxInstalledDatasetCandidateVerification {{ throw 'immutable verification was rewritten' }}
function Remove-TicketboxPostgresqlRestoreCandidateService {{ param($Subject, $Paths) }}
function Set-TicketboxInstalledDatasetRestorePhysicalSelection {{
    param($Paths, $Selection)
    if ($Selection -cne 'Candidate') {{ throw 'retry selected the wrong dataset' }}
    [Console]::Out.WriteLine('verified-successor-republished')
    exit 0
}}
function Invoke-TicketboxInstalledDatasetRestoreFailureCompensation {{ return 'rolled_back' }}
function Exit-TicketboxLifecycleLock {{ param($Lock) }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{
    param($Primary, $Cleanup)
    if ($null -ne $Primary) {{ throw $Primary }}
}}
{assert_operation}
{classifier}
{reducer}
"""
    (tmp_path / "windows_dataset_restore_runtime.ps1").write_text(
        stubs,
        encoding="utf-8-sig",
    )

    for engine in powershell_contract_engines():
        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(entrypoint),
                "-DataRoot",
                r"C:\TicketboxData",
                "-BackupGeneration",
                "ticketbox-backup-44444444-4444-4444-8444-444444444444",
                "-RestoreAttemptId",
                "11111111-1111-4111-8111-111111111111",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "verified-successor-republished"
