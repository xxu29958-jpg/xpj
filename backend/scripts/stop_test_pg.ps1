#Requires -Version 5.1
<#
.SYNOPSIS
  Stop and delete the marker-owned test PostgreSQL cluster.

.DESCRIPTION
  Refuses unmarked or identity-mismatched data directories. A running cluster is
  verified by marker, pg_controldata system identifier, postmaster generation,
  loopback listener, and one online identity session before pg_ctl stops it.
  The directory is deleted only after a second offline identity check.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 5438,
    [string]$DataDir = (Join-Path $env:TEMP "xpj_pg_test$Port"),
    [ValidateSet('local', 'ci')][string]$Purpose = 'local',
    [string]$PostgresBin = '',
    [ValidateRange(1, 7200)][int]$LifecycleMutexTimeoutSeconds = 300,
    [ValidateRange(5, 600)][int]$ProcessTimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'test_pg_cluster_contract.ps1')
$script:XpjTestPostgresProcessTimeoutSeconds = $ProcessTimeoutSeconds

Assert-XpjTestPostgresLifecycleRequest -Purpose $Purpose -Port $Port

Invoke-XpjTestPostgresLifecycleLocked `
    -Port $Port `
    -TimeoutSeconds $LifecycleMutexTimeoutSeconds `
    -Operation {
$DataDir = Resolve-XpjTestPostgresDataDirectory $DataDir
$PostgresBin = Resolve-XpjTestPostgresBin $PostgresBin
Assert-XpjTestPostgresRequiredAuthClient $PostgresBin
$parentPathLease = [XpjTestDirectoryPathLease]::OpenParent($DataDir)
$dataPathLease = $null
try {
[void](Complete-XpjTestPostgresPendingDeletion `
    -PostgresBin $PostgresBin `
    -DataDirectory $DataDir `
    -Purpose $Purpose `
    -Port $Port)
Remove-XpjTestPostgresAbandonedStaging `
    -PostgresBin $PostgresBin `
    -DataDirectory $DataDir `
    -Purpose $Purpose `
    -Port $Port
if (-not (Test-Path -LiteralPath $DataDir)) {
    Write-Host "No test PostgreSQL data directory at $DataDir - nothing to stop."
    return
}
$dataPathLease = [XpjTestDirectoryPathLease]::OpenPath($DataDir)
$marker = Assert-XpjTestPostgresDataOwnership `
    -PostgresBin $PostgresBin `
    -DataDirectory $DataDir `
    -Purpose $Purpose `
    -Port $Port

$pidPath = Join-Path $DataDir 'postmaster.pid'
$record = $null
if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $record = Read-XpjTestPostgresPostmasterRecord $DataDir
    $generation = Get-XpjTestPostgresProcessGeneration $record
    if ($generation.State -eq 'matching') {
        $verifiedProcess = $generation.Process
        [void]$verifiedProcess.Handle
        try {
        Invoke-XpjTestPostgresIdentitySession `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDir `
            -Port $Port `
            -SystemIdentifier $marker.SystemIdentifier `
            -RequireNoOtherSessions
        $stopTimeout = [Math]::Min(30, $ProcessTimeoutSeconds)
        $stopResult = Invoke-XpjTestPostgresBoundedProcess `
            -FilePath (Join-Path $PostgresBin 'pg_ctl.exe') `
            -ArgumentList @(
                '-D', $DataDir,
                '-m', 'immediate',
                '-w',
                '-t', [string]$stopTimeout,
                'stop'
            ) `
            -TimeoutSeconds ([Math]::Min(600, $stopTimeout + 5))
        if ($stopResult.TimedOut -or $stopResult.ExitCode -ne 0) {
            throw "pg_ctl could not stop the verified test PostgreSQL process; data was preserved (exit=$($stopResult.ExitCode), timed_out=$($stopResult.TimedOut))."
        }
        $verifiedProcess.Refresh()
        if (-not $verifiedProcess.HasExited) {
            throw 'Verified test PostgreSQL process is still alive after pg_ctl; data was preserved.'
        }
        $remainingListeners = @(
            Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        )
        if ($remainingListeners.Count -gt 0) {
            throw "A listener remains on test PostgreSQL port $Port after stop; data was preserved."
        }
        Write-Host "Stopped owned PostgreSQL postmaster PID $($record.ProcessId)"
        }
        finally {
            $verifiedProcess.Dispose()
        }
    }
    else {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction Stop
        Write-Host "Removed stale pidfile for marker-owned PostgreSQL PID $($record.ProcessId) ($($generation.State) generation)"
    }
}

[void](Assert-XpjTestPostgresQuiescent `
    -DataDirectory $DataDir `
    -Port $Port)
[void](Assert-XpjTestPostgresDataOwnership `
    -PostgresBin $PostgresBin `
    -DataDirectory $DataDir `
    -Purpose $Purpose `
    -Port $Port)
$dataPathLease.Dispose()
$dataPathLease = $null

[void](New-XpjTestPostgresDeletionReceipt `
    -PostgresBin $PostgresBin `
    -DataDirectory $DataDir `
    -Purpose $Purpose `
    -Port $Port `
    -SystemIdentifier $marker.SystemIdentifier)
try {
    [void](Complete-XpjTestPostgresPendingDeletion `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDir `
        -Purpose $Purpose `
        -Port $Port)
}
catch {
    throw "Owned test PostgreSQL was stopped, but receipt-backed cleanup must be resumed: $($_.Exception.Message)"
}
Write-Host "Removed owned test PostgreSQL data directory $DataDir"
$global:LASTEXITCODE = 0
}
finally {
    if ($null -ne $dataPathLease) {
        $dataPathLease.Dispose()
    }
    $parentPathLease.Dispose()
}
}
