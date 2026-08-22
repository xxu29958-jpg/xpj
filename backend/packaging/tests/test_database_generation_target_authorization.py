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


def test_target_authorization_binds_dataset_identity_from_exact_database_binding(
    tmp_path: Path,
) -> None:
    authorization = _function(
        TARGET_AUTHORIZATION.read_text(encoding="utf-8-sig"),
        "Invoke-TicketboxDatabaseGenerationTargetAuthorization",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{authorization}
$operation = '11111111-1111-4111-8111-111111111111'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $operation
        target_revision = 'intent-target-revision'
        generation_program_sha256 = ('9' * 64)
    }}
}}
$source = [pscustomobject]@{{
    PayloadSha256 = ('2' * 64)
    Payload = [pscustomobject]@{{
        intent_sha256 = ('a' * 64)
        cluster_system_identifier = 'cluster-one'
        database_oid = 42
        source_revision = 'source-revision'
    }}
}}
$binding = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        dataset_id = '22222222-2222-4222-8222-222222222222'
        restore_epoch = 37
        schema_revision = 'intent-target-revision'
    }}
}}
function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {{ return [pscustomobject]@{{}} }}
function Assert-TicketboxDatabaseGenerationMaintenanceAuthority {{}}
function Get-TicketboxDatabaseAuthorizationContract {{ return [pscustomobject]@{{ DatabaseName = 'ticketbox' }} }}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{
    return [pscustomobject]@{{ Exists = $true; ClusterSystemIdentifier = 'cluster-one'; DatabaseOid = 42 }}
}}
function Renew-TicketboxDatabaseGenerationMigratorWindow {{}}
function Invoke-TicketboxPackagedManagedSchemaUpgrade {{ return [pscustomobject]@{{ result = 'target_committed' }} }}
function Get-TicketboxDatabaseMaintenanceHelperEvidence {{ return [pscustomobject]@{{}} }}
function Get-TicketboxDatabaseGenerationProgramEvidence {{ return [pscustomobject]@{{}} }}
function Set-TicketboxDatabaseRuntimeAcl {{}}
function Get-TicketboxDatabaseGenerationFrozenFence {{ return [ordered]@{{ schema = 'fence' }} }}
function Get-TicketboxDatabaseRoleAuthorityEvidence {{ return 'role-evidence' }}
function Get-TicketboxDatabaseRuntimeAclEvidence {{ return 'acl-evidence' }}
function Invoke-TicketboxDatabaseGenerationTargetRecovery {{
    return [pscustomobject]@{{ PayloadSha256 = ('7' * 64) }}
}}
function New-TicketboxDatabaseGenerationExecutionAuthority {{ return [ordered]@{{ schema = 'execution' }} }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ return 'canonical' }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('6' * 64) }}
function Set-TicketboxDatabaseGenerationDatabaseBinding {{ return $binding }}
$credentials = [pscustomobject]@{{ MigratorPassword = 'migrator' }}
$maintenance = [pscustomobject]@{{ Secret = 'superuser' }}
$release = [pscustomobject]@{{
    MaintenanceHelperPath = 'maintenance.exe'
    DatabaseGenerationProgramPath = 'program.json'
}}
$actual = Invoke-TicketboxDatabaseGenerationTargetAuthorization `
    -StateRoot 'C:\\state' -Intent $intent -SourceBinding $source `
    -Credentials $credentials -ReleaseIdentity $release `
    -LifecycleLock ([pscustomobject]@{{}}) -HostContract ([pscustomobject]@{{}}) `
    -MaintenanceAuthority $maintenance
