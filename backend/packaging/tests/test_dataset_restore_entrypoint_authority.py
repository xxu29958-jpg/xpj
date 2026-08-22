from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
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
def test_restore_shipment_parses_as_whole_files_on_ps51_and_ps7(tmp_path: Path) -> None:
    paths = ",".join("'" + str(path).replace("'", "''") + "'" for path in (RESTORE, *RESTORE_CONTRACT_PATHS))
    script = f"""
$ErrorActionPreference = 'Stop'
foreach ($path in @({paths})) {{
    $tokens = $null
    $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile(
        $path, [ref]$tokens, [ref]$errors
    )
    if ($errors.Count -ne 0) {{ throw "PowerShell parse failed: $path" }}
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-parse.ps1",
    )


def test_request_only_crash_state_creates_exact_successor_before_mutation(
    tmp_path: Path,
) -> None:
    entrypoint = tmp_path / "windows_dataset_restore.ps1"
    entrypoint.write_text(RESTORE.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    for name in RESTORE_DEPENDENCIES:
        (tmp_path / name).write_text("", encoding="utf-8-sig")
    classifier = powershell_function(
        DATASET_OPERATION.read_text(encoding="utf-8-sig"),
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    stubs = rf"""
$predecessorOperation = '11111111-1111-4111-8111-111111111111'
$predecessorIntentSha = ('a' * 64)
$predecessorCurrentSha = ('b' * 64)
$requestSha = ('d' * 64)
$script:predecessorIntent = [pscustomobject]@{{
    PayloadSha256 = $predecessorIntentSha
    Payload = [pscustomobject]@{{ operation_id = $predecessorOperation }}
}}
$script:predecessorCurrent = [pscustomobject]@{{
    PayloadSha256 = $predecessorCurrentSha
    Payload = [pscustomobject]@{{ operation_id = $predecessorOperation }}
}}
$script:durableRequest = [pscustomobject]@{{
    PayloadSha256 = $requestSha
    Payload = [pscustomobject]@{{
        operation_id = '22222222-2222-4222-8222-222222222222'
        backup_generation = 'ticketbox-backup-33333333-3333-4333-8333-333333333333'
        backup_manifest_sha256 = ('e' * 64)
        release_manifest_sha256 = ('7' * 64)
        backup_id = '33333333-3333-4333-8333-333333333333'
        dataset_id = '44444444-4444-4444-8444-444444444444'
        active_dataset_id = '44444444-4444-4444-8444-444444444444'
        predecessor_intent_sha256 = $predecessorIntentSha
        current_sha256 = $predecessorCurrentSha
        predecessor_intent_payload = [pscustomobject]@{{ projection_contract_sha256 = ('6' * 64) }}
        public_base_url = 'https://lifecycle.example'
        restart_backend = $false
    }}
}}
function Get-TicketboxDatabaseGenerationExecutionDependencyPaths {{ return @() }}
function Enter-TicketboxLifecycleLock {{ return [pscustomobject]@{{ token = 'lock' }} }}
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Get-TicketboxInstallerStateDirectory {{ return 'C:\installer-state' }}
function Get-TicketboxDatabaseGenerationStateRoot {{ return 'C:\state' }}
function Assert-TicketboxInstalledDatasetSubject {{
    return [pscustomobject]@{{
        Identity = [pscustomobject]@{{
            DataRoot = 'C:\TicketboxData'; PgPort = 5432; BackendVersionFloor = '1.0.0'
        }}
        Release = [pscustomobject]@{{ secret_byte_count = 32 }}
        Manifest = [pscustomobject]@{{
            Sha256 = ('7' * 64)
            DatabaseMaintenanceHelper = [pscustomobject]@{{ Size = 123; Sha256 = ('8' * 64) }}
        }}
    }}
}}
function Assert-TicketboxInstalledDatasetServiceAuthority {{ param($Subject) }}
function Read-TicketboxDatabaseGenerationActiveIntent {{ return $script:predecessorIntent }}
function Read-TicketboxDatabaseGenerationCurrent {{ return $script:predecessorCurrent }}
function Read-TicketboxInstalledDatasetOperation {{ return $script:durableRequest }}
function Read-TicketboxInstalledDatasetRestoreResult {{ return $null }}
function Invoke-TicketboxInstalledDatasetBackupInspection {{
    return [pscustomobject]@{{ Evidence = [pscustomobject]@{{
        manifest_sha256 = ('e' * 64)
        dataset_id = '44444444-4444-4444-8444-444444444444'
    }} }}
}}
function Assert-TicketboxInstalledPostgresToolArtifact {{ param($Subject, $Tool) }}
function New-TicketboxInstalledDatabaseGenerationContracts {{
    return [pscustomobject]@{{ Program = @{{}}; Host = @{{}}; Projection = @{{}} }}
}}
function Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 {{ return ('6' * 64) }}
function Assert-TicketboxInstalledDatasetOperation {{ param($Operation, $ExpectedOperationKind); return $Operation }}
{classifier}
function New-TicketboxDatabaseGenerationIntent {{
    param(
        $InstallerState, $LifecycleLock, $ExpectedPredecessorSha256,
        $SourceRequestSha256, $TargetBackendVersion, $MaintenanceHelperSize,
        $MaintenanceHelperSha256, $ProgramContract, $HostContract,
        $ProjectionContract
    )
    if (
        $ExpectedPredecessorSha256 -cne $predecessorCurrentSha -or
        $SourceRequestSha256 -cne $requestSha
    ) {{ throw 'successor intent lost request-only authority' }}
    [Console]::Out.WriteLine('request-only-resumed-before-mutation')
    exit 0
}}
function Stop-TicketboxInstalledDatasetWriters {{ throw 'writer mutation poison' }}
function Initialize-TicketboxPostgresqlRestoreCandidateCluster {{ throw 'candidate mutation poison' }}
function Exit-TicketboxLifecycleLock {{ param($Lock) }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{
    param($Primary, $Cleanup)
    if ($null -ne $Primary) {{ throw $Primary }}
}}
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
                "ticketbox-backup-33333333-3333-4333-8333-333333333333",
                "-RestoreAttemptId",
                "22222222-2222-4222-8222-222222222222",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "request-only-resumed-before-mutation"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_reobserves_exact_authority_before_successor_artifacts(
    tmp_path: Path,
) -> None:
    entrypoint = tmp_path / "windows_dataset_restore.ps1"
    entrypoint.write_text(RESTORE.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    dependency_names = (
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
    for name in dependency_names:
        (tmp_path / name).write_text("", encoding="utf-8-sig")
    classifier = powershell_function(
        DATASET_OPERATION.read_text(encoding="utf-8-sig"),
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    stubs = f"""
$script:activeReads = 0
$script:poison = @()
$successor = '22222222-2222-4222-8222-222222222222'
$predecessorSha = ('a' * 64)
$script:durableRequest = [pscustomobject]@{{
    PayloadSha256 = ('d' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        backup_generation = 'ticketbox-backup-33333333-3333-4333-8333-333333333333'
        backup_manifest_sha256 = ('e' * 64)
        release_manifest_sha256 = ('7' * 64)
        backup_id = '33333333-3333-4333-8333-333333333333'
        dataset_id = '44444444-4444-4444-8444-444444444444'
        active_dataset_id = '44444444-4444-4444-8444-444444444444'
        current_sha256 = $predecessorSha
        public_base_url = 'https://public.example'
        predecessor_intent_payload = [pscustomobject]@{{ projection_contract_sha256 = ('6' * 64) }}
        restart_backend = $false
    }}
}}
$validIntent = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successor
        source_request_sha256 = ('d' * 64)
        expected_predecessor_sha256 = $predecessorSha
        projection_contract_sha256 = ('6' * 64)
    }}
}}
$foreignIntent = [pscustomobject]@{{
    PayloadSha256 = ('f' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '55555555-5555-4555-8555-555555555555'
        source_request_sha256 = ('9' * 64)
        expected_predecessor_sha256 = ('8' * 64)
    }}
}}
$current = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successor
        intent_sha256 = ('c' * 64)
        expected_predecessor_sha256 = $predecessorSha
    }}
}}
function Get-TicketboxDatabaseGenerationExecutionDependencyPaths {{ param($Root); return @() }}
function Enter-TicketboxLifecycleLock {{ return [pscustomobject]@{{}} }}
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
        Release = [pscustomobject]@{{
            secret_byte_count = 32; service_state_timeout_ms = 1000
            service_poll_interval_ms = 10
        }}
        Manifest = [pscustomobject]@{{ Sha256 = ('7' * 64) }}
    }}
}}
function Assert-TicketboxInstalledDatasetServiceAuthority {{ param($Subject) }}
function Read-TicketboxDatabaseGenerationActiveIntent {{
    param($StateRoot)
    $script:activeReads++
    if ($script:activeReads -eq 1) {{ return $validIntent }}
    return $foreignIntent
}}
function Read-TicketboxDatabaseGenerationCurrent {{ return $current }}
function Read-TicketboxInstalledDatasetOperation {{ param($StateRoot, $ExpectedOperationKind, [switch]$AllowAbsent); return $script:durableRequest }}
function Read-TicketboxInstalledDatasetRestoreResult {{ return $null }}
function Invoke-TicketboxInstalledDatasetBackupInspection {{
    return [pscustomobject]@{{ Evidence = [pscustomobject]@{{
        manifest_sha256 = ('e' * 64); dataset_id = '44444444-4444-4444-8444-444444444444'
    }} }}
}}
function Assert-TicketboxInstalledPostgresToolArtifact {{ param($Subject, $Tool) }}
function New-TicketboxInstalledDatabaseGenerationContracts {{
    param($Subject, $PublicBaseUrl)
    return [pscustomobject]@{{ Program = @{{}}; Host = @{{}}; Projection = @{{}}; ReleaseIdentity = @{{}} }}
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); return '{{}}' }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ param($Text); return ('6' * 64) }}
function Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 {{ param($ProjectionContract); return ('6' * 64) }}
function Get-TicketboxInstalledDatasetRestorePaths {{
    return [pscustomobject]@{{ operation_id = $successor }}
}}
function Assert-TicketboxInstalledDatasetOperation {{ param($Operation, $ExpectedOperationKind); return $Operation }}
{classifier}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    $script:poison += 'artifact-read'; throw 'artifact poison'
}}
function Get-OrCreatePostgresBootstrapRecoveryState {{ $script:poison += 'bootstrap'; throw 'bootstrap poison' }}
function New-TicketboxDatabaseGenerationCredentials {{ $script:poison += 'credentials'; throw 'credential poison' }}
function Stop-TicketboxInstalledDatasetWriters {{ $script:poison += 'writers'; throw 'writer poison' }}
function Initialize-TicketboxPostgresqlRestoreCandidateCluster {{ $script:poison += 'candidate'; throw 'candidate poison' }}
function Invoke-TicketboxInstalledDatasetRestoreFailureCompensation {{ return 'rejected-before-mutation' }}
function Exit-TicketboxLifecycleLock {{ param($Lock) }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{
    param($Primary, $Cleanup)
    if ($null -eq $Primary) {{ throw 'expected authority rejection' }}
    if ($Primary.Exception.Message -cnotmatch 'active intent differs') {{ throw $Primary }}
    if ($script:poison.Count -ne 0) {{ throw "authority crossed poison: $($script:poison -join '|')" }}
    [Console]::Out.WriteLine('fresh-authority-rejected')
    exit 0
}}
"""
    (tmp_path / "windows_dataset_restore_runtime.ps1").write_text(
        stubs,
        encoding="utf-8-sig",
    )
    source = RESTORE.read_text(encoding="utf-8-sig")
    prefix, loop = source.split("while ($true) {", maxsplit=1)
    mutated_loop = loop.replace(
        "-Request $request -Intent $active -Current $current",
        "-Request $request -Intent $intentContext.Artifact -Current $current",
        1,
    )
    mutated = prefix + "while ($true) {" + mutated_loop
    for engine in powershell_contract_engines():
        entrypoint.write_text(source, encoding="utf-8-sig")
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
                "ticketbox-backup-33333333-3333-4333-8333-333333333333",
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
        assert completed.stdout.strip() == "fresh-authority-rejected"
        entrypoint.write_text(mutated, encoding="utf-8-sig")
        escaped = subprocess.run(
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
                "ticketbox-backup-33333333-3333-4333-8333-333333333333",
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
        assert escaped.returncode != 0
        assert "artifact poison" in escaped.stderr
