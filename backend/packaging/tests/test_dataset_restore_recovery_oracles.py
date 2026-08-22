from __future__ import annotations

import json
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
CONTRACTS = (
    PACKAGING / "windows_installed_dataset_reader.ps1",
    PACKAGING / "windows_installed_dataset_restore_artifacts.ps1",
    PACKAGING / "windows_installed_dataset_restore_verification.ps1",
    PACKAGING / "windows_dataset_restore_filesystem.ps1",
    PACKAGING / "windows_dataset_restore_reducer.ps1",
    PACKAGING / "windows_dataset_restore_database.ps1",
    PACKAGING / "windows_dataset_restore_runtime.ps1",
)


def _restore_contract() -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in CONTRACTS)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_compensation_reclassifies_durable_runtime_verification(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    verification = powershell_function(
        contract,
        "Assert-TicketboxInstalledDatasetRuntimeVerification",
    )
    compensation = powershell_function(
        contract,
        "Invoke-TicketboxInstalledDatasetRestoreFailureCompensation",
    )
    classifier = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:events = @()
$successor = '22222222-2222-4222-8222-222222222222'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successor
        source_request_sha256 = ('d' * 64)
        expected_predecessor_sha256 = ('a' * 64)
    }}
}}
$current = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successor
        intent_sha256 = ('c' * 64)
        expected_predecessor_sha256 = ('a' * 64)
    }}
}}
$request = [pscustomobject]@{{
    PayloadSha256 = ('d' * 64)
    Payload = [pscustomobject]@{{
        restart_backend = $true
        predecessor_current_sha256 = ('a' * 64)
        backup_manifest_sha256 = ('e' * 64)
        backup_id = '33333333-3333-4333-8333-333333333333'
        dataset_id = '44444444-4444-4444-8444-444444444444'
        backup_restore_epoch = 4
        active_restore_epoch = 6
    }}
}}
$runtime = [pscustomobject]@{{
    Kind = 'runtime-verification'
    Payload = [pscustomobject][ordered]@{{
        schema = 'ticketbox-installed-dataset-runtime-verification-v1'
        operation_id = $successor
        intent_sha256 = ('c' * 64)
        source_request_sha256 = ('d' * 64)
        current_sha256 = ('b' * 64)
        backup_manifest_sha256 = ('e' * 64)
        backup_id = '33333333-3333-4333-8333-333333333333'
        dataset_id = '44444444-4444-4444-8444-444444444444'
        restore_epoch = 7
        original_count = 9
        health_contract = 'ticketbox-installation-health-v2'
        result = 'restored_runtime_verified'
    }}
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "unexpected fields: $Label" }}
}}
function Assert-TicketboxInstalledDatasetRestoreRequest {{ param($Request); return $Request }}
function Read-TicketboxDatabaseGenerationCurrent {{
    $script:events += 'read-current'
    return $current
}}
function Read-TicketboxDatabaseGenerationActiveIntent {{
    param($StateRoot)
    $script:events += 'read-intent'
    return $intent
}}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    param($StateRoot, $OperationId, $Kind, [switch]$AllowAbsent)
    $script:events += "read-artifact:${{OperationId}}:$Kind"
    if ($OperationId -cne $successor -or $Kind -cne 'runtime-verification') {{
        throw 'runtime verification read crossed operation authority'
    }}
    return $runtime
}}
function Set-TicketboxInstalledDatasetBackendDesiredState {{
    param($Subject, $ShouldRun)
    $script:events += "desired:$ShouldRun"
}}
function Remove-TicketboxPostgresqlRestoreCandidateService {{ throw 'rollback after durable verification' }}
function Stop-TicketboxInstalledDatasetWriters {{ throw 'rollback after durable verification' }}
function Restore-TicketboxInstalledDatasetPredecessorRuntime {{ throw 'rollback after durable verification' }}
{verification}
{classifier}
{compensation}
$inspection = [pscustomobject]@{{ Evidence = [pscustomobject]@{{ original_count = 9 }} }}
$outcome = Invoke-TicketboxInstalledDatasetRestoreFailureCompensation `
    -Subject ([pscustomobject]@{{}}) -Request $request `
    -Paths ([pscustomobject]@{{ operation_id = $successor }}) `
    -StateRoot 'C:\\state' -Contracts ([pscustomobject]@{{}}) `
    -Inspection $inspection -LifecycleLock ([pscustomobject]@{{}})