if (
    [string]$actual.database_binding_sha256 -cne ('b' * 64) -or
    [string]$actual.dataset_id -cne '22222222-2222-4222-8222-222222222222' -or
    [int64]$actual.restore_epoch -ne 37 -or
    [string]$actual.schema_revision -cne 'intent-target-revision'
) {{ throw 'target authorization did not use exact database binding operands' }}
$binding.Payload.schema_revision = 'foreign-live-revision'
$rejected = $false
try {{
    Invoke-TicketboxDatabaseGenerationTargetAuthorization `
        -StateRoot 'C:\\state' -Intent $intent -SourceBinding $source `
        -Credentials $credentials -ReleaseIdentity $release `
        -LifecycleLock ([pscustomobject]@{{}}) -HostContract ([pscustomobject]@{{}}) `
        -MaintenanceAuthority $maintenance | Out-Null
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'target authorization accepted a foreign live schema revision' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-target-binding.ps1",
    )


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
    close_backup_credential = _function(
        CREDENTIALS.read_text(encoding="utf-8-sig"),
        "Close-TicketboxDatabaseGenerationBackupCredential",
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
{close_backup_credential}
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
$backupCredential = [pscustomobject]@{{
    CandidateSha256 = ('c' * 64)
    BackupPassword = New-FailingSecret 'backup-capability'
}}
try {{ Close-TicketboxDatabaseGenerationBackupCredential $backupCredential }}
catch {{ $backupCleanup = $_.Exception }}
if (
    $backupCleanup.Message -cnotlike '*dispose failure: backup-capability*' -or
    ($script:disposed -join ',') -cne
        'runtime,migrator,backup,runtime-again,backup-again,http,backup-capability' -or
    $null -ne $backupCredential.BackupPassword -or
    $null -ne $backupCredential.CandidateSha256
) {{ throw 'backup credential cleanup lost failure or retained capability' }}
"""
    run_powershell_contract_script(script, tmp_path, filename="database-generation-owner.ps1")


def test_database_binding_rejects_live_revision_before_publication(tmp_path: Path) -> None:
    binding = _function(
        DATABASE_BINDING.read_text(encoding="utf-8-sig"),
        "Set-TicketboxDatabaseGenerationDatabaseBinding",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{ DatabaseName = 'ticketbox'; RuntimeRole = 'ticketbox_runtime' }}
}}
function Assert-TicketboxLifecycleOperationLease {{}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{}}
function Get-TicketboxDatabaseGenerationLiveIdentity {{ return $script:identity }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ return 'canonical-binding' }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('f' * 64) }}
function ConvertTo-TicketboxPostgresqlSqlLiteral {{ param($Value); return "'$Value'" }}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    $script:publicationCalls += 1
    return 'canonical-binding'
}}
{binding}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        installation_id = '22222222-2222-4222-8222-222222222222'
        target_revision = '20260821_0001'
        generation_program_sha256 = ('b' * 64)
    }}
}}
$source = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{ cluster_system_identifier = 'cluster'; database_oid = 42 }}
}}
$script:identity = [pscustomobject]@{{
    ClusterSystemIdentifier = 'cluster'; DatabaseOid = 42; DatabaseName = 'ticketbox'
    DatasetId = '33333333-3333-4333-8333-333333333333'; RestoreEpoch = 0
    SchemaRevision = 'foreign-live-revision'; SchemaMinCompatible = '20260809_0001'
    SemanticRevision = 'ticketbox-dataset-semantics-v1'
}}
$script:publicationCalls = 0
$arguments = @{{
    Intent = $intent; SourceBinding = $source; HostAuthority = @{{}}
    SuperuserPassword = [Security.SecureString]::new()
    ExecutionAuthoritySha256 = ('1' * 64); RoleAuthoritySha256 = ('2' * 64)
    RuntimeAclSha256 = ('3' * 64); WriterFenceSha256 = ('4' * 64)
    TargetRecoveryEvidenceSha256 = ('5' * 64); LifecycleLock = @{{}}
}}
$rejected = $false
try {{ Set-TicketboxDatabaseGenerationDatabaseBinding @arguments | Out-Null }}
catch {{ $rejected = $true }}
if (-not $rejected -or $script:publicationCalls -ne 0) {{
    throw 'foreign live schema revision reached database binding publication'
}}
$script:identity.SchemaRevision = '20260821_0001'
$actual = Set-TicketboxDatabaseGenerationDatabaseBinding @arguments
if (
    $script:publicationCalls -ne 1 -or
    [string]$actual.Payload.schema_revision -cne '20260821_0001'
) {{ throw 'matching live schema revision was not published exactly once' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-binding-revision.ps1",
    )
