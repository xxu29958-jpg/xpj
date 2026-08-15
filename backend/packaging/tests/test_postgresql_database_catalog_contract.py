from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
HOST_OPERATIONS = PACKAGING / "windows_pg_recovery_tools.ps1"
ENTRYPOINT = PACKAGING / "windows_postgresql_database_catalog.ps1"
COMPONENTS = (
    PACKAGING / "postgresql_database_catalog" / "primitives.ps1",
    PACKAGING / "postgresql_database_catalog" / "query.ps1",
    PACKAGING / "postgresql_database_catalog" / "codec.ps1",
    PACKAGING / "postgresql_database_catalog" / "observation.ps1",
)
C07_DATABASE = PACKAGING / "windows_c07_database.ps1"
GENERATION_RECOVERY = PACKAGING / "windows_database_generation_target_recovery.ps1"
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


def test_catalog_adapter_is_small_generic_and_old_c07_entrypoints_are_retired() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8-sig")
    sources = [path.read_text(encoding="utf-8-sig") for path in COMPONENTS]
    generic = entrypoint + "\n" + "\n".join(sources)
    production_sources = {
        path: path.read_text(encoding="utf-8-sig")
        for path in PACKAGING.rglob("*.ps1")
        if "tests" not in path.parts
    }
    c07_database = production_sources[C07_DATABASE]

    for path in (ENTRYPOINT, *COMPONENTS):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert all(len(source.splitlines()) <= 180 for source in sources)
    for forbidden in (
        "C07",
        "c07",
        "ticketbox-c07",
        "ticketbox_owner",
        "ticketbox_runtime",
        "Marker",
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

    legacy = (
        "Get-TicketboxC07DatabaseIdentity",
        "Get-TicketboxC07DatabaseBootstrapCatalog",
    )
    for symbol in legacy:
        assert all(symbol not in source for source in production_sources.values())
    assert "Get-TicketboxPostgresqlDatabaseCatalogObservation" in c07_database
    assert "function Get-TicketboxC07DatabaseCatalogObservation" in c07_database
    for consumer in (C07_DATABASE, GENERATION_RECOVERY):
        assert "Get-TicketboxC07DatabaseCatalogObservation" in production_sources[consumer]


def test_catalog_adapter_is_actively_packaged_and_provenance_bound() -> None:
    inno_lines = INNO.read_text(encoding="utf-8-sig").splitlines()
    active_sources = tuple(
        line.strip()
        for line in inno_lines
        if line.lstrip().startswith("Source:")
    )
    build = BUILD.read_text(encoding="utf-8-sig")
    provenance = PROVENANCE.read_text(encoding="utf-8-sig")
    expected = {
        "windows_postgresql_database_catalog.ps1": (
            'Source: "windows_postgresql_database_catalog.ps1"; '
            'DestDir: "{app}\\installer"; Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\primitives.ps1": (
            'Source: "postgresql_database_catalog\\primitives.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; '
            'Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\query.ps1": (
            'Source: "postgresql_database_catalog\\query.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; '
            'Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\codec.ps1": (
            'Source: "postgresql_database_catalog\\codec.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; '
            'Flags: ignoreversion'
        ),
        "postgresql_database_catalog\\observation.ps1": (
            'Source: "postgresql_database_catalog\\observation.ps1"; '
            'DestDir: "{app}\\installer\\postgresql_database_catalog"; '
            'Flags: ignoreversion'
        ),
    }
    for item, exact_source in expected.items():
        assert exact_source in active_sources
        assert item in provenance
    for variable in (
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
$script:output = (
    "7123456789012345678`t42`t5001`ttrue`t" +
    "6d61726b6572096c696e650a"
)
function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile {{
    param($PsqlPath, $DatabaseUrl, $Password, $Sql, $Label, $TimeoutMilliseconds)
    if ($PsqlPath -cne 'C:\\pg\\psql.exe') {{ throw 'psql path drifted' }}
    if ($DatabaseUrl -cne 'postgresql://postgres@127.0.0.1:5544/postgres') {{
        throw 'database URL drifted'
    }}
    if ($Password -cne 'secret') {{ throw 'password drifted' }}
    if ($Label -cne 'PostgreSQL database-catalog observation') {{
        throw 'diagnostic label drifted'
    }}
    foreach ($surface in @($PsqlPath, $DatabaseUrl, $Sql, $Label)) {{
        if ([string]$surface -like '*secret*') {{ throw 'secret reached diagnostic surface' }}
    }}
    $expectedSql = @"
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
    $normalizedSql = $Sql.Replace("`r`n", "`n")
    $normalizedExpectedSql = $expectedSql.Replace("`r`n", "`n")
    if ($normalizedSql -cne $normalizedExpectedSql) {{
        throw 'catalog query was not exact'
    }}
    return [pscustomobject]@{{ ExitCode = 0; StandardOutput = $script:output }}
}}
. '{_literal(ENTRYPOINT)}'
$parameters = @{{
    PsqlPath = 'C:\\pg\\psql.exe'
    DatabaseUrl = 'postgresql://postgres@127.0.0.1:5544/postgres'
    Password = 'secret'
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

$script:output = "secret-native-output"
function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile {{
    return [pscustomobject]@{{ ExitCode = 3; StandardOutput = $script:output }}
}}
$safeFailure = $false
try {{ Get-TicketboxPostgresqlDatabaseCatalogObservation @parameters | Out-Null }}
catch {{
    $safeFailure = $_.Exception.Message -cnotlike '*secret*'
}}
if (-not $safeFailure) {{ throw 'native failure leaked catalog output' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_catalog_observation_distinguishes_absence_and_rejects_bad_evidence(
    engine: str,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$script:output = "7123456789012345678`t`t`t`t"
. '{_literal(HOST_OPERATIONS)}'
function Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile {{
    return [pscustomobject]@{{ ExitCode = 0; StandardOutput = $script:output }}
}}
. '{_literal(ENTRYPOINT)}'
$parameters = @{{
    PsqlPath = 'C:\\pg\\psql.exe'
    DatabaseUrl = 'postgresql://postgres@127.0.0.1:5544/postgres'
    Password = 'secret'
    TargetDatabase = 'target_db'
    TimeoutMilliseconds = 5000
}}
$missing = Get-TicketboxPostgresqlDatabaseCatalogObservation @parameters
if (
    $missing.Exists -or
    [uint32]$missing.DatabaseOid -ne 0 -or
    [uint32]$missing.OwnerRoleOid -ne 0 -or
    $missing.AllowsConnections -or
    $missing.Comment -cne ''
) {{ throw 'absent database evidence drifted' }}

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


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_catalog_adapter_preserves_policy_mapping_and_deadline(engine: str) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{_literal(C07_DATABASE)}'
$script:timeoutCalls = 0
function Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds {{
    param($MaximumMilliseconds, $Label)
    if ($MaximumMilliseconds -ne 30000 -or $Label -cne 'C07 database catalog observation') {{
        throw 'C07 catalog timeout contract drifted'
    }}
    $script:timeoutCalls++
    return 4321
}}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{
    param($PsqlPath, $DatabaseUrl, $Password, $TargetDatabase, $TimeoutMilliseconds)
    if (
        $PsqlPath -cne 'C:\\pg\\psql.exe' -or
        $DatabaseUrl -cne
            'postgresql://postgres@127.0.0.1:5544/postgres?require_auth=scram-sha-256' -or
        $Password -cne ('A' * 40) -or
        $TargetDatabase -cne 'ticketbox' -or
        $TimeoutMilliseconds -ne 4321
    ) {{ throw 'C07 catalog adapter invocation drifted' }}
    return [pscustomobject][ordered]@{{
        ClusterSystemIdentifier = '7123456789012345678'
        Database = 'ticketbox'
        DatabaseOid = [uint32]42
        OwnerRoleOid = [uint32]5001
        AllowsConnections = $false
        Comment = "marker`tline`n"
        Exists = $true
    }}
}}
$authority = [pscustomobject]@{{
    Schema = 'ticketbox-c07-host-db-authority-v1'
    PsqlPath = 'C:\\pg\\psql.exe'
    Port = 5544
}}
$secret = New-Object Security.SecureString
foreach ($character in ('A' * 40).ToCharArray()) {{
    $secret.AppendChar($character)
}}
$secret.MakeReadOnly()
$result = Get-TicketboxC07DatabaseCatalogObservation `
    -Authority $authority `
    -SuperuserPassword $secret `
    -Database 'ticketbox'
if (
    $script:timeoutCalls -ne 1 -or
    $result.ClusterSystemIdentifier -cne '7123456789012345678' -or
    $result.Database -cne 'ticketbox' -or
    [uint32]$result.DatabaseOid -ne 42 -or
    [uint32]$result.OwnerRoleOid -ne 5001 -or
    $result.AllowsConnections -or
    $result.Marker -cne "marker`tline`n" -or
    -not $result.Exists
) {{ throw 'C07 catalog policy projection drifted' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
