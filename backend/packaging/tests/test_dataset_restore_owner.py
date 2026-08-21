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
CONTRACT = PACKAGING / "windows_installed_dataset_contract.ps1"
CLUSTER = PACKAGING / "windows_postgresql_candidate_cluster.ps1"


def test_restore_does_not_ship_unowned_clone_identity_producer() -> None:
    launch = (PACKAGING / "launch.py").read_text(encoding="utf-8")
    restore_service = (
        PACKAGING.parent / "app" / "services" / "dataset_restore_service.py"
    ).read_text(encoding="utf-8")
    restore_action = (
        PACKAGING.parent / "app" / "database" / "_dataset_restore_action.py"
    ).read_text(encoding="utf-8")

    assert "--clone-dataset-id" not in launch
    assert "clone_dataset_id" not in restore_service
    assert "clone_dataset_id" not in restore_action


def test_restore_owner_is_explicit_durable_isolated_and_h1_published() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    cluster = CLUSTER.read_text(encoding="utf-8-sig")

    assert "[Parameter(Mandatory = $true)][string]$BackupGeneration" in restore
    assert "Get-TicketboxInstalledDatasetRestoreRequest" in contract
    assert "Resolve-TicketboxInstalledDatasetRestoreNextAction" in contract
    assert "New-TicketboxInstalledDatasetRestoreRequest" in restore
    assert restore.rindex("New-TicketboxInstalledDatasetRestoreRequest") < restore.rindex(
        "Stop-TicketboxInstalledDatasetWriters"
    )
    assert "Initialize-TicketboxPostgresqlRestoreCandidateCluster" in cluster
    assert "Start-TicketboxPostgresqlRestoreCandidateService" in cluster
    assert "Initialize-TicketboxPostgresqlRestoreCandidateDatabase" in cluster
    assert "New-TicketboxPostgresqlRestoreCandidate" not in cluster
    assert "Invoke-TicketboxInstalledDatabaseGeneration" in restore
    assert "Publish-TicketboxDatabaseGenerationCurrent" not in restore
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


def test_restore_candidate_uses_official_frozen_restore_and_exact_role_owner() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    cluster = CLUSTER.read_text(encoding="utf-8-sig")

    assert '"--isolated-dataset-restore"' in restore
    assert "--restore-role" in restore
    assert "ticketbox_owner" in restore
    assert "function Assert-TicketboxInstalledPostgresToolArtifact" in contract
    assert restore.count("Assert-TicketboxInstalledPostgresToolArtifact") >= 2
    owner_body = restore.split("$inspection =", maxsplit=1)[1]
    assert owner_body.index("Assert-TicketboxInstalledPostgresToolArtifact") < owner_body.index(
        "Stop-TicketboxInstalledDatasetWriters"
    )
    assert "Invoke-TicketboxBoundedNativeProcess" in cluster
    assert "initdb.exe" in cluster
    assert "New-TicketboxInitdbServiceImagePath" in cluster
    assert "Invoke-TicketboxOwnedOneShotService" in cluster
    assert '"obj=", ([string]$release.service_logon_account)' in cluster
    assert "New-TicketboxPgServiceImagePath" in cluster
    assert "Set-TicketboxExactDirectoryAcl" in cluster
    assert "Assert-TicketboxReleaseServiceIdentity" in cluster
    incomplete_cluster_cleanup = cluster.split(
        'if ((Get-TicketboxPathEntryKindNoFollow $pgVersion) -cne "File") {',
        maxsplit=1,
    )[1].split("Invoke-TicketboxScChecked", maxsplit=1)[0]
    assert "-ExpectedExecutable $ownedServiceExecutable" in incomplete_cluster_cleanup
    assert "-ExpectedExecutable $shawl" not in incomplete_cluster_cleanup
    removal = powershell_function(
        cluster,
        "Remove-TicketboxPostgresqlRestoreCandidateService",
    )
    assert "Assert-TicketboxPgServiceCommand" in removal
    assert "Assert-TicketboxReleaseServiceIdentity" in removal


