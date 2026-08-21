import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]
COMMAND = PACKAGING / "windows_postgresql_database_command.ps1"
CONTRACT = PACKAGING / "windows_ticketbox_database_contract.ps1"
ACL = PACKAGING / "windows_ticketbox_database_acl.ps1"
ROLES = PACKAGING / "windows_ticketbox_database_roles.ps1"
OLD_C07_DATABASE = PACKAGING / "windows_c07_database.ps1"
OWNER = PACKAGING / "windows_database_generation.ps1"
SOURCE = PACKAGING / "windows_database_generation_source.ps1"
RECOVERY = PACKAGING / "windows_database_generation_target_recovery.ps1"
RECOVERY_EVIDENCE = PACKAGING / "windows_database_generation_recovery_evidence.ps1"
CREDENTIALS = PACKAGING / "windows_postgresql_credentials.ps1"
INNO = PACKAGING / "ticketbox-installer.iss"
BUILD = PACKAGING / "build_inno_installer.ps1"
PROVENANCE = PACKAGING.parent / "scripts" / "windows_build_provenance.ps1"
PROJECTION_POSTGRES = (
    PACKAGING / "tests" / "powershell_fixtures" / "database_generation_projection_postgres.ps1"
)


def _powershell_string_array(source: str, property_name: str) -> set[str]:
    marker = f"{property_name} = @("
    start = source.index(marker) + len(marker)
    depth = 1
    cursor = start
    while depth:
        character = source[cursor]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        cursor += 1
    return set(re.findall(r'"([a-z][a-z0-9_]*)"', source[start : cursor - 1]))


def _powershell_engines() -> list[str]:
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    return engines


def _ps_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _run_harness(tmp_path: Path, name: str, script: str) -> None:
    harness = tmp_path / f"{name}.ps1"
    harness.write_text(script, encoding="utf-8-sig")
    for engine in _powershell_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_database_host_cutover_has_real_consumers_shipment_and_retirement() -> None:
    owners = (COMMAND, CONTRACT, ACL, ROLES)
    assert all(path.is_file() for path in owners)
    assert not OLD_C07_DATABASE.exists()
    production = {
        path: path.read_text(encoding="utf-8-sig")
        for path in PACKAGING.rglob("*.ps1")
        if "tests" not in path.parts
    }
    owner = production[OWNER]
    inno = INNO.read_text(encoding="utf-8-sig")
    build = BUILD.read_text(encoding="utf-8-sig")
    provenance = PROVENANCE.read_text(encoding="utf-8-sig")
    for path in owners:
        assert owner.count(f'"{path.name}"') == 1
        assert inno.count(f'Source: "{path.name}";') == 1
        assert build.count(path.name) >= 1
        assert provenance.count(f"packaging\\{path.name}") == 1
    for retired in (
        "Assert-TicketboxC07DatabaseRequiredProperties",
        "Assert-TicketboxC07DatabaseSha256",
        "Assert-TicketboxC07HostSha256",
        "Assert-TicketboxC07LiveHostConnection",
        "Assert-TicketboxC07MigratorCredential",
        "Assert-TicketboxC07RetiredRoleCatalog",
        "Assert-TicketboxC07RoleCatalog",
        "Assert-TicketboxC07RuntimeAclContract",
        "Assert-TicketboxC07RuntimeCredential",
        "Assert-TicketboxC07SqlTarget",
        "ConvertTo-TicketboxC07SqlLiteral",
        "ConvertFrom-TicketboxC07SingleRow",
        "ConvertTo-TicketboxC07SqlTextArray",
        "Get-TicketboxC07DatabaseCatalogObservation",
        "Get-TicketboxC07DatabasePrivilegeSql",
        "Get-TicketboxC07DatabaseTextSha256",
        "Get-TicketboxC07MigratorRetirementSql",
        "Get-TicketboxC07MigratorRetirementVerificationSql",
        "Get-TicketboxC07RoleAuthoritySha256",
        "Get-TicketboxC07RoleBootstrapIdentity",
        "Get-TicketboxC07RoleOid",
        "Get-TicketboxC07RuntimeAclSha256",
        "Invoke-TicketboxC07Sql",
        "Invoke-TicketboxC07SqlResult",
        "New-TicketboxC07DatabaseClassifiedFailure",
        "New-TicketboxC07LocalDatabaseUrl",
        "Set-TicketboxC07DatabaseMarker",
        "Set-TicketboxManagedSchemaRuntimeAcl",
        "$script:TicketboxC07DatabaseName",
        "$script:TicketboxC07OwnerRole",
        "$script:TicketboxC07MigratorRole",
        "$script:TicketboxC07RuntimeRole",
    ):
        assert all(retired not in text for text in production.values()), retired
    for text in (owner, inno, build, provenance):
        assert "windows_c07_database.ps1" not in text
    projection_postgres = PROJECTION_POSTGRES.read_text(encoding="utf-8-sig")
    for retired_global in (
        "$script:TicketboxC07DatabaseName",
        "$script:TicketboxC07OwnerRole",
        "$script:TicketboxC07MigratorRole",
    ):
        assert retired_global not in projection_postgres


