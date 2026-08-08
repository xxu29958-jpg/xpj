import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]
C07_DATABASE_SCRIPT = PACKAGING / "windows_c07_database.ps1"


def _powershell_engines() -> list[str]:
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    return engines


def _ps_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _run_harness(
    tmp_path: Path,
    name: str,
    script: str,
) -> None:
    harness = tmp_path / f"{name}.ps1"
    harness.write_text(script, encoding="utf-8-sig")
    for engine in _powershell_engines():
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, (
            f"{engine}:\n{result.stdout}\n{result.stderr}"
        )


def test_c07_database_source_is_narrow_and_secret_safe() -> None:
    source = C07_DATABASE_SCRIPT.read_text(encoding="utf-8-sig")
    assert source.startswith("#Requires -Version 5.1")
    assert "ticketbox_owner" in source
    assert "ticketbox_migrator" in source
    assert "ticketbox_runtime" in source
    assert "TicketboxC07RuntimeBootstrapAuthorityTables" not in source
    assert "Set-TicketboxManagedSchemaRuntimeAcl" in source
    assert "IncludeManagedSchemaCurrencyAuthority" in source
    for table in (
        "installation_currency_bindings",
        "installation_idempotency_keys",
        "installation_currency_audit_log",
    ):
        assert f'"{table}"' in source
    assert '"api_idempotency_contract_fences"' not in source
    assert 'NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE' in source
    assert 'LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE' in source
    assert "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE" in source
    assert "SET LOCAL ROLE" in source
    assert "REASSIGN OWNED BY" in source
    assert "DROP DATABASE" in source
    assert "ClusterSystemIdentifier" in source
    assert "DatabaseOid" in source
    assert "cleanup_pending" in source
    assert "ticketbox-c07-role-v2" in source
    assert "ticketbox-c07-database-v2" in source
    assert "ticketbox-c07-restore-database-v3" in source
    assert "legacy restore marker v2" in source
    assert "CreateAttemptId" in source
    assert "ticketbox-c07-production-authority-result-v2" in source
    assert "Invoke-TicketboxC07ProductionAuthorityCoordinator" in source
    assert "ticketbox-c07-production-lifecycle-binding-v2" in source
    assert "ALLOW_CONNECTIONS false" in source
    assert "REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM PUBLIC" in source
    assert not re.search(
        r"GRANT\s+.+\s+ON\s+ALL\s+(?:TABLES|SEQUENCES|ROUTINES|FUNCTIONS)",
        source,
        flags=re.IGNORECASE,
    )
    startup_probe_grant = (
        "GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system()"
    )
    assert startup_probe_grant in source
    assert not re.search(
        r"GRANT\s+EXECUTE\s+ON",
        source.replace(startup_probe_grant, ""),
        flags=re.IGNORECASE,
    )
    assert "PGPASSWORD" not in source
    assert "trust" not in source.lower()
    assert "[string]$DatabaseUrl" not in source
    assert "$env:" not in source

    raw = C07_DATABASE_SCRIPT.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell GUID contract")
def test_fresh_database_operation_id_matches_shared_canonical_guid_contract(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'

$historical = '1493b3d9-3721-0e51-0255-58aba5ba6e99'
$rfcUuid = '123e4567-e89b-42d3-a456-426614174099'
foreach ($accepted in @($historical, $rfcUuid)) {{
    $parsed = ConvertTo-TicketboxC07OperationGuid $accepted
    if ($parsed.ToString('D') -cne $accepted) {{
        throw "database operation ID did not round-trip: $accepted"
    }}
}}

foreach ($rejected in @(
    '',
    '00000000-0000-0000-0000-000000000000',
    '1493B3D9-3721-0E51-0255-58ABA5BA6E99',
    'not-a-guid'
)) {{
    $failedClosed = $false
    try {{
        ConvertTo-TicketboxC07OperationGuid $rejected | Out-Null
    }}
    catch {{
        $failedClosed = $true
    }}
    if (-not $failedClosed) {{
        throw "non-canonical database operation ID was accepted: $rejected"
    }}
}}

$script:observedOperationIds = [System.Collections.Generic.List[string]]::new()
function Assert-TicketboxC07SecureString {{ param($Value, $Label) }}
function Assert-TicketboxC07MigratorCredentialWindow {{ param($Value) }}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{ Schema = 'test-host-authority' }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
function Assert-TicketboxC07FreshPreflight {{
    param($Authority, $SuperuserPassword, [string]$OperationId)
    $script:observedOperationIds.Add($OperationId)
    return [pscustomobject]@{{ Phase = 'authority_ready' }}
}}
function Renew-TicketboxC07RoleCredentialWindow {{
    param(
        $Authority,
        $SuperuserPassword,
        $RuntimePassword,
        $MigratorPassword,
        $MigratorValidUntilUtc,
        [string]$OperationId,
        [string]$Mode
    )
    $script:observedOperationIds.Add($OperationId)
}}
function Assert-TicketboxC07RoleCatalog {{ param($Authority, $Password) }}
function Get-TicketboxC07DatabaseIdentity {{
    param($Authority, $SuperuserPassword, $Database)
    return [pscustomobject]@{{ State = 'ready' }}
}}

$result = Initialize-TicketboxC07FreshDatabaseAuthority `
    -SuperuserPassword $null `
    -RuntimePassword $null `
    -MigratorPassword $null `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(5)) `
    -OperationId $historical
if ([string]$result.State -cne 'ready') {{
    throw 'fresh database authority did not complete the stubbed ready path'
}}
if (
    $script:observedOperationIds.Count -ne 2 -or
    $script:observedOperationIds[0] -cne $historical -or
    $script:observedOperationIds[1] -cne $historical
) {{
    throw 'fresh database authority changed the historical operation ID'
}}
"""
    _run_harness(tmp_path, "fresh-operation-guid", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell managed ACL contract")
def test_managed_schema_runtime_acl_is_opt_in_applied_and_attested(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
$baseSql = Get-TicketboxC07DatabasePrivilegeSql
$managedSql = Get-TicketboxC07DatabasePrivilegeSql `
    -IncludeManagedSchemaCurrencyAuthority
foreach ($table in @(
    'installation_currency_bindings',
    'installation_idempotency_keys',
    'installation_currency_audit_log'
)) {{
    if ($baseSql.Contains($table)) {{
        throw "managed table leaked into the frozen C07 ACL: $table"
    }}
    if (-not $managedSql.Contains($table)) {{
        throw "managed table missing from the post-upgrade ACL: $table"
    }}
}}
foreach ($required in @(
    "managed_binding_tables text[] := ARRAY['installation_currency_bindings']::text[];",
    "managed_authority_tables text[] := ARRAY['installation_idempotency_keys']::text[];",
    "managed_audit_insert_tables text[] := ARRAY['installation_currency_audit_log']::text[];"
)) {{
    if (-not $managedSql.Contains($required)) {{
        throw "managed ACL privilege class is not exact: $required"
    }}
}}
$password = [Security.SecureString]::new()
foreach ($character in ('not-a-real-secret-0123456789abcdef').ToCharArray()) {{
    $password.AppendChar($character)
}}
$script:applicationSql = ''
$script:attestationSql = ''
$script:attestationCalls = 0
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label
    )
    if ($Label -ceq 'managed schema exact runtime ACL application') {{
        $script:applicationSql = $Sql
        return ''
    }}
    if ($Label -ceq 'C07 structured runtime ACL attestation') {{
        $script:attestationSql = $Sql
        $script:attestationCalls += 1
        return "true`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue"
    }}
    throw "unexpected SQL call: $Label"
}}
Set-TicketboxManagedSchemaRuntimeAcl `
    -Authority ([pscustomobject]@{{ Schema = 'test-authority' }}) `
    -SuperuserPassword $password