def test_restore_promotion_is_forward_reconcilable_and_keeps_old_bytes_until_current() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    assert "candidate_pgdata" in contract
    assert "rollback_pgdata" in contract
    assert "candidate_uploads" in contract
    assert "rollback_uploads" in contract
    assert "Resolve-TicketboxInstalledDatasetRestorePhysicalState" in contract
    assert "Set-TicketboxInstalledDatasetRestorePhysicalSelection" in contract
    assert "Invoke-TicketboxInstalledDatasetRestorePromotion" not in contract
    assert '-Selection "Predecessor"' in restore
    compensation = restore.split("catch {", maxsplit=1)[-1]
    assert compensation.index("Read-TicketboxDatabaseGenerationCurrent") < compensation.index(
        '-Selection "Predecessor"'
    )
    assert restore.index("Invoke-TicketboxInstalledDatabaseGeneration") < restore.index(
        "Remove-TicketboxInstalledDatasetRestoreRollback"
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_physical_selection_can_recover_every_precurrent_cutpoint(tmp_path: Path) -> None:
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    classifier = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestorePhysicalState",
    )
    selector = powershell_function(
        contract,
        "Set-TicketboxInstalledDatasetRestorePhysicalSelection",
    )
    base = str(tmp_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (Test-Path -LiteralPath $Path -PathType Container) {{ return 'Directory' }}
    return 'Missing'
}}
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


