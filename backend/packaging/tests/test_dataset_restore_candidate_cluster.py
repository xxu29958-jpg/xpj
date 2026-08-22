from __future__ import annotations

from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
CLUSTER = PACKAGING / "windows_postgresql_candidate_cluster.ps1"
INITDB = PACKAGING / "windows_postgresql_candidate_initdb.ps1"
CANDIDATE_RUNTIME = PACKAGING / "windows_postgresql_candidate_runtime.ps1"
FILESYSTEM = PACKAGING / "windows_dataset_restore_filesystem.ps1"
RESTORE = PACKAGING / "windows_dataset_restore.ps1"
RESTORE_CONTRACTS = (
    PACKAGING / "windows_installed_dataset_reader.ps1",
    PACKAGING / "windows_installed_dataset_restore_artifacts.ps1",
    PACKAGING / "windows_installed_dataset_restore_verification.ps1",
    PACKAGING / "windows_dataset_restore_filesystem.ps1",
    PACKAGING / "windows_dataset_restore_reducer.ps1",
    PACKAGING / "windows_dataset_restore_database.ps1",
    PACKAGING / "windows_dataset_restore_runtime.ps1",
)

_CLUSTER_OWNER_FUNCTIONS = (
    "Get-TicketboxPostgresqlRestoreCandidateClusterObservation",
    "Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction",
    "Reset-TicketboxPostgresqlRestoreCandidateInitdbAttempt",
    "Initialize-TicketboxPostgresqlRestoreCandidateInitdbCapability",
    "Invoke-TicketboxPostgresqlRestoreCandidateInitdbOneShot",
    "Remove-TicketboxPostgresqlRestoreCandidateInitdbCapability",
    "Wait-TicketboxPostgresqlRestoreCandidateInitdbTerminal",
    "Initialize-TicketboxPostgresqlRestoreCandidateCluster",
)


def _cluster_owner_source(*names: str) -> str:
    source = "\n".join(path.read_text(encoding="utf-8-sig") for path in (CLUSTER, INITDB))
    return "\n".join(powershell_function(source, name) for name in names)


