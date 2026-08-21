import re
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
SOURCE = PACKAGING / "windows_database_generation_source.ps1"
CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"


def _function(source: str, name: str) -> str:
    match = re.search(rf"(?m)^function {re.escape(name)}\s*\{{", source)
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


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_preinstall_eligibility_is_read_only_and_fails_closed(tmp_path: Path) -> None:
    eligibility = _function(
        CONTRACT.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxDatabaseGenerationPreinstallEligibility",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:active = $null
$script:current = $null
$script:services = @{{}}
$script:pathKinds = @{{}}
$script:writes = 0
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Read-TicketboxDatabaseGenerationActiveIntent {{ param($Root, [switch]$AllowAbsent); return $script:active }}
function Read-TicketboxDatabaseGenerationCurrent {{ param([switch]$AllowAbsent); return $script:current }}
function Test-TicketboxServiceExists {{ param($Name); return [bool]$script:services[$Name] }}
function Get-TicketboxPathEntryKindNoFollow {{
    param($Path)
    if ($script:pathKinds.ContainsKey([string]$Path)) {{ return $script:pathKinds[[string]$Path] }}
    return 'Missing'
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join "`n") -cne ($expected -join "`n")) {{ throw 'open path fact' }}
}}
function New-TicketboxDatabaseGenerationIntent {{ $script:writes += 1 }}
function Start-Service {{ $script:writes += 1 }}
function Remove-Item {{ $script:writes += 1 }}
{eligibility}
if (-not (Get-Command Assert-TicketboxDatabaseGenerationPreinstallEligibility).Parameters.ContainsKey('LifecycleEvidence')) {{
    throw 'preinstall eligibility lacks closed lifecycle authority'
}}
$lock = [pscustomobject]@{{ Identity = 'held' }}
$facts = @([pscustomobject][ordered]@{{ Path = 'pgdata\\PG_VERSION'; Label = 'PG_VERSION' }})
$lifecycle = [pscustomobject][ordered]@{{
    schema = 'ticketbox-database-generation-lifecycle-evidence-v1'
    receipt_present = $false
    install_completed = $false
    operation_id = ''
    current_sha256 = ''
}}

Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $false $lifecycle $facts
if ($script:writes -ne 0) {{ throw 'empty classification mutated state' }}

$script:services['pg'] = $true
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $false $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'existing service crossed eligibility gate' }}
$script:services.Clear()

$script:pathKinds['pgdata\\PG_VERSION'] = 'File'
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $false $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'existing PGDATA crossed eligibility gate' }}
$script:pathKinds.Clear()

$operation = '11111111-1111-4111-8111-111111111111'
$script:active = [pscustomobject]@{{ PayloadSha256 = ('a' * 64); Payload = [pscustomobject]@{{ operation_id = $operation }} }}
$script:current = [pscustomobject]@{{ PayloadSha256 = ('b' * 64); Payload = [pscustomobject]@{{ operation_id = $operation; intent_sha256 = ('a' * 64) }} }}
$lifecycle.receipt_present = $true
$lifecycle.operation_id = $operation
Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts
if ($script:writes -ne 0) {{ throw 'exact retry mutated state' }}

$lifecycle.current_sha256 = ('b' * 64)
$beforeRetry = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts
$afterRetry = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
if ($beforeRetry -cne $afterRetry -or $script:writes -ne 0) {{ throw 'exact bound retry mutated authority' }}

$savedCurrent = $script:current
$script:current = $null
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'receipt-bound missing CURRENT crossed eligibility gate' }}
$script:current = $savedCurrent

$lifecycle.operation_id = '33333333-3333-4333-8333-333333333333'
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'foreign lifecycle receipt crossed eligibility gate' }}
$lifecycle.operation_id = $operation

$lifecycle.current_sha256 = ('c' * 64)
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'foreign lifecycle CURRENT crossed eligibility gate' }}
$lifecycle.current_sha256 = ('b' * 64)

$lifecycle.install_completed = $true
$beforeCompleted = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
$afterCompleted = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
if (-not $rejected -or $beforeCompleted -cne $afterCompleted -or $script:writes -ne 0) {{ throw 'completed install crossed fresh-only eligibility gate' }}

