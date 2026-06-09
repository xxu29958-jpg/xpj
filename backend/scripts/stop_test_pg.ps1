#Requires -Version 5.1
<#
.SYNOPSIS
  Stop and delete the throwaway test PostgreSQL started by start_test_pg.ps1.

.DESCRIPTION
  Kills ONLY the ephemeral cluster's own process tree by its postmaster PID
  (read from <DataDir>\postmaster.pid) and removes the data directory. NEVER
  kills postgres by binary path — the production cluster on 5432 shares the same
  binaries — and never touches 5432 / 5433.

  Mirrors the proven CI teardown (.gitea/workflows/windows-ci.yml): pg_ctl stop
  hung ~60s on Windows, so force-kill the ephemeral postmaster's own PID tree.

.PARAMETER Port
  TCP port of the throwaway cluster. Default 5438.

.PARAMETER DataDir
  Cluster data directory. Default: $env:TEMP\xpj_pg_test<Port>.
#>
[CmdletBinding()]
param(
    [int]$Port = 5438,
    [string]$DataDir = (Join-Path $env:TEMP "xpj_pg_test$Port")
)

if ($Port -eq 5432 -or $Port -eq 5433) {
    throw "Refusing port ${Port}: 5432 is prod, 5433 is CI. This script only tears down the throwaway test cluster."
}

$pidfile = Join-Path $DataDir "postmaster.pid"
if (Test-Path $pidfile) {
    $pmpid = (Get-Content $pidfile -TotalCount 1 -ErrorAction SilentlyContinue)
    if ($pmpid) {
        & taskkill /F /T /PID $pmpid | Out-Null
        Write-Host "Stopped ephemeral PostgreSQL (postmaster PID $pmpid)"
    }
}
else {
    Write-Host "No $pidfile — nothing to stop."
}

if (Test-Path $DataDir) {
    Remove-Item -Recurse -Force $DataDir -ErrorAction SilentlyContinue
    Write-Host "Removed data dir $DataDir"
}

$global:LASTEXITCODE = 0