def test_database_policy_is_closed_normalized_and_secret_safe() -> None:
    command = COMMAND.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    acl = ACL.read_text(encoding="utf-8-sig")
    roles = ROLES.read_text(encoding="utf-8-sig")
    source = SOURCE.read_text(encoding="utf-8-sig")
    recovery = RECOVERY.read_text(encoding="utf-8-sig")
    for path in (COMMAND, CONTRACT, ACL, ROLES):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    for forbidden in ("C07", "c07", "ticketbox-c07", "PGPASSWORD", "$env:"):
        assert forbidden not in command
    assert "scriptblock" not in (command + contract + acl + roles).lower()
    assert "ticketbox_owner" not in command
    for identity in ("ticketbox", "ticketbox_owner", "ticketbox_migrator", "ticketbox_runtime"):
        assert f'"{identity}"' in contract
    policy_properties = (
        "BusinessTables",
        "FinancialAppendTables",
        "AuthorityTables",
        "MigrationAppendTables",
        "AuditAppendTables",
        "AuditMutableTables",
        "RetentionFactTables",
        "ReadOnlyTables",
        "ManagedBindingTables",
        "ManagedAuthorityTables",
        "ManagedAuditInsertTables",
    )
    policy_tables = set().union(
        *(_powershell_string_array(contract, name) for name in policy_properties)
    )
    model_tables: set[str] = set()
    for model_path in (PACKAGING.parent / "app" / "models").rglob("*.py"):
        model_tables.update(
            re.findall(
                r'__tablename__\s*=\s*["\']([a-z][a-z0-9_]*)["\']',
                model_path.read_text(encoding="utf-8"),
            )
        )
    assert policy_tables == model_tables | {"alembic_version"}
    assert "installation_owner_claims" in _powershell_string_array(
        contract, "AuthorityTables"
    )
    for table in (
        "installation_currency_bindings",
        "installation_idempotency_keys",
        "installation_currency_audit_log",
    ):
        assert f'"{table}"' in contract
    assert '"api_idempotency_contract_fences"' not in contract
    assert "REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM PUBLIC" in acl
    for role_property in ("RuntimeRole", "MigratorRole"):
        assert f'ALTER ROLE "$($policy.{role_property})" RESET ALL;' in acl
        assert (
            f'ALTER ROLE "$($policy.{role_property})" '
            'IN DATABASE "$($policy.DatabaseName)" RESET ALL;'
            in acl
        )
    for guard_message in (
        "Ticketbox database has a foreign or excessive ACL grantee",
        "Ticketbox public schema has a foreign or excessive ACL grantee",
        "Ticketbox public relation has a foreign ACL grantee",
        "Ticketbox public routine has a foreign ACL grantee",
        "Ticketbox creator default privileges retain a foreign grantee",
    ):
        assert guard_message in acl
    assert not re.search(
        r"GRANT\s+.+\s+ON\s+ALL\s+(?:TABLES|SEQUENCES|ROUTINES|FUNCTIONS)",
        acl,
        flags=re.IGNORECASE,
    )
    startup_grant = "GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system()"
    assert startup_grant in acl
    assert not re.search(
        r"GRANT\s+EXECUTE\s+ON",
        acl.replace(startup_grant, ""),
        flags=re.IGNORECASE,
    )
    assert "ticketbox-database-generation-source-binding-v1" in source
    assert 'source_kind = "empty"' in source
    assert 'source_revision = "base"' in source
    for retired_mode in ("fresh_install", "legacy_adoption", "runtime_ready"):
        assert retired_mode not in source
    assert "DROP DATABASE" in recovery
    assert "restore_database_absent" in recovery
    assert "Get-TicketboxDatabaseGenerationTextSha256" not in acl + roles
    assert "Get-TicketboxDatabaseRoleAuthorityEvidence" in roles
    assert "Get-TicketboxDatabaseRuntimeAclEvidence" in acl
    empty_source_match = re.search(
        r"(?ms)^function Invoke-TicketboxDatabaseGenerationEmptySource \{.*?(?=^function |\Z)",
        source,
    )
    assert empty_source_match is not None
    empty_source = empty_source_match.group()
    assert "Assert-TicketboxDatabaseRuntimeAcl" not in empty_source
    assert "New-TicketboxDatabaseForeignAclGuardSql" in empty_source
    for role_sql_function in (
        "New-TicketboxDatabaseActiveRoleObservationSql",
        "New-TicketboxDatabaseRetiredRoleObservationSql",
    ):
        role_sql_match = re.search(
            rf"(?ms)^function {role_sql_function} \{{.*?(?=^function |\Z)",
            roles,
        )
        assert role_sql_match is not None
        role_sql = role_sql_match.group()
        assert "NOT rolinherit" in role_sql
        assert role_sql.count("rolconnlimit = -1") == 2
        assert "rolconfig @>" not in role_sql
        assert role_sql.count("rolconfig = ARRAY") == 2
        assert role_sql.count("pg_db_role_setting") == 2


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell managed ACL contract")
def test_managed_schema_runtime_acl_is_opt_in_applied_and_attested(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(COMMAND)}'
. '{_ps_literal(CONTRACT)}'
. '{_ps_literal(ACL)}'
$baseSql = New-TicketboxDatabaseRuntimeAclSql -PreserveRuntimeFence
$managedSql = New-TicketboxDatabaseRuntimeAclSql `
    -IncludeManagedSchemaCurrencyAuthority
foreach ($table in @(
    'installation_currency_bindings',
    'installation_idempotency_keys',
    'installation_currency_audit_log'
)) {{
    if ($baseSql.Contains($table)) {{ throw "managed table leaked into base ACL: $table" }}
    if (-not $managedSql.Contains($table)) {{ throw "managed table missing: $table" }}
}}
$password = [Security.SecureString]::new()
foreach ($character in ('not-a-real-secret-0123456789abcdef').ToCharArray()) {{
    $password.AppendChar($character)
}}
$script:applicationSql = ''
$script:attestationSql = ''
function ConvertFrom-TicketboxPostgresqlHostEvidenceRow {{
    param([string]$Output, [int]$FieldCount, [string]$Label)
    $fields = @($Output -split "`t")
    if ($fields.Count -ne $FieldCount) {{ throw "$Label field count" }}
    return $fields
}}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    param([object]$Authority, [string]$Database, [string]$Role,
        [Security.SecureString]$Password, [string]$Sql, [string]$Label)
    if ($Label -ceq 'Ticketbox managed-schema runtime ACL application') {{
        $script:applicationSql = $Sql
        return ''
    }}
    if ($Label -ceq 'Ticketbox structured runtime ACL attestation') {{
        $script:attestationSql = $Sql
        return (@('true') * 8) -join "`t"
    }}
    throw "unexpected SQL call: $Label"
}}
Set-TicketboxDatabaseRuntimeAcl `
    -Authority ([pscustomobject]@{{ Schema = 'test-authority' }}) `
    -SuperuserPassword $password
