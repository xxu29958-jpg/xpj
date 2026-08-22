from __future__ import annotations

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


def _restore_contract() -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in CONTRACTS)


def test_restore_promotion_is_forward_reconcilable_and_keeps_old_bytes_until_current() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = _restore_contract()

    assert "candidate_pgdata" in contract
    assert "rollback_pgdata" in contract
    assert "candidate_uploads" in contract
    assert "rollback_uploads" in contract
    assert "Resolve-TicketboxInstalledDatasetRestorePhysicalState" in contract
    assert "Set-TicketboxInstalledDatasetRestorePhysicalSelection" in contract
    assert "Invoke-TicketboxInstalledDatasetRestorePromotion" not in contract
    assert '-Selection "Predecessor"' in contract
    compensation = powershell_function(
        contract,
        "Invoke-TicketboxInstalledDatasetRestoreFailureCompensation",
    )
    predecessor = powershell_function(
        contract,
        "Restore-TicketboxInstalledDatasetPredecessorRuntime",
    )
    assert "Read-TicketboxDatabaseGenerationCurrent" in compensation
    assert "Restore-TicketboxInstalledDatasetPredecessorRuntime" in compensation
    assert predecessor.index('-Selection "Predecessor"') < predecessor.index(
        "Publish-TicketboxDatabaseGenerationRuntimeProjection"
    )
    assert predecessor.index("Publish-TicketboxDatabaseGenerationRuntimeProjection") < (
        predecessor.index("Restore-TicketboxInstalledDatabaseGenerationPredecessor")
    )
    assert restore.index("Invoke-TicketboxInstalledDatabaseGeneration") < restore.index(
        "Remove-TicketboxInstalledDatasetRestoreRollback"
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_physical_selection_can_recover_every_precurrent_cutpoint(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    classifier = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestorePhysicalState",
    )
    selector = powershell_function(
        contract,
        "Set-TicketboxInstalledDatasetRestorePhysicalSelection",
    )
    base = str(tmp_path).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (Test-Path -LiteralPath $Path -PathType Container) {{ return 'Directory' }}
    return 'Missing'
}}
function Assert-TicketboxInstalledDatasetRestorePathAuthority {{ param($Paths); return $Paths }}
{classifier}
{selector}
$root = '{base}'
$names = @('stable_pgdata','stable_uploads','candidate_pgdata','candidate_uploads','rollback_pgdata','rollback_uploads')
$forwardCase = Join-Path $root 'forward'
if (Test-Path -LiteralPath $forwardCase) {{ [IO.Directory]::Delete($forwardCase, $true) }}
$forwardPaths = [pscustomobject][ordered]@{{
    stable_pgdata = Join-Path $forwardCase 'stable-pg'
    stable_uploads = Join-Path $forwardCase 'stable-uploads'
    candidate_pgdata = Join-Path $forwardCase 'candidate/pg'
    candidate_uploads = Join-Path $forwardCase 'candidate/uploads'
    rollback_pgdata = Join-Path $forwardCase 'rollback/pg'
    rollback_uploads = Join-Path $forwardCase 'rollback/uploads'
    candidate_root = Join-Path $forwardCase 'candidate'
    rollback_root = Join-Path $forwardCase 'rollback'
}}
foreach ($name in @('stable_pgdata','stable_uploads','candidate_pgdata','candidate_uploads')) {{
    [IO.Directory]::CreateDirectory([string]$forwardPaths.$name) | Out-Null
}}
Set-TicketboxInstalledDatasetRestorePhysicalSelection -Paths $forwardPaths -Selection 'Candidate'
if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $forwardPaths) -cne 'candidate_published') {{
    throw 'candidate publication did not reach its exact physical state'
}}
Set-TicketboxInstalledDatasetRestorePhysicalSelection -Paths $forwardPaths -Selection 'Predecessor'
if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $forwardPaths) -cne 'candidate_ready') {{
    throw 'published candidate did not return to predecessor selection'
}}
$signatures = @('011110','001111','100111','110011')
foreach ($signature in $signatures) {{
    $case = Join-Path $root $signature
    if (Test-Path -LiteralPath $case) {{ [IO.Directory]::Delete($case, $true) }}
    $paths = [pscustomobject][ordered]@{{
        stable_pgdata = Join-Path $case 'stable-pg'
        stable_uploads = Join-Path $case 'stable-uploads'
        candidate_pgdata = Join-Path $case 'candidate/pg'
        candidate_uploads = Join-Path $case 'candidate/uploads'
        rollback_pgdata = Join-Path $case 'rollback/pg'
        rollback_uploads = Join-Path $case 'rollback/uploads'
        candidate_root = Join-Path $case 'candidate'
        rollback_root = Join-Path $case 'rollback'
    }}
    for ($index = 0; $index -lt $names.Count; $index++) {{
        if ($signature[$index] -ceq '1') {{
            [IO.Directory]::CreateDirectory([string]$paths.($names[$index])) | Out-Null
        }}
    }}
    Set-TicketboxInstalledDatasetRestorePhysicalSelection -Paths $paths -Selection 'Predecessor'
    if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $paths) -cne 'candidate_ready') {{
        throw "predecessor recovery failed for $signature"
    }}
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-physical-compensation.ps1",
    )


