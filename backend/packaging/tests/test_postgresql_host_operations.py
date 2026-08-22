from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
HOST_OPERATIONS = PACKAGING / "windows_pg_recovery_tools.ps1"


def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_ps(engine: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=30,
        check=False,
    )


def test_host_psql_contract_is_generic_quiet_and_owns_credential_rotation() -> None:
    host = HOST_OPERATIONS.read_text(encoding="utf-8-sig")

    assert "function Invoke-TicketboxPostgresqlHostNative" in host
    assert "function Invoke-TicketboxPostgresqlHostPsql" in host
    assert "function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile" in host
    assert "function ConvertFrom-TicketboxPostgresqlHostEvidenceRow" in host
    assert "function Invoke-TicketboxPostgresqlHostCredentialRotation" in host
    assert '"--quiet",' in host
    assert host.index('"--quiet",') < host.index('"--tuples-only",')
    assert "ALTER ROLE postgres WITH LOGIN PASSWORD" in host


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_host_psql_quiet_contract_preserves_exact_one_row_parser(engine: str) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$script:nativeArguments = @()
$script:nativeInput = ''
function Invoke-TicketboxBoundedNativeProcess {{
    param($FilePath,$Arguments,$StandardInputText,$TimeoutMilliseconds,$Label)
    $script:nativeArguments = @($Arguments)
    $script:nativeInput = [string]$StandardInputText
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = "postgres`tpostgres`n"
        StandardError = ''
    }}
}}
. {_ps_literal(HOST_OPERATIONS)}
$result = Invoke-TicketboxPostgresqlHostPsql `
    -PsqlPath 'psql.exe' `
    -DatabaseUrl 'postgresql://postgres@localhost:55432/postgres' `
    -Sql 'SELECT session_user, current_user;' `
    -Label 'host psql test'
$quietIndex = [Array]::IndexOf($script:nativeArguments, '--quiet')
$tuplesIndex = [Array]::IndexOf($script:nativeArguments, '--tuples-only')
if ($quietIndex -lt 0 -or $tuplesIndex -lt 0 -or $quietIndex -ge $tuplesIndex) {{
    throw 'psql quiet/tuples-only ordering drifted'
}}
if ($script:nativeInput -cne "SELECT session_user, current_user;`n") {{
    throw 'psql SQL was not sent only through stdin'
}}
$fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
    -Output $result.StandardOutput -FieldCount 2 -Label 'quiet evidence'