def test_restore_candidate_uses_official_frozen_restore_and_exact_role_owner() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = "\n".join(path.read_text(encoding="utf-8-sig") for path in RESTORE_CONTRACTS)
    cluster = CLUSTER.read_text(encoding="utf-8-sig")
    initdb = INITDB.read_text(encoding="utf-8-sig")
    candidate_runtime = CANDIDATE_RUNTIME.read_text(encoding="utf-8-sig")
    maintenance_cli = (PACKAGING.parent / "app" / "dataset_maintenance_cli.py").read_text(encoding="utf-8")

    assert '"--isolated-dataset-restore"' in contract
    assert "--verify-restored-dataset-candidate" not in restore + maintenance_cli
    assert "run_verified_isolated_dataset_restore_action" in maintenance_cli
    helper = powershell_function(contract, "Invoke-TicketboxInstalledDatasetRestoreHelper")
    for argument in (
        "--generation-program-path",
        "--expected-generation-program-sha256",
        "--active-installation-id",
        "--operation-id",
    ):
        assert argument in helper
    assert "--restore-role" in contract
    assert "ticketbox_owner" in contract
    assert "function Assert-TicketboxInstalledPostgresToolArtifact" in contract
    assert restore.count("Assert-TicketboxInstalledPostgresToolArtifact") == 1
    assert "Assert-TicketboxInstalledPostgresToolArtifact" in helper
    owner_body = restore.split("$inspection =", maxsplit=1)[1]
    assert owner_body.index("Assert-TicketboxInstalledPostgresToolArtifact") < (
        owner_body.index("Stop-TicketboxInstalledDatasetWriters")
    )
    assert "Invoke-TicketboxBoundedNativeProcess" in cluster
    assert "initdb.exe" in initdb
    assert "New-TicketboxInitdbServiceImagePath" in initdb
    assert "Invoke-TicketboxOwnedOneShotService" in initdb
    assert '"obj=", ([string]$release.service_logon_account)' in candidate_runtime
    assert "New-TicketboxPgServiceImagePath" in candidate_runtime
    assert "Set-TicketboxExactDirectoryAcl" in candidate_runtime
    assert "Assert-TicketboxReleaseServiceIdentity" in candidate_runtime
    cleanup = powershell_function(
        initdb,
        "Reset-TicketboxPostgresqlRestoreCandidateInitdbAttempt",
    )
    assert '@("absent", "owned_initdb")' in cleanup
    assert "-ExpectedExecutable ([string]$observation.service_executable)" in cleanup
    assert 'service_kind -ceq "owned_pgctl"' not in cleanup
    removal = powershell_function(
        candidate_runtime,
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
    physical_move = promotion_body.index("Set-TicketboxInstalledDatasetRestorePhysicalSelection")
    assert physical_move > 0
    assert "Invoke-TicketboxInstalledDatasetRestoreHelper" not in promotion_body
    assert "New-TicketboxInstalledDatasetCandidateVerification" not in promotion_body
    assert "Initialize-TicketboxPostgresqlRestoreCandidateDatabase" not in promotion_body

    restore_action_source = (PACKAGING.parent / "app" / "database" / "_dataset_restore_action.py").read_text(
        encoding="utf-8"
    )
    assert "def _reset_restore_target(" in restore_action_source
    assert "DROP SCHEMA public CASCADE" in restore_action_source
    assert "target_is_empty" not in restore_action_source
    assert "def assert_restored_dataset_candidate(" not in (
        PACKAGING.parent / "app" / "database" / "_dataset_restore_authority.py"
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_candidate_root_ancestor_is_guarded_before_any_mutation(tmp_path: Path) -> None:
    initializer = _cluster_owner_source(
        "Get-TicketboxPostgresqlRestoreCandidateClusterObservation",
        "Initialize-TicketboxPostgresqlRestoreCandidateCluster",
    )
    paths_factory = powershell_function(
        FILESYSTEM.read_text(encoding="utf-8-sig"),
        "Get-TicketboxInstalledDatasetRestorePaths",
    )
    path_guard = powershell_function(
        FILESYSTEM.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxInstalledDatasetRestorePathAuthority",
    )
    root = str(tmp_path.resolve()).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$operation = '22222222-2222-4222-8222-222222222222'
$dataRoot = Join-Path '{root}' 'data'
$candidateRoot = Join-Path $dataRoot "restore-candidates\$operation"
$rollbackRoot = Join-Path $dataRoot "restore-rollbacks\$operation"
$paths = [pscustomobject][ordered]@{{
    operation_id = $operation
    data_root = $dataRoot
    stable_pgdata = Join-Path $dataRoot 'pgdata'
    stable_uploads = Join-Path $dataRoot 'app\uploads'
    candidate_pgdata = Join-Path $candidateRoot 'pgdata'
    candidate_uploads = Join-Path $candidateRoot 'uploads'
    rollback_pgdata = Join-Path $rollbackRoot 'pgdata'
    rollback_uploads = Join-Path $rollbackRoot 'uploads'
    candidate_root = $candidateRoot
    rollback_root = $rollbackRoot
}}
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Test-TicketboxPathEquals {{
    param($Left, $Right)
    return [IO.Path]::GetFullPath([string]$Left) -ceq [IO.Path]::GetFullPath([string]$Right)
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "unexpected fields: $Label" }}
}}
function Assert-NoTicketboxAncestorReparsePoints {{ throw 'ancestor reparse rejected' }}
{paths_factory}
{path_guard}
{initializer}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ DataRoot = $dataRoot }}
    Release = [pscustomobject]@{{}}
}}
$rejected = $false
try {{
    Initialize-TicketboxPostgresqlRestoreCandidateCluster `
        -Subject $subject -OperationId $operation -Paths $paths `
        -BootstrapState ([pscustomobject]@{{}}) `
        -LifecycleLock ([pscustomobject]@{{}})
}}
catch {{ $rejected = $_.Exception.Message -like '*ancestor reparse rejected*' }}
if (-not $rejected) {{ throw 'candidate ancestor guard was not authoritative' }}
if ([IO.Directory]::Exists($candidateRoot)) {{ throw 'candidate root mutated before ancestor guard' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="candidate-root-ancestor-pre-mutation.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_candidate_cluster_reducer_is_closed_and_io_free(tmp_path: Path) -> None:
    reducer = _cluster_owner_source("Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction")
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "unexpected fields: $Label" }}
}}
{reducer}
function New-Observation {{
    param($Service, $PgData, $Password = 'missing', $State = 'stopped', $Exit = 0)
    return [pscustomobject][ordered]@{{
        schema = 'ticketbox-postgresql-restore-candidate-observation-v1'
        candidate_root_kind = 'directory'
        pgdata_state = $PgData
        password_kind = $Password
        service_kind = $Service
        service_executable = ''
        service_state = $State
        exit_code = [uint32]$Exit
        service_specific_exit_code = [uint32]0
    }}
}}
$cases = @(
    @('absent', 'missing', 'missing', 'stopped', 0, 'prepare_initdb'),
    @('absent', 'partial', 'missing', 'stopped', 0, 'reset_stale_attempt'),
    @('owned_initdb', 'missing', 'missing', 'stopped', 0, 'reset_stale_attempt'),
    @('owned_initdb', 'missing', 'file', 'stopped', 0, 'run_prepared_initdb'),
    @('owned_initdb', 'complete', 'file', 'stopped', 0, 'retire_initdb_capability'),
    @('owned_initdb', 'missing', 'file', 'running', 0, 'wait_initdb_terminal'),
    @('owned_initdb', 'partial', 'file', 'stopped', 1, 'reset_stale_attempt'),
    @('owned_pgctl', 'complete', 'missing', 'absent', 0, 'reconcile_loopback')
)
foreach ($case in $cases) {{
    $observation = New-Observation $case[0] $case[1] $case[2] $case[3] $case[4]
    $actual = Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction $observation
    if ([string]$actual -cne [string]$case[5]) {{ throw "unexpected action: $actual" }}
}}
$rejected = $false
try {{
    Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction `
        (New-Observation 'owned_pgctl' 'partial') | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'incomplete pg_ctl-owned cluster was accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="candidate-cluster-reducer.ps1",
    )
