from __future__ import annotations

import re
from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
RESTORE = PACKAGING / "windows_dataset_restore.ps1"
CONTRACTS = (
    PACKAGING / "windows_installed_dataset_reader.ps1",
    PACKAGING / "windows_installed_dataset_operation.ps1",
    PACKAGING / "windows_installed_dataset_restore_artifacts.ps1",
    PACKAGING / "windows_installed_dataset_restore_verification.ps1",
    PACKAGING / "windows_dataset_restore_filesystem.ps1",
    PACKAGING / "windows_dataset_restore_reducer.ps1",
    PACKAGING / "windows_dataset_restore_database.ps1",
    PACKAGING / "windows_dataset_restore_runtime.ps1",
)
CLUSTER = PACKAGING / "windows_postgresql_candidate_cluster.ps1"
CLUSTER_INITDB = PACKAGING / "windows_postgresql_candidate_initdb.ps1"
CLUSTER_RUNTIME = PACKAGING / "windows_postgresql_candidate_runtime.ps1"


def _restore_contract() -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in CONTRACTS)


def test_restore_owner_is_explicit_durable_isolated_and_h1_published() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = _restore_contract()
    cluster = CLUSTER.read_text(encoding="utf-8-sig")
    cluster_initdb = CLUSTER_INITDB.read_text(encoding="utf-8-sig")
    cluster_runtime = CLUSTER_RUNTIME.read_text(encoding="utf-8-sig")

    assert "[Parameter(Mandatory = $true)][string]$BackupGeneration" in restore
    assert "Read-TicketboxInstalledDatasetOperation" in contract
    assert "Resolve-TicketboxInstalledDatasetRestoreNextAction" in contract
    assert "Start-TicketboxInstalledDatasetRestoreOperation" in restore
    assert restore.rindex("Start-TicketboxInstalledDatasetRestoreOperation") < (
        restore.rindex("Stop-TicketboxInstalledDatasetWriters")
    )
    assert "Initialize-TicketboxPostgresqlRestoreCandidateCluster" in cluster_initdb
    assert "Start-TicketboxPostgresqlRestoreCandidateService" in cluster_runtime
    assert "Initialize-TicketboxPostgresqlRestoreCandidateDatabase" in cluster_runtime
    assert "New-TicketboxPostgresqlRestoreCandidate" not in cluster + cluster_initdb
    assert "Invoke-TicketboxInstalledDatabaseGeneration" in restore
    assert "Publish-TicketboxDatabaseGenerationCurrent" not in restore
    current_callers = []
    for path in PACKAGING.glob("*.ps1"):
        source = path.read_text(encoding="utf-8-sig")
        if re.search(
            r"(?m)^\s+(?:return\s+)?Publish-TicketboxDatabaseGenerationCurrent\b",
            source,
        ):
            current_callers.append(path.name)
    assert current_callers == ["windows_database_generation.ps1"]
    assert "LastWriteTime" not in restore
    assert "latest" not in restore.casefold()
    assert "function Assert-TicketboxInstalledDatasetServiceAuthority" in contract
    authority_check = restore.index("Assert-TicketboxInstalledDatasetServiceAuthority")
    first_stop = restore.index("Stop-TicketboxInstalledDatasetWriters", authority_check)
    assert authority_check < first_stop
    service_authority = powershell_function(
        contract,
        "Assert-TicketboxInstalledDatasetServiceAuthority",
    )
    assert "[string]$identity.BackendServiceName" in service_authority
    assert "[string]$identity.PgServiceName" in service_authority
    assert "Assert-TicketboxReleaseServiceIdentity" in service_authority
    assert "Assert-TicketboxPgServiceCommand" in service_authority
    assert '"app\\backups"' not in contract
    assert '"backups"' in contract
    assert "[string]$decoded.release_id -cne [string]$Subject.Manifest.Sha256" in contract
    inspection = powershell_function(
        contract,
        "Invoke-TicketboxInstalledDatasetBackupInspection",
    )
    assert "Get-ChildItem -LiteralPath $generationPath -Force -Recurse" in inspection
    assert "Assert-TicketboxExactFileAcl" in inspection
    assert inspection.rindex("Assert-TicketboxExactFileAcl") < inspection.index(
        "Open-TicketboxVerifiedDatabaseMaintenanceHelperLease"
    )