if ($script:applicationSql -cne $managedSql -or $script:attestationCalls -ne 1) {{
    throw 'managed ACL was not applied and attested as one exact contract'
}}
$probeIndex = $script:attestationSql.IndexOf("'pg_catalog.pg_control_system()'")
if ($probeIndex -lt 0) {{
    throw 'runtime startup probe is absent from ACL attestation'
}}
$probePrefix = $script:attestationSql.Substring(
    [Math]::Max(0, $probeIndex - 160),
    [Math]::Min(160, $probeIndex)
)
if (
    -not $probePrefix.Contains('has_function_privilege(') -or
    $probePrefix.Contains('NOT has_function_privilege(')
) {{
    throw 'runtime startup probe grant and ACL attestation disagree'
}}
"""
    _run_harness(tmp_path, "managed-schema-runtime-acl", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell failure contract")
def test_sql_exit_three_is_transient_but_structured_acl_false_is_invariant(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
$password = [Security.SecureString]::new()
foreach ($character in ('not-a-real-secret-0123456789abcdef').ToCharArray()) {{
    $password.AppendChar($character)
}}
$authority = [pscustomobject]@{{ Schema = 'test-authority' }}
function Invoke-TicketboxC07SqlResult {{
    return [pscustomobject]@{{ ExitCode = 3; Output = '' }}
}}
$nativeFailure = $null
try {{
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database 'ticketbox' `
        -Role 'postgres' `
        -Password $password `
        -Sql 'SELECT 1' `
        -Label 'injected exit three' | Out-Null
}}
catch {{ $nativeFailure = $_.Exception }}
if ($null -eq $nativeFailure -or
    -not [string]::IsNullOrEmpty(
        [string]$nativeFailure.Data['TicketboxC07FailureClass']
    )) {{
    throw 'psql exit=3 was incorrectly treated as an invariant'
}}
function Invoke-TicketboxC07Sql {{
    return "true`ttrue`tfalse`ttrue`ttrue`ttrue`ttrue`ttrue"
}}
$aclFailure = $null
try {{
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $authority `
        -SuperuserPassword $password
}}
catch {{ $aclFailure = $_.Exception }}
if ($null -eq $aclFailure -or
    [string]$aclFailure.Data['TicketboxC07FailureClass'] -cne 'invariant' -or
    [string]$aclFailure.Data['TicketboxC07FailureCode'] -cne
        'runtime_acl_invariant_failed') {{
    throw (
        'structured ACL false did not produce the stable invariant contract: ' +
        [string]$aclFailure.Message + '; class=' +
        [string]$aclFailure.Data['TicketboxC07FailureClass'] + '; code=' +
        [string]$aclFailure.Data['TicketboxC07FailureCode']
    )
}}
function Invoke-TicketboxC07Sql {{
    return "true`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue"
}}
Assert-TicketboxC07RuntimeAclContract `
    -Authority $authority `
    -SuperuserPassword $password
"""
    _run_harness(tmp_path, "sql-failure-classification", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell coordinator contract")
def test_production_coordinator_typed_contracts_are_exact(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
$operation = '123e4567-e89b-42d3-a456-426614174000'
$source = '20260722_0001'
$target = '20260729_0001'
$upperA = 'A' * 64
$upperB = 'B' * 64
$upperC = 'C' * 64
$upperD = 'D' * 64
$upperE = 'E' * 64
$lowerA = 'a' * 64
$lowerB = 'b' * 64
$lowerC = 'c' * 64
$lowerD = 'd' * 64
$recovery = [pscustomobject]@{{
    ManifestSha256 = $lowerA
    DumpSha256 = $lowerB
    InventorySha256 = $lowerC
    CopiesSha256 = $lowerD
    MoneyFactsSha256 = ('7' * 64)
    ResourceShapeSha256 = ('8' * 64)
    RestoreEvidenceSha256 = ('9' * 64)
    IntegrityScope = 'acl_hash_only'
    ReleaseFingerprint = $upperD
    InstallationId = '223e4567-e89b-42d3-a456-426614174000'
    BuildManifestSha256 = $upperE
    BackendVersion = '0.3.0'
    RootAuthorityChainSha256 = $upperA
    RootFreezeProofSha256 = $upperB
    RootHeartbeatSequence = [int64]9
}}
$lifecycleInput = [pscustomobject][ordered]@{{
    schema = 'ticketbox-c07-production-lifecycle-binding-v2'
    operation_id = $operation
    root_authority_chain_sha256 = $upperA
    current_authority_chain_sha256 = $upperB
    current_receipt_payload_sha256 = $upperC
    current_stage = 'ddl_started'
    current_stage_sequence = [int64]4
    current_coordinator_binding_sha256 = $upperD
    current_coordinator_binding_sequence = [int64]2
    current_heartbeat_sequence = [int64]10
    current_freeze_proof_sha256 = $upperE
    recovery_manifest_sha256 = $lowerA.ToUpperInvariant()
    target_recovery_manifest_sha256 = '0' * 64
}}
$lifecycle = Assert-TicketboxC07ProductionLifecycleBinding `
    -LifecycleAuthority $lifecycleInput `
    -OperationId $operation `
    -Recovery $recovery `
    -ExpectedStage 'ddl_started' `
    -ExpectedStageSequence 4
if (
    $lifecycle.RootAuthorityChainSha256 -cne $upperA -or
    $lifecycle.CurrentCoordinatorBindingSequence -ne 2 -or
    $lifecycle.CurrentHeartbeatSequence -ne 10
) {{
    throw 'typed lifecycle authority binding was not preserved'
}}
$badLifecycle = [pscustomobject]@{{}}
foreach ($property in $lifecycleInput.PSObject.Properties) {{
    $badLifecycle | Add-Member -NotePropertyName $property.Name `
        -NotePropertyValue $property.Value
}}
$badLifecycle.root_authority_chain_sha256 = 'F' * 64
$badRejected = $false
try {{
    Assert-TicketboxC07ProductionLifecycleBinding `
        -LifecycleAuthority $badLifecycle `
        -OperationId $operation `
        -Recovery $recovery `
        -ExpectedStage 'ddl_started' `
        -ExpectedStageSequence 4 | Out-Null
}}
catch {{ $badRejected = $true }}
if (-not $badRejected) {{ throw 'lifecycle root drift was accepted' }}

$migrationEvidence = [pscustomobject][ordered]@{{
    schema = 'ticketbox-c07-migration-evidence-v1'
    operation_id = $operation
    source_revision = $source
    target_revision = $target
    result = 'target_committed'
    alembic_revision = $target
    money_facts_sha256 = ('7' * 64)
    statistics_table_count = 18
    statistics_table_set_sha256 = ('6' * 64)
}}
$migrationSha = Get-TicketboxC07MigrationEvidenceSha256 `
    -Evidence $migrationEvidence `
    -OperationId $operation `
    -ExpectedSourceRevision $source `
    -TargetRevision $target
if ($migrationSha -cnotmatch '^[0-9a-f]{{64}}$') {{
    throw 'migration evidence digest is not canonical'
}}
$catalog = [pscustomobject]@{{
    ClusterSystemIdentifier = '7123456789012345678'
    DatabaseOid = [uint32]4242
    Marker = ''
}}
$marker = New-TicketboxC07ProductionMarker `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -Phase 'migration_completed' `
    -Catalog $catalog `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryManifestSha256 $lowerA `
    -MigrationEvidenceSha256 $migrationSha
$catalog.Marker = $marker
$parsed = Assert-TicketboxC07ProductionMarker `
    -Catalog $catalog `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryManifestSha256 $lowerA
if (
    $parsed.Phase -cne 'migration_completed' -or
    $parsed.MigrationEvidenceSha256 -cne $migrationSha
) {{
    throw 'production durable marker did not preserve migration evidence'
}}
$databaseState = [pscustomobject]@{{
    ClusterSystemIdentifier = '7123456789012345678'
    DatabaseOid = [uint32]4242
    LogicalServerId = '323e4567-e89b-42d3-a456-426614174000'
    DataGeneration = '423e4567-e89b-42d3-a456-426614174000'
}}
$live = [pscustomobject]@{{
    LegacySessionCount = 0
    MigratorSessionCount = 0
    MigratorCanLogin = $false
    MigratorPasswordPresent = $false
}}
$result = New-TicketboxC07ProductionResult `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -Recovery $recovery `
    -DatabaseState $databaseState `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -MigrationEvidenceSha256 $migrationSha `
    -RoleAuthoritySha256 $lowerB `
    -RuntimeAclSha256 $lowerC `
    -Live $live `
    -LivePostconditionsSha256 $lowerD
$expectedProperties = @(
    'schema',
    'operation_id',
    'mode',
    'result',
    'recovery_manifest_sha256',
    'recovery_dump_sha256',
    'recovery_inventory_sha256',
    'recovery_copies_sha256',
    'integrity_scope',
    'cluster_system_identifier',
    'database_oid',
    'logical_server_id',
    'data_generation',
    'source_alembic_revision',
    'target_alembic_revision',
    'migration_evidence_sha256',
    'money_facts_sha256',
    'resource_shape_sha256',
    'role_authority_sha256',
    'runtime_acl_sha256',
    'legacy_session_count',
    'migrator_session_count',
    'migrator_can_login',
    'migrator_password_present',
    'live_postconditions_sha256',
    'target_restore_evidence_sha256'
)
$actualProperties = @($result.PSObject.Properties.Name)
if (
    ($actualProperties -join '|') -cne ($expectedProperties -join '|') -or
    $result.schema -cne 'ticketbox-c07-production-authority-result-v2' -or
    $result.result -cne 'production_authority_ready' -or
    $result.migrator_session_count -ne 0 -or
    $result.migrator_can_login
) {{
    throw 'production coordinator result schema drifted'
}}
$command = Get-Command Invoke-TicketboxC07ProductionAuthorityCoordinator
foreach ($parameterName in @('RecoveryGeneration', 'LifecycleAuthority', 'MigrationAction')) {{
    $parameter = $command.Parameters[$parameterName]
    if ($null -eq $parameter -or -not $parameter.Attributes.Mandatory) {{
        throw "production coordinator parameter is not mandatory: $parameterName"
    }}
}}
"""
    _run_harness(tmp_path, "production-coordinator-contract", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell coordinator flow")
def test_production_coordinator_runs_migrator_once_and_rebinds_takeover(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
function New-TestSecureString([char]$Character) {{
    $value = New-Object Security.SecureString
    foreach ($index in 1..32) {{ $value.AppendChar($Character) }}
    $value.MakeReadOnly()
    return $value
}}
$superuserSecret = New-TestSecureString 'S'
$runtimeSecret = New-TestSecureString 'R'
$migratorSecret = New-TestSecureString 'M'
$operation = '123e4567-e89b-42d3-a456-426614174000'
$source = '20260722_0001'
$target = '20260729_0001'
$script:revision = $source
$script:retired = $false
$script:migrationCalls = 0
$script:markerWrites = 0
$script:renewalCalls = 0
$script:activeRoleCatalogCalls = 0
$script:retiredRoleCatalogCalls = 0
$script:credentialWindowExpired = $false
$script:allowRetiredRenewal = $false
$script:expectedTargetRecoveryOperation = $operation
$script:catalog = [pscustomobject]@{{
    ClusterSystemIdentifier = '7123456789012345678'
    Database = 'ticketbox'
    DatabaseOid = [uint32]4242
    OwnerRoleOid = [uint32]5001
    AllowsConnections = $true
    Marker = ''
    Exists = $true
}}
$script:recovery = [pscustomobject]@{{
    ManifestSha256 = 'a' * 64
    DumpSha256 = 'b' * 64
    InventorySha256 = 'c' * 64
    CopiesSha256 = 'd' * 64
    MoneyFactsSha256 = '7' * 64
    IntegrityScope = 'acl_hash_only'
    ReleaseFingerprint = 'e' * 64
    InstallationId = '223e4567-e89b-42d3-a456-426614174000'
    BuildManifestSha256 = 'f' * 64
    BackendVersion = '0.3.0'
    RootAuthorityChainSha256 = 'A' * 64
    RootFreezeProofSha256 = 'B' * 64
    RootHeartbeatSequence = [int64]9
}}
$script:targetRecovery = [pscustomobject]@{{
    ManifestSha256 = '9' * 64
    DumpSha256 = '8' * 64
    InventorySha256 = '7' * 64
    CopiesSha256 = '6' * 64
    MoneyFactsSha256 = '5' * 64
    ResourceShapeSha256 = '4' * 64
    RestoreEvidenceSha256 = '3' * 64
    IntegrityScope = 'acl_hash_only'
}}
function New-TestLifecycleBinding(
    [string]$CurrentChain,
    [bool]$TargetRecoveryReady = $false
) {{
    return [pscustomobject][ordered]@{{
        schema = 'ticketbox-c07-production-lifecycle-binding-v2'
        operation_id = $operation
        root_authority_chain_sha256 = 'A' * 64
        current_authority_chain_sha256 = $CurrentChain
        current_receipt_payload_sha256 = 'C' * 64
        current_stage = if ($TargetRecoveryReady) {{
            'target_isolated_restore_verified'
        }} else {{ 'ddl_started' }}
        current_stage_sequence = if ($TargetRecoveryReady) {{
            [int64]7
        }} else {{ [int64]4 }}
        current_coordinator_binding_sha256 = 'D' * 64
        current_coordinator_binding_sequence = [int64]2
        current_heartbeat_sequence = [int64]10
        current_freeze_proof_sha256 = 'E' * 64
        recovery_manifest_sha256 = ('a' * 64).ToUpperInvariant()
        target_recovery_manifest_sha256 = if ($TargetRecoveryReady) {{
            ('9' * 64).ToUpperInvariant()
        }} else {{ '0' * 64 }}
    }}
}}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        Port = 5544
        PsqlPath = 'C:\\protected\\psql.exe'
        PgData = 'C:\\protected\\pgdata'
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
}}
function Get-TicketboxC07ProductionDatabaseState {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
    return [pscustomobject]@{{
        ClusterSystemIdentifier = '7123456789012345678'
        DatabaseOid = [uint32]4242
        LogicalServerId = '323e4567-e89b-42d3-a456-426614174000'
        DataGeneration = '423e4567-e89b-42d3-a456-426614174000'
        AlembicRevision = $script:revision
    }}
}}
function Assert-TicketboxC07ProductionRecoveryBinding {{
    param(
        [object]$RecoveryGeneration,
        [string]$OperationId,
        [string]$ExpectedSourceRevision,
        [object]$DatabaseState
    )
    return $script:recovery
}}
function Assert-TicketboxC07ProductionTargetRecoveryBinding {{
    param(
        [object]$TargetRecoveryGeneration,
        [string]$OperationId,
        [string]$TargetRevision,
        [object]$DatabaseState
    )
    if (
        $OperationId -cne $script:expectedTargetRecoveryOperation -or
        $TargetRevision -cne $target -or
        $DatabaseState.AlembicRevision -cne $target
    ) {{ throw 'target recovery was not bound to live target' }}
    if (
        $null -ne $script:historicalTargetRecovery -and
        $OperationId -ceq $script:predecessorOperation
    ) {{ return $script:historicalTargetRecovery }}
    return $script:targetRecovery
}}
function Get-TicketboxC07DatabaseBootstrapCatalog {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Database
    )
    return $script:catalog
}}
function Initialize-TicketboxC07FreshDatabaseAuthority {{
    param(
        [Security.SecureString]$SuperuserPassword,
        [Security.SecureString]$RuntimePassword,
        [Security.SecureString]$MigratorPassword,
        [DateTime]$MigratorValidUntilUtc,
        [string]$OperationId
    )
}}
function Get-TicketboxC07RoleBootstrapIdentity {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$OperationId,
        [string]$Mode
    )
    return [pscustomobject]@{{
        OwnerRoleOid = [uint32]5001
        MigratorRoleOid = [uint32]5002
        RuntimeRoleOid = [uint32]5003
    }}
}}
function Assert-TicketboxC07DatabaseMarker {{
    param(
        [object]$Catalog,
        [string]$OperationId,
        [string]$Mode,
        [object]$Roles,
        [uint32]$LegacyRoleOid
    )
    return 'authority_ready'
}}
function Set-TicketboxC07DatabaseMarker {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Database,
        [string]$Marker,
        [string]$Label
    )
    $script:catalog.Marker = $Marker
    $script:markerWrites += 1
}}
function Get-TicketboxC07MigratorRetirementState {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
    return [pscustomobject]@{{
        IsActive = -not $script:retired
        IsRetired = $script:retired
    }}
}}
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    if ($Label -ceq 'C07 retired role catalog verification') {{
        if (-not $script:retired) {{
            throw 'retired role catalog was verified before migrator retirement'
        }}
        if (
            $Sql -notmatch 'NOT rolcanlogin' -or
            $Sql -notmatch 'rolpassword IS NULL' -or
            $Sql -notmatch "ticketbox_migrator',\\s*'ticketbox',\\s*'CONNECT'" -or
            $Sql -match 'rolvaliduntil\\s*>' -or
            $Sql -match 'count\\(\\*\\)\\s*=\\s*1'
        ) {{
            throw 'retired role catalog SQL revived the active migrator contract'
        }}
        $script:retiredRoleCatalogCalls += 1
        return (@('true') * 15) -join "`t"
    }}
    return ''
}}
function Assert-TicketboxC07RoleCatalog {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
    $script:activeRoleCatalogCalls += 1
    if ($script:retired) {{
        throw 'active TTL/LOGIN role catalog verifier reached retired state'
    }}
}}
function Assert-TicketboxC07RoleCredentials {{
    param(
        [object]$Authority,
        [Security.SecureString]$RuntimePassword,
        [Security.SecureString]$MigratorPassword
    )
    if ($script:credentialWindowExpired) {{
        throw 'expired migrator credential reached authenticated probe'
    }}
}}
function Renew-TicketboxC07RoleCredentialWindow {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [Security.SecureString]$RuntimePassword,
        [Security.SecureString]$MigratorPassword,
        [DateTime]$MigratorValidUntilUtc,
        [string]$OperationId,
        [string]$Mode
    )
    if (
        -not [object]::ReferenceEquals($RuntimePassword, $runtimeSecret) -or
        -not [object]::ReferenceEquals($MigratorPassword, $migratorSecret) -or
        $OperationId -cne $operation -or
        $Mode -cne 'fresh_install' -or
        ($script:retired -and -not $script:allowRetiredRenewal)
    ) {{
        throw 'credential renewal lost authority or revived a retired role'
    }}
    if ($script:retired) {{ $script:retired = $false }}
    $script:renewalCalls += 1
    $script:credentialWindowExpired = $false
}}
function Test-TicketboxC07DatabaseRoleMatrix {{
    param(
        [Security.SecureString]$SuperuserPassword,
        [Security.SecureString]$RuntimePassword,
        [Security.SecureString]$MigratorPassword,
        [string]$OperationId
    )
}}
function Assert-TicketboxC07RuntimeAclContract {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
}}
function Get-TicketboxC07RoleAuthoritySha256 {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
    if ($script:retired) {{ return '2' * 64 }}
    return '1' * 64
}}
function Get-TicketboxC07RuntimeAclSha256 {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
    if ($script:retired) {{ return '4' * 64 }}
    return '3' * 64
}}
function Disable-TicketboxC07MigratorLogin {{
    param(
        [Security.SecureString]$SuperuserPassword,
        [string]$OperationId,
        [string]$Mode
    )
    $script:retired = $true
}}
function Get-TicketboxC07ProductionLiveState {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Mode
    )
    return [pscustomobject]@{{
        LegacySessionCount = 0
        MigratorSessionCount = 0
        MigratorCanLogin = $false
        MigratorPasswordPresent = $false
    }}
}}
function Assert-TicketboxC07RuntimeCredential {{
    param([object]$Authority, [Security.SecureString]$RuntimePassword)
}}
$recoveryGeneration = [pscustomobject]@{{ Payload = [pscustomobject]@{{}} }}
$migrationAction = {{
    param($HostAuthority, $MigratorPassword, $ExpectedSource, $ExpectedTarget)
    if (
        $args.Count -ne 0 -or
        $HostAuthority.Schema -cne 'ticketbox-c07-host-db-authority-v1' -or
        $HostAuthority.Port -ne 5544 -or
        -not [object]::ReferenceEquals($MigratorPassword, $migratorSecret) -or
        $ExpectedSource -cne $source -or
        $ExpectedTarget -cne $target
    ) {{
        throw 'MigrationAction received runtime credential or unbound authority'
    }}
    $script:migrationCalls += 1
    $script:revision = $target
    return [pscustomobject][ordered]@{{
        schema = 'ticketbox-c07-migration-evidence-v2'
        operation_id = $operation
        source_revision = $source
        target_revision = $target
        result = 'target_committed'
        alembic_revision = $target
        resource_shape_sha256 = ('4' * 64)
        money_facts_sha256 = ('7' * 64)
        statistics_table_count = 18
        statistics_table_set_sha256 = ('6' * 64)
    }}
}}
$first = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('B' * 64)) `
    -MigrationAction $migrationAction `
    -StopAfterMigrationCompleted
if (
    $first.result -cne 'target_committed' -or
    $script:migrationCalls -ne 1 -or
    $script:renewalCalls -ne 1 -or
    $script:retired
) {{
    throw 'DDL phase did not stop at exact durable target commit'
}}
$targetRecoveryGeneration = [pscustomobject]@{{ Payload = [pscustomobject]@{{}} }}
$ready = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -TargetRecoveryGeneration $targetRecoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('B' * 64) $true) `
    -MigrationAction $migrationAction
if (
    $ready.result -cne 'production_authority_ready' -or
    $script:migrationCalls -ne 1 -or
    $script:renewalCalls -ne 2 -or
    -not $script:retired -or
    $ready.target_restore_evidence_sha256 -cne ('3' * 64)
) {{
    throw 'post-DDL recovery phase did not close production authority'
}}
$writesBeforePrecommittedValidation = $script:markerWrites
$renewalsBeforePrecommittedValidation = $script:renewalCalls
$retiredCatalogsBeforePrecommittedValidation =
    $script:retiredRoleCatalogCalls
$validated = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -TargetRecoveryGeneration $targetRecoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('F' * 64) $true) `
    -MigrationAction $migrationAction `
    -ExpectedProductionResult $ready
if (
    $validated.live_postconditions_sha256 -cne
        $ready.live_postconditions_sha256 -or
    $script:migrationCalls -ne 1 -or
    $script:renewalCalls -ne $renewalsBeforePrecommittedValidation -or
    $script:markerWrites -ne $writesBeforePrecommittedValidation -or
    $script:retiredRoleCatalogCalls -ne
        ($retiredCatalogsBeforePrecommittedValidation + 1)
) {{
    throw 'precommitted production validation mutated durable authority'
}}
$mutated = $ready | Select-Object *
$mutated.role_authority_sha256 = '9' * 64
$mutationFailure = $null
try {{
    Invoke-TicketboxC07ProductionAuthorityCoordinator `
        -SuperuserPassword $superuserSecret `
        -RuntimePassword $runtimeSecret `
        -MigratorPassword $migratorSecret `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
        -OperationId $operation `
        -Mode 'fresh_install' `
        -ExpectedSourceRevision $source `
        -TargetRevision $target `
        -RecoveryGeneration $recoveryGeneration `
        -TargetRecoveryGeneration $targetRecoveryGeneration `
        -LifecycleAuthority (New-TestLifecycleBinding ('F' * 64) $true) `
        -MigrationAction $migrationAction `
        -ExpectedProductionResult $mutated | Out-Null
}}
catch {{ $mutationFailure = $_.Exception }}
if (
    $null -eq $mutationFailure -or
    [string]$mutationFailure.Data['TicketboxC07FailureClass'] -cne 'invariant' -or
    [string]$mutationFailure.Data['TicketboxC07FailureCode'] -cne
        'runtime_acl_invariant_failed' -or
    $script:migrationCalls -ne 1 -or
    $script:markerWrites -ne $writesBeforePrecommittedValidation
) {{
    throw 'mutated precommitted production authority did not fail closed'
}}
$writesAfterFirst = $script:markerWrites
$second = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -TargetRecoveryGeneration $targetRecoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('F' * 64) $true) `
    -MigrationAction $migrationAction
if (
    $second.result -cne 'production_authority_ready' -or
    $script:migrationCalls -ne 1 -or
    $script:renewalCalls -ne 2 -or
    $script:markerWrites -ne ($writesAfterFirst + 1)
) {{
    throw 'takeover re-entry reran DDL or failed to rebind READY evidence'
}}

$script:retired = $false
$script:credentialWindowExpired = $true
$script:catalog.Marker = New-TicketboxC07ProductionMarker `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -Phase 'migration_started' `
    -Catalog $script:catalog `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryManifestSha256 $script:recovery.ManifestSha256
$script:shapeVerifierCalls = 0
$shapeRejectingAction = {{
    param($HostAuthority, $MigratorPassword, $ExpectedSource, $ExpectedTarget)
    $script:shapeVerifierCalls += 1
    throw 'injected target money-shape mismatch'
}}
$writesBeforeShapeRejection = $script:markerWrites
$shapeRejected = $false
try {{
    Invoke-TicketboxC07ProductionAuthorityCoordinator `
        -SuperuserPassword $superuserSecret `
        -RuntimePassword $runtimeSecret `
        -MigratorPassword $migratorSecret `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
        -OperationId $operation `
        -Mode 'fresh_install' `
        -ExpectedSourceRevision $source `
        -TargetRevision $target `
        -RecoveryGeneration $recoveryGeneration `
        -LifecycleAuthority (New-TestLifecycleBinding ('7' * 64)) `
        -MigrationAction $shapeRejectingAction `
        -StopAfterMigrationCompleted | Out-Null
}}
catch {{
    if ($_.Exception.Message -notmatch 'money-shape mismatch') {{ throw }}
    $shapeRejected = $true
}}
if (
    -not $shapeRejected -or
    $script:shapeVerifierCalls -ne 1 -or
    $script:markerWrites -ne $writesBeforeShapeRejection
) {{
    throw 'target revision bypassed frozen shape verifier before migration_completed'
}}
$renewalsBeforeTargetObserved = $script:renewalCalls
$migrationsBeforeTargetObserved = $script:migrationCalls
$targetObserved = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('7' * 64)) `
    -MigrationAction $migrationAction `
    -StopAfterMigrationCompleted
if (
    $targetObserved.result -cne 'target_committed' -or
    $script:renewalCalls -ne ($renewalsBeforeTargetObserved + 1) -or
    $script:migrationCalls -ne ($migrationsBeforeTargetObserved + 1) -or
    $script:retired -or
    $script:credentialWindowExpired
) {{
    throw 'target-observed replay did not renew, validate shape, and converge'
}}
$renewalsAfterTargetObserved = $script:renewalCalls
$script:credentialWindowExpired = $true
$readyTargetReplay = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('7' * 64)) `
    -MigrationAction $migrationAction `
    -StopAfterMigrationCompleted
if (
    $readyTargetReplay.result -cne 'target_committed' -or
    $script:renewalCalls -ne ($renewalsAfterTargetObserved + 1) -or
    $script:retired
) {{
    throw 'READY replay renewed or revived the retired migrator'
}}

$script:retired = $false
$script:credentialWindowExpired = $true
$script:catalog.Marker = New-TicketboxC07ProductionMarker `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -Phase 'migration_completed' `
    -Catalog $script:catalog `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryManifestSha256 $script:recovery.ManifestSha256 `
    -MigrationEvidenceSha256 $first.migration_evidence_sha256
$renewalsBeforeCompleted = $script:renewalCalls
$migrationsBeforeCompleted = $script:migrationCalls
$completedReplay = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('8' * 64)) `
    -MigrationAction $migrationAction `
    -StopAfterMigrationCompleted
if (
    $completedReplay.result -cne 'target_committed' -or
    $script:renewalCalls -ne ($renewalsBeforeCompleted + 1) -or
    $script:migrationCalls -ne ($migrationsBeforeCompleted + 1) -or
    $script:retired -or
    $script:credentialWindowExpired
) {{
    throw 'migration-completed expired replay did not renew and converge'
}}
$renewalsAfterCompleted = $script:renewalCalls
$script:credentialWindowExpired = $true
$readyCompletedReplay = Invoke-TicketboxC07ProductionAuthorityCoordinator `
    -SuperuserPassword $superuserSecret `
    -RuntimePassword $runtimeSecret `
    -MigratorPassword $migratorSecret `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryGeneration $recoveryGeneration `
    -LifecycleAuthority (New-TestLifecycleBinding ('8' * 64)) `
    -MigrationAction $migrationAction `
    -StopAfterMigrationCompleted
if (
    $readyCompletedReplay.result -cne 'target_committed' -or
    $script:renewalCalls -ne ($renewalsAfterCompleted + 1) -or
    $script:retired
) {{
    throw 'migration-completed READY replay revived the retired migrator'
}}

# A predecessor may durably publish a tail DB marker and then fail before the
# host lifecycle publishes READY.  A new immutable successor must validate the
# old target recovery and marker, transfer only to its own migration_started,
# and run the target-observed verifier without replaying source DDL.
$script:predecessorOperation = '523e4567-e89b-42d3-a456-426614174000'
$script:historicalTargetRecovery = [pscustomobject]@{{
    ManifestSha256 = '9' * 64
    DumpSha256 = '8' * 64
    InventorySha256 = '7' * 64
    CopiesSha256 = '6' * 64
    MoneyFactsSha256 = '7' * 64
    ResourceShapeSha256 = '4' * 64
    RestoreEvidenceSha256 = '3' * 64
    IntegrityScope = 'acl_hash_only'
}}
function New-TestForwardIntent([string]$MarkerSha256) {{
    return [pscustomobject]@{{
        Payload = [pscustomobject]@{{
            schema = 'ticketbox-c07-successor-intent-v2'
            successor_operation_id = $operation
            successor_mode = 'forward_repair'
            predecessor_operation_id = $script:predecessorOperation
            predecessor_terminal_stage = 'repair_required'
            predecessor_production_marker_sha256 = $MarkerSha256
            live_alembic_revision = $target
        }}
    }}
}}
foreach ($tailCase in @(
    [pscustomobject]@{{ Phase = 'runtime_acl_verified'; Retired = $false }},
    [pscustomobject]@{{ Phase = 'runtime_acl_verified'; Retired = $true }},
    [pscustomobject]@{{ Phase = 'production_ready'; Retired = $true }}
)) {{
    $tailPhase = [string]$tailCase.Phase
    $script:revision = $target
    $script:retired = [bool]$tailCase.Retired
    $script:allowRetiredRenewal = $true
    $script:expectedTargetRecoveryOperation = $script:predecessorOperation
    $oldMigrationSha256 = '5' * 64
    $oldRoleSha256 = if ($tailPhase -ceq 'production_ready') {{
        '2' * 64
    }} else {{ '1' * 64 }}
    $oldAclSha256 = if ($tailPhase -ceq 'production_ready') {{
        '4' * 64
    }} else {{ '3' * 64 }}
    $oldLiveSha256 = if ($tailPhase -ceq 'production_ready') {{
        '8' * 64
    }} else {{ '' }}
    $script:catalog.Marker = New-TicketboxC07ProductionMarker `
        -OperationId $script:predecessorOperation `
        -Mode 'fresh_install' `
        -Phase $tailPhase `
        -Catalog $script:catalog `
        -ExpectedSourceRevision $source `
        -TargetRevision $target `
        -RecoveryManifestSha256 $script:historicalTargetRecovery.ManifestSha256 `
        -MigrationEvidenceSha256 $oldMigrationSha256 `
        -RoleAuthoritySha256 $oldRoleSha256 `
        -RuntimeAclSha256 $oldAclSha256 `
        -LivePostconditionsSha256 $oldLiveSha256
    $intent = New-TestForwardIntent (
        (Get-TicketboxC07DatabaseTextSha256 $script:catalog.Marker).ToUpperInvariant()
    )
    $predecessorTarget = [pscustomobject]@{{
        Payload = [pscustomobject]@{{
            lifecycle = [pscustomobject]@{{
                migration_evidence_sha256 = $oldMigrationSha256
            }}
        }}
    }}
    $writesBeforeTail = $script:markerWrites
    $migrationsBeforeTail = $script:migrationCalls
    $retiredCatalogsBeforeTail = $script:retiredRoleCatalogCalls
    $tailResult = Invoke-TicketboxC07ProductionAuthorityCoordinator `
        -SuperuserPassword $superuserSecret `
        -RuntimePassword $runtimeSecret `
        -MigratorPassword $migratorSecret `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
        -OperationId $operation `
        -Mode 'fresh_install' `
        -ExpectedSourceRevision $source `
        -TargetRevision $target `
        -RecoveryGeneration $recoveryGeneration `
        -PredecessorTargetRecoveryGeneration $predecessorTarget `
        -LifecycleAuthority (New-TestLifecycleBinding ('9' * 64)) `
        -MigrationAction $migrationAction `
        -SuccessorIntent $intent `
        -StopAfterMigrationCompleted
    $tailMarkerParts = @(([string]$script:catalog.Marker).Split([char]'|'))
    if (
        $tailResult.result -cne 'target_committed' -or
        $script:migrationCalls -ne ($migrationsBeforeTail + 1) -or
        $script:markerWrites -ne ($writesBeforeTail + 2) -or
        $script:retiredRoleCatalogCalls -ne (
            $retiredCatalogsBeforeTail +
            $(if ($tailCase.Retired) {{ 1 }} else {{ 0 }})
        ) -or
        $tailMarkerParts[1] -cne $operation -or
        $tailMarkerParts[3] -cne 'migration_completed'
    ) {{
        throw "$tailPhase/$($tailCase.Retired) predecessor tail did not converge through successor target observation"
    }}
}}

# An exact intent hash mismatch must fail before marker mutation or target
# observation.  This covers tampering between successor authorization and the
# durable operation transfer.
$script:revision = $target
$script:retired = $false
$script:allowRetiredRenewal = $true
$oldMigrationSha256 = '5' * 64
$script:catalog.Marker = New-TicketboxC07ProductionMarker `
    -OperationId $script:predecessorOperation `
    -Mode 'fresh_install' `
    -Phase 'runtime_acl_verified' `
    -Catalog $script:catalog `
    -ExpectedSourceRevision $source `
    -TargetRevision $target `
    -RecoveryManifestSha256 $script:historicalTargetRecovery.ManifestSha256 `
    -MigrationEvidenceSha256 $oldMigrationSha256 `
    -RoleAuthoritySha256 ('1' * 64) `
    -RuntimeAclSha256 ('3' * 64)
$tamperedIntent = New-TestForwardIntent ('F' * 64)
$predecessorTarget = [pscustomobject]@{{
    Payload = [pscustomobject]@{{
        lifecycle = [pscustomobject]@{{
            migration_evidence_sha256 = $oldMigrationSha256
        }}
    }}
}}
$writesBeforeTamper = $script:markerWrites
$migrationsBeforeTamper = $script:migrationCalls
$tamperRejected = $false
try {{
    Invoke-TicketboxC07ProductionAuthorityCoordinator `
        -SuperuserPassword $superuserSecret `
        -RuntimePassword $runtimeSecret `
        -MigratorPassword $migratorSecret `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
        -OperationId $operation `
        -Mode 'fresh_install' `
        -ExpectedSourceRevision $source `
        -TargetRevision $target `
        -RecoveryGeneration $recoveryGeneration `
        -PredecessorTargetRecoveryGeneration $predecessorTarget `
        -LifecycleAuthority (New-TestLifecycleBinding ('A' * 64)) `
        -MigrationAction $migrationAction `
        -SuccessorIntent $tamperedIntent `
        -StopAfterMigrationCompleted | Out-Null
}}
catch {{
    if ($_.Exception.Message -notmatch 'immutable intent') {{ throw }}
    $tamperRejected = $true
}}
if (
    -not $tamperRejected -or
    $script:markerWrites -ne $writesBeforeTamper -or
    $script:migrationCalls -ne $migrationsBeforeTamper
) {{
    throw 'tampered predecessor marker intent mutated DB state'
}}

# Marker phase/hash mixing must fail closed even when every individual digest
# is syntactically valid.
$mixedParts = @(([string]$script:catalog.Marker).Split([char]'|'))
$mixedParts[12] = '6' * 64
$script:catalog.Marker = [string]::Join('|', $mixedParts)
$mixedIntent = New-TestForwardIntent (
    (Get-TicketboxC07DatabaseTextSha256 $script:catalog.Marker).ToUpperInvariant()
)
$mixedRejected = $false
try {{
    Invoke-TicketboxC07ProductionAuthorityCoordinator `
        -SuperuserPassword $superuserSecret `
        -RuntimePassword $runtimeSecret `
        -MigratorPassword $migratorSecret `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
        -OperationId $operation `
        -Mode 'fresh_install' `
        -ExpectedSourceRevision $source `
        -TargetRevision $target `
        -RecoveryGeneration $recoveryGeneration `
        -PredecessorTargetRecoveryGeneration $predecessorTarget `
        -LifecycleAuthority (New-TestLifecycleBinding ('B' * 64)) `
        -MigrationAction $migrationAction `
        -SuccessorIntent $mixedIntent `
        -StopAfterMigrationCompleted | Out-Null
}}
catch {{
    if ($_.Exception.Message -notmatch 'phase/hash shape') {{ throw }}
    $mixedRejected = $true
}}
if (-not $mixedRejected) {{
    throw 'mixed-phase predecessor marker was accepted'
}}
"""
    _run_harness(tmp_path, "production-coordinator-flow", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell role contract")
def test_scram_uuid_and_missing_legacy_authority_fail_closed(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'

function New-TestSecureString([char]$Character) {{
    $value = New-Object Security.SecureString
    foreach ($index in 1..32) {{ $value.AppendChar($Character) }}
    $value.MakeReadOnly()
    return $value
}}
$secretText = 'A' * 32
$secret = New-TestSecureString 'A'
$verifier = ConvertTo-TicketboxC07ScramVerifier `
    -Password $secret `
    -Salt ([byte[]](0..15))
$expected = 'SCRAM-SHA-256$4096:AAECAwQFBgcICQoLDA0ODw==$' +
    '355HF2woQrDOhRxNERGHA3h4zRZKzRmQ0VrawXpeRxQ=:' +
    'scGvEICb0PIcJDvEa8hxDlCgyBzb2cWy3JRZ0MSW52Q='
if ($verifier -cne $expected -or $verifier.Contains($secretText)) {{
    throw 'SCRAM verifier contract mismatch or plaintext leak'
}}

$operation = '123e4567-e89b-42d3-a456-426614174000'
$attempt = '223e4567-e89b-42d3-a456-426614174000'
$otherAttempt = '323e4567-e89b-42d3-a456-426614174000'
$expectedName = Get-TicketboxC07RestoreDatabaseName `
    -OperationId $operation `
    -CreateAttemptId $attempt
$otherName = Get-TicketboxC07RestoreDatabaseName `
    -OperationId $operation `
    -CreateAttemptId $otherAttempt
if (
    $expectedName -cnotmatch '^ticketbox_c07_restore_[0-9a-f]{{40}}$' -or
    $expectedName -ceq $otherName -or
    $expectedName -ceq (Get-TicketboxC07LegacyRestoreDatabaseName $operation)
) {{
    throw 'restore database name was not bound to operation plus create attempt'
}}
$injectionRejected = $false
try {{
    Get-TicketboxC07RestoreDatabaseName `
        -OperationId '123e4567-e89b-42d3-a456-426614174000";DROP DATABASE ticketbox;--' `
        -CreateAttemptId $attempt
}}
catch {{ $injectionRejected = $true }}
if (-not $injectionRejected) {{ throw 'database-name injection was accepted' }}

$script:hostReads = 0
$script:sqlCalls = 0
function Resolve-TicketboxC07DatabaseHostAuthority {{
    $script:hostReads++
    throw 'host resolver must not run without authority'
}}
function Invoke-TicketboxC07Sql {{
    $script:sqlCalls++
    throw 'SQL must not run without authority'
}}
$missingRejected = $false
try {{
    Invoke-TicketboxC07LegacyDatabaseAdoption `
        -SuperuserPassword $null `
        -RuntimePassword $secret `
        -MigratorPassword $secret `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) | Out-Null
}}
catch {{ $missingRejected = $true }}
if (-not $missingRejected -or $script:hostReads -ne 0 -or $script:sqlCalls -ne 0) {{
    throw 'legacy adoption without protected authority was not zero-mutation'
}}
"""
    _run_harness(tmp_path, "scram-uuid-legacy-denial", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell phase contract")
def test_fresh_and_legacy_database_phase_markers_bind_live_role_oids(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
$operation = '123e4567-e89b-42d3-a456-426614174000'
$otherOperation = '223e4567-e89b-42d3-a456-426614174000'
$roles = [pscustomobject]@{{
    Exists = $true
    OwnerRoleOid = [uint32]5001
    MigratorRoleOid = [uint32]5002
    RuntimeRoleOid = [uint32]5003
}}
$fresh = [pscustomobject]@{{
    Exists = $true
    ClusterSystemIdentifier = '7123456789012345678'
    DatabaseOid = [uint32]4242
    OwnerRoleOid = [uint32]5001
    AllowsConnections = $false
    Marker = ''
}}
$fresh.Marker = New-TicketboxC07DatabaseMarker `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -Phase 'database_created' `
    -Catalog $fresh `
    -Roles $roles
$phase = Assert-TicketboxC07DatabaseMarker `
    -Catalog $fresh `
    -OperationId $operation `
    -Mode 'fresh_install' `
    -Roles $roles
if ($phase -cne 'database_created') {{
    throw 'fresh phase was not reusable'
}}
$foreignRejected = $false
try {{
    Assert-TicketboxC07DatabaseMarker `
        -Catalog $fresh `
        -OperationId $otherOperation `
        -Mode 'fresh_install' `
        -Roles $roles | Out-Null
}}
catch {{ $foreignRejected = $true }}
if (-not $foreignRejected) {{
    throw 'fresh database marker accepted another operation'
}}

$legacyOid = [uint32]4001
$legacy = [pscustomobject]@{{
    Exists = $true
    ClusterSystemIdentifier = '7123456789012345678'
    DatabaseOid = [uint32]4242
    OwnerRoleOid = $legacyOid
    AllowsConnections = $true
    Marker = ''
}}
$legacy.Marker = New-TicketboxC07DatabaseMarker `
    -OperationId $operation `
    -Mode 'legacy_adoption' `
    -Phase 'roles_created' `
    -Catalog $legacy `
    -Roles $roles `
    -LegacyRoleOid $legacyOid
$phase = Assert-TicketboxC07DatabaseMarker `
    -Catalog $legacy `
    -OperationId $operation `
    -Mode 'legacy_adoption' `
    -Roles $roles `
    -LegacyRoleOid $legacyOid
if ($phase -cne 'roles_created') {{
    throw 'legacy roles_created phase was not reusable'
}}
$legacy.OwnerRoleOid = [uint32]5001
$stalePhaseRejected = $false
try {{
    Assert-TicketboxC07DatabaseMarker `
        -Catalog $legacy `
        -OperationId $operation `
        -Mode 'legacy_adoption' `
        -Roles $roles `
        -LegacyRoleOid $legacyOid | Out-Null
}}
catch {{ $stalePhaseRejected = $true }}
if (-not $stalePhaseRejected) {{
    throw 'legacy roles_created marker survived an owner transition'
}}
$legacy.Marker = New-TicketboxC07DatabaseMarker `
    -OperationId $operation `
    -Mode 'legacy_adoption' `
    -Phase 'objects_reassigned' `
    -Catalog $legacy `
    -Roles $roles `
    -LegacyRoleOid $legacyOid
$phase = Assert-TicketboxC07DatabaseMarker `
    -Catalog $legacy `
    -OperationId $operation `
    -Mode 'legacy_adoption' `
    -Roles $roles `
    -LegacyRoleOid $legacyOid
if ($phase -cne 'objects_reassigned') {{
    throw 'legacy objects_reassigned phase was not reusable'
}}
"""
    _run_harness(tmp_path, "fresh-legacy-phase-identity", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell SCM contract")
def test_host_authority_is_derived_from_scm_and_postmaster_pid(
    tmp_path: Path,
) -> None:
    pg_data = tmp_path / "managed" / "pgdata"
    pg_bin = tmp_path / "program" / "pg" / "bin"
    pg_data.mkdir(parents=True)
    pg_bin.mkdir(parents=True)
    pg_ctl = pg_bin / "pg_ctl.exe"
    psql = pg_bin / "psql.exe"
    pg_ctl.write_bytes(b"stub")
    psql.write_bytes(b"stub")
    (pg_data / "postmaster.pid").write_text(
        f"4321\n{pg_data}\n0\n5544\n",
        encoding="ascii",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'

$script:imageArguments = @(
    '{_ps_literal(pg_ctl)}', 'runservice', '-N', 'TicketboxPg',
    '-D', '{_ps_literal(pg_data)}', '-w'
)
function Test-TicketboxServiceExists([string]$Name) {{ return $Name -ceq 'TicketboxPg' }}
function Assert-TicketboxServiceAccount {{
    param([string]$Name, [string]$ExpectedAccount)
    if ($Name -cne 'TicketboxPg' -or $ExpectedAccount -cne 'NT SERVICE\\TicketboxPg') {{
        throw 'service account contract mismatch'
    }}
}}
function Get-TicketboxServiceImagePath([string]$Name) {{ return 'host-owned-image-path' }}
function Split-TicketboxWindowsCommandLine([string]$CommandLine) {{
    return $script:imageArguments
}}
function ConvertTo-TicketboxFullPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path)
}}
function Assert-TicketboxPgServiceCommand {{
    param(
        [string]$Name,
        [string]$ExpectedExecutable,
        [string]$ExpectedServiceName,
        [string]$ExpectedDataRoot
    )
    if ($Name -cne 'TicketboxPg' -or $ExpectedServiceName -cne 'TicketboxPg') {{
        throw 'SCM command validation was not called'
    }}
}}
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{}}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    return 'Missing'
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left),
        [IO.Path]::GetFullPath($Right),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Get-TicketboxServiceProcessId([string]$Name) {{ return 9876 }}

