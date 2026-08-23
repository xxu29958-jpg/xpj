from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines, run_powershell_contract_script
from _powershell_contract import powershell_function as _function

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
OWNER = PACKAGING / "windows_database_generation.ps1"
CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
RELEASE = PACKAGING / "windows_database_generation_release.ps1"
FAILURE = PACKAGING / "windows_operation_failure.ps1"
ARTIFACTS = PACKAGING / "windows_database_generation_artifacts.ps1"
COMMIT_VERIFIER = PACKAGING / "windows_database_generation_commit_verifier.ps1"
POLICY = PACKAGING / "windows_database_generation_policy.ps1"
LIFECYCLE_LOCK = PACKAGING / "windows_lifecycle_lock.ps1"
PREPARE = PACKAGING / "prepare_bundled_upgrade.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_first_intent_state_root_creates_owned_parent_before_child(tmp_path: Path) -> None:
    artifacts_source = ARTIFACTS.read_text(encoding="utf-8-sig")
    get_state_root = _function(
        artifacts_source,
        "Get-TicketboxDatabaseGenerationStateRoot",
    )
    initialize_state_root = _function(
        artifacts_source,
        "Initialize-TicketboxDatabaseGenerationStateRoot",
    )
    machine_root = tmp_path / "machine-root"
    machine_root.mkdir()
    installer_state = machine_root / "installer-state"
    script = f"""
$ErrorActionPreference = 'Stop'
$script:TicketboxDatabaseGenerationRootName = 'database-generation'
$script:leaseChecks = 0
$script:initialized = New-Object System.Collections.Generic.List[string]
function Assert-TicketboxLifecycleOperationLease {{
    param($Lock)
    if ($null -eq $Lock) {{ throw 'missing lifecycle operation lease' }}
    $script:leaseChecks += 1
}}
function Initialize-TicketboxInstallerStateDirectory {{
    param([Parameter(Mandatory = $true)][string]$Path)
    $fullPath = [IO.Path]::GetFullPath($Path)
    $parent = [IO.Path]::GetDirectoryName($fullPath)
    if (-not [IO.Directory]::Exists($parent)) {{
        throw "installer-state parent missing: $parent"
    }}
    [void]$script:initialized.Add($fullPath)
    [IO.Directory]::CreateDirectory($fullPath) | Out-Null
    return $fullPath
}}
{get_state_root}
{initialize_state_root}
$lock = [pscustomobject]@{{ operation = 'held' }}
$first = Initialize-TicketboxDatabaseGenerationStateRoot `
    -InstallerState '{installer_state}' `
    -LifecycleLock $lock
$second = Initialize-TicketboxDatabaseGenerationStateRoot `
    -InstallerState '{installer_state}' `
    -LifecycleLock $lock
$expectedState = [IO.Path]::GetFullPath('{installer_state}')
$expectedChild = Join-Path $expectedState 'database-generation'
if (
    $script:leaseChecks -ne 2 -or
    $script:initialized.Count -ne 4 -or
    $script:initialized[0] -cne $expectedState -or
    $script:initialized[1] -cne $expectedChild -or
    $script:initialized[2] -cne $expectedState -or
    $script:initialized[3] -cne $expectedChild -or
    $first -cne $expectedChild -or
    $second -cne $expectedChild -or
    -not [IO.Directory]::Exists($expectedState) -or
    -not [IO.Directory]::Exists($expectedChild)
) {{
    throw 'Generation Owner did not establish its protected root before its child'
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-first-intent-state-root.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_pre_copy_receipt_mutation_uses_bootstrap_authority_without_installed_payload(
    tmp_path: Path,
) -> None:
    prepare_source = PREPARE.read_text(encoding="utf-8-sig")
    bootstrap_path = _function(
        prepare_source,
        "Get-TicketboxBootstrapDatabaseGenerationAuthorityPath",
    )
    block_start = prepare_source.index("    $preMutationLifecycleReceipt = $null")
    block_end = prepare_source.index(
        "    Set-TicketboxPreparedRuntimeServiceContract",
        block_start,
    )
    pre_copy_receipt_mutation = prepare_source[block_start:block_end]
    bootstrap = tmp_path / "bootstrap"
    install_dir = tmp_path / "program-files"
    bootstrap.mkdir()
    install_dir.mkdir()
    receipt_path = tmp_path / "lifecycle-receipt.json"
    receipt_path.write_text("{}", encoding="utf-8")
    authority_path = bootstrap / "windows_database_generation.ps1"
    authority_path.write_text(
        """