def test_restore_durable_request_owns_backend_restart_compensation() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = (PACKAGING / "windows_installed_dataset_operation.ps1").read_text(encoding="utf-8-sig")
    request = powershell_function(
        contract,
        "Assert-TicketboxInstalledDatasetOperation",
    )

    assert '"restart_backend"' in request
    assert "$payload.restart_backend -isnot [bool]" in request
    create = powershell_function(
        contract,
        "Start-TicketboxInstalledDatasetRestoreOperation",
    )
    assert "[Parameter(Mandatory = $true)][bool]$RestartBackend" in create
    assert "restart_backend = $RestartBackend" in create
    assert '"restart_backend"' in request
    assert '"predecessor_current_payload"' in request
    assert "RestartBackend $restartBackend" in restore
    assert "RestoreAttemptId" in restore
    assert "source_request_sha256" in restore
    runtime = restore.split('"verify_runtime" {', maxsplit=1)[1].split('"retire_rollback" {', maxsplit=1)[0]
    assert runtime.index("Set-TicketboxInstalledDatasetBackendDesiredState") < (
        runtime.index("New-TicketboxInstalledDatasetRuntimeVerification")
    )
    terminal = restore.rindex("New-TicketboxInstalledDatasetRestoreResult")
    retirement = restore.rindex("Remove-TicketboxInstalledDatasetOperation")
    assert terminal < retirement
    assert "function Remove-TicketboxInstalledDatasetOperation" in contract


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_owner_compensation_restores_exact_predecessor_before_restart(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    compensation = powershell_function(
        contract,
        "Invoke-TicketboxInstalledDatasetRestoreFailureCompensation",
    )
    classifier = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = @()
$script:published = $false
function Read-TicketboxDatabaseGenerationCurrent {{
    $script:events += 'read-current'
    $operation = if ($script:published) {{ '22222222-2222-4222-8222-222222222222' }} else {{ '11111111-1111-4111-8111-111111111111' }}
    $sha = if ($script:published) {{ ('b' * 64) }} else {{ ('a' * 64) }}
    return [pscustomobject]@{{
        PayloadSha256 = $sha
        Payload = [pscustomobject]@{{
            operation_id = $operation
            expected_predecessor_sha256 = ('a' * 64)
            intent_sha256 = ('c' * 64)
        }}
    }}
}}
function Read-TicketboxDatabaseGenerationActiveIntent {{
    param($StateRoot)
    $script:events += 'read-intent'
    return [pscustomobject]@{{
        PayloadSha256 = ('c' * 64)
        Payload = [pscustomobject]@{{
            operation_id = '22222222-2222-4222-8222-222222222222'
            source_request_sha256 = ('d' * 64)
            expected_predecessor_sha256 = ('a' * 64)
        }}
    }}
}}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    param($StateRoot, $OperationId, $Kind, [switch]$AllowAbsent)
    $script:events += 'read-runtime-verification'
    return $null
}}
function Remove-TicketboxPostgresqlRestoreCandidateService {{ param($Subject, $Paths); $script:events += 'remove-candidate-service' }}
function Stop-TicketboxInstalledDatasetWriters {{ param($Subject); $script:events += 'stop-writers' }}
function Restore-TicketboxInstalledDatasetPredecessorRuntime {{
    param($Subject, $Request, $Paths, $StateRoot, $Contracts, $Intent, $Current, $LifecycleLock)
    $script:events += "restore-predecessor:$($Current.PayloadSha256)"
}}
function Set-TicketboxInstalledDatasetBackendDesiredState {{
    param($Subject, $ShouldRun)
    $script:events += "desired:$ShouldRun"
}}
function Assert-TicketboxInstalledDatasetOperation {{ param($Operation, $ExpectedOperationKind); return $Operation }}
{classifier}
{compensation}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\Ticketbox'; PgServiceName = 'ticketbox-pg'; BackendServiceName = 'ticketbox-backend' }}
    Release = [pscustomobject]@{{ service_state_timeout_ms = 1000; service_poll_interval_ms = 10 }}
}}
$request = [pscustomobject]@{{ PayloadSha256 = ('d' * 64); Payload = [pscustomobject]@{{
    restart_backend = $true
    current_sha256 = ('a' * 64)
}} }}
$paths = [pscustomobject]@{{ operation_id = '22222222-2222-4222-8222-222222222222' }}
$script:published = $true
$outcome = Invoke-TicketboxInstalledDatasetRestoreFailureCompensation `
    -Subject $subject -Request $request -Paths $paths -StateRoot 'C:\state' `
    -Contracts ([pscustomobject]@{{}}) `
    -Inspection ([pscustomobject]@{{ Evidence = [pscustomobject]@{{ original_count = 9 }} }}) `
    -LifecycleLock ([pscustomobject]@{{}})
$expected = 'read-current|read-intent|read-runtime-verification|remove-candidate-service|stop-writers|restore-predecessor:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|desired:True'
if (($script:events -join '|') -cne $expected -or $outcome -cne 'rolled_back') {{
    throw "published CURRENT did not restore exact predecessor: $outcome / $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-owner-compensation.ps1",
    )
