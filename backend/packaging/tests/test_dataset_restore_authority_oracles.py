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
ARTIFACTS = PACKAGING / "windows_database_generation_artifacts.ps1"
INSTALLED_READER = PACKAGING / "windows_installed_dataset_reader.ps1"
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"
GENERATION_CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
RESTORE = PACKAGING / "windows_dataset_restore.ps1"
RESTORE_ARTIFACTS = PACKAGING / "windows_installed_dataset_restore_artifacts.ps1"
RUNTIME = PACKAGING / "windows_dataset_restore_runtime.ps1"


def test_dataset_owners_do_not_assign_powershell_host_automatic_variable() -> None:
    offenders = []
    paths = {
        *PACKAGING.glob("windows_*dataset*.ps1"),
        *PACKAGING.glob("windows_database_generation*.ps1"),
    }
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8-sig")
        if re.search(r"(?im)^\s*\$host\s*=", source):
            offenders.append(path.name)
    assert offenders == []


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
    producer = powershell_function(
        RUNTIME.read_text(encoding="utf-8-sig"),
        "New-TicketboxInstalledDatasetRuntimeVerification",
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
{producer}
$operation = '22222222-2222-4222-8222-222222222222'
$intentContext = [pscustomobject]@{{
    StateRoot = 'C:\\state'
    Artifact = [pscustomobject]@{{
        PayloadSha256 = ('b' * 64)
        Payload = [pscustomobject]@{{ operation_id = $operation }}
    }}
}}
$request = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        backup_manifest_sha256 = ('e' * 64)
        backup_id = '33333333-3333-4333-8333-333333333333'
        dataset_id = '44444444-4444-4444-8444-444444444444'
        backup_restore_epoch = 4
        active_restore_epoch = 6
    }}
}}
$current = [pscustomobject]@{{ PayloadSha256 = ('d' * 64) }}
$inspection = [pscustomobject]@{{ Evidence = [pscustomobject]@{{ original_count = 9 }} }}
$written = New-TicketboxInstalledDatasetRuntimeVerification `
    -IntentContext $intentContext -Request $request -Current $current `
    -Inspection $inspection -LifecycleLock ([pscustomobject]@{{}})
$read = Read-TicketboxDatabaseGenerationOperationArtifact `
    -StateRoot 'C:\\state' -OperationId $operation -Kind 'runtime-verification'
$candidatePath = Get-TicketboxDatabaseGenerationArtifactPath `
    -StateRoot 'C:\\state' -OperationId $operation -Kind 'candidate-verification'
if (
    [string]$written.Kind -cne 'runtime-verification' -or
    [string]$read.Kind -cne 'runtime-verification' -or
    [string]$read.Payload.operation_id -cne $operation -or
    [string]$read.Payload.result -cne 'restored_runtime_verified' -or
    $script:store.ContainsKey($candidatePath)
) {{ throw 'runtime verification did not round-trip through the closed artifact API' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-runtime-verification-artifact-registry.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_installed_projection_preserves_valid_public_base_url(
    tmp_path: Path,
) -> None:
    reader_source = INSTALLED_READER.read_text(encoding="utf-8-sig")
    contracts = powershell_function(
        reader_source,
        "New-TicketboxInstalledDatabaseGenerationContracts",
    )
    public_base_url = powershell_function(
        GENERATION_CONTRACT.read_text(encoding="utf-8-sig"),
        "ConvertTo-TicketboxDatabaseGenerationPublicBaseUrl",
    )
    environment_writer = powershell_function(
        PROJECTION.read_text(encoding="utf-8-sig"),
        "Write-TicketboxDatabaseGenerationRuntimeEnvironment",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:writtenLines = @()
function Read-TicketboxDatabaseGenerationProgramContract {{
    param($Path, $ExpectedSha256)
    return [pscustomobject]@{{ RelativePath = 'DATABASE_GENERATION_PROGRAM.json'; Size = 1; Sha256 = ('a' * 64) }}
}}
function New-TicketboxDatabaseGenerationHostContract {{ param($BackendServiceName, $DataRoot, $InstallDir, $PgCtlPath, $PgServiceName, $PgDumpPath, $PgDumpSize, $PgDumpSha256, $PgRestorePath, $PgRestoreSize, $PgRestoreSha256, $ReleaseConfig); return [pscustomobject]@{{}} }}
function New-TicketboxDatabaseGenerationProjectionContract {{
    param($BackendServiceName, $EnvPath, $StopTimeoutMilliseconds, $BackendPort, $PgBin, $Timezone, $PublicBaseUrl, $PsqlPath, $PgData, $DatabaseToolTimeoutMilliseconds)
    return [pscustomobject]@{{ public_base_url = ConvertTo-TicketboxDatabaseGenerationPublicBaseUrl $PublicBaseUrl; backend_service_name = $BackendServiceName; env_path = $EnvPath; stop_timeout_ms = $StopTimeoutMilliseconds; backend_port = $BackendPort; pg_bin = $PgBin; timezone = $Timezone }}
}}
function ConvertTo-TicketboxTimeoutSeconds {{ param($Milliseconds); return 60 }}
function Write-EnvNoBom {{ param($Path, $Lines, $BackendServiceName); $script:writtenLines = @($Lines) }}
{public_base_url}
{contracts}
{environment_writer}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{
        InstallDir = 'C:\\Ticketbox'; DataRoot = 'C:\\TicketboxData'
        BackendServiceName = 'ticketbox-backend'; PgServiceName = 'ticketbox-pg'
        BackendPort = 8000; OperationId = '11111111-1111-4111-8111-111111111111'
        InstallationId = '22222222-2222-4222-8222-222222222222'; BackendVersionFloor = '1.0.0'
    }}
    Manifest = [pscustomobject]@{{
        DatabaseGenerationProgram = [pscustomobject]@{{ RelativePath = 'DATABASE_GENERATION_PROGRAM.json'; Sha256 = ('a' * 64) }}
        PgDump = [pscustomobject]@{{ Size = 1; Sha256 = ('b' * 64) }}
        PgRestore = [pscustomobject]@{{ Size = 1; Sha256 = ('c' * 64) }}
        DatabaseMaintenanceHelper = [pscustomobject]@{{ RelativePath = 'helper.exe'; Size = 1; Sha256 = ('d' * 64) }}
    }}
    Release = [pscustomobject]@{{ stop_timeout_ms = 60000; database_tool_timeout_ms = 60000; default_timezone = 'Asia/Shanghai' }}
}}
$resolved = New-TicketboxInstalledDatabaseGenerationContracts `
    -Subject $subject -PublicBaseUrl 'https://public.example/'
if ([string]$resolved.Projection.public_base_url -cne 'https://public.example') {{
    throw 'installed projection dropped PUBLIC_BASE_URL'
}}
Write-TicketboxDatabaseGenerationRuntimeEnvironment `
    -DatabaseUrl 'postgresql://runtime' -ProjectionContract $resolved.Projection `
    -HttpBootstrapSecret 'bootstrap'
if ('PUBLIC_BASE_URL=https://public.example' -cnotin $script:writtenLines) {{
    throw 'runtime projection did not preserve PUBLIC_BASE_URL'
}}
$rejected = $false
try {{
    New-TicketboxInstalledDatabaseGenerationContracts `
        -Subject $subject -PublicBaseUrl 'http://public.example' | Out-Null
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'public HTTP origin was accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-public-base-url-preservation.ps1",
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