$authority = Resolve-TicketboxC07DatabaseHostAuthority
if (
    $authority.ServiceName -cne 'TicketboxPg' -or
    $authority.ServiceProcessId -ne 9876 -or
    $authority.PostmasterProcessId -ne 4321 -or
    $authority.Port -ne 5544 -or
    -not (Test-TicketboxPathEquals $authority.PgData '{_ps_literal(pg_data)}') -or
    -not (Test-TicketboxPathEquals $authority.PsqlPath '{_ps_literal(psql)}')
) {{
    throw 'host authority accepted caller data or failed to derive SCM data'
}}
"""
    _run_harness(tmp_path, "host-authority", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell restore contract")
def test_restore_cleanup_rejects_oid_replacement_and_is_reentrant(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
function New-TestSecureString([char]$Character) {{
    $value = New-Object Security.SecureString
    foreach ($index in 1..32) {{ $value.AppendChar($Character) }}
    $value.MakeReadOnly()
    return $value
}}
$secret = New-TestSecureString 'B'
$operation = '123e4567-e89b-42d3-a456-426614174000'
$attempt = '323e4567-e89b-42d3-a456-426614174000'
$otherAttempt = '423e4567-e89b-42d3-a456-426614174000'
$database = Get-TicketboxC07RestoreDatabaseName `
    -OperationId $operation `
    -CreateAttemptId $attempt
$identity = [pscustomobject]@{{
    Schema = 'ticketbox-c07-restore-db-v2'
    OperationId = $operation
    ClusterSystemIdentifier = '7123456789012345678'
    Database = $database
    DatabaseOid = [uint32]4242
    OwnerRoleOid = [uint32]5001
    MigratorRoleOid = [uint32]5002
    MarkerPhase = 'active'
    State = 'active'
    CreateAttemptId = $attempt
}}
$script:liveIdentity = $null
$script:liveCatalog = $null
$script:dropCalls = 0
$script:latchCalls = 0
$script:dropExitCode = 0
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{ Schema = 'ticketbox-c07-host-db-authority-v1'; Port = 5544 }}
}}
function Assert-TicketboxC07LiveHostConnection {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
}}
function Get-TicketboxC07DatabaseIdentity {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Database
    )
    return $script:liveIdentity
}}
function Get-TicketboxC07DatabaseBootstrapCatalog {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Database
    )
    return $script:liveCatalog
}}
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    if ($Label -cne 'C07 isolated restore cleanup latch') {{
        throw 'unexpected cleanup SQL call'
    }}
    if (
        $Sql -cnotmatch 'cleanup_pending' -or
        $Sql -cnotmatch 'ALLOW_CONNECTIONS false'
    ) {{
        throw 'cleanup latch omitted durable phase or connection fence'
    }}
    $script:latchCalls++
    return ''
}}
function Invoke-TicketboxC07SqlResult {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    if ($Sql -cne 'DROP DATABASE "' + $identity.Database + '" WITH (FORCE);') {{
        throw 'cleanup did not use the exact derived database name'
    }}
    $script:dropCalls++
    return [pscustomobject]@{{ ExitCode = $script:dropExitCode; Output = '' }}
}}

$script:liveIdentity = [pscustomobject]@{{
    ClusterSystemIdentifier = $identity.ClusterSystemIdentifier
    Database = $identity.Database
    DatabaseOid = [uint32]9999
    Exists = $true
}}
$replacedRejected = $false
try {{
    Remove-TicketboxC07RestoreDatabaseExact `
        -SuperuserPassword $secret `
        -Identity $identity `
        -CreateAttemptId $attempt | Out-Null
}}
catch {{ $replacedRejected = $true }}
if (-not $replacedRejected -or $script:dropCalls -ne 0) {{
    throw 'same-name database with a replacement OID was deleted'
}}

$script:liveIdentity = [pscustomobject]@{{
    ClusterSystemIdentifier = $identity.ClusterSystemIdentifier
    Database = $identity.Database
    DatabaseOid = [uint32]4242
    Exists = $true
}}
$script:liveCatalog = [pscustomobject]@{{
    ClusterSystemIdentifier = $identity.ClusterSystemIdentifier
    Database = $identity.Database
    DatabaseOid = [uint32]4242
    OwnerRoleOid = [uint32]5001
    AllowsConnections = $true
    Marker = (
        'ticketbox-c07-restore-database-v2|' + $operation +
        '|active|7123456789012345678|' + $database + '|4242|5001|5002'
    )
    Exists = $true
}}
$legacyRejected = $false
try {{
    Remove-TicketboxC07RestoreDatabaseExact `
        -SuperuserPassword $secret `
        -Identity $identity `
        -CreateAttemptId $attempt | Out-Null
}}
catch {{
    $legacyRejected = $_.Exception.Message -match 'legacy restore marker v2'
}}
if (
    -not $legacyRejected -or
    $script:latchCalls -ne 0 -or
    $script:dropCalls -ne 0
) {{
    throw 'legacy attempt-less marker was upgraded, adopted, or deleted'
}}

$script:liveCatalog.Marker = (
    'ticketbox-c07-restore-database-v3|' + $operation + '|' + $otherAttempt +
    '|active|7123456789012345678|' + $database + '|4242|5001|5002'
)
$wrongAttemptRejected = $false
try {{
    Remove-TicketboxC07RestoreDatabaseExact `
        -SuperuserPassword $secret `
        -Identity $identity `
        -CreateAttemptId $attempt | Out-Null
}}
catch {{ $wrongAttemptRejected = $true }}
if (
    -not $wrongAttemptRejected -or
    $script:latchCalls -ne 0 -or
    $script:dropCalls -ne 0
) {{
    throw 'different create-attempt marker reached destructive cleanup'
}}

$script:liveCatalog.Marker = (
    'ticketbox-c07-restore-database-v3|' + $operation + '|' + $attempt +
    '|active|7123456789012345678|' + $database + '|4242|5001|5002'
)
$script:dropExitCode = 1
$pending = Remove-TicketboxC07RestoreDatabaseExact `
    -SuperuserPassword $secret `
    -Identity $identity `
    -CreateAttemptId $attempt
if (
    $pending.State -cne 'cleanup_pending' -or
    $pending.MarkerPhase -cne 'cleanup_pending' -or
    $script:latchCalls -ne 1 -or
    $script:dropCalls -ne 1
) {{
    throw 'failed exact cleanup did not become cleanup_pending'
}}

$script:liveIdentity = [pscustomobject]@{{
    ClusterSystemIdentifier = $identity.ClusterSystemIdentifier
    Database = $identity.Database
    DatabaseOid = [uint32]0
    Exists = $false
}}
$cleaned = Remove-TicketboxC07RestoreDatabaseExact `
    -SuperuserPassword $secret `
    -Identity $pending `
    -CreateAttemptId $attempt
if (
    $cleaned.State -cne 'cleaned' -or
    $script:latchCalls -ne 1 -or
    $script:dropCalls -ne 1
) {{
    throw 'cleanup_pending re-entry was not idempotent'
}}
"""
    _run_harness(tmp_path, "restore-exact-cleanup", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell restore contract")
def test_restore_creation_registers_before_open_and_reuses_exact_operation(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
function New-TestSecureString([char]$Character) {{
    $value = New-Object Security.SecureString
    foreach ($index in 1..32) {{ $value.AppendChar($Character) }}
    $value.MakeReadOnly()
    return $value
}}
$secret = New-TestSecureString 'D'
$operation = '123e4567-e89b-42d3-a456-426614174000'
$installation = '223e4567-e89b-42d3-a456-426614174000'
$attempt = '323e4567-e89b-42d3-a456-426614174000'
$database = Get-TicketboxC07RestoreDatabaseName `
    -OperationId $operation `
    -CreateAttemptId $attempt
$generationSha = 'a' * 64
$operationKind = 'c07_money_minor_bigint_v1'
$targetRevision = '20260729_0001'
$revisionManifestSha256 = 'E' * 64
$authoritySha = Get-TicketboxC07DatabaseTextSha256 (
    @(
        'schema=ticketbox-c07-recovery-restore-create-intent-v1',
        "operation_id=$operation",
        "operation_kind=$operationKind",
        "target_alembic_revision=$targetRevision",
        "revision_manifest_sha256=$revisionManifestSha256",
        "installation_id=$installation",
        'cluster_system_identifier=7123456789012345678',
        "database=$database",
        "attempt_id=$attempt",
        "generation_payload_sha256=$generationSha",
        'integrity_scope=acl_hash_only'
    ) -join "`n"
)
$createIntent = [pscustomobject]@{{
    Payload = [pscustomobject]@{{
        schema = 'ticketbox-c07-recovery-restore-create-intent-v1'
        operation_id = $operation
        operation_kind = $operationKind
        target_alembic_revision = $targetRevision
        revision_manifest_sha256 = $revisionManifestSha256
        installation_id = $installation
        cluster_system_identifier = '7123456789012345678'
        database = $database
        attempt_id = $attempt
        generation_payload_sha256 = $generationSha
        create_authority_sha256 = $authoritySha
        database_oid = ''
        state = 'create_pending'
        integrity_scope = 'acl_hash_only'
        updated_at_utc = '2026-07-30T00:00:00.0000000+00:00'
    }}
    PayloadSha256 = 'b' * 64
    CreateAuthoritySha256 = $authoritySha
    AttemptId = $attempt
    Path = 'C:\\protected\\restore-create-intent.json'
}}
$script:restoreDatabase = $database
$script:catalog = [pscustomobject]@{{
    ClusterSystemIdentifier = '7123456789012345678'
    Database = $database
    Exists = $false
}}
$script:labels = @()
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{ Schema = 'ticketbox-c07-host-db-authority-v1'; Port = 5544 }}
}}
function Assert-TicketboxC07LiveHostConnection {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
}}
function Get-TicketboxC07RoleOid {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Role,
        [switch]$AllowAbsent
    )
    if ($Role -ceq 'ticketbox_owner') {{ return [uint32]5001 }}
    if ($Role -ceq 'ticketbox_migrator') {{ return [uint32]5002 }}
    throw 'unexpected role OID lookup'
}}
function Get-TicketboxC07DatabaseBootstrapCatalog {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Database
    )
    return $script:catalog
}}
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    $script:labels += $Label
    if ($Label -ceq 'C07 restore attempt namespace inspect') {{
        if ($script:catalog.Exists) {{
            return [string]$script:catalog.Database
        }}
        return ''
    }}
    elseif ($Label -ceq 'C07 unregistered restore attempt fence inspect') {{
        return "true`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue"
    }}
    elseif ($Label -ceq 'C07 isolated restore database create') {{
        if ($Sql -cnotmatch 'ALLOW_CONNECTIONS false') {{
            throw 'restore database was exposed during creation'
        }}
        $script:catalog = [pscustomobject]@{{
            ClusterSystemIdentifier = '7123456789012345678'
            Database = $script:restoreDatabase
            DatabaseOid = [uint32]4242
            OwnerRoleOid = [uint32]5001
            AllowsConnections = $false
            Marker = ''
            Exists = $true
        }}
    }}
    elseif ($Label -ceq 'C07 isolated restore exact identity registration') {{
        if ($script:catalog.AllowsConnections -or $Sql -cnotmatch 'registered') {{
            throw 'restore identity was not registered while connection-fenced'
        }}
        $script:catalog.Marker = (
            'ticketbox-c07-restore-database-v3|' + $operation + '|' + $attempt +
            '|registered|7123456789012345678|' + $script:restoreDatabase +
            '|4242|5001|5002'
        )
    }}
    elseif ($Label -ceq 'C07 isolated restore ACL/open transaction') {{
        if (
            $script:catalog.Marker -cnotmatch '\\|registered\\|' -or
            $Sql -cnotmatch 'REVOKE ALL ON DATABASE' -or
            $Sql -cnotmatch 'foreign_grantee' -or
            $Sql -cnotmatch 'foreign active session' -or
            $Sql -cmatch 'GRANT CONNECT ON DATABASE' -or
            $Sql -cnotmatch 'ALLOW_CONNECTIONS true'
        ) {{
            throw 'restore database opened before registration/ACL hardening'
        }}
        $script:catalog.Marker = (
            'ticketbox-c07-restore-database-v3|' + $operation + '|' + $attempt +
            '|active|7123456789012345678|' + $script:restoreDatabase +
            '|4242|5001|5002'
        )
        $script:catalog.AllowsConnections = $true
    }}
    elseif ($Label -ceq 'C07 isolated restore database ACL verification') {{
        return "true`ttrue`ttrue`ttrue`ttrue"
    }}
    else {{
        throw "unexpected SQL label: $Label"
    }}
    return ''
}}

