#Requires -Version 5.1
<#
.SYNOPSIS
  Start an owned, disposable PostgreSQL instance for backend tests.

.DESCRIPTION
  Creates a loopback-only PostgreSQL cluster and binds its lifecycle to a
  script-owned marker containing purpose, port, and PostgreSQL system identifier.
  Existing unmarked data directories are rejected. Local mode uses port 5438;
  CI mode is an explicit exception for the reserved port 5433.

  After it prints OK, run the suite with:
    .\.venv\Scripts\python.exe scripts\run_test_lanes.py full

.PARAMETER Port
  TCP port for the throwaway cluster. Default 5438.

.PARAMETER DataDir
  Cluster data directory. Default: $env:TEMP\xpj_pg_test<Port>.

.PARAMETER Purpose
  local (default) or ci. CI purpose is accepted only on port 5433.

.PARAMETER PostgresBin
  Optional explicit PostgreSQL bin directory. Otherwise discovered from the OS
  Program Files root.

.PARAMETER ResetDatabases
  Recreate the required test databases after online cluster identity is proven.
  CI and repeatable full-project verification use this; normal local starts keep
  databases for a faster edit/test loop.

.PARAMETER InjectedReadinessFailures
  Test-only fault injection. Fail this many initial authenticated readiness
  probes so lifecycle tests can prove startup retry behavior deterministically.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 5438,
    [string]$DataDir = (Join-Path $env:TEMP "xpj_pg_test$Port"),
    [ValidateSet('local', 'ci')][string]$Purpose = 'local',
    [string]$PostgresBin = '',
    [switch]$ResetDatabases,
    [switch]$AcquireConsumerLease,
    [ValidateRange(1, 7200)][int]$LifecycleMutexTimeoutSeconds = 300,
    [ValidateRange(5, 600)][int]$ProcessTimeoutSeconds = 60,
    [ValidateRange(0, 10)][int]$InjectedReadinessFailures = 0
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'test_pg_cluster_contract.ps1')
$script:XpjTestPostgresProcessTimeoutSeconds = $ProcessTimeoutSeconds

Assert-XpjTestPostgresLifecycleRequest -Purpose $Purpose -Port $Port
$DataDir = Resolve-XpjTestPostgresDataDirectory $DataDir