$expected = "read-current|read-intent|read-artifact:${{successor}}:runtime-verification|desired:True"
if ($outcome -cne 'committed' -or ($script:events -join '|') -cne $expected) {{
    throw "durable verification was not reclassified: $outcome / $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-durable-verification-compensation.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_predecessor_runtime_uses_one_exact_predecessor_artifact_chain(
    tmp_path: Path,
) -> None:
    predecessor = powershell_function(
        _restore_contract(),
        "Restore-TicketboxInstalledDatasetPredecessorRuntime",
    )
    classifier = powershell_function(
        _restore_contract(),
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:events = @()
$predecessorOperation = '11111111-1111-4111-8111-111111111111'
$successorOperation = '22222222-2222-4222-8222-222222222222'
$lifecycleLock = [pscustomobject]@{{ token = 'lock' }}
$transitionSentinel = [pscustomobject]@{{ token = 'transition' }}
$predecessorCandidate = [pscustomobject]@{{ PayloadSha256 = ('d' * 64); Payload = [pscustomobject]@{{ operation_id = $predecessorOperation }} }}
$successorCandidate = [pscustomobject]@{{ PayloadSha256 = ('e' * 64); Payload = [pscustomobject]@{{ operation_id = $successorOperation }} }}
function Set-TicketboxInstalledDatasetRestorePhysicalSelection {{ param($Paths, $Selection); $script:events += "select:$Selection" }}
function Set-TicketboxInstalledDatasetPublishedAcls {{ param($Subject, $Paths); $script:events += 'set-acls' }}
function Start-TicketboxOwnedServiceIfExists {{ param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds); $script:events += "start:$Name" }}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    param($StateRoot, $OperationId, $Kind)
    $script:events += "read:${{OperationId}}:$Kind"
    if ($OperationId -ceq $predecessorOperation) {{ return $predecessorCandidate }}
    if ($OperationId -ceq $successorOperation) {{ return $successorCandidate }}
    throw 'foreign candidate operation'
}}
function Read-TicketboxDatabaseGenerationRuntimeCredentials {{
    param($StateRoot, $Intent, $Candidate)
    $script:events += "credentials:$($Intent.Payload.operation_id):$($Candidate.PayloadSha256)"
    return [pscustomobject]@{{}}
}}
function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {{ param($HostContract); return [pscustomobject]@{{}} }}
function Publish-TicketboxDatabaseGenerationRuntimeProjection {{
    param($Intent, $Candidate, $Credentials, $HostAuthority, $ProjectionContract, $LifecycleLock)
    if ([string]$ProjectionContract.public_base_url -cne 'https://public.example') {{
        throw 'rollback projection dropped PUBLIC_BASE_URL'
    }}
    $script:events += "projection:$($Intent.Payload.operation_id):$($Candidate.PayloadSha256)"
}}
function New-TicketboxInstalledDatasetRestorePredecessorCurrentTransition {{
    param($Current, $RestoreRequest)
    if (-not [object]::ReferenceEquals($Current, $current)) {{
        throw 'transition builder did not receive exact observed CURRENT'
    }}
    if (-not [object]::ReferenceEquals($RestoreRequest, $request)) {{
        throw 'transition builder did not receive exact restore request'
    }}
    $script:events += "transition:$($RestoreRequest.Payload.predecessor_current_sha256)"
    return $transitionSentinel
}}
function Publish-TicketboxDatabaseGenerationCurrent {{
    param($Transition, $LifecycleLock)
    if (-not [object]::ReferenceEquals($Transition, $transitionSentinel)) {{
        throw 'CURRENT publisher did not receive exact transition'
    }}
    if (-not [object]::ReferenceEquals($LifecycleLock, $lifecycleLock)) {{
        throw 'CURRENT publisher did not receive exact lifecycle lock'
    }}
    $script:events += 'publish-current'
}}
function Close-TicketboxDatabaseGenerationRuntimeCredentials {{ param($Credentials); $script:events += 'close-credentials' }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{
    param($Primary, $Cleanup)
    if ($null -ne $Primary) {{ throw $Primary }}
    if (@($Cleanup).Count -gt 0) {{ throw [string]@($Cleanup)[0] }}
}}
function Assert-TicketboxInstalledDatasetRestoreRequest {{ param($Request); return $Request }}
{classifier}
{predecessor}
$request = [pscustomobject]@{{
    PayloadSha256 = ('f' * 64)
    Payload = [pscustomobject]@{{
        predecessor_current_sha256 = ('a' * 64)
        predecessor_intent_sha256 = ('c' * 64)
        predecessor_intent_payload = [pscustomobject]@{{ operation_id = $predecessorOperation }}
        predecessor_current_payload = [pscustomobject]@{{
            intent_sha256 = ('c' * 64)
            candidate_sha256 = ('d' * 64)
        }}
    }}
}}
$current = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successorOperation
        intent_sha256 = ('b' * 64)
        expected_predecessor_sha256 = ('a' * 64)
    }}
}}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successorOperation
        source_request_sha256 = ('f' * 64)
        expected_predecessor_sha256 = ('a' * 64)
    }}
}}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\\Ticketbox'; PgServiceName = 'ticketbox-pg' }}
    Release = [pscustomobject]@{{ service_state_timeout_ms = 1000; service_poll_interval_ms = 10 }}
}}
Restore-TicketboxInstalledDatasetPredecessorRuntime `
    -Subject $subject -Request $request `
    -Paths ([pscustomobject]@{{ operation_id = $successorOperation }}) `
    -StateRoot 'C:\\state' `
    -Contracts ([pscustomobject]@{{ Host = [pscustomobject]@{{}}; Projection = [pscustomobject]@{{ public_base_url = 'https://public.example' }} }}) `
    -Intent $intent -Current $current -LifecycleLock $lifecycleLock
$expected = @(
    'select:Predecessor', 'set-acls', 'start:ticketbox-pg',
    "read:${{predecessorOperation}}:candidate",
    "credentials:${{predecessorOperation}}:$('d' * 64)",
    "projection:${{predecessorOperation}}:$('d' * 64)",
    "transition:$('a' * 64)", 'publish-current', 'close-credentials'
)
if (($script:events -join '|') -cne ($expected -join '|')) {{
    throw "predecessor artifact chain drifted: $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-predecessor-artifact-chain.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_entrypoint_replays_terminal_after_request_retirement(
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
        "windows_installed_dataset_restore_artifacts.ps1",
        "windows_installed_dataset_restore_verification.ps1",
        "windows_dataset_restore_filesystem.ps1",
        "windows_dataset_restore_reducer.ps1",
        "windows_dataset_restore_database.ps1",
        "windows_dataset_restore_runtime.ps1",
        "windows_postgresql_candidate_cluster.ps1",
        "windows_bundled_database.ps1",
    )
    for name in dependency_names:
        (tmp_path / name).write_text("", encoding="utf-8-sig")
    replay = powershell_function(
        _restore_contract(),
        "Complete-TicketboxInstalledDatasetRestoreTerminalReplay",
    )
    stubs = r"""
function Get-TicketboxDatabaseGenerationExecutionDependencyPaths { param($Root); return @() }
function Enter-TicketboxLifecycleLock { return [pscustomobject]@{} }
function Assert-TicketboxLifecycleOperationLease { param($Lock) }
function Get-TicketboxInstallerStateDirectory { return 'C:\installer-state' }
function Get-TicketboxDatabaseGenerationStateRoot { param($InstallerState); return 'C:\state' }
function Assert-TicketboxInstalledDatasetSubject {
    param($DataRoot)
    return [pscustomobject]@{
        Identity = [pscustomobject]@{ DataRoot = $DataRoot; PgPort = 15432 }
        Release = [pscustomobject]@{ secret_byte_count = 32 }
        Manifest = [pscustomobject]@{ Sha256 = ('c' * 64) }
    }
}
function Assert-TicketboxInstalledDatasetServiceAuthority { param($Subject) }
function Read-TicketboxDatabaseGenerationActiveIntent { param($StateRoot); return [pscustomobject]@{} }
function Read-TicketboxDatabaseGenerationCurrent {
    return [pscustomobject]@{
        PayloadSha256 = ('b' * 64)
        Payload = [pscustomobject]@{ operation_id = '44444444-4444-4444-8444-444444444444' }
    }
}
function Get-TicketboxInstalledDatasetRestoreRequest { param($StateRoot, [switch]$AllowAbsent); return $null }
function Read-TicketboxInstalledDatasetRestoreResult {
    param($StateRoot, $RestoreAttemptId, $BackupGeneration, $Current, $ExpectedReleaseManifestSha256, [switch]$AllowAbsent)
    return [pscustomobject]@{
        Disposition = 'current'
        Artifact = [pscustomobject]@{ Payload = [pscustomobject]@{
            request_sha256 = ('a' * 64)
            release_manifest_sha256 = ('c' * 64)
            restore_attempt_id = $RestoreAttemptId
            backup_id = '22222222-2222-4222-8222-222222222222'
            dataset_id = '33333333-3333-4333-8333-333333333333'
            restore_epoch = 5
            generation_operation_id = '44444444-4444-4444-8444-444444444444'
        } }
    }
}
function Invoke-TicketboxInstalledDatasetBackupInspection { throw 'terminal replay entered restore mutation path' }
function Exit-TicketboxLifecycleLock { param($Lock) }
function Throw-TicketboxDatabaseGenerationOperationFailure {
    param($Primary, $Cleanup)
    if ($null -ne $Primary) { throw $Primary }
    if (@($Cleanup).Count -gt 0) { throw [string]@($Cleanup)[0] }
}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson { param($Value); return ($Value | ConvertTo-Json -Depth 20 -Compress) }
""" + replay
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
                "ticketbox-backup-22222222-2222-4222-8222-222222222222",
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
        result = json.loads(completed.stdout.strip())
        assert result["restore_attempt_id"] == "11111111-1111-4111-8111-111111111111"
        assert result["generation_operation_id"] == "44444444-4444-4444-8444-444444444444"
        assert result["result"] == "current_published"
