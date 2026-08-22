from __future__ import annotations

from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
ARTIFACTS = PACKAGING / "windows_database_generation_artifacts.ps1"
RESTORE_ARTIFACTS = PACKAGING / "windows_installed_dataset_restore_artifacts.ps1"
RUNTIME = PACKAGING / "windows_dataset_restore_runtime.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_runtime_verification_round_trips_through_closed_artifact_api(
    tmp_path: Path,
) -> None:
    source = ARTIFACTS.read_text(encoding="utf-8-sig")
    functions = "\n".join(
        powershell_function(source, name)
        for name in (
            "Get-TicketboxDatabaseGenerationArtifactPath",
            "Get-TicketboxDatabaseGenerationPayloadProperties",
            "Read-TicketboxDatabaseGenerationEnvelope",
            "Write-TicketboxDatabaseGenerationEnvelope",
            "Read-TicketboxDatabaseGenerationOperationArtifact",
            "New-TicketboxDatabaseGenerationChainedArtifact",
        )
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM')
$script:TicketboxDatabaseGenerationOwnerAccount = 'SYSTEM'
$script:store = @{{}}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
function Get-TicketboxPathEntryKindNoFollow {{
    param($Path)
    if ($script:store.ContainsKey($Path)) {{ return 'File' }}
    return 'Missing'
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $OwnerAccount)
    $script:store[$Path] = $Text
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    return [pscustomobject]@{{ Text = [string]$script:store[$Path] }}
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "unexpected fields: $Label" }}
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Depth 30 -Compress)
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{ param($Text); return ('a' * 64) }}
{functions}
$operation = '22222222-2222-4222-8222-222222222222'
$payload = [ordered]@{{
    schema = 'ticketbox-installed-dataset-runtime-verification-v1'
    operation_id = $operation
    intent_sha256 = ('b' * 64)
    source_request_sha256 = ('c' * 64)
    current_sha256 = ('d' * 64)
    backup_manifest_sha256 = ('e' * 64)
    backup_id = '33333333-3333-4333-8333-333333333333'
    dataset_id = '44444444-4444-4444-8444-444444444444'
    restore_epoch = 7
    original_count = 9
    health_contract = 'ticketbox-installation-health-v2'
    result = 'restored_runtime_verified'
}}
$written = New-TicketboxDatabaseGenerationChainedArtifact `
    -StateRoot 'C:\\state' -OperationId $operation `
    -Kind 'runtime-verification' -Payload $payload `
    -LifecycleLock ([pscustomobject]@{{}})
$read = Read-TicketboxDatabaseGenerationOperationArtifact `
    -StateRoot 'C:\\state' -OperationId $operation -Kind 'runtime-verification'
if (
    [string]$written.Kind -cne 'runtime-verification' -or
    [string]$read.Kind -cne 'runtime-verification' -or
    [string]$read.Payload.operation_id -cne $operation -or
    [string]$read.Payload.result -cne 'restored_runtime_verified'
) {{ throw 'runtime verification did not round-trip through the closed artifact API' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-runtime-verification-artifact-registry.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_compensation_rejects_foreign_authority_before_side_effects(
    tmp_path: Path,
) -> None:
    compensation = powershell_function(
        RUNTIME.read_text(encoding="utf-8-sig"),
        "Invoke-TicketboxInstalledDatasetRestoreFailureCompensation",
    )
    classifier = powershell_function(
        RESTORE_ARTIFACTS.read_text(encoding="utf-8-sig"),
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$successor = '22222222-2222-4222-8222-222222222222'
$predecessorSha = ('a' * 64)
$request = [pscustomobject]@{{
    PayloadSha256 = ('d' * 64)
    Payload = [pscustomobject]@{{
        restart_backend = $true
        predecessor_current_sha256 = $predecessorSha
    }}
}}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $successor
        source_request_sha256 = ('d' * 64)
        expected_predecessor_sha256 = $predecessorSha
    }}
}}
function Read-TicketboxDatabaseGenerationCurrent {{
    $script:events += 'read-current'
    return $script:current
}}
function Read-TicketboxDatabaseGenerationActiveIntent {{
    param($StateRoot)
    $script:events += 'read-intent'
    return $intent
}}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    $script:events += 'read-artifact'
    throw 'artifact read crossed foreign authority'
}}
function Assert-TicketboxInstalledDatasetRestoreRequest {{ param($Request); return $Request }}
function Remove-TicketboxPostgresqlRestoreCandidateService {{ throw 'candidate service changed under foreign authority' }}
function Stop-TicketboxInstalledDatasetWriters {{ throw 'writers changed under foreign authority' }}
function Restore-TicketboxInstalledDatasetPredecessorRuntime {{ throw 'physical state changed under foreign authority' }}
function Set-TicketboxInstalledDatasetBackendDesiredState {{ throw 'backend state changed under foreign authority' }}
{classifier}
{compensation}
$cases = @(
    [pscustomobject]@{{
        PayloadSha256 = ('f' * 64)
        Payload = [pscustomobject]@{{
            operation_id = '55555555-5555-4555-8555-555555555555'
            intent_sha256 = ('c' * 64)
            expected_predecessor_sha256 = $predecessorSha
        }}
    }},
    [pscustomobject]@{{
        PayloadSha256 = ('b' * 64)
        Payload = [pscustomobject]@{{
            operation_id = $successor
            intent_sha256 = ('f' * 64)
            expected_predecessor_sha256 = $predecessorSha
        }}
    }}
)
foreach ($case in $cases) {{
    $script:events = @()
    $script:current = $case
    $rejected = $false
    try {{
        Invoke-TicketboxInstalledDatasetRestoreFailureCompensation `
            -Subject ([pscustomobject]@{{}}) -Request $request `
            -Paths ([pscustomobject]@{{ operation_id = $successor }}) `
            -StateRoot 'C:\\state' -Contracts ([pscustomobject]@{{}}) `
            -Inspection ([pscustomobject]@{{}}) `
            -LifecycleLock ([pscustomobject]@{{}}) | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected -or ($script:events -join '|') -cne 'read-current|read-intent') {{
        throw "foreign authority was not rejected before side effects: $($script:events -join '|')"
    }}
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-compensation-foreign-authority.ps1",
    )