$crashObserved = $false
try {{
    New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $secret `
        -OperationId $operation `
        -CreateIntent $createIntent `
        -OperationKind $operationKind `
        -TargetAlembicRevision $targetRevision `
        -RevisionManifestSha256 $revisionManifestSha256 `
        -AfterCreateCrashProbe {{
            param([string]$CreatedDatabase, [string]$CreateAttemptId)
            if (
                $CreatedDatabase -cne $database -or
                $CreateAttemptId -cne $attempt
            ) {{
                throw 'crash probe lost exact create identity'
            }}
            throw 'injected process crash after CREATE acknowledgement'
        }} | Out-Null
}}
catch {{
    $crashObserved =
        $_.Exception.Message -eq 'injected process crash after CREATE acknowledgement'
}}
if (
    -not $crashObserved -or
    -not $script:catalog.Exists -or
    -not [string]::IsNullOrEmpty([string]$script:catalog.Marker) -or
    $script:catalog.AllowsConnections -or
    @(
        $script:labels |
            Where-Object {{ $_ -ceq 'C07 isolated restore database create' }}
    ).Count -ne 1 -or
    @(
        $script:labels |
            Where-Object {{
                $_ -in @(
                    'C07 isolated restore exact identity registration',
                    'C07 isolated restore ACL/open transaction'
                )
            }}
    ).Count -ne 0
) {{
    throw 'CREATE-to-marker crash cut did not preserve exact fenced residue'
}}
$script:labels = @()
$first = New-TicketboxC07RestoreDatabase `
    -SuperuserPassword $secret `
    -OperationId $operation `
    -CreateIntent $createIntent `
    -OperationKind $operationKind `
    -TargetAlembicRevision $targetRevision `
    -RevisionManifestSha256 $revisionManifestSha256
