import re
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent
OWNER = PACKAGING / "windows_database_generation.ps1"
CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
ARTIFACTS = PACKAGING / "windows_database_generation_artifacts.ps1"
ADAPTER = PACKAGING / "windows_database_generation_adapter.ps1"
SOURCE = PACKAGING / "windows_database_generation_source.ps1"
RECOVERY_EVIDENCE = PACKAGING / "windows_database_generation_recovery_evidence.ps1"
TARGET_RECOVERY = PACKAGING / "windows_database_generation_target_recovery.ps1"
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"
LIFECYCLE_LOCK = PACKAGING / "windows_lifecycle_lock.ps1"
RETIRED_C07_RECOVERY = PACKAGING / "windows_c07_recovery_generation.ps1"
RETIRED_C07_AUTHORITY = PACKAGING / "windows_c07_heartbeat_authority.ps1"
RETIRED_C07_LIFECYCLE = PACKAGING / "windows_c07_lifecycle.ps1"
RETIRED_C07_HEARTBEAT_HELPER = PACKAGING / "windows_c07_heartbeat_helper.ps1"
RETIRED_C07_FAILURE_SUMMARY = PACKAGING / "windows_c07_failure_summary.ps1"
RETIRED_C07_DEADLINE_POLICY = PACKAGING / "windows_c07_deadline_policy.ps1"
RETIRED_C07_WRITER_FENCE = PACKAGING / "c07_lifecycle" / "writer_fence.ps1"
RETIRED_C07_WRITER_FENCE_POLICY = PACKAGING / "c07_lifecycle" / "writer_fence" / "policy.ps1"
RETIRED_C07_WRITER_FENCE_ADAPTER = PACKAGING / "c07_lifecycle" / "writer_fence" / "adapter.ps1"
INSTALLER = PACKAGING / "install_bundled_services.ps1"
ISS = PACKAGING / "ticketbox-installer.iss"
FLOW = PACKAGING / "ticketbox-installer-flow.isph"
BUILD = PACKAGING / "build_inno_installer.ps1"
PROVENANCE = BACKEND / "scripts" / "windows_build_provenance.ps1"


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^function {re.escape(name)}(?:\([^{{\r\n]*\))?\s*\{{",
        source,
    )
    assert match is not None, name
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"unterminated PowerShell function: {name}")


def _inno_function(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index(f"function {next_name}(", start)
    return source[start:end]


def _run_both(script: str, tmp_path: Path) -> None:
    path = tmp_path / "database-generation-owner.ps1"
    path.write_text(script, encoding="utf-8-sig")
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", path],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_generation_owner_is_one_real_shipped_consumer_and_retires_old_authorities() -> None:
    owner = OWNER.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    artifacts = ARTIFACTS.read_text(encoding="utf-8-sig")
    adapter = ADAPTER.read_text(encoding="utf-8-sig")
    source = SOURCE.read_text(encoding="utf-8-sig")
    recovery_evidence = RECOVERY_EVIDENCE.read_text(encoding="utf-8-sig")
    target_recovery = TARGET_RECOVERY.read_text(encoding="utf-8-sig")
    installer = INSTALLER.read_text(encoding="utf-8-sig")
    flow = FLOW.read_text(encoding="utf-8-sig")
    production = "\n".join(path.read_text(encoding="utf-8-sig") for path in PACKAGING.glob("*.ps1"))
    assert installer.count("Invoke-TicketboxInstalledDatabaseGeneration `") == 1
    assert "New-TicketboxDatabaseGenerationIntent `" not in installer
    assert installer.count("Read-TicketboxDatabaseGenerationIntentContext `") == 1
    prepare_to_install = _inno_function(
        flow,
        "PrepareToInstall",
        "AuthoritativePayloadReplacementPrepared",
    )
    assert prepare_to_install.count("-PersistDatabaseGenerationIntentOnly") == 1
    assert prepare_to_install.index("-PersistDatabaseGenerationIntentOnly") < (
        prepare_to_install.index("install_windows_prerequisites.ps1")
    )
    prepare = (PACKAGING / "prepare_bundled_upgrade.ps1").read_text(
        encoding="utf-8-sig"
    )
    persist_branch = re.search(
        r"(?m)^    if \(\$PersistDatabaseGenerationIntentOnly\) \{$",
        prepare,
    )
    assert persist_branch is not None
    persist_end = prepare.index("    # A trusted older installer", persist_branch.end())
    persist_body = prepare[persist_branch.end() : persist_end]
    eligibility = persist_body.index(
        "Start-TicketboxDatabaseGenerationIntent `"
    )
    assert "New-TicketboxDatabaseGenerationIntent" not in persist_body
    for hostile_existing_fact in (
        "$HasPersistedInstalledReleaseConfig",
        "$LifecycleReceiptPath",
        "$InstalledBuildManifestPath",
        "$BackendExe",
        "$PgBootstrapRecoveryPath",
    ):
        assert hostile_existing_fact in persist_body[:eligibility]
    payload_replacement = _inno_function(
        flow,
        "PrepareAuthoritativePayloadReplacement",
        "PrepareToInstall",
    )
    assert "StartDataRootMutationGuard(" in payload_replacement
    assert "-PersistDatabaseGenerationIntentOnly" not in payload_replacement
    for retired in (
        "Invoke-TicketboxC07InstalledReleaseMigration",
        "Complete-TicketboxInstalledRuntimePublication",
        "Invoke-TicketboxC07InstalledProductionLifecycle",
        "Invoke-TicketboxC07ProductionLifecycleCoordinator",
        "Invoke-TicketboxC07ProductionAuthorityCoordinator",
        "Set-TicketboxLifecycleReceiptC07ReadyEvidence",
        "Invoke-TicketboxC07TargetRecoveryGeneration",
        "Test-TicketboxC07TargetRecoveryGenerationRestore",
    ):
        assert retired not in production
    for retired_path in (
        RETIRED_C07_RECOVERY,
        RETIRED_C07_AUTHORITY,
        RETIRED_C07_LIFECYCLE,
        RETIRED_C07_HEARTBEAT_HELPER,
        RETIRED_C07_FAILURE_SUMMARY,
        RETIRED_C07_DEADLINE_POLICY,
        RETIRED_C07_WRITER_FENCE,
        RETIRED_C07_WRITER_FENCE_POLICY,
        RETIRED_C07_WRITER_FENCE_ADAPTER,
    ):
        assert not retired_path.exists()
        retired_relative = str(retired_path.relative_to(PACKAGING))
        for shipment_surface in (
            installer,
            ISS.read_text(encoding="utf-8-sig"),
            BUILD.read_text(encoding="utf-8-sig"),
            PROVENANCE.read_text(encoding="utf-8-sig"),
        ):
            assert retired_relative not in shipment_surface
            assert retired_relative.replace("\\", "/") not in shipment_surface
    assert "Invoke-TicketboxDatabaseGenerationTargetRecovery" in target_recovery
    assert "[scriptblock]" not in recovery_evidence + target_recovery
    assert "Invoke-TicketboxDatabaseGenerationTargetRecovery" in adapter
    assert "Get-TicketboxPostgresqlWriterFenceObservation" in adapter
    assert "Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority" not in adapter
    assert "target_recovery_evidence_sha256" in adapter
    assert "target_recovery_evidence_sha256" in artifacts
    for build_bound_tool_field in (
        "pg_dump_path",
        "pg_dump_size",
        "pg_dump_sha256",
        "pg_restore_path",
        "pg_restore_size",
        "pg_restore_sha256",
    ):
        assert build_bound_tool_field in contract
    assert "Assert-TicketboxDatabaseGenerationToolIdentity" in recovery_evidence
    assert recovery_evidence.count("Assert-TicketboxDatabaseGenerationToolIdentity") >= 5
    assert target_recovery.count("Assert-TicketboxDatabaseGenerationToolIdentity") >= 2
    assert "Resolve-TicketboxDatabaseGenerationNextAction" in owner
    assert "Publish-TicketboxDatabaseGenerationCurrent" in owner
    assert "host_contract_sha256" in owner
    assert "projection_contract_sha256" in owner
    assert 'source_kind = "empty"' in source
    for leaked_mode in ("fresh_install", "legacy_adoption", "runtime_ready", "forward_repair"):
        assert leaked_mode not in owner + contract + artifacts + adapter + source
    for name in (
        "windows_database_generation.ps1",
        "windows_database_generation_program_execution.ps1",
        "windows_database_generation_contract.ps1",
        "windows_database_generation_artifacts.ps1",
        "windows_database_generation_adapter.ps1",
        "windows_database_generation_source.ps1",
        "windows_database_generation_recovery_evidence.ps1",
        "windows_database_generation_target_recovery.ps1",
        "windows_database_generation_projection.ps1",
    ):
        assert name in ISS.read_text(encoding="utf-8-sig")
        assert name in BUILD.read_text(encoding="utf-8-sig")
        assert name in PROVENANCE.read_text(encoding="utf-8-sig")


def test_target_execution_authority_is_retry_stable_and_binding_is_insert_only(tmp_path: Path) -> None:
    adapter = ADAPTER.read_text(encoding="utf-8-sig")
    authority = _function(
        adapter,
        "New-TicketboxDatabaseGenerationExecutionAuthority",
    )
    failure = _function(
        OWNER.read_text(encoding="utf-8-sig"),
        "Throw-TicketboxDatabaseGenerationOperationFailure",
    )
    binding = _function(
        adapter,
        "Set-TicketboxDatabaseGenerationDatabaseBinding",
    )
    assert "ON CONFLICT (key) DO NOTHING" in binding
    assert "DO UPDATE" not in binding
    assert binding.count("Assert-TicketboxLifecycleOperationLease $LifecycleLock") >= 2
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{ param($Value, $ExpectedNames, $Label) }}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{ param($Value, $Label) }}
{authority}
{failure}
$intent = [pscustomobject]@{{ PayloadSha256 = ('a' * 64); Payload = [pscustomobject]@{{
    operation_id = '11111111-1111-4111-8111-111111111111'
    target_revision = '20260809_0001'
    generation_program_sha256 = ('b' * 64)
}} }}
$source = [pscustomobject]@{{ Payload = [pscustomobject]@{{ source_revision = 'base' }} }}
$committed = [pscustomobject][ordered]@{{
    schema = 'ticketbox-managed-schema-upgrade-result-v2'; source_revision = 'base'
    target_revision = '20260809_0001'; generation_program_sha256 = ('b' * 64)
    result = 'target_committed'; alembic_revision = '20260809_0001'
}}
$observed = $committed.PSObject.Copy()
$observed.result = 'target_observed_after_interruption'
$first = New-TicketboxDatabaseGenerationExecutionAuthority $intent $source $committed
$retry = New-TicketboxDatabaseGenerationExecutionAuthority $intent $source $observed
if (($first | ConvertTo-Json -Compress) -cne ($retry | ConvertTo-Json -Compress)) {{
    throw 'response-loss retry changed execution authority'
}}
if ($first.PSObject.Properties.Name -contains 'result') {{
    throw 'attempt outcome leaked into execution authority'
}}
$unknown = $committed.PSObject.Copy()
$unknown.result = 'unknown'
$rejected = $false
try {{ New-TicketboxDatabaseGenerationExecutionAuthority $intent $source $unknown | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'unknown execution outcome was accepted' }}
$primaryError = [InvalidOperationException]::new('primary')
$primaryError.Data['TicketboxC07FailureCode'] = 'C07-PRIMARY'
$primaryError.Data['TicketboxC07FailureCodes'] = @('C07-PRIMARY')
try {{ throw $primaryError }} catch {{ $primary = $_ }}
try {{ throw [InvalidOperationException]::new('cleanup') }} catch {{ $cleanup = $_ }}
try {{ Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup }} catch {{ $aggregate = $_.Exception }}
if (
    $aggregate -isnot [AggregateException] -or
    $aggregate.InnerExceptions.Count -ne 2 -or
    [string]$aggregate.Data['TicketboxC07FailureCode'] -cne 'C07-PRIMARY' -or
    @($aggregate.Data['TicketboxC07FailureCodes']).Count -ne 1
) {{ throw 'aggregate failure lost primary identity' }}
"""
    _run_both(script, tmp_path)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_generation_intent_bootstrap_loads_without_execution_dependencies(tmp_path: Path) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    for source in (OWNER, CONTRACT, ARTIFACTS):
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
if ($null -eq (Get-Command Import-TicketboxDatabaseGenerationExecutionDependencies -ErrorAction Stop)) {{
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
$projectionContract = [ordered]@{{ schema = 'projection-v1'; backend_port = 8765 }}
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
    MigrationHelperSize = 456; MigrationHelperSha256 = ('b' * 64)
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
$operationStream.Dispose()
if (
    $first.Artifact.PayloadSha256 -cne $second.Artifact.PayloadSha256 -or
    $first.Artifact.PayloadSha256 -cne $readback.Artifact.PayloadSha256 -or
    ([Convert]::ToBase64String($before) -cne [Convert]::ToBase64String($after))
) {{
    throw 'intent write/read/retry did not preserve exact bytes'
}}
"""
    _run_both(script, tmp_path)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_generation_recovery_tools_are_bound_to_build_identity(tmp_path: Path) -> None:
    assertion = _function(
        RECOVERY_EVIDENCE.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxDatabaseGenerationToolIdentity",
    )
    tool = tmp_path / "pg_dump.exe"
    other = tmp_path / "other.exe"
    script = f"""
$ErrorActionPreference = 'Stop'
function ConvertTo-TicketboxWin32CanonicalPath {{ param([string]$Path); return [IO.Path]::GetFullPath($Path) }}
function Test-TicketboxPathEquals {{ param([string]$Left, [string]$Right); return [IO.Path]::GetFullPath($Left) -ieq [IO.Path]::GetFullPath($Right) }}
function Get-TicketboxPathEntryKindNoFollow {{ param([string]$Path); if ([IO.File]::Exists($Path)) {{ return 'File' }}; return 'Missing' }}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPortableFileSha256 {{
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '') }}
    finally {{ $sha.Dispose(); $stream.Dispose() }}
}}
{assertion}
$tool = '{tool}'
$other = '{other}'
[IO.File]::WriteAllText($tool, 'original', [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($other, 'original', [Text.UTF8Encoding]::new($false))
$expected = (Get-TicketboxPortableFileSha256 $tool).ToLowerInvariant()
$resolved = Assert-TicketboxDatabaseGenerationToolIdentity $tool $tool 8 $expected 'pg_dump.exe'
if ([IO.Path]::GetFullPath($resolved) -ine [IO.Path]::GetFullPath($tool)) {{ throw 'tool identity did not resolve exact path' }}
$wrongPath = $false
try {{ Assert-TicketboxDatabaseGenerationToolIdentity $other $tool 8 $expected 'pg_dump.exe' | Out-Null }} catch {{ $wrongPath = $true }}
if (-not $wrongPath) {{ throw 'same bytes at a different path were accepted' }}
[IO.File]::WriteAllText($tool, 'modified', [Text.UTF8Encoding]::new($false))
$swapped = $false
try {{ Assert-TicketboxDatabaseGenerationToolIdentity $tool $tool 8 $expected 'pg_dump.exe' | Out-Null }} catch {{ $swapped = $true }}
if (-not $swapped) {{ throw 'same-size swapped tool bytes were accepted' }}
"""
    _run_both(script, tmp_path)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_generation_reducer_is_pure_closed_and_mode_free(tmp_path: Path) -> None:
    reducer = _function(
        OWNER.read_text(encoding="utf-8-sig"),
        "Resolve-TicketboxDatabaseGenerationNextAction",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{reducer}
$x = [pscustomobject]@{{ value = 1 }}
$actions = @(
    Resolve-TicketboxDatabaseGenerationNextAction $null $null $null $null $null
    Resolve-TicketboxDatabaseGenerationNextAction $x $null $null $null $null
    Resolve-TicketboxDatabaseGenerationNextAction $x $x $null $null $null
    Resolve-TicketboxDatabaseGenerationNextAction $x $x $x $null $null
    Resolve-TicketboxDatabaseGenerationNextAction $x $x $x $x $null
    Resolve-TicketboxDatabaseGenerationNextAction $null $x $x $x $x
)
$expected = 'ensure_credentials,bind_source,authorize_target,seal_candidate,publish_current,reconcile_projection'
if (($actions -join ',') -cne $expected) {{ throw "unexpected reducer: $($actions -join ',')" }}
$invalid = $false
try {{ Resolve-TicketboxDatabaseGenerationNextAction $null $x $null $null $null | Out-Null }} catch {{ $invalid = $true }}
if (-not $invalid) {{ throw 'reducer accepted source without credential/current' }}
"""
    _run_both(script, tmp_path)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_generation_current_is_idempotent_expected_predecessor_cas(tmp_path: Path) -> None:
    publish = _function(
        ARTIFACTS.read_text(encoding="utf-8-sig"),
        "Publish-TicketboxDatabaseGenerationCurrent",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); $Value | ConvertTo-Json -Depth 12 -Compress }}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
$script:current = $null
$script:writes = 0
function Read-TicketboxDatabaseGenerationCurrent {{ param($StateRoot, [switch]$AllowAbsent); return $script:current }}
function Write-TicketboxDatabaseGenerationEnvelope {{
    param($Path, $Kind, $Payload, $LifecycleLock)
    $script:writes += 1
    $script:current = [pscustomobject]@{{ Payload = [pscustomobject]$Payload; PayloadSha256 = ('a' * 64) }}
    return $script:current
}}
{publish}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        installation_id = '22222222-2222-4222-8222-222222222222'
        generation_program_sha256 = ('c' * 64)
        expected_predecessor_sha256 = ''
    }}
}}
$candidate = [pscustomobject]@{{ PayloadSha256 = ('d' * 64); Payload = [pscustomobject]@{{ target_revision = '20260809_0001'; database_binding_sha256 = ('9' * 64) }} }}
$lock = @{{}}
$first = Publish-TicketboxDatabaseGenerationCurrent 'state' $intent $candidate $lock
$second = Publish-TicketboxDatabaseGenerationCurrent 'state' $intent $candidate $lock
if ($script:writes -ne 1 -or $first.PayloadSha256 -cne $second.PayloadSha256) {{ throw 'idempotent CURRENT failed' }}
$script:current.Payload.candidate_sha256 = ('e' * 64)
$conflict = $false
try {{ Publish-TicketboxDatabaseGenerationCurrent 'state' $intent $candidate $lock | Out-Null }} catch {{ $conflict = $true }}
if (-not $conflict -or $script:writes -ne 1) {{ throw 'CURRENT conflict did not fail closed' }}
$script:current = $null
$intent.Payload.expected_predecessor_sha256 = ('f' * 64)
$stale = $false
try {{ Publish-TicketboxDatabaseGenerationCurrent 'state' $intent $candidate $lock | Out-Null }} catch {{ $stale = $true }}
if (-not $stale -or $script:writes -ne 1) {{ throw 'stale predecessor mutated CURRENT' }}
"""
    _run_both(script, tmp_path)
