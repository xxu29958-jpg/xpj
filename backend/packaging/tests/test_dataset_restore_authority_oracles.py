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
DATASET_OPERATION = PACKAGING / "windows_installed_dataset_operation.ps1"
RESTORE_ARTIFACTS = PACKAGING / "windows_installed_dataset_restore_artifacts.ps1"
RUNTIME = PACKAGING / "windows_dataset_restore_runtime.ps1"
AUTHORITY_CONTRACTS = (
    DATASET_OPERATION,
    RESTORE_ARTIFACTS,
    PACKAGING / "windows_installed_dataset_reader.ps1",
    PACKAGING / "windows_dataset_restore_reducer.ps1",
)


def _restore_authority_contract() -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in AUTHORITY_CONTRACTS)


def test_restore_does_not_ship_unowned_clone_identity_producer() -> None:
    launch = (PACKAGING / "launch.py").read_text(encoding="utf-8")
    restore_service = (PACKAGING.parent / "app" / "services" / "dataset_restore_service.py").read_text(encoding="utf-8")
    restore_action = (PACKAGING.parent / "app" / "database" / "_dataset_restore_action.py").read_text(encoding="utf-8")

    assert "--clone-dataset-id" not in launch
    assert "clone_dataset_id" not in restore_service
    assert "clone_dataset_id" not in restore_action