def test_restore_durable_request_owns_backend_restart_compensation() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    artifacts = (PACKAGING / "windows_database_generation_artifacts.ps1").read_text(encoding="utf-8-sig")
    request = powershell_function(
        contract,
        "Assert-TicketboxInstalledDatasetRestoreRequest",
    )

    assert '"restart_backend"' in request
    assert "$payload.restart_backend -isnot [bool]" in request
    create = powershell_function(
        contract,
        "New-TicketboxInstalledDatasetRestoreRequest",
    )
    assert "[Parameter(Mandatory = $true)][bool]$RestartBackend" in create
    assert "restart_backend = $RestartBackend" in create
    request_fields = artifacts.split('"dataset-restore-request" {', maxsplit=1)[1].split(
        '"source-binding" {', maxsplit=1
    )[0]
    assert '"restart_backend"' in request_fields
    assert "RestartBackend $restartBackend" in restore
    assert "priorPredecessor" in restore
    assert "expected_predecessor_sha256" in restore
    assert "source_request_sha256" in restore
    done = restore.index('"done" {')
    backend_restart = restore.index("Start-TicketboxOwnedServiceIfExists", done)
    assert done < backend_restart
    assert "if ($restartBackend -and $null -ne $result)" in restore[done:backend_restart]
    retirement = restore.index(
        "Remove-TicketboxInstalledDatasetRestoreRequest",
        backend_restart,
    )
    assert backend_restart < retirement
    assert "function Remove-TicketboxInstalledDatasetRestoreRequest" in contract


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_owner_compensation_is_current_guarded_and_ordered(tmp_path: Path) -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    compensation = powershell_function(
        restore,
        "Invoke-TicketboxInstalledDatasetRestoreFailureCompensation",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:events = @()
$script:published = $false
function Read-TicketboxDatabaseGenerationCurrent {{
    $script:events += 'read-current'
    $operation = if ($script:published) {{ '22222222-2222-4222-8222-222222222222' }} else {{ '11111111-1111-4111-8111-111111111111' }}
    return [pscustomobject]@{{ Payload = [pscustomobject]@{{ operation_id = $operation }} }}
}}
function Remove-TicketboxPostgresqlRestoreCandidateService {{ param($Subject, $Paths); $script:events += 'remove-candidate-service' }}
function Stop-TicketboxInstalledDatasetWriters {{ param($Subject); $script:events += 'stop-writers' }}
function Stop-TicketboxOwnedServiceIfExists {{
    param(
        $Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds,
        $BackendPort, $ExpectedRuntimeExecutables
    )
    $script:events += "stop:$Name"
}}
function Set-TicketboxInstalledDatasetRestorePhysicalSelection {{ param($Paths, $Selection); $script:events += "select:$Selection" }}
function Set-TicketboxInstalledDatasetPublishedAcls {{ param($Subject, $Paths); $script:events += 'set-acls' }}
function Start-TicketboxOwnedServiceIfExists {{
    param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds)
    $script:events += "start:$Name"
}}
{compensation}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\\Ticketbox'; PgServiceName = 'ticketbox-pg'; BackendServiceName = 'ticketbox-backend' }}
    Release = [pscustomobject]@{{ service_state_timeout_ms = 1000; service_poll_interval_ms = 10 }}
}}
$request = [pscustomobject]@{{ Payload = [pscustomobject]@{{ restart_backend = $true }} }}
$paths = [pscustomobject]@{{}}
Invoke-TicketboxInstalledDatasetRestoreFailureCompensation $subject $request $paths '22222222-2222-4222-8222-222222222222'
$expected = 'read-current|remove-candidate-service|stop-writers|select:Predecessor|set-acls|start:ticketbox-pg|start:ticketbox-backend'
if (($script:events -join '|') -cne $expected) {{ throw "unexpected compensation order: $($script:events -join '|')" }}
$script:events = @()
$script:published = $true
Invoke-TicketboxInstalledDatasetRestoreFailureCompensation $subject $request $paths '22222222-2222-4222-8222-222222222222'
$expected = 'read-current|stop:ticketbox-backend'
if (($script:events -join '|') -cne $expected) {{
    throw "published CURRENT compensation did not fail closed: $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-owner-compensation.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_predecessor_classifier_distinguishes_committed_and_pending_successors(
    tmp_path: Path,
) -> None:
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    classifier = powershell_function(
        contract,
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


def test_completed_restore_can_create_a_new_successor_after_request_retirement() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    intent_branch = restore.split(
        "$contracts = New-TicketboxInstalledDatabaseGenerationContracts",
        maxsplit=1,
    )[1].split("$operationId =", maxsplit=1)[0]

    assert "$resumeCommittedRestore = $false" in restore
    assert "$resumeCommittedRestore = $true" in restore
    assert "-not $resumeCommittedRestore" in intent_branch
    assert "IsNullOrEmpty" not in intent_branch


def test_published_candidate_reconciles_main_host_before_h1_publication() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    publication = restore.split('"publish_current" {', maxsplit=1)[1].split('"retire_rollback" {', maxsplit=1)[0]

    assert publication.index("Set-TicketboxInstalledDatasetPublishedAcls") < publication.index(
        "Start-TicketboxOwnedServiceIfExists"
    )
    assert publication.index("Start-TicketboxOwnedServiceIfExists") < publication.index(
        "Invoke-TicketboxInstalledDatabaseGeneration"
    )


def test_restore_keeps_rollback_until_runtime_and_originals_are_verified() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    verification = restore.split('"verify_runtime" {', maxsplit=1)[1].split(
        '"retire_rollback" {', maxsplit=1
    )[0]
    assert verification.index("Start-TicketboxOwnedServiceIfExists") < verification.index(
        "Wait-TicketboxInstalledBackendHealth"
    )
    assert verification.index("Wait-TicketboxInstalledBackendHealth") < verification.index(
        "Invoke-TicketboxInstalledRestoredOriginalsVerification"
    )
    assert verification.index(
        "Invoke-TicketboxInstalledRestoredOriginalsVerification"
    ) < verification.index("New-TicketboxInstalledDatasetRuntimeVerification")
    assert "runtime-verification" in contract


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_next_action_reducer_is_closed_and_io_free(tmp_path: Path) -> None:
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    reducer = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestoreNextAction",
    )
    assert "[AllowNull()]" not in reducer
    assert reducer.count('[ValidateSet("absent", "present")]') == 3
    script = f"""
$ErrorActionPreference = 'Stop'
{reducer}
$cases = @(
    @('complete', 'absent', 'absent', 'absent', 'build_candidate'),
    @('candidate_building', 'absent', 'absent', 'absent', 'restore_candidate'),
    @('candidate_ready', 'present', 'absent', 'absent', 'promote_candidate'),
    @('old_pg_staged', 'present', 'absent', 'absent', 'promote_candidate'),
    @('old_staged', 'present', 'absent', 'absent', 'promote_candidate'),
    @('candidate_pg_published', 'present', 'absent', 'absent', 'promote_candidate'),
    @('candidate_published', 'present', 'absent', 'absent', 'publish_current'),
    @('candidate_published', 'present', 'present', 'absent', 'verify_runtime'),
    @('candidate_published', 'present', 'present', 'present', 'retire_rollback'),
    @('complete', 'present', 'present', 'present', 'done')
)
foreach ($case in $cases) {{
    $actual = Resolve-TicketboxInstalledDatasetRestoreNextAction `
        $case[0] $case[1] $case[2] $case[3]
    if ($actual -cne $case[4]) {{ throw "unexpected next action: $actual" }}
}}
$rejected = $false
try {{
    Resolve-TicketboxInstalledDatasetRestoreNextAction `
        'candidate_published' 'absent' 'absent' 'absent' | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'authority-free publication state was accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-next-action.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_retirement_partial_effects_remain_classifiable_and_retryable(
    tmp_path: Path,
) -> None:
    contract = CONTRACT.read_text(encoding="utf-8-sig")
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
    $partialState 'present' 'present' 'present'
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
    $containerState 'present' 'present' 'present'
if ($containerAction -cne 'retire_rollback') {{ throw "container cleanup was not retried: $containerAction" }}

$rejected = $false
try {{
    Resolve-TicketboxInstalledDatasetRestoreNextAction `
        'rollback_retiring' 'present' 'present' 'absent' | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'rollback retirement proceeded without runtime verification' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-retirement-retry.ps1",
    )