if (
    $first.Schema -cne 'ticketbox-c07-restore-db-v2' -or
    $first.DatabaseOid -ne 4242 -or
    $first.OwnerRoleOid -ne 5001 -or
    $first.MigratorRoleOid -ne 5002 -or
    $first.MarkerPhase -cne 'active'
) {{
    throw 'restore identity omitted exact database/role authority'
}}
$firstMutationLabels = @(
    $script:labels | Where-Object {{
        $_ -in @(
            'C07 isolated restore database create',
            'C07 isolated restore exact identity registration',
            'C07 isolated restore ACL/open transaction'
        )
    }}
)
if (
    $firstMutationLabels.Count -ne 2 -or
    $firstMutationLabels[0] -cne 'C07 isolated restore exact identity registration' -or
    $firstMutationLabels[1] -cne 'C07 isolated restore ACL/open transaction'
) {{
    throw 'restore create/register/open ordering changed'
}}

$labelCount = $script:labels.Count
$second = New-TicketboxC07RestoreDatabase `
    -SuperuserPassword $secret `
    -OperationId $operation `
    -CreateIntent $createIntent `
    -OperationKind $operationKind `
    -TargetAlembicRevision $targetRevision `
    -RevisionManifestSha256 $revisionManifestSha256
$secondLabels = @($script:labels[$labelCount..($script:labels.Count - 1)])
$secondMutationLabels = @(
    $secondLabels | Where-Object {{
        $_ -in @(
            'C07 isolated restore database create',
            'C07 isolated restore exact identity registration',
            'C07 isolated restore ACL/open transaction'
        )
    }}
)
if (
    $second.DatabaseOid -ne $first.DatabaseOid -or
    $second.MarkerPhase -cne 'active' -or
    $secondMutationLabels.Count -ne 0 -or
    -not ($secondLabels -contains 'C07 restore attempt namespace inspect') -or
    $script:labels[-1] -cne 'C07 isolated restore database ACL verification'
) {{
    throw 'exact same-operation restore residue was not reused read-only'
}}
"""
    _run_harness(tmp_path, "restore-create-reentry", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell restore contract")
def test_restore_creation_rejects_unmarked_preexisting_database_without_mutation(
    tmp_path: Path,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
function New-TestSecureString([char]$Character) {{
    $value = New-Object Security.SecureString
    foreach ($index in 1..32) {{ $value.AppendChar($Character) }}
    $value.MakeReadOnly()
    return $value
}}
$secret = New-TestSecureString 'D'
$operation = '123e4567-e89b-42d3-a456-426614174000'
$installation = '223e4567-e89b-42d3-a456-426614174000'
$attempt = '323e4567-e89b-42d3-a456-426614174000'
$database = Get-TicketboxC07RestoreDatabaseName `
    -OperationId $operation `
    -CreateAttemptId $attempt
$generationSha = 'a' * 64
$operationKind = 'c07_money_minor_bigint_v1'
$targetRevision = '20260729_0001'
$revisionManifestSha256 = 'E' * 64
$authoritySha = Get-TicketboxC07DatabaseTextSha256 (
    @(
        'schema=ticketbox-c07-recovery-restore-create-intent-v1',
        "operation_id=$operation",
        "operation_kind=$operationKind",
        "target_alembic_revision=$targetRevision",
        "revision_manifest_sha256=$revisionManifestSha256",
        "installation_id=$installation",
        'cluster_system_identifier=7123456789012345678',
        "database=$database",
        "attempt_id=$attempt",
        "generation_payload_sha256=$generationSha",
        'integrity_scope=acl_hash_only'
    ) -join "`n"
)
$createIntent = [pscustomobject]@{{
    Payload = [pscustomobject]@{{
        schema = 'ticketbox-c07-recovery-restore-create-intent-v1'
        operation_id = $operation
        operation_kind = $operationKind
        target_alembic_revision = $targetRevision
        revision_manifest_sha256 = $revisionManifestSha256
        installation_id = $installation
        cluster_system_identifier = '7123456789012345678'
        database = $database
        attempt_id = $attempt
        generation_payload_sha256 = $generationSha
        create_authority_sha256 = $authoritySha
        database_oid = ''
        state = 'create_pending'
        integrity_scope = 'acl_hash_only'
        updated_at_utc = '2026-07-30T00:00:00.0000000+00:00'
    }}
    PayloadSha256 = 'b' * 64
    CreateAuthoritySha256 = $authoritySha
    AttemptId = $attempt
    Path = 'C:\\protected\\restore-create-intent.json'
}}
$script:mutations = 0
$script:sqlCalls = 0
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{ Schema = 'ticketbox-c07-host-db-authority-v1'; Port = 5544 }}
}}
function Assert-TicketboxC07LiveHostConnection {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
}}
function Get-TicketboxC07RoleOid {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Role,
        [switch]$AllowAbsent
    )
    $script:sqlCalls += 1
    if ($Role -ceq 'ticketbox_owner') {{ return [uint32]5001 }}
    if ($Role -ceq 'ticketbox_migrator') {{ return [uint32]5002 }}
    throw 'unexpected role OID lookup'
}}
function Get-TicketboxC07DatabaseBootstrapCatalog {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Database
    )
    $script:sqlCalls += 1
    return [pscustomobject]@{{
        ClusterSystemIdentifier = '7123456789012345678'
        Database = $database
        DatabaseOid = [uint32]4242
        OwnerRoleOid = [uint32]5001
        AllowsConnections = $false
        Marker = ''
        Exists = $true
    }}
}}
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    $script:sqlCalls += 1
    if ($Label -ceq 'C07 restore attempt namespace inspect') {{
        return [string]$createIntent.Payload.database
    }}
    if ($Label -ceq 'C07 unregistered restore attempt fence inspect') {{
        return "true`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`tfalse"
    }}
    $script:mutations += 1
    throw 'unsafe markerless database must not be mutated'
}}

$missingIntentRejected = $false
try {{
    New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $secret `
        -OperationId $operation `
        -OperationKind $operationKind `
        -TargetAlembicRevision $targetRevision `
        -RevisionManifestSha256 $revisionManifestSha256 | Out-Null
}}
catch {{
    $missingIntentRejected = $_.Exception.Message -match 'CreateIntent'
}}
if (-not $missingIntentRejected -or $script:sqlCalls -ne 0) {{
    throw 'missing protected create-intent reached SQL authority'
}}

$originalOperation = $createIntent.Payload.operation_id
$createIntent.Payload.operation_id = '423e4567-e89b-42d3-a456-426614174000'
$wrongOperationRejected = $false
try {{
    New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $secret `
        -OperationId $operation `
        -CreateIntent $createIntent `
        -OperationKind $operationKind `
        -TargetAlembicRevision $targetRevision `
        -RevisionManifestSha256 $revisionManifestSha256 | Out-Null
}}
catch {{ $wrongOperationRejected = $true }}
$createIntent.Payload.operation_id = $originalOperation

$originalDatabase = $createIntent.Payload.database
$createIntent.Payload.database = 'ticketbox_c07_restore_wrong'
$wrongDatabaseRejected = $false
try {{
    New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $secret `
        -OperationId $operation `
        -CreateIntent $createIntent `
        -OperationKind $operationKind `
        -TargetAlembicRevision $targetRevision `
        -RevisionManifestSha256 $revisionManifestSha256 | Out-Null
}}
catch {{ $wrongDatabaseRejected = $true }}
$createIntent.Payload.database = $originalDatabase

$originalAuthority = $createIntent.Payload.create_authority_sha256
$createIntent.Payload.create_authority_sha256 = 'c' * 64
$createIntent.CreateAuthoritySha256 = 'c' * 64
$wrongHashRejected = $false
try {{
    New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $secret `
        -OperationId $operation `
        -CreateIntent $createIntent `
        -OperationKind $operationKind `
        -TargetAlembicRevision $targetRevision `
        -RevisionManifestSha256 $revisionManifestSha256 | Out-Null
}}
catch {{ $wrongHashRejected = $true }}
$createIntent.Payload.create_authority_sha256 = $originalAuthority
$createIntent.CreateAuthoritySha256 = $originalAuthority

$createIntent.Payload.cluster_system_identifier = '8123456789012345678'
$wrongClusterAuthority = Get-TicketboxC07DatabaseTextSha256 (
    @(
        'schema=ticketbox-c07-recovery-restore-create-intent-v1',
        "operation_id=$operation",
        "operation_kind=$operationKind",
        "target_alembic_revision=$targetRevision",
        "revision_manifest_sha256=$revisionManifestSha256",
        "installation_id=$installation",
        'cluster_system_identifier=8123456789012345678',
        "database=$database",
        "attempt_id=$attempt",
        "generation_payload_sha256=$generationSha",
        'integrity_scope=acl_hash_only'
    ) -join "`n"
)
$createIntent.Payload.create_authority_sha256 = $wrongClusterAuthority
$createIntent.CreateAuthoritySha256 = $wrongClusterAuthority
$wrongClusterRejected = $false
try {{
    New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $secret `
        -OperationId $operation `
        -CreateIntent $createIntent `
        -OperationKind $operationKind `
        -TargetAlembicRevision $targetRevision `
        -RevisionManifestSha256 $revisionManifestSha256 | Out-Null
}}
catch {{ $wrongClusterRejected = $_.Exception.Message -match 'cluster authority' }}
$createIntent.Payload.cluster_system_identifier = '7123456789012345678'
$createIntent.Payload.create_authority_sha256 = $originalAuthority
$createIntent.CreateAuthoritySha256 = $originalAuthority
if (
    -not $wrongOperationRejected -or
    -not $wrongDatabaseRejected -or
    -not $wrongHashRejected -or
    -not $wrongClusterRejected -or
    $script:mutations -ne 0
) {{
    throw 'invalid protected create-intent reached restore mutation'
}}

$rejected = $false
try {{
    New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $secret `
        -OperationId $operation `
        -CreateIntent $createIntent `
        -OperationKind $operationKind `
        -TargetAlembicRevision $targetRevision `
        -RevisionManifestSha256 $revisionManifestSha256 | Out-Null
}}
catch {{
    $rejected = $_.Exception.Message -match 'exact attempt'
}}
if (-not $rejected -or $script:mutations -ne 0) {{
    throw 'unmarked pre-existing database was adopted or mutated'
}}
"""
    _run_harness(tmp_path, "restore-unmarked-preexisting-rejected", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell role probe")
def test_role_matrix_emits_dml_and_denial_sql_contract(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
function New-TestSecureString([char]$Character) {{
    $value = New-Object Security.SecureString
    foreach ($index in 1..32) {{ $value.AppendChar($Character) }}
    $value.MakeReadOnly()
    return $value
}}
$secret = New-TestSecureString 'C'
$script:calls = @()
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{ Schema = 'ticketbox-c07-host-db-authority-v1'; Port = 5544 }}
}}
function Assert-TicketboxC07LiveHostConnection {{
    param([object]$Authority, [Security.SecureString]$SuperuserPassword)
}}
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    $script:calls += [pscustomobject]@{{ Role = $Role; Sql = $Sql; Label = $Label }}
    return ''
}}
Test-TicketboxC07DatabaseRoleMatrix `
    -SuperuserPassword $secret `
    -RuntimePassword $secret `
    -MigratorPassword $secret `
    -OperationId '123e4567-e89b-42d3-a456-426614174000'