Invoke-XpjTestPostgresLifecycleLocked `
    -Port $Port `
    -DataDirectory $DataDir `
    -TimeoutSeconds $LifecycleMutexTimeoutSeconds `
    -Operation {
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
$marker = $null

if (Test-Path -LiteralPath $DataDir) {
    $dataPathLease = [XpjTestDirectoryPathLease]::OpenPath($DataDir)
    $marker = Assert-XpjTestPostgresDataOwnership `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDir `
        -Purpose $Purpose `
        -Port $Port
}
else {
    $marker = New-XpjTestPostgresDataDirectory `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDir `
        -Purpose $Purpose `
        -Port $Port
    $dataPathLease = [XpjTestDirectoryPathLease]::OpenPath($DataDir)
}

$alreadyUp = $false
$uncommittedStart = $null
try {
    $listeners = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    )
    if ($listeners.Count -gt 0) {
        $liveRecord = Assert-XpjTestPostgresListenerOwnership `
            -ExpectedPort $Port `
            -ExpectedDataDirectory $DataDir
        if ($marker.Authentication -ceq 'legacy-trust') {
            $generation = Get-XpjTestPostgresProcessGeneration $liveRecord
            if ($generation.State -cne 'matching') {
                throw 'Legacy test PostgreSQL process generation changed before conversion.'
            }
            $verifiedProcess = $generation.Process
            [void]$verifiedProcess.Handle
            try {
                Assert-XpjTestPostgresLegacyOnlineIdentity `
                    -PostgresBin $PostgresBin `
                    -DataDirectory $DataDir `
                    -Port $Port `
                    -SystemIdentifier $marker.SystemIdentifier
                Stop-XpjTestPostgresVerifiedPostmaster `
                    -PostgresBin $PostgresBin `
                    -DataDirectory $DataDir `
                    -Port $Port `
                    -ProcessId $liveRecord.ProcessId `
                    -Process $verifiedProcess
            }
            finally {
                $verifiedProcess.Dispose()
            }
        }
        else {
            $alreadyUp = $true
        }
    }
    if (-not $alreadyUp) {
        $pidPath = Join-Path $DataDir 'postmaster.pid'
        if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
            $record = Read-XpjTestPostgresPostmasterRecord $DataDir
            $generation = Get-XpjTestPostgresProcessGeneration $record
            if ($generation.State -eq 'matching') {
                try {
                    throw "Marker-owned PostgreSQL is running but not on its recorded port $Port; refusing to start another postmaster."
                }
                finally {
                    $generation.Process.Dispose()
                }
            }
            Remove-Item -LiteralPath $pidPath -Force -ErrorAction Stop
        }
        $authentication = Prepare-XpjTestPostgresScramAuthenticationOffline `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDir `
            -Port $Port `
            -Marker $marker
        $marker = $authentication.Marker
        $credentialPath = [string]$authentication.CredentialPath
        $serverLog = Join-Path $DataDir 'server.log'
        $serverErrorLog = Join-Path $DataDir 'server-error.log'
        foreach ($processOutput in @($serverLog, $serverErrorLog)) {
            if (Test-Path -LiteralPath $processOutput) {
                $processOutputItem = Get-Item `
                    -LiteralPath $processOutput `
                    -Force `
                    -ErrorAction Stop
                if (
                    $processOutputItem.PSIsContainer -or
                    ($processOutputItem.Attributes -band
                        [System.IO.FileAttributes]::ReparsePoint) -ne 0
                ) {
                    throw "PostgreSQL process output target must be a regular file: $processOutput"
                }
                Remove-Item -LiteralPath $processOutput -Force -ErrorAction Stop
            }
        }
        $uncommittedStart = Start-XpjTestPostgresUncommittedProcess `
            -FilePath (Join-Path $PostgresBin 'postgres.exe') `
            -ArgumentList @(
                '-D', $DataDir,
                '-p', [string]$Port,
                '-c', 'listen_addresses=127.0.0.1',
                '-c', 'fsync=off',
                '-c', 'synchronous_commit=off',
                '-c', 'full_page_writes=off',
                '-c', 'password_encryption=scram-sha-256',
                '-c', 'log_statement=none',
                '-c', 'log_min_error_statement=panic'
            ) `
            -TargetPidSourcePath (Join-Path $DataDir 'postmaster.pid') `
            -TargetStdoutPath $serverLog `
            -TargetStderrPath $serverErrorLog `
            -RestrictWindowsAdminAuthority `
            -TimeoutSeconds $ProcessTimeoutSeconds
        $readyDeadline = [DateTime]::UtcNow.AddSeconds($ProcessTimeoutSeconds)
        $lastReadinessFailure = 'authenticated readiness probe has not completed'
        $readinessAttempt = 0
        while ($true) {
            if (-not $uncommittedStart.Job.IsStartedProcessRunning()) {
                $startupOutput = Get-XpjTestPostgresUncommittedOutput $uncommittedStart
                throw "PostgreSQL exited before becoming ready: $startupOutput"
            }
            $readinessAttempt += 1
            $readiness = if ($readinessAttempt -le $InjectedReadinessFailures) {
                [pscustomobject]@{
                    ExitCode = 1
                    TimedOut = $false
                    Output = 'injected transient PostgreSQL readiness failure'
                }
            }
            else {
                Invoke-XpjTestPostgresReadinessProbe `
                    -PostgresBin $PostgresBin `
                    -Port $Port
            }
            if (-not $readiness.TimedOut -and $readiness.ExitCode -eq 0) {
                break
            }
            $lastReadinessFailure = (
                "exit=$($readiness.ExitCode), timed_out=$($readiness.TimedOut), " +
                "output=$(([string]$readiness.Output).Trim())"
            )
            if ([DateTime]::UtcNow -ge $readyDeadline) {
                $startupOutput = Get-XpjTestPostgresUncommittedOutput $uncommittedStart
                throw (
                    'PostgreSQL did not reach authenticated SCRAM readiness within its ' +
                    "$ProcessTimeoutSeconds second start budget. " +
                    "Last probe: $lastReadinessFailure Startup output: $startupOutput"
                )
            }
            Start-Sleep -Milliseconds 100
        }
    }
    else {
        $authority = Get-XpjTestPostgresScramAuthority `
            -DataDirectory $DataDir `
            -Marker $marker
        $credentialPath = [string]$authority.CredentialPath
    }

    $requiredDatabases = if ($Purpose -eq 'ci') {
        @('xpj_test', 'xpj_smoke', 'xpj_restore')
    }
    else {
        @('xpj_test', 'xpj_smoke')
    }
    try {
        [void](Assert-XpjTestPostgresScramAuthenticationOnline `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDir `
            -Port $Port `
            -Marker $marker)
    }
    catch {
        if ($alreadyUp) {
            throw (
                'XPJ_TEST_POSTGRES_IDENTITY_MISMATCH: the live listener did not ' +
                'accept the marker-owned credential authority.'
            )
        }
        throw
    }
    Invoke-XpjTestPostgresIdentitySession `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDir `
        -Port $Port `
        -SystemIdentifier $marker.SystemIdentifier `
        -RequiredDatabases $requiredDatabases `
        -ResetDatabases:$ResetDatabases `
        -RequireNoOtherSessions:$ResetDatabases
    $env:XPJ_TEST_CLUSTER_AUTHORITY = 'owned-marker'
    $env:XPJ_TEST_CLUSTER_INSTANCE_ID = [string]$marker.InstanceId
    $env:XPJ_TEST_CLUSTER_MARKER_PATH = [string]$marker.Path
    $env:XPJ_TEST_CLUSTER_SYSTEM_IDENTIFIER = [string]$marker.SystemIdentifier
    $env:XPJ_TEST_POSTGRES_CREDENTIAL_FILE = $credentialPath
    $env:XPJ_TEST_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:$Port/xpj_test"
    if ($null -ne $uncommittedStart) {
        Complete-XpjTestPostgresUncommittedProcess $uncommittedStart
        $uncommittedStart = $null
    }
}
finally {
    if ($null -ne $uncommittedStart) {
        Stop-XpjTestPostgresUncommittedProcess $uncommittedStart
    }
}

$verb = if ($alreadyUp) { 'Reusing' } else { 'Started' }
Write-Host "$verb owned PostgreSQL on 127.0.0.1:$Port (datadir=$DataDir)"
Write-Host ''
Write-Host "OK: test PostgreSQL ready ($($requiredDatabases -join ' + '))."
Write-Host 'Run the suite from backend\:'
Write-Host '  .\.venv\Scripts\python.exe scripts\run_test_lanes.py full'
$global:LASTEXITCODE = 0
if ($AcquireConsumerLease) {
    Enter-XpjTestPostgresConsumerLease `
        -DataDirectory $DataDir `
        -InstanceId $marker.InstanceId `
        -SystemIdentifier $marker.SystemIdentifier `
        -Port $Port `
        -TimeoutSeconds $LifecycleMutexTimeoutSeconds
}
}
finally {
    if ($null -ne $dataPathLease) {
        $dataPathLease.Dispose()
    }
    $parentPathLease.Dispose()
}
}
