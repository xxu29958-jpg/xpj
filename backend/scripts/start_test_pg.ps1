#Requires -Version 5.1
<#
.SYNOPSIS
  Start an isolated, throwaway PostgreSQL instance for the backend test suite.

.DESCRIPTION
  PG-only test-lane ergonomics (debt #4 / PG-only slimming). Spins an ephemeral
  PostgreSQL cluster on a dedicated port (default 5438) using the locally
  installed initdb, isolated from the production cluster on 5432 and the CI
  cluster on 5433. Non-durable settings (fsync / synchronous_commit /
  full_page_writes off) because the data is disposable test data.

  Idempotent: if our cluster is already up on the port it is reused; the
  xpj_test / xpj_smoke databases are created only when missing.

  After it prints OK, run the suite with:
    $env:XPJ_TEST_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5438/xpj_test"
    .\.venv\Scripts\python.exe -m pytest
  (or just `pytest` — the default test DB URL points at :5438/xpj_test too.)

  NEVER touches 5432 (prod) or 5433 (CI). Teardown: stop_test_pg.ps1.

.PARAMETER Port
  TCP port for the throwaway cluster. Default 5438.

.PARAMETER DataDir
  Cluster data directory. Default: $env:TEMP\xpj_pg_test<Port>.
#>
[CmdletBinding()]
param(
    [int]$Port = 5438,
    [string]$DataDir = (Join-Path $env:TEMP "xpj_pg_test$Port")
)

$ErrorActionPreference = "Stop"

if ($Port -eq 5432 -or $Port -eq 5433) {
    throw "Refusing port ${Port}: 5432 is prod, 5433 is CI. Use a dedicated test port (default 5438)."
}

# Numeric version sort: a lingering 9.x client must not beat 17 by string order ("9" > "1").
$pgctl = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_ctl.exe' -ErrorAction SilentlyContinue |
    Sort-Object {
        $v = 0.0
        if ([double]::TryParse($_.Directory.Parent.Name, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$v)) { $v } else { -1.0 }
    } -Descending |
    Select-Object -First 1
if (-not $pgctl) {
    throw "PostgreSQL not installed (expected C:\Program Files\PostgreSQL\<ver>\bin\pg_ctl.exe)."
}
$pgbin = $pgctl.DirectoryName

$alreadyUp = $false
$listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($listening) {
    # Confirm it is OUR throwaway cluster (its data dir exists), not some other
    # process squatting on the port — never assume a foreign listener is ours.
    if (Test-Path (Join-Path $DataDir "postmaster.pid")) {
        $alreadyUp = $true
        Write-Host "Reusing PostgreSQL already up on 127.0.0.1:$Port (datadir=$DataDir)"
    }
    else {
        throw "Port $Port is in use but $DataDir\postmaster.pid is missing — not our cluster. Pick another -Port."
    }
}

if (-not $alreadyUp) {
    if (-not (Test-Path $DataDir)) {
        & "$pgbin\initdb.exe" -D $DataDir -U postgres --auth=trust -E UTF8 --locale=C | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "initdb failed" }
    }
    $opts = "-p $Port -c listen_addresses=localhost -c fsync=off -c synchronous_commit=off -c full_page_writes=off"
    & "$pgbin\pg_ctl.exe" -D $DataDir -o $opts -l "$DataDir\server.log" -w start
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path "$DataDir\server.log") { Get-Content "$DataDir\server.log" }
        throw "pg_ctl start failed"
    }
    Write-Host "Started PostgreSQL on 127.0.0.1:$Port (datadir=$DataDir)"
}

foreach ($db in @("xpj_test", "xpj_smoke")) {
    $exists = & "$pgbin\psql.exe" -h localhost -p $Port -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'"
    if (-not ($exists -match "1")) {
        & "$pgbin\createdb.exe" -h localhost -p $Port -U postgres $db
        if ($LASTEXITCODE -ne 0) { throw "createdb $db failed" }
        Write-Host "Created database $db"
    }
}

Write-Host ""
Write-Host "OK: test PostgreSQL ready on 127.0.0.1:$Port (xpj_test + xpj_smoke)."
Write-Host "Run the suite from backend\:"
Write-Host "  .\.venv\Scripts\python.exe -m pytest"