if ($script:calls.Count -ne 7) {{ throw 'unexpected role probe call count' }}
$runtimeDml = @($script:calls | Where-Object {{ $_.Label -ceq 'C07 runtime DML matrix' }})
$runtimeDdl = @($script:calls | Where-Object {{ $_.Label -ceq 'C07 runtime DDL denial matrix' }})
$futureDenial = @(
    $script:calls |
        Where-Object {{ $_.Label -ceq 'C07 future authority and routine denial matrix' }}
)
$migrator = @($script:calls | Where-Object {{ $_.Label -ceq 'C07 migrator SET LOCAL ROLE matrix' }})
if (
    $runtimeDml.Count -ne 1 -or
    $runtimeDml[0].Role -cne 'ticketbox_runtime' -or
    $runtimeDml[0].Sql -cnotmatch 'public.accounts' -or
    $runtimeDml[0].Sql -cnotmatch 'INSERT INTO' -or
    $runtimeDml[0].Sql -cnotmatch 'UPDATE public' -or
    $runtimeDml[0].Sql -cnotmatch 'pg_catalog.pg_control_system' -or
    $runtimeDml[0].Sql -cnotmatch 'pg_catalog.shobj_description' -or
    $runtimeDml[0].Sql -cnotmatch 'DELETE FROM' -or
    $runtimeDdl.Count -ne 1 -or
    $runtimeDdl[0].Sql -cnotmatch 'insufficient_privilege' -or
    $runtimeDdl[0].Sql -cnotmatch 'CREATE TABLE' -or
    $runtimeDdl[0].Sql -cnotmatch 'ALTER TABLE' -or
    $runtimeDdl[0].Sql -cnotmatch 'DROP TABLE' -or
    $futureDenial.Count -ne 1 -or
    $futureDenial[0].Sql -cnotmatch 'SECURITY DEFINER EXECUTE unexpectedly succeeded' -or
    $futureDenial[0].Sql -cnotmatch 'app_meta DELETE unexpectedly succeeded' -or
    $futureDenial[0].Sql -cnotmatch 'schema_migrations UPDATE unexpectedly succeeded' -or
    $futureDenial[0].Sql -cnotmatch 'alembic_version UPDATE unexpectedly succeeded' -or
    $futureDenial[0].Sql -cnotmatch 'append-only fact % UPDATE unexpectedly succeeded' -or
    $futureDenial[0].Sql -cnotmatch 'append-only fact % DELETE unexpectedly succeeded' -or
    $futureDenial[0].Sql -cnotmatch 'append-only fact % TRUNCATE unexpectedly succeeded' -or
    $migrator.Count -ne 1 -or
    $migrator[0].Role -cne 'ticketbox_migrator' -or
    $migrator[0].Sql -cnotmatch 'SET LOCAL ROLE "ticketbox_owner"'
) {{
    throw 'role matrix omitted a required emitted PostgreSQL permission probe'
}}
"""
    _run_harness(tmp_path, "role-matrix", script)
