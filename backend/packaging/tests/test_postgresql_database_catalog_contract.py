from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
HOST_OPERATIONS = PACKAGING / "windows_pg_recovery_tools.ps1"
COMMAND = PACKAGING / "windows_postgresql_database_command.ps1"
CREDENTIALS = PACKAGING / "windows_postgresql_credentials.ps1"
ENTRYPOINT = PACKAGING / "windows_postgresql_database_catalog.ps1"
COMPONENTS = (
    PACKAGING / "postgresql_database_catalog" / "primitives.ps1",
    PACKAGING / "postgresql_database_catalog" / "query.ps1",
    PACKAGING / "postgresql_database_catalog" / "codec.ps1",
    PACKAGING / "postgresql_database_catalog" / "observation.ps1",
)
GENERATION_CONSUMERS = (
    PACKAGING / "windows_database_generation.ps1",
    PACKAGING / "windows_database_generation_source.ps1",
    PACKAGING / "windows_database_generation_target_recovery.ps1",
)
INNO = PACKAGING / "ticketbox-installer.iss"
BUILD = PACKAGING / "build_inno_installer.ps1"
PROVENANCE = PACKAGING.parent / "scripts" / "windows_build_provenance.ps1"


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _run(engine: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_catalog_is_generic_and_database_command_is_the_only_host_adapter() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8-sig")
    sources = [path.read_text(encoding="utf-8-sig") for path in COMPONENTS]
    generic = entrypoint + "\n" + "\n".join(sources)
    command = COMMAND.read_text(encoding="utf-8-sig")
    production = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in PACKAGING.rglob("*.ps1")
        if "tests" not in path.parts
    )
    for path in (COMMAND, ENTRYPOINT, *COMPONENTS):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert all(len(source.splitlines()) <= 180 for source in sources)
    for forbidden in (
        "C07",
        "c07",
        "ticketbox-c07",
        "ticketbox_owner",
        "ticketbox_runtime",
        "scriptblock",
    ):
        assert forbidden not in generic
    for required in (
        "Get-TicketboxPostgresqlDatabaseCatalogObservation",
        "pg_catalog.pg_control_system()",
        "pg_catalog.pg_database",
        "pg_catalog.shobj_description",
        "OPERATOR(pg_catalog.=)",
        "pg_catalog.encode",
        "pg_catalog.convert_to",
        "datdba",
        "datallowconn",
        "[uint64]::TryParse",
    ):
        assert required in generic
    result_function = re.search(
        r"(?ms)^function Invoke-TicketboxPostgresqlDatabaseCommandResult \{.*?(?=^function |\Z)",
        command,
    )
    assert result_function is not None
    assert "Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile" in result_function.group()
    assert "Invoke-TicketboxWithPgPassFile" not in result_function.group()
    assert "Invoke-TicketboxBoundedNativeProcess" not in result_function.group()
    primitives = COMPONENTS[0].read_text(encoding="utf-8-sig")
    for duplicate in (
        "Assert-TicketboxPostgresqlDatabaseCatalogIdentifier",
        "ConvertTo-TicketboxPostgresqlDatabaseCatalogSqlLiteral",
    ):
        assert duplicate not in generic
    for shared_codec in (
        "Assert-TicketboxPostgresqlDatabaseIdentifier",
        "ConvertTo-TicketboxPostgresqlSqlLiteral",
    ):
        assert shared_codec in primitives
    for retired in (
        "Get-TicketboxC07DatabaseCatalogObservation",
        "Get-TicketboxC07DatabaseIdentity",
        "Get-TicketboxC07DatabaseBootstrapCatalog",
    ):
        assert retired not in production