$script:bootstrapAuthorityLoaded = $true
function Assert-TicketboxPrepareLifecycleReceiptMutationAuthority {
    param($Receipt)
    if ([string]$Receipt.marker -cne 'receipt') { throw 'wrong receipt' }
    $script:mutationAuthorityCalls += 1
}
""",
        encoding="utf-8-sig",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:bootstrapAuthorityLoaded = $false
$script:mutationAuthorityCalls = 0
$script:closedGuards = 0
$ScriptDir = '{str(bootstrap).replace("'", "''")}'
$InstallDir = '{str(install_dir).replace("'", "''")}'
$DataRoot = 'C:\\TicketboxData'
$PgPort = 5432
$BackendPort = 8765
$TargetReleaseConfig = [pscustomobject]@{{}}
$TargetBackendVersion = '1.2.0'
$InstallerLockOwnerProcessId = 1234
$LifecycleReceiptPath = '{str(receipt_path).replace("'", "''")}'
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    return 'Missing'
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxInstalledDatabaseGenerationAuthorityPath {{
    throw 'pre-copy mutation consulted the unpublished installed payload'
}}
function Read-TicketboxLifecycleReceipt {{
    [CmdletBinding()]
    param(
        [string]$Path,
        [string]$InstallDir,
        [string]$DataRoot,
        [int]$PgPort,
        [int]$BackendPort,
        $TargetReleaseConfig,
        [string]$CurrentTargetBackendVersion,
        [int]$InstallerOwnerProcessId,
        [switch]$AllowPreviousInstallerOwnerProcessId
    )
    return [pscustomobject]@{{ marker = 'receipt' }}
}}
function Close-TicketboxLifecycleBackupGuard {{
    param($Receipt)
    $script:closedGuards += 1
}}
{bootstrap_path}
{pre_copy_receipt_mutation}
if (
    -not $script:bootstrapAuthorityLoaded -or
    $script:mutationAuthorityCalls -ne 1 -or
    $script:closedGuards -ne 1
) {{
    throw 'bootstrap owner did not exclusively authorize the pre-copy mutation'
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-pre-copy-bootstrap-owner.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_generation_intent_bootstrap_loads_without_execution_dependencies(tmp_path: Path) -> None:
    owner_source = OWNER.read_text(encoding="utf-8-sig")
    artifacts_source = ARTIFACTS.read_text(encoding="utf-8-sig")
    commit_verifier_source = COMMIT_VERIFIER.read_text(encoding="utf-8-sig")
    prepare_source = PREPARE.read_text(encoding="utf-8-sig")
    assert "function Import-TicketboxDatabaseGenerationExecutionDependencies" not in owner_source
    assert "function Import-TicketboxInstalledDatabaseGenerationAuthority" not in prepare_source
    assert "function Import-TicketboxBootstrapDatabaseGenerationAuthority" not in prepare_source
    assert "Get-TicketboxInstalledDatabaseGenerationAuthorityPath" not in prepare_source
    assert prepare_source.count(". (Get-TicketboxBootstrapDatabaseGenerationAuthorityPath)") == 3
    assert (
        owner_source.count("foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `") == 1
    )
    owner_consumer = _function(
        owner_source,
        "Invoke-TicketboxInstalledDatabaseGeneration",
    )
    commit_ready_consumer = _function(
        commit_verifier_source,
        "Assert-TicketboxDatabaseGenerationCommitReadyArtifact",
    )
    assert (
        owner_consumer.count("foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `") == 1
    )
    assert "-Root $PSScriptRoot" in owner_consumer
    assert "Get-TicketboxDatabaseGenerationExecutionDependencyPaths" not in (commit_ready_consumer)
    assert "windows_database_generation_recovery_evidence.ps1" in (commit_verifier_source)
    assert "Assert-TicketboxDatabaseGenerationCommitReadyArtifact" not in (artifacts_source)
    bootstrap_path = _function(
        prepare_source,
        "Get-TicketboxBootstrapDatabaseGenerationAuthorityPath",
    )
    assert 'Join-Path $ScriptDir "windows_database_generation.ps1"' in bootstrap_path
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    for source in (
        OWNER,
        CONTRACT,
        RELEASE,
        FAILURE,
        ARTIFACTS,
        COMMIT_VERIFIER,
        POLICY,
    ):
        (bootstrap / source.name).write_bytes(source.read_bytes())
    owner_path = bootstrap / OWNER.name
    state_root = bootstrap / "state"
    operation_path = bootstrap / "operation.lock"
    lifecycle_source = LIFECYCLE_LOCK.read_text(encoding="utf-8-sig")
    assert_held = _function(lifecycle_source, "Assert-TicketboxLifecycleLockIsHeld")
    assert_lease = _function(
        lifecycle_source,
        "Assert-TicketboxLifecycleOperationLease",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:TicketboxSharingViolationErrorCode = 32
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Test-TicketboxPathEquals {{ param($Left, $Right); return [IO.Path]::GetFullPath($Left) -ieq [IO.Path]::GetFullPath($Right) }}
function Get-TicketboxLifecycleOperationLockPath {{ return '{operation_path}' }}
function Get-TicketboxLifecycleLockPath {{ return (Join-Path '{bootstrap}' 'lifecycle.lock') }}
{assert_held}
{assert_lease}
function Test-TicketboxServiceExists {{ param($Name); return $false }}
function ConvertTo-TicketboxNumericVersion {{ param([string]$Version); return $Version }}
function Initialize-TicketboxInstallerStateDirectory {{
    param([string]$Path)
    [IO.Directory]::CreateDirectory($Path) | Out-Null
    return $Path
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param([string]$Path, [string]$Text, $FullControlAccounts, [string]$OwnerAccount)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param([string]$Path, $FullControlAccounts, [string]$OwnerAccount)
    return [pscustomobject]@{{ Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) }}
}}
. '{owner_path}'
if ($null -eq (Get-Command Get-TicketboxDatabaseGenerationExecutionDependencyPaths -ErrorAction Stop)) {{
    throw 'execution dependency gate was not loaded'
}}
if (Test-Path -LiteralPath (Join-Path '{bootstrap}' 'windows_atomic_artifacts.ps1')) {{
    throw 'bootstrap unexpectedly contains atomic execution dependencies'
}}
if (Test-Path -LiteralPath (Join-Path '{bootstrap}' 'windows_database_generation_target_recovery.ps1')) {{
    throw 'bootstrap unexpectedly contains target recovery execution dependencies'
}}
if (Test-Path -LiteralPath (Join-Path '{bootstrap}' 'windows_database_generation_recovery_evidence.ps1')) {{
    throw 'bootstrap unexpectedly contains recovery evidence execution dependencies'
}}
if (Test-Path -LiteralPath (Join-Path '{bootstrap}' 'windows_database_generation_retirement.ps1')) {{
    throw 'bootstrap unexpectedly contains bootstrap retirement execution dependencies'
}}
if (Test-Path -LiteralPath (Join-Path '{bootstrap}' 'windows_database_generation_projection.ps1')) {{
    throw 'bootstrap unexpectedly contains runtime projection execution dependencies'
}}
$program = [pscustomobject]@{{
    RelativePath = 'DATABASE_GENERATION_PROGRAM.json'
    Sha256 = ('a' * 64)
    Size = [int64]123
    TargetRevision = '20260809_0001'
}}
$hostContract = [ordered]@{{ schema = 'host-v1'; pg_major = 17 }}
$projectionContract = [pscustomobject][ordered]@{{
    backend_service_name = 'ticketbox-backend'
    env_path = 'C:\\data\\app\\.env'
    stop_timeout_ms = 60000
    backend_port = 8765
    pg_bin = 'C:\\Ticketbox\\pg\\bin'
    timezone = 'Asia/Shanghai'
    psql_path = 'C:\\Ticketbox\\pg\\bin\\psql.exe'
    pg_data = 'C:\\data\\pgdata'
    database_tool_timeout_ms = 60000
}}
$preinstallFacts = [pscustomobject][ordered]@{{
    BackendServiceName = 'backend'
    ExistingPathFacts = @()
    HasPersistedInstalledReleaseConfig = $false
    LifecycleEvidence = [pscustomobject][ordered]@{{
        current_sha256 = ''
        install_completed = $false
        operation_id = ''
        receipt_present = $false
        schema = 'ticketbox-database-generation-lifecycle-evidence-v1'
    }}
    PgServiceName = 'postgres'
    StateRoot = '{state_root}'
}}
$operationStream = [IO.File]::Open(
    '{operation_path}',
    [IO.FileMode]::OpenOrCreate,
    [IO.FileAccess]::ReadWrite,
    [IO.FileShare]::None
)
$lock = [pscustomobject]@{{ Operation = $operationStream }}
$start = @{{
    InstallerState = '{state_root}'; LifecycleLock = $lock
    PreinstallFacts = $preinstallFacts; TargetBackendVersion = '1.2.3'
    MaintenanceHelperSize = 456; MaintenanceHelperSha256 = ('b' * 64)
    ProgramContract = $program; HostContract = $hostContract
    ProjectionContract = $projectionContract
}}
$hostileFacts = $preinstallFacts.PSObject.Copy()
$hostileFacts.HasPersistedInstalledReleaseConfig = $true
$start.PreinstallFacts = $hostileFacts
$rejected = $false
try {{ Start-TicketboxDatabaseGenerationIntent @start | Out-Null }} catch {{ $rejected = $true }}
$activeIntent = Join-Path '{state_root}' 'database-generation\active-intent.json'
if (-not $rejected -or [IO.File]::Exists($activeIntent)) {{ throw 'hostile installed facts reached intent write' }}
$start.PreinstallFacts = $preinstallFacts
$first = Start-TicketboxDatabaseGenerationIntent @start
$before = [IO.File]::ReadAllBytes($first.Artifact.Path)
$second = Start-TicketboxDatabaseGenerationIntent @start
$readback = Read-TicketboxDatabaseGenerationIntentContext `
    -InstallerState '{state_root}' `
    -LifecycleLock $lock `
    -HostContract $hostContract `
    -ProjectionContract $projectionContract
$after = [IO.File]::ReadAllBytes($second.Artifact.Path)
$driftRejected = 0
$start.MaintenanceHelperSha256 = ('c' * 64)
try {{ Start-TicketboxDatabaseGenerationIntent @start | Out-Null }} catch {{ $driftRejected += 1 }}
$start.MaintenanceHelperSha256 = ('b' * 64)
$program.Sha256 = ('d' * 64)
try {{ Start-TicketboxDatabaseGenerationIntent @start | Out-Null }} catch {{ $driftRejected += 1 }}
$program.Sha256 = ('a' * 64)
$program.TargetRevision = '20260810_0001'
try {{ Start-TicketboxDatabaseGenerationIntent @start | Out-Null }} catch {{ $driftRejected += 1 }}
$program.TargetRevision = '20260809_0001'
$hostContract.pg_major = 18
try {{ Start-TicketboxDatabaseGenerationIntent @start | Out-Null }} catch {{ $driftRejected += 1 }}
$hostContract.pg_major = 17
$projectionContract.backend_port = 9876
try {{ Start-TicketboxDatabaseGenerationIntent @start | Out-Null }} catch {{ $driftRejected += 1 }}
$projectionContract.backend_port = 8765
$operationStream.Dispose()
if (
    $first.Artifact.PayloadSha256 -cne $second.Artifact.PayloadSha256 -or
    $first.Artifact.PayloadSha256 -cne $readback.Artifact.PayloadSha256 -or
    ([Convert]::ToBase64String($before) -cne [Convert]::ToBase64String($after)) -or
    $driftRejected -ne 5
) {{
    throw 'intent retry did not preserve exact immutable release binding'
}}
        $dependencyNames = @(
            'windows_atomic_artifacts.ps1',
            'windows_pg_recovery_tools.ps1',
            'windows_postgresql_credentials.ps1',
            'windows_postgresql_database_command.ps1',
            'windows_postgresql_database_catalog.ps1',
            'windows_postgresql_single_user.ps1',
            'windows_postgresql_writer_fence.ps1',
            'windows_ticketbox_database_contract.ps1',
            'windows_ticketbox_database_acl.ps1',
            'windows_ticketbox_database_acl_observation.ps1',
            'windows_ticketbox_database_roles.ps1',
            'windows_service_contract.ps1',
            'windows_service_identity.ps1',
            'windows_service_lifecycle.ps1',
            'windows_database_generation_credentials.ps1',
            'windows_database_generation_role_fence.ps1',
            'windows_database_generation_host_authority.ps1',
            'windows_database_generation_role_bootstrap.ps1',
            'windows_database_generation_source.ps1',
            'windows_database_generation_source_binding.ps1',
            'windows_database_generation_program_adapter.ps1',
            'windows_database_generation_program_execution.ps1',
            'windows_database_generation_recovery_evidence.ps1',
                'windows_database_generation_target_recovery.ps1',
                'windows_database_generation_target_authorization.ps1',
                'windows_database_generation_database_binding.ps1',
            'windows_database_generation_current.ps1',
            'windows_database_generation_retirement.ps1',
            'windows_database_generation_projection.ps1'
        )
for ($index = 0; $index -lt $dependencyNames.Count; $index += 1) {{
    $text = if ($index -eq 0) {{
        "function Test-TicketboxExecutionDependencyMarker {{ return 'loaded' }}"
    }} else {{ '' }}
    [IO.File]::WriteAllText(
        (Join-Path '{bootstrap}' $dependencyNames[$index]),
        $text,
        [Text.UTF8Encoding]::new($false)
    )
}}
foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `
    -Root '{bootstrap}')) {{
    . $dependency
}}
if ((Test-TicketboxExecutionDependencyMarker) -cne 'loaded') {{
    throw 'execution dependency did not survive in the consuming scope'
}}
foreach ($name in $dependencyNames) {{
    [IO.File]::Delete((Join-Path '{bootstrap}' $name))
}}
"""
    run_powershell_contract_script(script, tmp_path, filename="database-generation-owner.ps1")


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_successor_intent_replaces_only_exact_predecessor_authority(tmp_path: Path) -> None:
    successor = _function(
        POLICY.read_text(encoding="utf-8-sig"),
        "New-TicketboxDatabaseGenerationIntent",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxLifecycleOperationLease {{}}
function ConvertTo-TicketboxNumericVersion {{ param($Version); return $Version }}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "$Label invalid" }}
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{}}
function Initialize-TicketboxDatabaseGenerationStateRoot {{ return 'state' }}
function Get-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); return ($Value | ConvertTo-Json -Depth 8 -Compress) }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); return ($Value | ConvertTo-Json -Depth 8 -Compress) }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('9' * 64) }}
function Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 {{ return ('9' * 64) }}
$script:TicketboxDatabaseGenerationProgramRelativePath = 'DATABASE_GENERATION_PROGRAM.json'
$script:TicketboxDatabaseMaintenanceHelperRelativePath = 'ticketbox-database-maintenance.exe'
$script:writes = 0
$script:existing = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        installation_id = '22222222-2222-4222-8222-222222222222'
        expected_predecessor_sha256 = ''
    }}
}}
$script:current = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $script:existing.Payload.operation_id
        installation_id = $script:existing.Payload.installation_id
        intent_sha256 = $script:existing.PayloadSha256
    }}
}}
function Read-TicketboxDatabaseGenerationActiveIntent {{ return $script:existing }}
function Read-TicketboxDatabaseGenerationCurrent {{ return $script:current }}
function New-TicketboxDatabaseGenerationActiveIntent {{
    throw 'create-only writer cannot replace active intent'
}}
function Replace-TicketboxDatabaseGenerationActiveIntent {{
    param($StateRoot, $ExpectedPayloadSha256, $Payload, $Lock)
    if ([string]$ExpectedPayloadSha256 -cne [string]$script:existing.PayloadSha256) {{
        throw 'stale active-intent CAS'
    }}
    $script:writes += 1
    $script:existing = [pscustomobject]@{{
        PayloadSha256 = ('c' * 64)
        Payload = [pscustomobject]$Payload
    }}
    return $script:existing
}}
{successor}
$request = @{{
    InstallerState = 'state'; LifecycleLock = @{{}}
    ExpectedPredecessorSha256 = ('b' * 64)
    SourceRequestSha256 = ('d' * 64)
    TargetBackendVersion = '1.2.3'
    MaintenanceHelperSize = 1; MaintenanceHelperSha256 = ('e' * 64)
    ProgramContract = [pscustomobject]@{{
        RelativePath = 'DATABASE_GENERATION_PROGRAM.json'; Sha256 = ('f' * 64)
        Size = 1; TargetRevision = '20260821_0001'
    }}
    HostContract = [pscustomobject]@{{ schema = 'host-v1' }}
    ProjectionContract = [pscustomobject]@{{ schema = 'projection-v1' }}
}}
$first = New-TicketboxDatabaseGenerationIntent @request
$second = New-TicketboxDatabaseGenerationIntent @request
if (
    $script:writes -ne 1 -or
    [string]$first.Artifact.Payload.operation_id -ceq
        [string]$script:current.Payload.operation_id -or
    [string]$first.Artifact.Payload.installation_id -cne
        [string]$script:current.Payload.installation_id -or
    [string]$first.Artifact.Payload.source_request_sha256 -cne ('d' * 64) -or
    [string]$second.Artifact.PayloadSha256 -cne [string]$first.Artifact.PayloadSha256
) {{ throw 'successor intent did not replace exact predecessor once' }}
$script:current.PayloadSha256 = ('8' * 64)
$rejected = $false
try {{ New-TicketboxDatabaseGenerationIntent @request | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 1) {{ throw 'stale predecessor mutated active intent' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-successor-intent.ps1",
    )
