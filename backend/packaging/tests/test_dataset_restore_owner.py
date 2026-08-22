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
    PACKAGING / "windows_installed_dataset_restore_artifacts.ps1",
    PACKAGING / "windows_installed_dataset_restore_verification.ps1",
    PACKAGING / "windows_dataset_restore_filesystem.ps1",
    PACKAGING / "windows_dataset_restore_reducer.ps1",
    PACKAGING / "windows_dataset_restore_database.ps1",
    PACKAGING / "windows_dataset_restore_runtime.ps1",
)
CLUSTER = PACKAGING / "windows_postgresql_candidate_cluster.ps1"


def _restore_contract() -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in CONTRACTS)


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
    contract = _restore_contract()
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
    inspection = powershell_function(
        contract,
        "Invoke-TicketboxInstalledDatasetBackupInspection",
    )
    assert "Get-ChildItem -LiteralPath $generationPath -Force -Recurse" in inspection
    assert "Assert-TicketboxExactFileAcl" in inspection
    assert inspection.rindex("Assert-TicketboxExactFileAcl") < inspection.index(
        "Open-TicketboxVerifiedDatabaseMaintenanceHelperLease"
    )


def test_restore_candidate_uses_official_frozen_restore_and_exact_role_owner() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = _restore_contract()
    cluster = CLUSTER.read_text(encoding="utf-8-sig")
    launch = (PACKAGING / "launch.py").read_text(encoding="utf-8")

    assert '"--isolated-dataset-restore"' in contract
    assert "--verify-restored-dataset-candidate" not in restore + launch
    assert "run_verified_isolated_dataset_restore_action" in launch
    helper = powershell_function(contract, "Invoke-TicketboxInstalledDatasetRestoreHelper")
    for argument in (
        "--generation-program-path",
        "--expected-generation-program-sha256",
        "--operation-id",
    ):
        assert argument in helper
    assert "--restore-role" in contract
    assert "ticketbox_owner" in contract
    assert "function Assert-TicketboxInstalledPostgresToolArtifact" in contract
    assert restore.count("Assert-TicketboxInstalledPostgresToolArtifact") == 1
    assert "Assert-TicketboxInstalledPostgresToolArtifact" in helper
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

    restore_action = restore.index('"restore_candidate" {')
    verified = restore.index("Invoke-TicketboxInstalledDatasetRestoreHelper", restore_action)
    evidence = restore.index("New-TicketboxInstalledDatasetCandidateVerification", verified)
    promotion = restore.index('"promote_candidate" {', evidence)
    assert verified < evidence < promotion
    promotion_body = restore[promotion : restore.index('"publish_current" {', promotion)]
    reobserved = promotion_body.index("Invoke-TicketboxInstalledDatasetRestoreHelper")
    rebound = promotion_body.index("New-TicketboxInstalledDatasetCandidateVerification")
    physical_move = promotion_body.index("Set-TicketboxInstalledDatasetRestorePhysicalSelection")
    assert reobserved < rebound < physical_move
    assert 'if ($physical -ceq "candidate_ready")' in promotion_body

    restore_action_source = (
        PACKAGING.parent / "app" / "database" / "_dataset_restore_action.py"
    ).read_text(encoding="utf-8")
    assert "def _reset_restore_target(" in restore_action_source
    assert "DROP SCHEMA public CASCADE" in restore_action_source
    assert "target_is_empty" not in restore_action_source
    assert "def assert_restored_dataset_candidate(" not in (
        PACKAGING.parent / "app" / "database" / "_dataset_restore_authority.py"
    ).read_text(encoding="utf-8")


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
        predecessor.index("Publish-TicketboxDatabaseGenerationCurrent")
    )
    assert restore.index("Invoke-TicketboxInstalledDatabaseGeneration") < restore.index(
        "Remove-TicketboxInstalledDatasetRestoreRollback"
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_physical_selection_can_recover_every_precurrent_cutpoint(tmp_path: Path) -> None:
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
    contract = (PACKAGING / "windows_installed_dataset_restore_artifacts.ps1").read_text(
        encoding="utf-8-sig"
    )
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
    assert '"predecessor_current_payload"' in request_fields
    assert "RestartBackend $restartBackend" in restore
    assert "RestoreAttemptId" in restore
    assert "source_request_sha256" in restore
    runtime = restore.split('"verify_runtime" {', maxsplit=1)[1].split(
        '"retire_rollback" {', maxsplit=1
    )[0]
    assert runtime.index("Set-TicketboxInstalledDatasetBackendDesiredState") < runtime.index(
        "New-TicketboxInstalledDatasetRuntimeVerification"
    )
    terminal = restore.rindex("New-TicketboxInstalledDatasetRestoreResult")
    retirement = restore.rindex("Remove-TicketboxInstalledDatasetRestoreRequest")
    assert terminal < retirement
    assert "function Remove-TicketboxInstalledDatasetRestoreRequest" in contract


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_terminal_result_survives_response_loss_and_is_attempt_bound(
    tmp_path: Path,
) -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    artifacts = (PACKAGING / "windows_installed_dataset_restore_artifacts.ps1").read_text(
        encoding="utf-8-sig"
    )
    subject_read = restore.index("Assert-TicketboxInstalledDatasetSubject")
    current_read = restore.index("Read-TicketboxDatabaseGenerationCurrent")
    request_read = restore.index("Get-TicketboxInstalledDatasetRestoreRequest")
    terminal_read = restore.index("Read-TicketboxInstalledDatasetRestoreResult")
    terminal_write = restore.rindex("New-TicketboxInstalledDatasetRestoreResult")
    request_retire = restore.rindex("Remove-TicketboxInstalledDatasetRestoreRequest")
    assert subject_read < current_read < request_read < terminal_read
    assert terminal_write < request_retire
    terminal_resume = powershell_function(
        _restore_contract(),
        "Complete-TicketboxInstalledDatasetRestoreTerminalReplay",
    )
    assert "terminal.request_sha256" in terminal_resume
    assert "terminal.release_manifest_sha256" in terminal_resume
    assert terminal_resume.index("Set-TicketboxInstalledDatasetBackendDesiredState") < (
        terminal_resume.index("Remove-TicketboxInstalledDatasetRestoreRequest")
    )

    functions = "\n".join(
        powershell_function(artifacts, name)
        for name in (
            "Get-TicketboxInstalledDatasetRestoreResultPath",
            "Assert-TicketboxInstalledDatasetRestoreResult",
            "Read-TicketboxInstalledDatasetRestoreResult",
            "New-TicketboxInstalledDatasetRestoreResult",
        )
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:stored = $null
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw 'bad digest' }}
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw 'unexpected fields' }}
}}
function Read-TicketboxDatabaseGenerationEnvelope {{
    param($Path, $ExpectedKind, [switch]$AllowAbsent)
    if ($null -eq $script:stored) {{ if ($AllowAbsent) {{ return $null }}; throw 'absent' }}
    return $script:stored
}}
function Write-TicketboxDatabaseGenerationEnvelope {{
    param($Path, $Kind, $Payload, $LifecycleLock)
    $script:stored = [pscustomobject]@{{
        Path = $Path
        Kind = $Kind
        PayloadSha256 = ('d' * 64)
        Payload = [pscustomobject]$Payload
    }}
    return $script:stored
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Depth 20 -Compress)
}}
{functions}
$attempt = '11111111-1111-4111-8111-111111111111'
$backup = '22222222-2222-4222-8222-222222222222'
$request = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        restore_attempt_id = $attempt
        backup_generation = "ticketbox-backup-$backup"
        release_manifest_sha256 = ('c' * 64)
        restart_backend = $true
    }}
}}
$current = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{ operation_id = '44444444-4444-4444-8444-444444444444' }}
}}
$payload = [pscustomobject]@{{
    backup_id = $backup
    dataset_id = '33333333-3333-4333-8333-333333333333'
    restore_epoch = 5
    generation_operation_id = '44444444-4444-4444-8444-444444444444'
}}
$first = New-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\\state' -Request $request -Current $current `
    -Payload $payload -LifecycleLock ([pscustomobject]@{{}})