def test_catalog_and_command_are_actively_packaged_and_provenance_bound() -> None:
    active_sources = tuple(
        line.strip()
        for line in INNO.read_text(encoding="utf-8-sig").splitlines()
        if line.lstrip().startswith("Source:")
    )
    build = BUILD.read_text(encoding="utf-8-sig")
    provenance = PROVENANCE.read_text(encoding="utf-8-sig")
    expected = {
        "windows_postgresql_database_command.ps1": (
            'Source: "windows_postgresql_database_command.ps1"; '
            'DestDir: "{app}\\installer"; Flags: ignoreversion'
        ),
        "windows_postgresql_database_catalog.ps1": (
            'Source: "windows_postgresql_database_catalog.ps1"; '
            'DestDir: "{app}\\installer"; Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\primitives.ps1": (
            'Source: "postgresql_database_catalog\\primitives.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\query.ps1": (
            'Source: "postgresql_database_catalog\\query.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\codec.ps1": (
            'Source: "postgresql_database_catalog\\codec.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\observation.ps1": (
            'Source: "postgresql_database_catalog\\observation.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; Flags: ignoreversion'
        ),
    }
    for item, exact_source in expected.items():
        assert exact_source in active_sources
        assert f"packaging\\{item}" in provenance
    for variable in (
        "PostgresqlDatabaseCommandScript",
        "PostgresqlDatabaseCatalogScript",
        "PostgresqlDatabaseCatalogPrimitivesScript",
        "PostgresqlDatabaseCatalogQueryScript",
        "PostgresqlDatabaseCatalogCodecScript",
        "PostgresqlDatabaseCatalogObservationScript",
    ):
        assert re.search(rf"Assert-File\s+`?\s*\${variable}\b", build)


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_catalog_observation_query_is_exact_and_facts_are_typed(engine: str) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_literal(HOST_OPERATIONS)}'
. '{_literal(CREDENTIALS)}'
. '{_literal(COMMAND)}'
$script:output = "7123456789012345678`t42`t5001`ttrue`t6d61726b6572096c696e650a"
$authority = [pscustomobject]@{{
    Schema = 'ticketbox-postgresql-host-authority-v1'
    PsqlPath = 'C:\\pg\\psql.exe'
    Port = 5544
}}
$secret = [Security.SecureString]::new()
foreach ($character in ('A' * 40).ToCharArray()) {{ $secret.AppendChar($character) }}
function Invoke-TicketboxPostgresqlDatabaseCommandResult {{
    param($Authority, $Database, $Role, $Password, $Sql, $Label, $TimeoutMilliseconds)
    if (
        $Authority -ne $script:authority -or $Password -ne $script:secret -or
        $Database -cne 'postgres' -or $Role -cne 'postgres' -or
        $Label -cne 'PostgreSQL database-catalog observation' -or
        $TimeoutMilliseconds -ne 5000
    ) {{ throw 'catalog host binding drifted' }}
    $expected = @"
SELECT
    control.system_identifier::pg_catalog.text,
    COALESCE(database.oid::pg_catalog.text, ''),
    COALESCE(database.datdba::pg_catalog.text, ''),
    COALESCE(database.datallowconn::pg_catalog.text, ''),
    COALESCE(
        pg_catalog.encode(
            pg_catalog.convert_to(
                pg_catalog.shobj_description(
                    database.oid,
                    'pg_database'
                ),
                'UTF8'
            ),
            'hex'
        ),
        ''
    )
FROM pg_catalog.pg_control_system() AS control
LEFT JOIN pg_catalog.pg_database AS database
  ON database.datname OPERATOR(pg_catalog.=) 'target_db';
"@
    if ($Sql.Replace("`r`n", "`n") -cne $expected.Replace("`r`n", "`n")) {{
        throw 'catalog query was not exact'
    }}
    return [pscustomobject]@{{ ExitCode = 0; StandardOutput = $script:output }}
}}
$script:authority = $authority
$script:secret = $secret
. '{_literal(ENTRYPOINT)}'
$parameters = @{{
    Authority = $authority
    SuperuserPassword = $secret
    TargetDatabase = 'target_db'
    TimeoutMilliseconds = 5000
}}
$result = Get-TicketboxPostgresqlDatabaseCatalogObservation @parameters
if (
    -not $result.Exists -or
    $result.ClusterSystemIdentifier -cne '7123456789012345678' -or
    $result.Database -cne 'target_db' -or
    [uint32]$result.DatabaseOid -ne 42 -or
    [uint32]$result.OwnerRoleOid -ne 5001 -or
    -not $result.AllowsConnections -or
    $result.Comment -cne "marker`tline`n"
) {{ throw 'typed catalog observation drifted' }}
$script:output = "7123456789012345678`t42`t5001`tfalse`t"
$closed = Get-TicketboxPostgresqlDatabaseCatalogObservation @parameters
if (-not $closed.Exists -or $closed.AllowsConnections -or $closed.Comment -cne '') {{
    throw 'canonical false catalog observation drifted'
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_catalog_observation_distinguishes_absence_and_rejects_bad_evidence(
    engine: str,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_literal(HOST_OPERATIONS)}'
. '{_literal(CREDENTIALS)}'
. '{_literal(COMMAND)}'
$script:output = "7123456789012345678`t`t`t`t"
function Invoke-TicketboxPostgresqlDatabaseCommandResult {{
    return [pscustomobject]@{{ ExitCode = 0; StandardOutput = $script:output }}
}}
. '{_literal(ENTRYPOINT)}'
$secret = [Security.SecureString]::new()
foreach ($character in ('A' * 40).ToCharArray()) {{ $secret.AppendChar($character) }}
$parameters = @{{
    Authority = [pscustomobject]@{{
        Schema = 'ticketbox-postgresql-host-authority-v1'
        PsqlPath = 'C:\\pg\\psql.exe'
        Port = 5544
    }}
    SuperuserPassword = $secret
    TargetDatabase = 'target_db'
    TimeoutMilliseconds = 5000
}}
$missing = Get-TicketboxPostgresqlDatabaseCatalogObservation @parameters
if ($missing.Exists -or [uint32]$missing.DatabaseOid -ne 0 -or
    [uint32]$missing.OwnerRoleOid -ne 0 -or $missing.AllowsConnections -or
    $missing.Comment -cne '') {{ throw 'absent database evidence drifted' }}
foreach ($bad in @(
    "0`t42`t5001`ttrue`t",
    "07123456789012345678`t42`t5001`ttrue`t",
    "18446744073709551616`t42`t5001`ttrue`t",
    "7123456789012345678`tbad`t5001`ttrue`t",
    "7123456789012345678`t0`t5001`ttrue`t",
    "7123456789012345678`t4294967296`t5001`ttrue`t",
    "7123456789012345678`t42`t0`ttrue`t",
    "7123456789012345678`t42`t4294967296`ttrue`t",
    "7123456789012345678`t42`t5001`tTRUE`t",
    "7123456789012345678`t42`t5001`ttrue`t0",
    "7123456789012345678`t42`t5001`ttrue`tff",
    "7123456789012345678`t42`t5001`ttrue`t`nextra",
    "7123456789012345678`t`t5001`t`t",
    "7123456789012345678`t`t`tfalse`t",
    "7123456789012345678`t`t`t`t61",
    "7123456789012345678`t42`t`ttrue`t",
    "7123456789012345678`t42`t5001`t`t"
)) {{
    $script:output = $bad
    $rejected = $false
    try {{ Get-TicketboxPostgresqlDatabaseCatalogObservation @parameters | Out-Null }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "bad catalog evidence was accepted: $bad" }}
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_generation_consumers_bind_catalog_to_explicit_authority_and_secret() -> None:
    for path in GENERATION_CONSUMERS:
        source = path.read_text(encoding="utf-8-sig")
        fragments = source.split("Get-TicketboxPostgresqlDatabaseCatalogObservation")[1:]
        assert fragments, path.name
        for fragment in fragments:
            call = fragment[:500]
            assert "-Authority" in call
            assert "-SuperuserPassword" in call
            assert "-TargetDatabase" in call
            assert "DatabaseUrl" not in call
            assert "PgPassFilePath" not in call
