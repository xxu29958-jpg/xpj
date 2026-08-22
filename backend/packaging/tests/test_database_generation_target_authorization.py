from pathlib import Path

import pytest
from _powershell_contract import powershell_function as _function
from _powershell_contract import run_powershell_contract_script

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
OWNER = PACKAGING / "windows_database_generation.ps1"
COMMIT_VERIFIER = PACKAGING / "windows_database_generation_commit_verifier.ps1"
DATABASE_BINDING = PACKAGING / "windows_database_generation_database_binding.ps1"
TARGET_AUTHORIZATION = PACKAGING / "windows_database_generation_target_authorization.ps1"
FAILURE = PACKAGING / "windows_operation_failure.ps1"
CREDENTIALS = PACKAGING / "windows_database_generation_credentials.ps1"


def test_target_authorization_consumes_normalized_source_without_mode_reclassification() -> None:
    owner = _function(
        OWNER.read_text(encoding="utf-8-sig"),
        "Invoke-TicketboxInstalledDatabaseGeneration",
    )
    target = owner.split('"authorize_target" {', maxsplit=1)[1].split('"seal_candidate" {', maxsplit=1)[0]

    assert "source_kind" not in target
    assert "source_request_sha256" not in target

    authorization = TARGET_AUTHORIZATION.read_text(encoding="utf-8-sig")
    assert 'schema = "ticketbox-database-generation-target-authorization-v2"' in authorization
    assert "database_binding_sha256 = [string]$databaseBinding.PayloadSha256" in authorization
    for field in ("dataset_id", "restore_epoch", "schema_revision"):
        assert f"{field} =" in authorization


def test_source_binding_downstream_does_not_reclassify_install_modes() -> None:
    verifier = COMMIT_VERIFIER.read_text(encoding="utf-8-sig")

    assert "Assert-TicketboxDatabaseGenerationSourceBindingChain" in verifier
    assert "source_kind" not in verifier
    assert "source_request_sha256" not in verifier
    assert '"source-create-attempt"' not in verifier
    assert '"restored-source"' not in verifier


def test_target_execution_authority_is_retry_stable_and_binding_is_insert_only(tmp_path: Path) -> None:
    database_binding = DATABASE_BINDING.read_text(encoding="utf-8-sig")
    authority = _function(
        database_binding,
        "New-TicketboxDatabaseGenerationExecutionAuthority",
    )
    failure = _function(
        FAILURE.read_text(encoding="utf-8-sig"),
        "Throw-TicketboxOperationFailure",
    )
    close_credentials = _function(
        CREDENTIALS.read_text(encoding="utf-8-sig"),
        "Close-TicketboxDatabaseGenerationCredentials",
    )
    close_runtime_credentials = _function(
        CREDENTIALS.read_text(encoding="utf-8-sig"),
        "Close-TicketboxDatabaseGenerationRuntimeCredentials",
    )
    binding = _function(
        database_binding,
        "Set-TicketboxDatabaseGenerationDatabaseBinding",
    )
    live_identity = _function(
        database_binding,
        "Get-TicketboxDatabaseGenerationLiveIdentity",
    )
    assert "ON CONFLICT (key) DO NOTHING" in binding
    assert "DO UPDATE" not in binding
    assert binding.count("Assert-TicketboxLifecycleOperationLease $LifecycleLock") >= 2
    assert "pg_catalog.pg_control_system()" in live_identity
    assert "pg_catalog.pg_database" in live_identity
    for field in (
        "cluster_system_identifier",
        "database_oid",
        "database_name",
        "runtime_role",
        "dataset_id",
        "restore_epoch",
        "schema_revision",
        "schema_min_compatible",
        "semantic_revision",
    ):
        assert field in binding
    assert "logical_server_id" not in binding
    assert "logical_data_generation" not in binding
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{ param($Value, $ExpectedNames, $Label) }}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{ param($Value, $Label) }}
{authority}
{failure}
{close_credentials}
{close_runtime_credentials}
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
$primaryError.Data['TicketboxFailureCode'] = 'C07-PRIMARY'
$primaryError.Data['TicketboxFailureCodes'] = @('C07-PRIMARY')
try {{ throw $primaryError }} catch {{ $primary = $_ }}
try {{ throw [InvalidOperationException]::new('cleanup-one') }} catch {{ $cleanupOne = $_ }}
try {{ throw [InvalidOperationException]::new('cleanup-two') }} catch {{ $cleanupTwo = $_ }}
try {{ throw [InvalidOperationException]::new('cleanup-three') }} catch {{ $cleanupThree = $_ }}
try {{ Throw-TicketboxOperationFailure $primary @($cleanupOne, $cleanupTwo, $cleanupThree) }} catch {{ $aggregate = $_.Exception }}
if (
    $aggregate -isnot [AggregateException] -or
    $aggregate.InnerExceptions.Count -ne 4 -or
    (($aggregate.InnerExceptions | ForEach-Object {{ $_.Message }}) -join '|') -cne
        'primary|cleanup-one|cleanup-two|cleanup-three' -or
    [string]$aggregate.Data['TicketboxFailureCode'] -cne 'C07-PRIMARY' -or
    @($aggregate.Data['TicketboxFailureCodes']).Count -ne 1
) {{ throw 'aggregate failure lost primary identity' }}
$script:disposed = @()
function New-FailingSecret([string]$Name) {{
    $secret = [pscustomobject]@{{ Name = $Name }}
    $secret | Add-Member ScriptMethod Dispose {{
        $script:disposed += $this.Name
        throw "dispose failure: $($this.Name)"
    }}
    return $secret
}}
$credentials = [pscustomobject]@{{
    RuntimePassword = New-FailingSecret 'runtime'
    MigratorPassword = New-FailingSecret 'migrator'
    BackupPassword = New-FailingSecret 'backup'
    RuntimeVerifier = 'runtime-verifier'
    MigratorVerifier = 'migrator-verifier'
    BackupVerifier = 'backup-verifier'
    Artifact = @{{}}
}}
try {{ Close-TicketboxDatabaseGenerationCredentials $credentials }}
catch {{ $credentialCleanup = $_.Exception }}
if (
    $credentialCleanup -isnot [AggregateException] -or
    $credentialCleanup.InnerExceptions.Count -ne 3 -or
    ($script:disposed -join ',') -cne 'runtime,migrator,backup' -or
    $null -ne $credentials.RuntimePassword -or
    $null -ne $credentials.MigratorPassword -or
    $null -ne $credentials.BackupPassword
) {{ throw 'credential cleanup did not preserve every failure and attempt' }}
$runtimeCredentials = [pscustomobject]@{{
    RuntimePassword = New-FailingSecret 'runtime-again'
    BackupPassword = New-FailingSecret 'backup-again'
    HttpBootstrapSecret = New-FailingSecret 'http'
    Artifact = @{{}}
}}
try {{ Close-TicketboxDatabaseGenerationRuntimeCredentials $runtimeCredentials }}
catch {{ $runtimeCleanup = $_.Exception }}
if (
    $runtimeCleanup -isnot [AggregateException] -or
    $runtimeCleanup.InnerExceptions.Count -ne 3 -or
    ($script:disposed -join ',') -cne 'runtime,migrator,backup,runtime-again,backup-again,http' -or
    $null -ne $runtimeCredentials.RuntimePassword -or
    $null -ne $runtimeCredentials.BackupPassword -or
    $null -ne $runtimeCredentials.HttpBootstrapSecret
) {{ throw 'runtime credential cleanup did not preserve every failure and attempt' }}
"""
    run_powershell_contract_script(script, tmp_path, filename="database-generation-owner.ps1")