def test_backup_and_restore_share_one_active_dataset_operation_authority() -> None:
    backup = (PACKAGING / "windows_dataset_backup.ps1").read_text(encoding="utf-8-sig")
    restore = RESTORE.read_text(encoding="utf-8-sig")

    assert DATASET_OPERATION.is_file()
    for owner in (backup, restore):
        assert '"windows_installed_dataset_operation.ps1"' in owner
        assert "Start-TicketboxInstalledDataset" in owner
        assert "Remove-TicketboxInstalledDatasetOperation" in owner
    assert not (PACKAGING / "windows_installed_dataset_backup_contract.ps1").exists()
    operation = DATASET_OPERATION.read_text(encoding="utf-8-sig")
    assert operation.count('"dataset-operation-active.json"') == 1
    assert 'ValidateSet("backup", "restore")' in operation


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_dataset_operation_path_is_singleton_across_kinds_and_attempts(
    tmp_path: Path,
) -> None:
    path_function = powershell_function(
        _restore_authority_contract(),
        "Get-TicketboxInstalledDatasetOperationPath",
    )
    root = str(tmp_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
{path_function}
$first = Get-TicketboxInstalledDatasetOperationPath -StateRoot '{root}'
$second = Get-TicketboxInstalledDatasetOperationPath -StateRoot '{root}'
if ($first -cne $second) {{ throw 'dataset operation path split by kind or attempt' }}
if ((Split-Path -Leaf $first) -cne 'dataset-operation-active.json') {{
    throw "dataset operation is not the singleton authority: $first"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-operation-singleton.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_predecessor_classifier_distinguishes_committed_and_pending_successors(
    tmp_path: Path,
) -> None:
    classifier = powershell_function(
        _restore_authority_contract(),
        "Resolve-TicketboxInstalledDatasetRestorePredecessor",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{classifier}
$shaA = 'a' * 64
$shaB = 'b' * 64
$fresh = [pscustomobject]@{{
    PayloadSha256 = $shaA
    Payload = [pscustomobject]@{{ operation_id = '11111111-1111-4111-8111-111111111111'; expected_predecessor_sha256 = '' }}
}}
$committedSuccessor = [pscustomobject]@{{
    PayloadSha256 = $shaB
    Payload = [pscustomobject]@{{ operation_id = '22222222-2222-4222-8222-222222222222'; expected_predecessor_sha256 = $shaA }}
}}
$freshCurrent = [pscustomobject]@{{ PayloadSha256 = $shaA; Payload = [pscustomobject]@{{ operation_id = $fresh.Payload.operation_id; intent_sha256 = $shaA }} }}
$successorCurrent = [pscustomobject]@{{ PayloadSha256 = $shaB; Payload = [pscustomobject]@{{ operation_id = $committedSuccessor.Payload.operation_id; intent_sha256 = $shaB }} }}

$first = Resolve-TicketboxInstalledDatasetRestorePredecessor $fresh $freshCurrent
if ($first.HasPendingSuccessor -or $first.PayloadSha256 -cne $shaA) {{ throw 'fresh CURRENT misclassified' }}
$repeat = Resolve-TicketboxInstalledDatasetRestorePredecessor $committedSuccessor $successorCurrent
if ($repeat.HasPendingSuccessor -or $repeat.PayloadSha256 -cne $shaB) {{ throw 'committed successor blocks repeat restore' }}
$pending = Resolve-TicketboxInstalledDatasetRestorePredecessor $committedSuccessor $freshCurrent
if (-not $pending.HasPendingSuccessor -or $pending.PayloadSha256 -cne $shaA) {{ throw 'pending successor misclassified' }}
$committedSuccessor.Payload.expected_predecessor_sha256 = $shaB
$rejected = $false
try {{ Resolve-TicketboxInstalledDatasetRestorePredecessor $committedSuccessor $freshCurrent | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'mismatched pending predecessor accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-predecessor.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_next_action_reducer_is_closed_and_io_free(tmp_path: Path) -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    reducer = powershell_function(
        _restore_authority_contract(),
        "Resolve-TicketboxInstalledDatasetRestoreNextAction",
    )
    assert reducer.count("[AllowNull()][object]") == 4
    assert '[ValidateSet("absent", "present")]' not in reducer
    assert "-RuntimeVerification $runtimeVerification" in restore
    script = f"""
$ErrorActionPreference = 'Stop'
{reducer}
$cases = @(
    @('complete', 'absent', 'absent', 'absent', 'absent', 'build_candidate'),
    @('candidate_building', 'absent', 'absent', 'absent', 'absent', 'restore_candidate'),
    @('candidate_ready', 'present', 'absent', 'absent', 'absent', 'verify_candidate'),
    @('candidate_ready', 'present', 'present', 'absent', 'absent', 'promote_candidate'),
    @('old_pg_staged', 'present', 'present', 'absent', 'absent', 'promote_candidate'),
    @('old_staged', 'present', 'present', 'absent', 'absent', 'promote_candidate'),
    @('candidate_pg_published', 'present', 'present', 'absent', 'absent', 'promote_candidate'),
    @('candidate_published', 'present', 'present', 'absent', 'absent', 'publish_current'),
    @('candidate_published', 'present', 'present', 'present', 'absent', 'verify_runtime'),
    @('candidate_published', 'present', 'present', 'present', 'present', 'retire_rollback'),
    @('complete', 'present', 'present', 'present', 'present', 'done')
)
foreach ($case in $cases) {{
    $source = if ($case[1] -ceq 'present') {{ [pscustomobject]@{{}} }} else {{ $null }}
    $candidate = if ($case[2] -ceq 'present') {{ [pscustomobject]@{{}} }} else {{ $null }}
    $current = if ($case[3] -ceq 'present') {{ [pscustomobject]@{{}} }} else {{ $null }}
    $runtime = if ($case[4] -ceq 'present') {{ [pscustomobject]@{{}} }} else {{ $null }}
    $actual = Resolve-TicketboxInstalledDatasetRestoreNextAction `
        $case[0] $source $candidate $current $runtime
    if ($actual -cne $case[5]) {{ throw "unexpected next action: $actual" }}
}}
$rejected = $false
try {{
    Resolve-TicketboxInstalledDatasetRestoreNextAction `
        'candidate_published' $null $null $null $null | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'authority-free publication state was accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-next-action.ps1",
    )


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
        DATASET_OPERATION.read_text(encoding="utf-8-sig"),
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
        current_sha256 = $predecessorSha
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
function Assert-TicketboxInstalledDatasetOperation {{ param($Operation, $ExpectedOperationKind); return $Operation }}
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