$retry = Read-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\\state' -RestoreAttemptId $attempt `
    -BackupGeneration "ticketbox-backup-$backup" `
    -Current $current -ExpectedReleaseManifestSha256 ('c' * 64)
if (
    $first.PayloadSha256 -cne $retry.Artifact.PayloadSha256 -or
    $retry.Disposition -cne 'current'
) {{ throw 'terminal result changed on retry' }}
$rejected = $false
try {{
    Read-TicketboxInstalledDatasetRestoreResult `
        -StateRoot 'C:\\state' -RestoreAttemptId $attempt `
        -BackupGeneration 'ticketbox-backup-55555555-5555-4555-8555-555555555555' `
        -Current $current -ExpectedReleaseManifestSha256 ('c' * 64) | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'terminal result crossed backup authority' }}
$rejected = $false
try {{
    Read-TicketboxInstalledDatasetRestoreResult `
        -StateRoot 'C:\\state' -RestoreAttemptId $attempt `
        -BackupGeneration "ticketbox-backup-$backup" `
        -Current $current -ExpectedReleaseManifestSha256 ('f' * 64) | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'terminal result crossed release authority' }}
$foreignCurrent = [pscustomobject]@{{
    PayloadSha256 = ('e' * 64)
    Payload = [pscustomobject]@{{ operation_id = '55555555-5555-4555-8555-555555555555' }}
}}
$superseded = Read-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\\state' -RestoreAttemptId $attempt `
    -BackupGeneration "ticketbox-backup-$backup" `
    -Current $foreignCurrent -ExpectedReleaseManifestSha256 ('c' * 64)
if (
    $superseded.Artifact.PayloadSha256 -cne $first.PayloadSha256 -or
    $superseded.Disposition -cne 'superseded'
) {{ throw 'stale terminal did not classify as superseded' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-terminal-retry.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_owner_compensation_restores_exact_predecessor_before_restart(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    compensation = powershell_function(
        contract,
        "Invoke-TicketboxInstalledDatasetRestoreFailureCompensation",
    )
    script = f"""
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
        }}
    }}
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
function Restore-TicketboxInstalledDatasetPredecessorRuntime {{
    param($Subject, $Request, $Paths, $StateRoot, $Contracts, $Current, $LifecycleLock)
    $script:events += "restore-predecessor:$($Current.PayloadSha256)"
}}
function Set-TicketboxInstalledDatasetBackendDesiredState {{
    param($Subject, $ShouldRun)
    $script:events += "desired:$ShouldRun"
}}
{compensation}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\\Ticketbox'; PgServiceName = 'ticketbox-pg'; BackendServiceName = 'ticketbox-backend' }}
    Release = [pscustomobject]@{{ service_state_timeout_ms = 1000; service_poll_interval_ms = 10 }}
}}
$request = [pscustomobject]@{{ Payload = [pscustomobject]@{{
    restart_backend = $true
    predecessor_current_sha256 = ('a' * 64)
}} }}
$paths = [pscustomobject]@{{ operation_id = '22222222-2222-4222-8222-222222222222' }}
$script:published = $true
$outcome = Invoke-TicketboxInstalledDatasetRestoreFailureCompensation `
    -Subject $subject -Request $request -Paths $paths -StateRoot 'C:\\state' `
    -Contracts ([pscustomobject]@{{}}) -RuntimeVerification $null `
    -LifecycleLock ([pscustomobject]@{{}})
$expected = 'read-current|remove-candidate-service|stop-writers|restore-predecessor:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|desired:True'
if (($script:events -join '|') -cne $expected -or $outcome -cne 'rolled_back') {{
    throw "published CURRENT did not restore exact predecessor: $outcome / $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-owner-compensation.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_terminal_replay_reconciles_desired_backend_before_request_retirement(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    replay = powershell_function(
        contract,
        "Complete-TicketboxInstalledDatasetRestoreTerminalReplay",
    )
    desired_state = powershell_function(
        contract,
        "Set-TicketboxInstalledDatasetBackendDesiredState",
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = @()
function Assert-TicketboxInstalledDatasetServiceAuthority {{ param($Subject); $script:events += 'authority' }}
function Start-TicketboxOwnedServiceIfExists {{ param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds); $script:events += "start:$Name" }}
function Stop-TicketboxOwnedServiceIfExists {{ param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds, $BackendPort, $ExpectedRuntimeExecutables); $script:events += "stop:$Name" }}
function Remove-TicketboxInstalledDatasetRestoreRequest {{ param($Request, $LifecycleLock); $script:events += 'remove-request' }}
{desired_state}
{replay}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\Ticketbox'; BackendServiceName = 'ticketbox-backend'; BackendPort = 8123 }}
    Release = [pscustomobject]@{{ service_state_timeout_ms = 1000; service_poll_interval_ms = 10 }}
}}
$request = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        restore_attempt_id = '11111111-1111-4111-8111-111111111111'
        backup_generation = 'ticketbox-backup-22222222-2222-4222-8222-222222222222'
        release_manifest_sha256 = ('c' * 64)
        restart_backend = $true
    }}
}}
$terminal = [pscustomobject]@{{
    Disposition = 'current'
    Artifact = [pscustomobject]@{{ Payload = [pscustomobject]@{{
        request_sha256 = ('a' * 64)
        release_manifest_sha256 = ('c' * 64)
        restore_attempt_id = '11111111-1111-4111-8111-111111111111'
        backup_id = '22222222-2222-4222-8222-222222222222'
        dataset_id = '33333333-3333-4333-8333-333333333333'
        restore_epoch = 4
        generation_operation_id = '44444444-4444-4444-8444-444444444444'
    }} }}
}}
$result = Complete-TicketboxInstalledDatasetRestoreTerminalReplay `
    -Subject $subject -Request $request -TerminalResult $terminal `
    -BackupGeneration ([string]$request.Payload.backup_generation) `
    -LifecycleLock ([pscustomobject]@{{}})
if (($script:events -join '|') -cne 'authority|start:ticketbox-backend|remove-request') {{
    throw "terminal replay retired request before desired state: $($script:events -join '|')"
}}
if ([string]$result.result -cne 'current_published') {{ throw 'terminal replay lost current result' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-terminal-state-reconciliation.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_request_path_is_singleton_across_attempts(tmp_path: Path) -> None:
    contract = _restore_contract()
    path_function = powershell_function(
        contract,
        "Get-TicketboxInstalledDatasetRestoreRequestPath",
    )
    root = str(tmp_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
{path_function}
$first = Get-TicketboxInstalledDatasetRestoreRequestPath -StateRoot '{root}'
$second = Get-TicketboxInstalledDatasetRestoreRequestPath -StateRoot '{root}'
if ($first -cne $second) {{ throw 'restore request path split by attempt' }}
if ((Split-Path -Leaf $first) -cne 'dataset-restore-request.json') {{
    throw "restore request is not the singleton authority: $first"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-request-singleton.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_backup_inspection_checks_each_exact_acl_operand_before_opening_helper(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    inspection = powershell_function(
        contract,
        "Invoke-TicketboxInstalledDatasetBackupInspection",
    )
    root = str(tmp_path).replace("'", "''")
    generation = "ticketbox-backup-11111111-1111-4111-8111-111111111111"
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = @()
function Test-TicketboxPathEquals {{ param($Left, $Right); return $true }}
function Assert-TicketboxProtectedDirectoryAcl {{
    param($Path)
    $script:events += "dir:$Path"
}}
function Assert-NoTicketboxReparsePoints {{ param($Path) }}
function Get-ChildItem {{
    param($LiteralPath, [switch]$Force, [switch]$Recurse)
    return @(
        [pscustomobject]@{{ FullName = (Join-Path $LiteralPath 'originals'); Kind = 'Directory' }},
        [pscustomobject]@{{ FullName = (Join-Path $LiteralPath 'manifest.json'); Kind = 'File' }},
        [pscustomobject]@{{ FullName = (Join-Path $LiteralPath 'database.dump'); Kind = 'File' }}
    )
}}
function Get-TicketboxPathEntryKindNoFollow {{ param($Path); if ($Path.EndsWith('originals')) {{ return 'Directory' }}; return 'File' }}
function Assert-TicketboxExactFileAcl {{
    param($Path, $Accounts, $OwnerAccount)
    $script:events += "file:${{Path}}:$($Accounts -join ','):$OwnerAccount"
}}
function Open-TicketboxVerifiedDatabaseMaintenanceHelperLease {{ throw 'stop-after-acl' }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{
    param($Primary, $Cleanup)
    if ($null -ne $Primary) {{ throw $Primary }}
}}
{inspection}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ DataRoot = (Join-Path '{root}' 'data'); InstallDir = (Join-Path '{root}' 'install') }}
}}
$failed = $false
try {{ Invoke-TicketboxInstalledDatasetBackupInspection $subject '{generation}' | Out-Null }}
catch {{ if ($_.Exception.Message -ceq 'stop-after-acl') {{ $failed = $true }} else {{ throw }} }}
if (-not $failed) {{ throw 'inspection crossed the helper boundary' }}
$generationPath = Join-Path (Join-Path $subject.Identity.DataRoot 'backups') '{generation}'
$expected = @(
    "dir:$(Join-Path $subject.Identity.DataRoot 'backups')",
    "dir:$generationPath",
    "dir:$(Join-Path $generationPath 'originals')",
    "file:$(Join-Path $generationPath 'manifest.json'):SYSTEM,BUILTIN\Administrators:SYSTEM",
    "file:$(Join-Path $generationPath 'database.dump'):SYSTEM,BUILTIN\Administrators:SYSTEM"
)
if (($script:events -join '|') -cne ($expected -join '|')) {{
    throw "backup ACL operands drifted: $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-backup-tree-acl-operands.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_predecessor_classifier_distinguishes_committed_and_pending_successors(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
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
    contract = _restore_contract()

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
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = _restore_contract()
    reducer = powershell_function(
        contract,
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
    $partialState ([pscustomobject]@{{}}) ([pscustomobject]@{{}}) `
    ([pscustomobject]@{{}}) ([pscustomobject]@{{}})
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
    $containerState ([pscustomobject]@{{}}) ([pscustomobject]@{{}}) `
    ([pscustomobject]@{{}}) ([pscustomobject]@{{}})
if ($containerAction -cne 'retire_rollback') {{ throw "container cleanup was not retried: $containerAction" }}

$rejected = $false
try {{
    Resolve-TicketboxInstalledDatasetRestoreNextAction `
        'rollback_retiring' ([pscustomobject]@{{}}) ([pscustomobject]@{{}}) `
        ([pscustomobject]@{{}}) $null | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'rollback retirement proceeded without runtime verification' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-retirement-retry.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_shipment_parses_as_whole_files_on_ps51_and_ps7(tmp_path: Path) -> None:
    paths = ",".join("'" + str(path).replace("'", "''") + "'" for path in (RESTORE, *CONTRACTS))
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
