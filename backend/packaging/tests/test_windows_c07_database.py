import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]
C07_DATABASE_SCRIPT = PACKAGING / "windows_c07_database.ps1"
GENERATION_SOURCE_SCRIPT = PACKAGING / "windows_database_generation_source.ps1"
GENERATION_RECOVERY_SCRIPT = (
    PACKAGING / "windows_database_generation_target_recovery.ps1"
)
GENERATION_RECOVERY_EVIDENCE_SCRIPT = (
    PACKAGING / "windows_database_generation_recovery_evidence.ps1"
)


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


def test_database_generation_source_is_narrow_normalized_and_secret_safe() -> None:
    source = C07_DATABASE_SCRIPT.read_text(encoding="utf-8-sig")
    generation_source = GENERATION_SOURCE_SCRIPT.read_text(encoding="utf-8-sig")
    generation_recovery = "\n".join(
        (
            GENERATION_RECOVERY_EVIDENCE_SCRIPT.read_text(encoding="utf-8-sig"),
            GENERATION_RECOVERY_SCRIPT.read_text(encoding="utf-8-sig"),
        )
    )
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
    assert "DROP DATABASE" in generation_recovery
    assert "ClusterSystemIdentifier" in generation_recovery
    assert "DatabaseOid" in generation_recovery
    assert "restore_database_absent" in generation_recovery
    assert "ticketbox-c07-role-v2" in source
    assert "ticketbox-c07-database-v2" in source
    assert "ticketbox-database-generation-restore-v1" in generation_recovery
    assert "create_attempt_id" in generation_recovery
    assert "Invoke-TicketboxC07ProductionAuthorityCoordinator" not in source
    assert "Invoke-TicketboxC07FreshDatabaseAuthority" not in source
    assert "Invoke-TicketboxC07LegacyDatabaseAdoption" not in source
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

    assert "ticketbox-database-generation-source-binding-v1" in generation_source
    assert "ticketbox-database-generation-role-v1" in generation_source
    assert 'NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE' in generation_source
    assert 'LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE' in generation_source
    assert "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE" in generation_source
    assert "ALLOW_CONNECTIONS false" in generation_source
    assert "source_kind = \"empty\"" in generation_source
    assert "source_revision = \"base\"" in generation_source
    assert "fresh_install" not in generation_source
    assert "legacy_adoption" not in generation_source
    assert "ticketbox-c07-database-v" not in generation_source
    assert "$env:" not in generation_source

    raw = C07_DATABASE_SCRIPT.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")


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
        if ($Label -ceq 'C07 role catalog verification') {{
            return (@('true') * 15) -join "`t"
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


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell role contract")
def test_scram_uuid_and_missing_legacy_authority_fail_closed(tmp_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'
. '{_ps_literal(GENERATION_RECOVERY_EVIDENCE_SCRIPT)}'
. '{_ps_literal(GENERATION_RECOVERY_SCRIPT)}'

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

    $attempt = '223e4567-e89b-42d3-a456-426614174000'
    $otherAttempt = '323e4567-e89b-42d3-a456-426614174000'
    $expectedName = Get-TicketboxDatabaseGenerationRestoreDatabaseName `
        -AttemptId $attempt
    $otherName = Get-TicketboxDatabaseGenerationRestoreDatabaseName `
        -AttemptId $otherAttempt
    if (
        $expectedName -cnotmatch '^ticketbox_c07_restore_[0-9a-f]{{32}}$' -or
        $expectedName -ceq $otherName
    ) {{
        throw 'restore database name was not bound to the random create attempt'
    }}
    $injectionRejected = $false
    try {{
        Get-TicketboxDatabaseGenerationRestoreDatabaseName `
            -AttemptId '223e4567-e89b-42d3-a456-426614174000";DROP DATABASE ticketbox;--'
}}
catch {{ $injectionRejected = $true }}
if (-not $injectionRejected) {{ throw 'database-name injection was accepted' }}

"""
    _run_harness(tmp_path, "scram-uuid-legacy-denial", script)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell SCM contract")
def test_c07_host_authority_is_a_compatibility_adapter_to_generic_windows_contract(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "managed"
    install_dir = tmp_path / "program"
    pg_ctl = install_dir / "pg" / "bin" / "pg_ctl.exe"
    pg_data = tmp_path / "runtime" / "data-root" / "pgdata"
    physical_pg_data = data_root / "pgdata"
    psql = install_dir / "pg" / "bin" / "psql.exe"
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(C07_DATABASE_SCRIPT)}'

$DataRoot = '{_ps_literal(data_root)}'
$InstallDir = '{_ps_literal(install_dir)}'
$BackendServiceName = 'TicketboxBackend'
$ReleaseConfig = [pscustomobject]@{{ schema = 'current' }}
$PreviousReleaseConfig = [pscustomobject]@{{ schema = 'legacy' }}
$script:resolverCalls = 0
function Get-TicketboxReleaseServiceIdentityShapes {{
    param($InstalledConfig,$TargetConfig,$ServiceName)
    if ($InstalledConfig -ne $PreviousReleaseConfig -or
        $TargetConfig -ne $ReleaseConfig -or
        $ServiceName -cne 'TicketboxPg') {{
        throw 'C07 adapter did not consume the generic release identity transition'
    }}
    return [pscustomobject]@{{
        LogonAccount = 'NT AUTHORITY\\LocalService'
        SidType = 'unrestricted'
    }}
}}
function Resolve-TicketboxPostgresServiceHostAuthority {{
    param(
        [string]$ServiceName,
        [string]$ExpectedPgCtlPath,
        [string]$DataRoot,
        [string]$InstallDir,
        [string]$BackendServiceName,
        [object[]]$AllowedServiceIdentityShapes
    )
    $script:resolverCalls += 1
    if (
        $ServiceName -cne 'TicketboxPg' -or
        [IO.Path]::GetFullPath($ExpectedPgCtlPath) -cne
            [IO.Path]::GetFullPath('{_ps_literal(pg_ctl)}') -or
        [IO.Path]::GetFullPath($DataRoot) -cne
            [IO.Path]::GetFullPath('{_ps_literal(data_root)}') -or
        [IO.Path]::GetFullPath($InstallDir) -cne
            [IO.Path]::GetFullPath('{_ps_literal(install_dir)}') -or
        $BackendServiceName -cne 'TicketboxBackend' -or
        $AllowedServiceIdentityShapes.Count -ne 1 -or
        $AllowedServiceIdentityShapes[0].LogonAccount -cne
            'NT AUTHORITY\\LocalService' -or
        $AllowedServiceIdentityShapes[0].SidType -cne 'unrestricted'
    ) {{
        throw 'C07 adapter changed the generic Windows host contract'
    }}
    return [pscustomobject]@{{
        ServiceName = 'TicketboxPg'
        ServiceProcessId = 9876
        PostmasterProcessId = 4321
        PgCtlPath = '{_ps_literal(pg_ctl)}'
        PsqlPath = '{_ps_literal(psql)}'
        PgData = '{_ps_literal(pg_data)}'
        PhysicalPgData = '{_ps_literal(physical_pg_data)}'
        Port = 5544
        UsesRuntimeBinding = $true
        DataVolumeIdentity = 'volume-A'
    }}
}}

$authority = Resolve-TicketboxC07DatabaseHostAuthority
if (
    $script:resolverCalls -ne 1 -or
    $authority.Schema -cne 'ticketbox-c07-host-db-authority-v1' -or
    $authority.ServiceName -cne 'TicketboxPg' -or
    $authority.ServiceProcessId -ne 9876 -or
    $authority.PostmasterProcessId -ne 4321 -or
    $authority.Port -ne 5544 -or
    [IO.Path]::GetFullPath($authority.PgData) -cne
        [IO.Path]::GetFullPath('{_ps_literal(pg_data)}') -or
    [IO.Path]::GetFullPath($authority.PhysicalPgData) -cne
        [IO.Path]::GetFullPath('{_ps_literal(physical_pg_data)}') -or
    [IO.Path]::GetFullPath($authority.PsqlPath) -cne
        [IO.Path]::GetFullPath('{_ps_literal(psql)}') -or
    -not $authority.UsesRuntimeBinding -or
    $authority.DataVolumeIdentity -cne 'volume-A'
) {{
    throw 'C07 compatibility schema did not preserve generic host authority'
}}
"""
    _run_harness(tmp_path, "c07-host-authority-adapter", script)