if ($script:applicationSql -cne $managedSql) {{ throw 'ACL application drift' }}
if (-not $script:attestationSql.Contains("'pg_catalog.pg_control_system()'")) {{
    throw 'runtime startup probe is absent from ACL attestation'
}}
"""
    _run_harness(tmp_path, "ticketbox-managed-schema-acl", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell failure contract")
def test_native_and_acl_failures_keep_distinct_typed_contracts(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(COMMAND)}'
. '{_ps_literal(CONTRACT)}'
. '{_ps_literal(ACL)}'
$password = [Security.SecureString]::new()
foreach ($character in ('not-a-real-secret-0123456789abcdef').ToCharArray()) {{
    $password.AppendChar($character)
}}
$authority = [pscustomobject]@{{
    Schema = 'ticketbox-postgresql-host-authority-v1'
    PsqlPath = 'C:\\pg\\psql.exe'
    Port = 5544
}}
function Assert-TicketboxPostgresqlSecureString {{}}
function Invoke-TicketboxWithPlainPostgresqlSecret {{
    param($Secret, $Action)
    return & $Action 'plain-test-secret'
}}
function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile {{
    return $script:nativeResult
}}
$script:nativeResult = [pscustomobject]@{{
    ExitCode = 0
    StandardOutput = "one`ntwo`n"
    StandardError = 'native stderr must stay suppressed'
}}
$typedResult = Invoke-TicketboxPostgresqlDatabaseCommandResult `
    -Authority $authority -Database 'ticketbox' -Role 'postgres' `
    -Password $password -Sql 'SELECT 1' -Label 'typed result probe'
$typedNames = @($typedResult.PSObject.Properties.Name | Sort-Object -CaseSensitive)
if (
    ($typedNames -join ',') -cne 'ExitCode,StandardOutput' -or
    [int]$typedResult.ExitCode -ne 0 -or
    [string]$typedResult.StandardOutput -cne "one`ntwo`n"
) {{ throw 'database command result contract is not closed' }}
foreach ($invalidResult in @(
    [pscustomobject]@{{ Label = 'null'; Value = $null }},
    [pscustomobject]@{{
        Label = 'missing exit code'
        Value = [pscustomobject]@{{ StandardOutput = '' }}
    }},
    [pscustomobject]@{{
        Label = 'missing standard output'
        Value = [pscustomobject]@{{ ExitCode = 0 }}
    }}
)) {{
    $script:nativeResult = $invalidResult.Value
    $rejected = $false
    try {{
        Invoke-TicketboxPostgresqlDatabaseCommandResult `
            -Authority $authority -Database 'ticketbox' -Role 'postgres' `
            -Password $password -Sql 'SELECT 1' `
            -Label "malformed $($invalidResult.Label)" | Out-Null
    }} catch {{ $rejected = $true }}
    if (-not $rejected) {{
        throw "database command accepted $($invalidResult.Label) native result"
    }}
}}
function ConvertFrom-TicketboxPostgresqlHostEvidenceRow {{
    param([string]$Output, [int]$FieldCount, [string]$Label)
    return @($Output -split "`t")
}}
function Invoke-TicketboxPostgresqlDatabaseCommandResult {{
    return [pscustomobject]@{{ ExitCode = 3; StandardOutput = '' }}
}}
$nativeFailure = $null
try {{
    Invoke-TicketboxPostgresqlDatabaseCommand -Authority $authority `
        -Database 'ticketbox' -Role 'postgres' -Password $password `
        -Sql 'SELECT 1' -Label 'injected exit three' | Out-Null
}} catch {{ $nativeFailure = $_.Exception }}
if ($null -eq $nativeFailure) {{
    throw 'native database command failure was not preserved'
}}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    return "true`ttrue`tfalse`ttrue`ttrue`ttrue`ttrue`ttrue"
}}
$aclFailure = $null
try {{ Assert-TicketboxDatabaseRuntimeAcl $authority $password }}
catch {{ $aclFailure = $_.Exception }}
if ($null -eq $aclFailure -or
    [string]$aclFailure.Data['TicketboxFailureCode'] -cne 'runtime_acl_invariant_failed') {{
    throw 'structured ACL false did not produce the stable failure contract'
}}
"""
    _run_harness(tmp_path, "ticketbox-database-failure-classification", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell role contract")
def test_scram_role_policy_and_restore_identity_are_closed(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(CREDENTIALS)}'
. '{_ps_literal(COMMAND)}'
. '{_ps_literal(CONTRACT)}'
. '{_ps_literal(ACL)}'
. '{_ps_literal(ROLES)}'
. '{_ps_literal(RECOVERY_EVIDENCE)}'
. '{_ps_literal(RECOVERY)}'
function ConvertFrom-TicketboxPostgresqlHostEvidenceRow {{
    param([string]$Output, [int]$FieldCount, [string]$Label)
    return @($Output -split "`t")
}}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    param([string]$Label)
    if ($Label -like '*role policy verification') {{
        return (@('true') * 15) -join "`t"
    }}
    if ($Label -in @(
        'Ticketbox role authority canonical evidence',
        'Ticketbox runtime ACL canonical evidence'
    )) {{
        return [string]$script:evidenceText
    }}
    throw "unexpected SQL call: $Label"
}}
$secret = [Security.SecureString]::new()
foreach ($character in ('A' * 32).ToCharArray()) {{ $secret.AppendChar($character) }}
$verifier = ConvertTo-TicketboxPostgresqlScramVerifier `
    -Password $secret -Salt ([byte[]](0..15))
$expected = 'SCRAM-SHA-256$4096:AAECAwQFBgcICQoLDA0ODw==$' +
    '355HF2woQrDOhRxNERGHA3h4zRZKzRmQ0VrawXpeRxQ=:' +
    'scGvEICb0PIcJDvEa8hxDlCgyBzb2cWy3JRZ0MSW52Q='
if ($verifier -cne $expected) {{ throw 'SCRAM verifier contract mismatch' }}
$authority = [pscustomobject]@{{ Schema = 'test-authority' }}
foreach ($phase in @('fenced', 'active', 'retired')) {{
    Assert-TicketboxDatabaseRolePolicy $authority $secret $phase
}}
$script:evidenceText = "first`r`nsecond`r`n"
$roleCrLf = Get-TicketboxDatabaseRoleAuthorityEvidence $authority $secret
$aclCrLf = Get-TicketboxDatabaseRuntimeAclEvidence $authority $secret
$script:evidenceText = "first`nsecond`n"
$roleLf = Get-TicketboxDatabaseRoleAuthorityEvidence $authority $secret
$aclLf = Get-TicketboxDatabaseRuntimeAclEvidence $authority $secret
if (
    $roleCrLf -cne "first`nsecond" -or $roleLf -cne $roleCrLf -or
    $aclCrLf -cne "first`nsecond" -or $aclLf -cne $aclCrLf
) {{ throw 'database evidence is not canonical across line endings' }}
$attempt = '223e4567-e89b-42d3-a456-426614174000'
$other = '323e4567-e89b-42d3-a456-426614174000'
$first = Get-TicketboxDatabaseGenerationRestoreDatabaseName -AttemptId $attempt
$second = Get-TicketboxDatabaseGenerationRestoreDatabaseName -AttemptId $other
if ($first -cnotmatch '^ticketbox_generation_restore_[0-9a-f]{{32}}$' -or $first -ceq $second) {{
    throw 'restore database name was not bound to the create attempt'
}}
"""
    _run_harness(tmp_path, "ticketbox-database-policy", script)