def test_restore_keeps_rollback_until_runtime_and_originals_are_verified() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = _restore_contract()

    verification = restore.split('"verify_runtime" {', maxsplit=1)[1].split('"retire_rollback" {', maxsplit=1)[0]
    assert verification.index("Start-TicketboxOwnedServiceIfExists") < (
        verification.index("Wait-TicketboxInstalledBackendHealth")
    )
    assert verification.index("Wait-TicketboxInstalledBackendHealth") < (
        verification.index("Invoke-TicketboxInstalledRestoredOriginalsVerification")
    )
    assert verification.index("Invoke-TicketboxInstalledRestoredOriginalsVerification") < verification.index(
        "New-TicketboxInstalledDatasetRuntimeVerification"
    )
    assert "runtime-verification" in contract


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_retirement_partial_effects_remain_classifiable_and_retryable(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    classifier = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestorePhysicalState",
    )
    reducer = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestoreNextAction",
    )
    base = str(tmp_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (Test-Path -LiteralPath $Path -PathType Container) {{ return 'Directory' }}
    return 'Missing'
}}
function Assert-TicketboxInstalledDatasetRestorePathAuthority {{ param($Paths); return $Paths }}
{classifier}
{reducer}
$root = '{base}'
function New-Paths([string]$Name) {{
    $case = Join-Path $root $Name
    return [pscustomobject][ordered]@{{
        stable_pgdata = Join-Path $case 'stable-pg'
        stable_uploads = Join-Path $case 'stable-uploads'
        candidate_pgdata = Join-Path $case 'candidate/pg'
        candidate_uploads = Join-Path $case 'candidate/uploads'
        rollback_pgdata = Join-Path $case 'rollback/pg'
        rollback_uploads = Join-Path $case 'rollback/uploads'
        candidate_root = Join-Path $case 'candidate'
        rollback_root = Join-Path $case 'rollback'
    }}
}}
$partial = New-Paths 'partial-child-delete'
foreach ($path in @($partial.stable_pgdata, $partial.stable_uploads, $partial.rollback_uploads)) {{
    [IO.Directory]::CreateDirectory([string]$path) | Out-Null
}}
$partialState = Resolve-TicketboxInstalledDatasetRestorePhysicalState $partial
if ($partialState -cne 'rollback_retiring') {{ throw "partial delete was not classified: $partialState" }}
$partialAction = Resolve-TicketboxInstalledDatasetRestoreNextAction `
    $partialState $true $true $true $true
if ($partialAction -cne 'retire_rollback') {{ throw "partial delete was not retried: $partialAction" }}

$containers = New-Paths 'empty-containers'
foreach ($path in @(
    $containers.stable_pgdata, $containers.stable_uploads,
    $containers.candidate_root, $containers.rollback_root
)) {{
    [IO.Directory]::CreateDirectory([string]$path) | Out-Null
}}
$containerState = Resolve-TicketboxInstalledDatasetRestorePhysicalState $containers
if ($containerState -cne 'cleanup_pending') {{ throw "empty cleanup roots were ignored: $containerState" }}
$containerAction = Resolve-TicketboxInstalledDatasetRestoreNextAction `
    $containerState $true $true $true $true
if ($containerAction -cne 'retire_rollback') {{ throw "container cleanup was not retried: $containerAction" }}

$rejected = $false
try {{
    Resolve-TicketboxInstalledDatasetRestoreNextAction `
        'rollback_retiring' $true $true $true $false | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'rollback retirement proceeded without runtime verification' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-retirement-retry.ps1",
    )


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
        current_sha256 = ('a' * 64)
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
function Assert-TicketboxInstalledDatasetOperation {{ param($Operation, $ExpectedOperationKind); return $Operation }}
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
