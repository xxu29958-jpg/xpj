import json
import runpy
from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
APP = PACKAGING.parent / "app"
BACKUP = PACKAGING / "windows_dataset_backup.ps1"


def test_dataset_maintenance_cli_is_not_owned_by_backend_launch_host() -> None:
    launch = (PACKAGING / "launch.py").read_text(encoding="utf-8")
    cli_path = APP / "dataset_maintenance_cli.py"
    assert cli_path.is_file()
    cli = cli_path.read_text(encoding="utf-8")
    for function in (
        "_parse_complete_dataset_backup_args",
        "_parse_dataset_backup_inspection_args",
        "_parse_isolated_dataset_restore_args",
        "_parse_restored_originals_verification_args",
        "_run_complete_dataset_backup",
        "_run_dataset_backup_inspection",
        "_run_isolated_dataset_restore",
        "_run_restored_originals_verification",
    ):
        assert f"def {function}" in cli
        assert f"def {function}" not in launch
    assert "from app.dataset_maintenance_cli import" in launch
    assert launch.count("run_dataset_maintenance(arguments)") == 1


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_backup_owner_argv_is_accepted_by_the_real_frozen_cli_parser(tmp_path: Path) -> None:
    helper = powershell_function(
        BACKUP.read_text(encoding="utf-8-sig"),
        "Invoke-TicketboxInstalledCompleteBackupHelper",
    )
    argv_path = tmp_path / "complete-backup-argv.json"
    escaped_argv_path = str(argv_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxInstalledPostgresToolArtifact {{
    param($Subject, $Tool)
    if ($Tool -ceq 'PgDump') {{ return 'C:\\pg\\pg_dump.exe' }}
    return 'C:\\pg\\pg_restore.exe'
}}
function New-TicketboxPostgresqlLocalDatabaseUrl {{ param($Authority, $Database, $Role); return 'postgresql://local' }}
function Invoke-TicketboxWithPlainPostgresqlSecret {{ param($Secret, $Action); return (& $Action 'password') }}
function New-TicketboxProtectedPgPassFile {{ param($DatabaseUrl, $Password); return [pscustomobject]@{{ Path = 'C:\\state\\pgpass'; FullControlAccounts = @(); OwnerAccount = 'owner' }} }}
function Open-TicketboxVerifiedDatabaseMaintenanceHelperLease {{ param($Path, $ExpectedRelativePath, $ExpectedSize, $ExpectedSha256); return [pscustomobject]@{{ Path = $Path }} }}
function New-TicketboxDatabaseGenerationHelperChildEnvironment {{ param($PgPassFilePath); return @{{}} }}
function Invoke-TicketboxBoundedNativeProcess {{
    param($FilePath, $Arguments, $StandardInputText, $TimeoutMilliseconds, $Label, $ChildEnvironment)
    $script:capturedArgv = @($Arguments)
    $script:capturedTimeoutMilliseconds = [int]$TimeoutMilliseconds
    return [pscustomobject]@{{
        ExitCode = 0
        StandardError = ''
        StandardOutput = '{{"schema":"ticketbox-complete-dataset-backup-result-v1","backup_id":"22222222-2222-4222-8222-222222222222","generation":"ticketbox-backup-22222222-2222-4222-8222-222222222222","dataset_id":"33333333-3333-4333-8333-333333333333","restore_epoch":4,"size_bytes":4096}}'
    }}
}}
function Get-TicketboxDatabaseGenerationJsonLine {{ param($StandardOutput, $Label); return $StandardOutput }}
function Assert-TicketboxDatabaseGenerationExactProperties {{ param($Value, $ExpectedNames, $Label) }}
function Assert-TicketboxDatabaseMaintenanceHelperLeaseUnchanged {{ param($Lease) }}
function Close-TicketboxDatabaseMaintenanceHelperLease {{ param($Lease) }}
function Remove-TicketboxProtectedPgPassArtifact {{ param($Path, $FullControlAccounts, $OwnerAccount) }}
function Throw-TicketboxOperationFailure {{ param($Primary, $Cleanup); if ($null -ne $Primary) {{ throw $Primary }} }}
{helper}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\\Ticketbox'; DataRoot = 'C:\\Data'; PgPort = 5432 }}
    Manifest = [pscustomobject]@{{
        Sha256 = ('a' * 64)
        DatabaseMaintenanceHelper = [pscustomobject]@{{ RelativePath = 'helper.exe'; Size = 1; Sha256 = ('d' * 64) }}
    }}
    Release = [pscustomobject]@{{
        database_tool_timeout_ms = 1000
        dataset_backup_helper_timeout_ms = 2000
    }}
}}
$authority = [pscustomobject]@{{ Credentials = [pscustomobject]@{{ BackupPassword = 'secret' }} }}
$request = [pscustomobject]@{{ Payload = [pscustomobject]@{{
    operation_id = '11111111-1111-4111-8111-111111111111'
    backup_id = '22222222-2222-4222-8222-222222222222'
    backup_kind = 'manual'
}} }}
$barrier = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        current_sha256 = ('c' * 64)
        dataset_id = '33333333-3333-4333-8333-333333333333'
        restore_epoch = 4
        schema_revision = '20260821_0001'
    }}
}}
[void](Invoke-TicketboxInstalledCompleteBackupHelper $subject $authority $request $barrier 2000)
if ([int]$script:capturedTimeoutMilliseconds -ne 2000) {{
    throw 'complete backup helper did not receive its composite timeout budget'
}}
[IO.File]::WriteAllText(
    '{escaped_argv_path}',
    ($script:capturedArgv | ConvertTo-Json -Compress),
    (New-Object Text.UTF8Encoding($false))
)
"""
    run_powershell_contract_script(script, tmp_path, filename="dataset-backup-real-cli-argv.ps1")
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    parser = runpy.run_path(str(APP / "dataset_maintenance_cli.py"))[
        "_parse_complete_dataset_backup_args"
    ]
    parsed = parser(argv)
    assert parsed.pg_dump_path == Path(r"C:\pg\pg_dump.exe")
    assert parsed.pg_restore_path == Path(r"C:\pg\pg_restore.exe")


def test_restore_helper_uses_its_complete_composite_timeout_budget() -> None:
    restore_database = PACKAGING / "windows_dataset_restore_database.ps1"
    restore_owner = (PACKAGING / "windows_dataset_restore.ps1").read_text(encoding="utf-8-sig")
    restore_policy = (PACKAGING / "windows_dataset_restore_reducer.ps1").read_text(encoding="utf-8-sig")
    helper = powershell_function(
        restore_database.read_text(encoding="utf-8-sig"),
        "Invoke-TicketboxInstalledDatasetRestoreHelper",
    )

    assert "-TimeoutMilliseconds $TimeoutMilliseconds" in helper
    assert "dataset_restore_helper_timeout_ms" in powershell_function(
        restore_policy,
        "Get-TicketboxInstalledDatasetRestoreActionBudgetMilliseconds",
    )
    assert "$phaseRequirement = Get-TicketboxInstalledDatasetRestoreActionBudgetMilliseconds" in restore_owner
    assert "-TimeoutMilliseconds $restoreHelperTimeout" in restore_owner


def test_payload_verifiers_do_not_reuse_database_tool_timeout() -> None:
    reader = (PACKAGING / "windows_installed_dataset_reader.ps1").read_text(encoding="utf-8-sig")
    runtime = (PACKAGING / "windows_dataset_restore_runtime.ps1").read_text(encoding="utf-8-sig")

    assert "dataset_payload_verification_timeout_ms" in reader
    assert "dataset_payload_verification_timeout_ms" in runtime
    assert "Subject.Release.database_tool_timeout_ms" not in powershell_function(
        reader,
        "Invoke-TicketboxInstalledDatasetBackupInspection",
    )
    assert "Subject.Release.database_tool_timeout_ms" not in powershell_function(
        runtime,
        "Invoke-TicketboxInstalledRestoredOriginalsVerification",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_complete_dataset_phase_cannot_start_without_its_full_remaining_budget(tmp_path: Path) -> None:
    deadline_source = (PACKAGING / "windows_deadline_budget.ps1").read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            powershell_function(deadline_source, "Assert-TicketboxProcessDeadlinePhaseBudget"),
            "$clock = [pscustomobject]@{ IsRunning = $true; ElapsedMilliseconds = 1000 }",
            "$budget = [pscustomobject]@{ TimeoutMilliseconds = 4000; Stopwatch = $clock }",
            "try {",
            "  Assert-TicketboxProcessDeadlinePhaseBudget -Budget $budget "
            "-RequiredMilliseconds 2000 -CleanupReserveMilliseconds 1500 -Label 'probe'",
            "  throw 'expired phase was admitted'",
            "} catch { if ($_.Exception.Message -notlike '*cannot start*') { throw } }",
        )
    )

    run_powershell_contract_script(script, tmp_path, filename="dataset-deadline-budget.ps1")


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_action_budgets_fit_the_complete_deadline_with_cleanup_reserved(tmp_path: Path) -> None:
    policy_source = (PACKAGING / "windows_dataset_restore_reducer.ps1").read_text(encoding="utf-8-sig")
    release = json.loads((PACKAGING / "windows-release-config.json").read_text(encoding="utf-8"))
    fields = "; ".join(f"{name} = {value}" for name, value in release.items() if isinstance(value, int))
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            powershell_function(policy_source, "Get-TicketboxInstalledDatasetRestoreActionBudgetMilliseconds"),
            f"$release = [pscustomobject]@{{ {fields} }}",
            "$total = [int64]$release.dataset_payload_verification_timeout_ms",
            "foreach ($action in @('build_candidate','restore_candidate','promote_candidate',"
            "'publish_current','verify_runtime','retire_rollback','done')) {",
            "  $total += Get-TicketboxInstalledDatasetRestoreActionBudgetMilliseconds $action $release",
            "}",
            "$required = $total + [int64]$release.complete_dataset_cleanup_reserve_ms",
            "$available = [int64]$release.complete_dataset_restore_timeout_ms + "
            "[int64]$release.complete_dataset_cleanup_reserve_ms",
            "if ($required -gt $available) { throw \"restore path budget $required exceeds $available\" }",
        )
    )

    run_powershell_contract_script(script, tmp_path, filename="dataset-restore-action-budget.ps1")
