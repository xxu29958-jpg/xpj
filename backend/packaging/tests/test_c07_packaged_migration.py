"""PowerShell bridge contracts for C07 and frozen release-schema actions."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]


def _ps_literal(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def test_packaged_bridge_contains_exact_c07_and_release_schema_authority() -> None:
    source = (PACKAGING / "windows_c07_packaged_migration.ps1").read_text(
        encoding="utf-8-sig"
    )

    for required in (
        "ticketbox-c07-production-migration-context-v5",
        '"upload_root_binding_sha256"',
        "non-zero canonical lowercase SHA-256",
        "ticketbox-c07-maintenance-plan-v2",
        "ticketbox-c07-maintenance-upgrade-result-v3",
        "ticketbox-c07-money-facts-result-v2",
        "ticketbox-c07-target-semantic-result-v1",
        "ticketbox-managed-schema-plan-v1",
        "ticketbox-managed-schema-upgrade-result-v1",
        "--expected-revision-manifest-sha256",
        "--maintenance-deadline-utc",
        "--maintenance-remaining-ceiling-ms",
        "--maintenance-authority-sha256",
        'ValidateSet("isolated_replay")',
        "resource_shape_sha256",
        "money_facts_sha256",
        "-ChildEnvironment $childEnvironment",
    ):
        assert required in source
    assert source.count("-PgPassFilePath $passfile.Path") == 6

    for forbidden in (
        "installed_descendant",
        "20260730",
        "--expected-recovery-manifest-sha256",
        "stable_replay_sha256",
        "device_close_sha256",
        "category_rule_public_id_sha256",
        "retention_evidence_sha256",
        "semantic_facts_sha256",
    ):
        assert forbidden not in source


def test_packaged_bridge_binds_exact_plan_attestations_and_secret_boundary(
    tmp_path: Path,
) -> None:
    helper = tmp_path / "ticketbox-c07-migrator.exe"
    helper.write_bytes(b"synthetic helper")
    helper_sha256 = hashlib.sha256(helper.read_bytes()).hexdigest().upper()
    harness = tmp_path / "c07-packaged-migration-contract.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(PACKAGING / "windows_c07_packaged_migration.ps1")}'

$script:testSecret = 'never-emit-this-c07-secret'
$script:testArguments = @()
$script:testInput = 'not-called'
$script:testChildEnvironment = $null
$script:testPlanChildEnvironment = $null
$script:testCleanupCount = 0
$script:ambientPg = [ordered]@{{
    PGHOSTADDR = '203.0.113.9'
    PGSERVICE = 'ambient-service'
    PGSSLMODE = 'disable'
    PGOPTIONS = '-c search_path=ambient'
    PGTARGETSESSIONATTRS = 'read-only'
    PGDATESTYLE = 'SQL, DMY'
    PGPASSWORD = 'ambient-secret'
    PGPASSFILE = 'C:/ambient/pgpass'
}}
foreach ($entry in $script:ambientPg.GetEnumerator()) {{
    [Environment]::SetEnvironmentVariable(
        [string]$entry.Key,
        [string]$entry.Value,
        [EnvironmentVariableTarget]::Process
    )
}}
[Environment]::SetEnvironmentVariable(
    'TICKETBOX_C07_ENV_SENTINEL',
    'preserve-me',
    [EnvironmentVariableTarget]::Process
)

function Assert-TicketboxC07ExactProperties {{
    param($Value, [string[]]$ExpectedNames, [string]$ArtifactName)
    $actual = @($Value.PSObject.Properties.Name)
    if (
        $actual.Count -ne $ExpectedNames.Count -or
        @($actual | Where-Object {{ $_ -cnotin $ExpectedNames }}).Count -ne 0
    ) {{
        throw "$ArtifactName shape mismatch"
    }}
}}
function ConvertTo-TicketboxC07CompactJson {{
    param($Value)
    return $Value | ConvertTo-Json -Compress -Depth 64
}}
function Assert-TicketboxC07LowerSha256 {{
    param([string]$Value, [string]$FieldName)
    if ($Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "bad lower $FieldName" }}
}}
function Assert-TicketboxC07Sha256 {{
    param([string]$Value, [string]$FieldName)
    if ($Value -cnotmatch '^[0-9A-F]{{64}}$') {{ throw "bad host $FieldName" }}
}}
function Get-TicketboxC07TextSha256 {{
    param([string]$Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '') }}
    finally {{ $sha.Dispose() }}
}}
function Get-TestArgumentValue {{
    param([string[]]$Arguments, [string]$Name)
    $index = [array]::IndexOf($Arguments, $Name)
    if ($index -lt 0 -or $index + 1 -ge $Arguments.Count) {{ throw "missing $Name" }}
    return [string]$Arguments[$index + 1]
}}

$revision = [ordered]@{{
    revision = '20260729_0001'
    down_revision = '20260722_0001'
    module_sha256 = ('1' * 64)
    transactionality = 'postgresql_single_transaction'
    reversibility = 'forward_only'
    downgrade_guard = 'raises_runtime_error_before_ddl'
    resources = @('column:expenses.amount_minor:int8')
    asset_recovery = 'same_generation_database_and_assets'
}}
$manifest = [ordered]@{{
    schema = 'ticketbox-c07-revision-manifest-v1'
    operation_kind = 'c07_money_minor_bigint_v1'
    source_revision = '20260722_0001'
    target_revision = '20260729_0001'
    revisions = @($revision)
}}
$manifestSha = (Get-TicketboxC07TextSha256 (
    ConvertTo-TicketboxC07CompactJson $manifest
)).ToLowerInvariant()
$plan = [ordered]@{{
    schema = 'ticketbox-c07-maintenance-plan-v2'
    operation_kind = 'c07_money_minor_bigint_v1'
    source_revision = '20260722_0001'
    target_revision = '20260729_0001'
    upgrade_required = $true
    revision_manifest = $manifest
    revision_manifest_sha256 = $manifestSha
}}
$managedPlan = [ordered]@{{
    schema = 'ticketbox-managed-schema-plan-v1'
    source_revision = '20260729_0001'
    target_revision = '20260802_0001'
    upgrade_required = $true
    revision_count = 1
    revision_manifest_sha256 = ('5' * 64)
}}
$parsedPlan = ConvertFrom-TicketboxC07PackagedMaintenancePlan `
    -StandardOutput ((ConvertTo-TicketboxC07CompactJson $plan) + "`n") `
    -SourceRevision '20260722_0001'

$descendantRejected = $false
$plan.target_revision = '20260730_0001'
$manifest.target_revision = '20260730_0001'
$plan.revision_manifest_sha256 = (Get-TicketboxC07TextSha256 (
    ConvertTo-TicketboxC07CompactJson $manifest
)).ToLowerInvariant()
try {{
    ConvertFrom-TicketboxC07PackagedMaintenancePlan `
        -StandardOutput ((ConvertTo-TicketboxC07CompactJson $plan) + "`n") `
        -SourceRevision '20260722_0001' | Out-Null
}}
catch {{ $descendantRejected = $true }}
$plan.target_revision = '20260729_0001'
$manifest.target_revision = '20260729_0001'
$plan.revision_manifest_sha256 = $manifestSha

$maintenance = [ordered]@{{
    schema = 'ticketbox-c07-maintenance-upgrade-result-v3'
    mode = 'isolated_replay'
    operation_id = '11111111-1111-4111-8111-111111111111'
    source_revision = '20260722_0001'
    target_revision = '20260729_0001'
    revision_manifest_sha256 = $manifestSha
    maintenance_authority_sha256 = ('4' * 64)
    maintenance_remaining_ceiling_ms = 599000
    resource_shape_sha256 = ('8' * 64)
    result = 'isolated_forward_replay_verified'
    alembic_revision = '20260729_0001'
    target_shape_sha256 = ('8' * 64)
    money_facts_sha256 = ('7' * 64)
}}
$parsedMaintenance = ConvertFrom-TicketboxC07PackagedMaintenanceResult `
    -StandardOutput ((ConvertTo-TicketboxC07CompactJson $maintenance) + "`n") `
    -Mode 'isolated_replay' `
    -OperationId '11111111-1111-4111-8111-111111111111' `
    -SourceRevision '20260722_0001' `
    -TargetRevision '20260729_0001' `
    -RevisionManifestSha256 $manifestSha.ToUpperInvariant() `
    -MaintenanceAuthoritySha256 ('4' * 64) `
    -MaintenanceRemainingCeilingMs 599000

$target = [ordered]@{{
    schema = 'ticketbox-c07-target-semantic-result-v1'
    operation_id = '11111111-1111-4111-8111-111111111111'
    database = 'ticketbox'
    snapshot_id = '00000003-0000001B-1'
    source_revision = '20260722_0001'
    target_revision = '20260729_0001'
    revision_manifest_sha256 = $manifestSha
    maintenance_authority_sha256 = ('4' * 64)
    maintenance_remaining_ceiling_ms = 599000
    alembic_revision = '20260729_0001'
    resource_shape_sha256 = ('8' * 64)
    money_facts_sha256 = ('7' * 64)
}}
$parsedTarget = ConvertFrom-TicketboxC07PackagedTargetSemanticResult `
    -StandardOutput ((ConvertTo-TicketboxC07CompactJson $target) + "`n") `
    -OperationId '11111111-1111-4111-8111-111111111111' `
    -Database 'ticketbox' `
    -SnapshotId '00000003-0000001B-1' `
    -SourceRevision '20260722_0001' `
    -TargetRevision '20260729_0001' `
    -RevisionManifestSha256 $manifestSha.ToUpperInvariant() `
    -MaintenanceAuthoritySha256 ('4' * 64) `
    -MaintenanceRemainingCeilingMs 599000

$fakeSemanticRejected = $false
$target.stable_replay_sha256 = ('9' * 64)
try {{
    ConvertFrom-TicketboxC07PackagedTargetSemanticResult `
        -StandardOutput ((ConvertTo-TicketboxC07CompactJson $target) + "`n") `
        -OperationId '11111111-1111-4111-8111-111111111111' `
        -Database 'ticketbox' `
        -SnapshotId '00000003-0000001B-1' `
        -SourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -RevisionManifestSha256 $manifestSha.ToUpperInvariant() `
        -MaintenanceAuthoritySha256 ('4' * 64) `
        -MaintenanceRemainingCeilingMs 599000 | Out-Null
}}
catch {{ $fakeSemanticRejected = $true }}

function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Assert-TicketboxC07MigrationHelperLeaseUnchanged {{ param($Lease) }}
function Close-TicketboxC07MigrationHelperLease {{ param($Lease) }}
function Get-TicketboxPathEntryKindNoFollow {{ return 'File' }}
function Test-TicketboxPathEquals {{
    param([string]$Left, [string]$Right)
    return [IO.Path]::GetFullPath($Left) -ieq [IO.Path]::GetFullPath($Right)
}}
function Open-TicketboxC07VerifiedMigrationHelperLease {{
    param([string]$Path, [string]$ExpectedRelativePath, [int64]$ExpectedSize, [string]$ExpectedSha256)
    return [pscustomobject]@{{ Path = $Path }}
}}
function Invoke-TicketboxC07WithPlainSecret {{
    param([Security.SecureString]$Secret, [scriptblock]$Action)
    return & $Action $script:testSecret
}}
function Get-TicketboxC07RestoreDatabaseName {{
    param([string]$OperationId, [string]$CreateAttemptId)
    return 'ticketbox_c07_restore_11111111111141118111111111111111'
}}
function New-TicketboxC07LocalDatabaseUrl {{
    param($Authority, [string]$Database, [string]$Role)
    if ($Role -cne 'ticketbox_migrator') {{ throw 'wrong role' }}
    return "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/$Database"
}}
function New-TicketboxProtectedPgPassFile {{
    param([string]$DatabaseUrl, [string]$Password)
    if ($Password -cne $script:testSecret) {{ throw 'secret mismatch' }}
    return [pscustomobject]@{{
        DatabaseUrl = $DatabaseUrl
        Path = 'C:\\TicketboxInstallerSecrets\\.ticketbox-pgpass-1-11111111111111111111111111111111'
        FullControlAccounts = @('SYSTEM')
        OwnerAccount = 'SYSTEM'
    }}
}}
function Remove-TicketboxProtectedPgPassArtifact {{
    param([string]$Path, [string[]]$FullControlAccounts, [string]$OwnerAccount)
    $script:testCleanupCount += 1
}}
function Invoke-TicketboxBoundedNativeProcess {{
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$TimeoutMilliseconds,
        [string]$Label,
        [string]$StandardInputText,
        [System.Collections.IDictionary]$ChildEnvironment
    )
    $script:testArguments = @($Arguments)
    $script:testInput = $StandardInputText
    $script:testChildEnvironment = $ChildEnvironment
    if ($Arguments -contains '--c07-installed-upgrade-plan') {{
        $script:testPlanChildEnvironment = $ChildEnvironment
        return [pscustomobject]@{{
            ExitCode = 0
            StandardOutput = (ConvertTo-TicketboxC07CompactJson $plan) + "`n"
            StandardError = ''
        }}
    }}
    if ($Arguments -contains '--managed-schema-plan') {{
        $script:testPlanChildEnvironment = $ChildEnvironment
        return [pscustomobject]@{{
            ExitCode = 0
            StandardOutput =
                (ConvertTo-TicketboxC07CompactJson $managedPlan) + "`n"
            StandardError = ''
        }}
    }}
    if ($Arguments -contains '--managed-schema-upgrade') {{
        $managedSource = Get-TestArgumentValue $Arguments '--source-revision'
        $managedTarget = Get-TestArgumentValue $Arguments '--target-revision'
        $managedResult = [ordered]@{{
            schema = 'ticketbox-managed-schema-upgrade-result-v1'
            source_revision = $managedSource
            target_revision = $managedTarget
            revision_manifest_sha256 =
                Get-TestArgumentValue $Arguments '--expected-revision-manifest-sha256'
            result = if ($managedSource -ceq $managedTarget) {{
                'target_observed_after_interruption'
            }} else {{
                'target_committed'
            }}
            alembic_revision = $managedTarget
        }}
        return [pscustomobject]@{{
            ExitCode = 0
            StandardOutput =
                (ConvertTo-TicketboxC07CompactJson $managedResult) + "`n"
            StandardError = ''
        }}
    }}
    $remaining = [int](Get-TestArgumentValue $Arguments '--maintenance-remaining-ceiling-ms')
    $result = [ordered]@{{
        schema = 'ticketbox-c07-maintenance-upgrade-result-v3'
        mode = 'isolated_replay'
        operation_id = '11111111-1111-4111-8111-111111111111'
        source_revision = '20260722_0001'
        target_revision = '20260729_0001'
        revision_manifest_sha256 = Get-TestArgumentValue $Arguments '--expected-revision-manifest-sha256'
        maintenance_authority_sha256 = Get-TestArgumentValue $Arguments '--maintenance-authority-sha256'
        maintenance_remaining_ceiling_ms = $remaining
        resource_shape_sha256 = ('8' * 64)
        result = 'isolated_forward_replay_verified'
        alembic_revision = '20260729_0001'
        target_shape_sha256 = ('8' * 64)
        money_facts_sha256 = ('7' * 64)
    }}
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = (ConvertTo-TicketboxC07CompactJson $result) + "`n"
        StandardError = ''
    }}
}}

$helperEvidence = [pscustomobject][ordered]@{{
    RelativePath = 'ticketbox-c07-migrator.exe'
    Size = [int64](Get-Item -LiteralPath '{_ps_literal(helper)}').Length
    Sha256 = '{helper_sha256}'
}}
$secure = New-Object Security.SecureString
1..32 | ForEach-Object {{ $secure.AppendChar('x') }}
$secure.MakeReadOnly()
$deadline = [DateTime]::UtcNow.AddMinutes(10).ToString('o')
$installedPlan = Get-TicketboxC07PackagedInstalledUpgradePlan `
    -SourceRevision '20260722_0001' `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}'
$installedManagedPlan = Get-TicketboxPackagedManagedSchemaPlan `
    -SourceRevision '20260729_0001' `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}'
$managedActionResult = Invoke-TicketboxPackagedManagedSchemaUpgrade `
    -HostAuthority ([pscustomobject]@{{ Schema = 'authority' }}) `
    -MigratorPassword $secure `
    -Plan $installedManagedPlan `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}'
$managedPlan.source_revision = '20260802_0001'
$managedPlan.upgrade_required = $false
$managedPlan.revision_count = 0
$managedPlan.revision_manifest_sha256 = ('6' * 64)
$installedManagedNoopPlan = Get-TicketboxPackagedManagedSchemaPlan `
    -SourceRevision '20260802_0001' `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}'
$managedNoopActionResult = Invoke-TicketboxPackagedManagedSchemaUpgrade `
    -HostAuthority ([pscustomobject]@{{ Schema = 'authority' }}) `
    -MigratorPassword $secure `
    -Plan $installedManagedNoopPlan `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}'
$actionResult = Invoke-TicketboxC07PackagedIsolatedReplayAction `
    -HostAuthority ([pscustomobject]@{{ Schema = 'authority' }}) `
    -MigratorPassword $secure `
    -RestoreDatabase 'ticketbox_c07_restore_11111111111141118111111111111111' `
    -OperationId '11111111-1111-4111-8111-111111111111' `
    -SourceRevision '20260722_0001' `
    -TargetRevision '20260729_0001' `
    -RevisionManifestSha256 $manifestSha.ToUpperInvariant() `
    -MaintenanceDeadlineUtc $deadline `
    -MaintenanceRemainingCeilingMs 600000 `
    -MaintenanceAuthoritySha256 ('4' * 64) `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}' `
    -CreateAttemptId '22222222-2222-4222-8222-222222222222'
$childPgEntries = @(
    $script:testChildEnvironment.GetEnumerator() |
        Where-Object {{
            ([string]$_.Key).StartsWith(
                'PG',
                [StringComparison]::OrdinalIgnoreCase
            )
        }} |
        Sort-Object {{ ([string]$_.Key).ToUpperInvariant() }}
)
$childPgNames = @($childPgEntries | ForEach-Object {{ [string]$_.Key }})
$childPgValues = @($childPgEntries | ForEach-Object {{ [string]$_.Value }})
$parentEnvironmentUnchanged = $true
foreach ($entry in $script:ambientPg.GetEnumerator()) {{
    if (
        [Environment]::GetEnvironmentVariable(
            [string]$entry.Key,
            [EnvironmentVariableTarget]::Process
        ) -cne [string]$entry.Value
    ) {{
        $parentEnvironmentUnchanged = $false
    }}
}}
$argumentPgPassFile = Get-TestArgumentValue `
    $script:testArguments `
    '--pgpassfile'
$childPgPassFile = [string]$script:testChildEnvironment['PGPASSFILE']
$planPgEntries = @(
    $script:testPlanChildEnvironment.GetEnumerator() |
        Where-Object {{
            ([string]$_.Key).StartsWith(
                'PG',
                [StringComparison]::OrdinalIgnoreCase
            )
        }}
)

[ordered]@{{
    plan_target = [string]$parsedPlan.target_revision
    maintenance_result = [string]$parsedMaintenance.result
    target_shape = [string]$parsedTarget.resource_shape_sha256
    descendant_rejected = [bool]$descendantRejected
    fake_semantic_rejected = [bool]$fakeSemanticRejected
    action_result = [string]$actionResult.result
    installed_plan_target = [string]$installedPlan.target_revision
    managed_plan_target = [string]$installedManagedPlan.target_revision
    managed_action_result = [string]$managedActionResult.result
    managed_noop_action_result = [string]$managedNoopActionResult.result
    cleanup_count = [int]$script:testCleanupCount
    stdin_empty = ([string]$script:testInput).Length -eq 0
    secret_in_argv = (($script:testArguments -join "`n").Contains($script:testSecret))
    secret_in_child_environment = (
        (($script:testChildEnvironment.Values -join "`n").Contains(
            $script:testSecret
        ))
    )
    child_pg_names = $childPgNames
    child_pg_values = $childPgValues
    child_non_pg_sentinel = [string]$script:testChildEnvironment[
        'TICKETBOX_C07_ENV_SENTINEL'
    ]
    argv_environment_pgpass_match = (
        Test-TicketboxPathEquals $argumentPgPassFile $childPgPassFile
    )
    parent_environment_unchanged = $parentEnvironmentUnchanged
    plan_pg_count = $planPgEntries.Count
    plan_non_pg_sentinel = [string]$script:testPlanChildEnvironment[
        'TICKETBOX_C07_ENV_SENTINEL'
    ]
    has_descendant_arg = (($script:testArguments -join "`n").Contains('descendant'))
    has_recovery_manifest_arg = ($script:testArguments -contains '--expected-recovery-manifest-sha256')
}} | ConvertTo-Json -Compress
""",
        encoding="utf-8-sig",
    )

    for engine in powershell_contract_engines():
        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        evidence = json.loads(completed.stdout.strip().splitlines()[-1])
        assert evidence == {
            "plan_target": "20260729_0001",
            "maintenance_result": "isolated_forward_replay_verified",
            "target_shape": "8" * 64,
            "descendant_rejected": True,
            "fake_semantic_rejected": True,
            "action_result": "isolated_forward_replay_verified",
            "installed_plan_target": "20260729_0001",
            "managed_plan_target": "20260802_0001",
            "managed_action_result": "target_committed",
            "managed_noop_action_result": "target_observed_after_interruption",
            "cleanup_count": 3,
            "stdin_empty": True,
            "secret_in_argv": False,
            "secret_in_child_environment": False,
            "child_pg_names": ["PGPASSFILE"],
            "child_pg_values": [
                r"C:\TicketboxInstallerSecrets\.ticketbox-pgpass-1-"
                + ("1" * 32)
            ],
            "child_non_pg_sentinel": "preserve-me",
            "argv_environment_pgpass_match": True,
            "parent_environment_unchanged": True,
            "plan_pg_count": 0,
            "plan_non_pg_sentinel": "preserve-me",
            "has_descendant_arg": False,
            "has_recovery_manifest_arg": False,
        }