$lifecycle.install_completed = $false
$script:current.Payload.operation_id = '22222222-2222-4222-8222-222222222222'
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'foreign CURRENT crossed eligibility gate' }}
"""
    path = tmp_path / "database-generation-preinstall-eligibility.ps1"
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


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_empty_source_classification_is_zero_write_and_operation_bound(
    tmp_path: Path,
) -> None:
    source_text = SOURCE.read_text(encoding="utf-8-sig")
    normalize = _function(
        source_text,
        "Invoke-TicketboxDatabaseGenerationEmptySource",
    )
    role_sql = _function(source_text, "New-TicketboxDatabaseGenerationEmptyRoleSql")
    sql_literal = _function(
        (PACKAGING / "windows_postgresql_database_command.ps1").read_text(
            encoding="utf-8-sig"
        ),
        "ConvertTo-TicketboxPostgresqlSqlLiteral",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:writes = 0
$script:nonempty = $false
$script:attempt = $null
$script:target = $null
function Assert-TicketboxDatabaseGenerationMaintenanceAuthority {{ param($Authority, $Intent, $HostAuthority, $Lock); return $Authority }}
function Read-TicketboxDatabaseGenerationOperationArtifact {{ param($Root, $Operation, $Kind, [switch]$AllowAbsent); return $script:attempt }}
function New-TicketboxDatabaseGenerationChainedArtifact {{ $script:writes += 1; return $script:attempt }}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{
        DatabaseName = 'ticketbox'
        OwnerRole = 'ticketbox_owner'
        MigratorRole = 'ticketbox_migrator'
        RuntimeRole = 'ticketbox_runtime'
        RetiredLegacyRole = 'ticketbox'
    }}
}}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{
    param($Authority, $SuperuserPassword, $TargetDatabase)
    if ($TargetDatabase -ceq 'ticketbox') {{ return $script:target }}
    return [pscustomobject]@{{
        Exists = $false; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]0
        OwnerRoleOid = [uint32]0; Comment = ''; AllowsConnections = $false
    }}
}}
function Get-TicketboxDatabaseRoleOid {{
    param($Authority, $SuperuserPassword, $RoleName)
    return [uint32]77
}}
function Assert-TicketboxDatabaseGenerationEmptySchema {{ if ($script:nonempty) {{ throw 'nonempty' }} }}
{sql_literal}
{role_sql}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    param($Authority, $Database, $Role, $Password, [string]$Label, [string]$Sql)
    $script:writes += 1
    if ($Label -ceq 'database generation empty-source ACL attestation') {{
        if ($Sql -cne 'DO ticketbox empty ACL guard;') {{ throw 'empty ACL guard drifted' }}
        $script:emptyAclAttested = $true
    }}
}}
function New-TicketboxDatabaseRuntimeAclSql {{ return 'SELECT 1;' }}
function New-TicketboxDatabaseForeignAclGuardSql {{ return 'DO ticketbox empty ACL guard;' }}
function Assert-TicketboxDatabaseCredential {{}}
function Assert-TicketboxDatabaseRolePolicy {{}}
function Assert-TicketboxDatabaseRuntimeAcl {{ throw 'full table ACL asserted before migration' }}
function Get-TicketboxDatabaseGenerationFrozenFence {{ return [ordered]@{{ state = 'frozen' }} }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); return ($Value | ConvertTo-Json -Compress) }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('f' * 64) }}
{normalize}
$operation = '11111111-1111-4111-8111-111111111111'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = $operation }}
}}
$migratorSecret = New-Object Security.SecureString
$migratorSecret.AppendChar('m')
$superuserSecret = New-Object Security.SecureString
$superuserSecret.AppendChar('s')
$credentials = [pscustomobject]@{{
    RuntimeVerifier = 'SCRAM-SHA-256$4096:x'; MigratorVerifier = 'SCRAM-SHA-256$4096:y'
    MigratorPassword = $migratorSecret
}}
$maintenanceAuthority = [pscustomobject]@{{ Secret = $superuserSecret }}
$roleBootstrapSql = New-TicketboxDatabaseGenerationEmptyRoleSql `
    -OperationId $operation `
    -RuntimeVerifier $credentials.RuntimeVerifier `
    -MigratorVerifier $credentials.MigratorVerifier `
    -MigratorValidUntilUtc ([DateTime]'2030-01-02T03:04:05Z')
if (
    $roleBootstrapSql -notlike "*PASSWORD 'SCRAM-SHA-256`$4096:x';*" -or
    $roleBootstrapSql -notlike "*PASSWORD 'SCRAM-SHA-256`$4096:y' VALID UNTIL '2030-01-02T03:04:05.000Z';*" -or
    $roleBootstrapSql -like "*PASSWORD ''SCRAM-SHA-256*" -or
    $roleBootstrapSql -like "*IS DISTINCT FROM ''SCRAM-SHA-256*" -or
    $roleBootstrapSql -like "*''11111111-1111-4111-8111-111111111111''*"
) {{ throw 'empty-source SQL literal ownership drifted' }}
$attemptFixture = [pscustomobject]@{{
    PayloadSha256 = ('d' * 64)
    Payload = [pscustomobject]@{{
        intent_sha256 = ('a' * 64); cluster_system_identifier = 'cluster-1'
        database_name = 'ticketbox'
        temporary_database = 'ticketbox_generation_11111111111141118111111111111111'
        observed_target_absent = $true
    }}
}}
$exactMarker = "ticketbox-database-generation-empty-source-v1|$operation|cluster-1|42"

# A pre-existing target cannot create an attempt or mutate roles/ACL.
$script:attempt = $null
$script:target = [pscustomobject]@{{ Exists = $true; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]42; OwnerRoleOid = [uint32]77; Comment = ''; AllowsConnections = $true }}
$rejected = $false
try {{ Invoke-TicketboxDatabaseGenerationEmptySource 'state' $intent $credentials @{{}} $maintenanceAuthority @{{}} | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'pre-existing target reached mutation' }}

# Even an operation marker cannot authorize a non-empty target.
$script:attempt = $attemptFixture
$script:target.Comment = $exactMarker
$script:nonempty = $true
$rejected = $false
try {{ Invoke-TicketboxDatabaseGenerationEmptySource 'state' $intent $credentials @{{}} $maintenanceAuthority @{{}} | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'non-empty exact marker reached mutation' }}

# The exact persisted attempt + marker + empty schema is the only retry lane.
$script:nonempty = $false
$script:emptyAclAttested = $false
$result = Invoke-TicketboxDatabaseGenerationEmptySource 'state' $intent $credentials @{{}} $maintenanceAuthority @{{}}
if (
    $script:writes -ne 4 -or
    -not $script:emptyAclAttested -or
    [string]$result.create_attempt_sha256 -cne ('d' * 64) -or
    [string]$result.source_kind -cne 'empty' -or
    [string]$result.database_oid -cne '42'
) {{ throw 'exact operation-bound retry did not converge' }}
"""
    path = tmp_path / "database-generation-source.ps1"
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