if (($fields -join '|') -cne 'postgres|postgres') {{
    throw 'quiet tuple evidence changed'
}}
$rolePolicyFields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
    -Output ((@('true') * 18) -join "`t") `
    -FieldCount 18 -Label 'role policy evidence'
if ($rolePolicyFields.Count -ne 18) {{
    throw 'closed role policy evidence width was rejected'
}}
$commandTagRejected = $false
try {{
    ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output "ALTER ROLE`r`npostgres`tpostgres`r`n" `
        -FieldCount 2 -Label 'command-tag evidence' | Out-Null
}}
catch {{ $commandTagRejected = $_.Exception.Message -like '*唯一结果行*' }}
if (-not $commandTagRejected) {{
    throw 'row parser filtered a PostgreSQL command tag instead of failing closed'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_host_psql_rejects_database_credentials_before_native_launch(
    engine: str,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$script:nativeInvoked = $false
function Invoke-TicketboxBoundedNativeProcess {{
    $script:nativeInvoked = $true
    throw 'native launch must not occur'
}}
. {_ps_literal(HOST_OPERATIONS)}
foreach ($databaseUrl in @(
    'postgresql://postgres:raw-secret@localhost:55432/postgres',
    'postgresql://postgres@localhost:55432/postgres?password=raw-secret',
    'https://postgres@localhost:55432/postgres'
)) {{
    $rejected = $false
    try {{
        Invoke-TicketboxPostgresqlHostPsql `
            -PsqlPath 'psql.exe' `
            -DatabaseUrl $databaseUrl `
            -Sql 'SELECT 1;' `
            -Label 'credential argv rejection' | Out-Null
    }}
    catch {{
        $rejected = $_.Exception.Message -like '*argv credential*'
    }}
    if (-not $rejected) {{ throw 'credential-bearing URL was not rejected' }}
}}
if ($script:nativeInvoked) {{ throw 'credential-bearing URL reached native launch' }}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_host_psql_protected_passfile_composition_is_exact(engine: str) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
function Invoke-TicketboxBoundedNativeProcess {{ throw 'unused' }}
. {_ps_literal(HOST_OPERATIONS)}
$script:observed = $null
function Invoke-TicketboxWithPgPassFile {{
    param($DatabaseUrl, $Password, $Action)
    if ($DatabaseUrl -cne 'postgresql://runtime@127.0.0.1:55432/ticketbox' -or
        $Password -cne 'not-a-real-secret') {{
        throw 'protected passfile inputs drifted'
    }}
    $previous = [string]$env:PGPASSFILE
    try {{
        $env:PGPASSFILE = 'C:\\protected\\ticketbox.pgpass'
        return & $Action 'postgresql://runtime@127.0.0.1:55432/ticketbox'
    }}
    finally {{ $env:PGPASSFILE = $previous }}
}}
function Invoke-TicketboxPostgresqlHostPsql {{
    param(
        $PsqlPath,
        $DatabaseUrl,
        $Sql,
        $Label,
        $PgPassFile,
        $TimeoutMilliseconds
    )
    $script:observed = [pscustomobject]@{{
        PsqlPath = $PsqlPath
        DatabaseUrl = $DatabaseUrl
        Sql = $Sql
        Label = $Label
        PgPassFile = $PgPassFile
        TimeoutMilliseconds = $TimeoutMilliseconds
    }}
    return [pscustomobject]@{{
        ExitCode = 3
        StandardOutput = "one`ttwo`n"
        StandardError = 'suppressed'
    }}
}}
$result = Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile `
    -PsqlPath 'C:\\pgsql\\psql.exe' `
    -DatabaseUrl 'postgresql://runtime@127.0.0.1:55432/ticketbox' `
    -Password 'not-a-real-secret' `
    -Sql 'SELECT 1;' `
    -Label 'generic protected psql' `
    -TimeoutMilliseconds 43210
if (
    $result.ExitCode -ne 3 -or
    $result.StandardOutput -cne "one`ttwo`n" -or
    $script:observed.PsqlPath -cne 'C:\\pgsql\\psql.exe' -or
    $script:observed.DatabaseUrl -cne
        'postgresql://runtime@127.0.0.1:55432/ticketbox' -or
    $script:observed.Sql -cne 'SELECT 1;' -or
    $script:observed.Label -cne 'generic protected psql' -or
    $script:observed.PgPassFile -cne 'C:\\protected\\ticketbox.pgpass' -or
    $script:observed.TimeoutMilliseconds -ne 43210
) {{
    throw 'protected passfile transport lost exact invocation context'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_host_rotation_accepts_quiet_tuple_and_rejects_command_tag(engine: str) -> None:
    expected_data = Path("C:/ProgramData/Ticketbox/pgdata")
    escaped_data = str(expected_data).replace("\\", "\\\\")
    script = f"""
$ErrorActionPreference = 'Stop'
function Test-TicketboxPathEquals {{
    param([string]$Left,[string]$Right)
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left),
        [IO.Path]::GetFullPath($Right),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Invoke-TicketboxBoundedNativeProcess {{ throw 'unused' }}
. {_ps_literal(HOST_OPERATIONS)}
$script:includeCommandTag = $true
function Invoke-TicketboxPostgresqlHostPsql {{
    param($PsqlPath,$DatabaseUrl,$Sql,$Label,$TimeoutMilliseconds)
    if ($Sql -notlike '*ALTER ROLE postgres WITH LOGIN PASSWORD*' -or
        $Sql -notlike '*pg_catalog.pg_control_system()*') {{
        throw 'generic host rotation SQL drifted'
    }}
    $row = (
        "postgres`tpostgres`t7123456789012345678`t" +
        "{escaped_data}`t55432`ttrue`ttrue`n"
    )
    if ($script:includeCommandTag) {{ $row = "ALTER ROLE`n" + $row }}
    return [pscustomobject]@{{ ExitCode = 0; StandardOutput = $row }}
}}
$parameters = @{{
    PsqlPath = 'psql.exe'
    DatabaseUrl = 'postgresql://postgres@localhost:55432/postgres'
    Verifier = 'SCRAM-SHA-256$4096:c2FsdA==$c3RvcmVk:c2VydmVy'
    ClusterSystemIdentifier = '7123456789012345678'
    ExpectedDataDirectories = @('{str(expected_data).replace("'", "''")}')
    Port = 55432
    Label = 'host rotation evidence'
}}
$commandTagRejected = $false
try {{ Invoke-TicketboxPostgresqlHostCredentialRotation @parameters }}
catch {{ $commandTagRejected = $_.Exception.Message -like '*唯一结果行*' }}
if (-not $commandTagRejected) {{
    throw 'credential rotation accepted command status plus tuple'
}}
$script:includeCommandTag = $false
Invoke-TicketboxPostgresqlHostCredentialRotation @parameters
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"
