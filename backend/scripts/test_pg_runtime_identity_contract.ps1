#Requires -Version 5.1

function Assert-XpjTestPostgresQuiescent {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $pidPath = Join-Path $DataDirectory 'postmaster.pid'
    if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
        throw "Test PostgreSQL is not quiescent: postmaster.pid still exists ($pidPath)."
    }
    $listeners = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    )
    if ($listeners.Count -gt 0) {
        $listenerPids = @(
            $listeners |
                ForEach-Object { [int]$_.OwningProcess } |
                Sort-Object -Unique
        )
        throw "Test PostgreSQL is not quiescent: port $Port still has listener PID(s) $($listenerPids -join ', ')."
    }
    return Get-XpjTestPostgresControlState `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory
}

function Assert-XpjTestPostgresCleanShutdown {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $controlState = Assert-XpjTestPostgresQuiescent `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port
    if ($controlState -cne 'shut down') {
        throw (
            'Test PostgreSQL did not complete a clean shutdown according to pg_controldata ' +
            "(state=$controlState)."
        )
    }
}

function Read-XpjTestPostgresPostmasterRecord {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    $pidPath = Join-Path $DataDirectory 'postmaster.pid'
    if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
        throw "Test PostgreSQL postmaster.pid is missing: $pidPath"
    }
    $lines = @(Get-Content -LiteralPath $pidPath -Encoding UTF8 -ErrorAction Stop)
    if ($lines.Count -lt 4) {
        throw "Test PostgreSQL postmaster.pid is truncated: $pidPath"
    }
    $postmasterPid = 0
    $startEpoch = 0L
    $postmasterPort = 0
    if (
        -not [int]::TryParse($lines[0].Trim(), [ref]$postmasterPid) -or
        $postmasterPid -le 0 -or
        -not [long]::TryParse($lines[2].Trim(), [ref]$startEpoch) -or
        $startEpoch -le 0 -or
        -not [int]::TryParse($lines[3].Trim(), [ref]$postmasterPort) -or
        $postmasterPort -lt 1 -or
        $postmasterPort -gt 65535
    ) {
        throw "Test PostgreSQL postmaster.pid has invalid identity fields: $pidPath"
    }
    $recordedDataDirectory = Resolve-XpjTestPostgresDataDirectory $lines[1].Trim()
    if (-not [string]::Equals(
        $recordedDataDirectory,
        $DataDirectory,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Test PostgreSQL postmaster.pid names a different data directory."
    }
    return [pscustomobject]@{
        Path = $pidPath
        ProcessId = $postmasterPid
        StartEpoch = $startEpoch
        Port = $postmasterPort
    }
}

function Get-XpjTestPostgresProcessGeneration {
    param([Parameter(Mandatory = $true)]$PostmasterRecord)

    $process = Get-Process -Id $PostmasterRecord.ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return [pscustomobject]@{ State = 'missing'; Process = $null }
    }
    try {
        $actualStartEpoch = ([DateTimeOffset]$process.StartTime).ToUnixTimeSeconds()
    }
    catch {
        throw "Cannot verify process generation for postmaster PID $($PostmasterRecord.ProcessId)."
    }
    if ([Math]::Abs($actualStartEpoch - $PostmasterRecord.StartEpoch) -gt 2) {
        return [pscustomobject]@{ State = 'reused'; Process = $process }
    }
    return [pscustomobject]@{ State = 'matching'; Process = $process }
}

function Stop-XpjTestPostgresVerifiedPostmaster {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process
    )

    if ($Process.Id -ne $ProcessId) {
        throw 'Verified PostgreSQL process handle does not match its recorded PID.'
    }
    # Windows cannot reuse this PID while the retained process object handle is
    # open, so pg_ctl's named-pipe signal stays bound to the verified generation.
    [void]$Process.Handle
    $Process.Refresh()
    if ($Process.HasExited) {
        throw 'Verified PostgreSQL process exited before the shutdown signal.'
    }
    $signal = Invoke-XpjTestPostgresBoundedProcess `
        -FilePath (Join-Path $PostgresBin 'pg_ctl.exe') `
        -ArgumentList @('kill', 'INT', [string]$ProcessId) `
        -TimeoutSeconds (Get-XpjTestPostgresProcessTimeoutSeconds)
    if ($signal.TimedOut -or $signal.ExitCode -ne 0) {
        throw (
            'pg_ctl could not signal the exact verified PostgreSQL process; ' +
            "data was preserved (exit=$($signal.ExitCode), timed_out=$($signal.TimedOut))."
        )
    }
    $waitMilliseconds = (Get-XpjTestPostgresProcessTimeoutSeconds) * 1000
    if (-not $Process.WaitForExit($waitMilliseconds)) {
        throw 'The exact verified PostgreSQL process did not complete fast shutdown.'
    }
    if (Test-Path -LiteralPath (Join-Path $DataDirectory 'postmaster.pid') -PathType Leaf) {
        throw 'PostgreSQL exited without removing postmaster.pid; data was preserved.'
    }
    $remainingListeners = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    )
    if ($remainingListeners.Count -gt 0) {
        throw "A listener remains on test PostgreSQL port $Port after exact-process stop."
    }
    [void](Assert-XpjTestPostgresCleanShutdown `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port)
}

function Assert-XpjTestPostgresListenerOwnership {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$ExpectedPort,
        [Parameter(Mandatory = $true)][string]$ExpectedDataDirectory
    )

    $record = Read-XpjTestPostgresPostmasterRecord $ExpectedDataDirectory
    if ($record.Port -ne $ExpectedPort) {
        throw "Test PostgreSQL postmaster.pid port does not match $ExpectedPort."
    }
    $connections = @(
        Get-NetTCPConnection -State Listen -LocalPort $ExpectedPort -ErrorAction SilentlyContinue
    )
    if ($connections.Count -eq 0) {
        throw "PostgreSQL is not listening on the expected test port $ExpectedPort."
    }
    $unsafeAddresses = @(
        $connections |
            Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') } |
            Select-Object -ExpandProperty LocalAddress -Unique
    )
    if ($unsafeAddresses.Count -gt 0) {
        throw "Port $ExpectedPort is not loopback-only (listener address(es): $($unsafeAddresses -join ', '))."
    }
    $listenerPids = @(
        $connections |
            ForEach-Object { [int]$_.OwningProcess } |
            Sort-Object -Unique
    )
    if ($listenerPids.Count -ne 1 -or $listenerPids[0] -ne $record.ProcessId) {
        $actualPids = if ($listenerPids.Count -gt 0) { $listenerPids -join ', ' } else { 'none' }
        throw "The postmaster.pid process $($record.ProcessId) does not own port $ExpectedPort (listener pid(s): $actualPids)."
    }
    $generation = Get-XpjTestPostgresProcessGeneration $record
    if ($generation.State -eq 'missing') {
        throw "The recorded test PostgreSQL process is no longer running."
    }
    if ($generation.State -ne 'matching') {
        throw "The postmaster.pid process id was reused by a different process generation."
    }
    return $record
}

function Invoke-XpjTestPostgresIdentitySession {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$SystemIdentifier,
        [string[]]$RequiredDatabases = @(),
        [switch]$ResetDatabases,
        [switch]$RequireNoOtherSessions
    )

    [void](Assert-XpjTestPostgresListenerOwnership `
        -ExpectedPort $Port `
        -ExpectedDataDirectory $DataDirectory)
    $databaseProvision = if ($RequiredDatabases.Count -gt 0) {
        $databaseRows = ($RequiredDatabases | ForEach-Object {
            if ($_ -notmatch '^[a-z][a-z0-9_]{0,62}$') {
                throw "Invalid test PostgreSQL database name: $_"
            }
            "('$_')"
        }) -join ",`n        "
        $databaseNames = ($RequiredDatabases | ForEach-Object { "'$_'" }) -join ', '
        $databaseReset = if ($ResetDatabases) {
            @"
SELECT format('DROP DATABASE %I WITH (FORCE)', datname)
FROM pg_database
WHERE datname IN ($databaseNames)
\gexec
"@
        }
        else {
            ''
        }
        $createFilter = if ($ResetDatabases) {
            ''
        }
        else {
            'WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = requested.name)'
        }
        @"
$databaseReset
SELECT format('CREATE DATABASE %I', requested.name)
FROM (VALUES
        $databaseRows
) AS requested(name)
$createFilter
\gexec
SELECT count(*) = $($RequiredDatabases.Count) AS xpj_databases_ok
FROM pg_database
WHERE datname IN ($databaseNames)
\gset
\if :xpj_databases_ok
\else
\echo XPJ_TEST_POSTGRES_DATABASE_PROVISION_FAILED
\quit 87
\endif
"@
    }
    else {
        ''
    }
    $sessionGuard = if ($RequireNoOtherSessions) {
        @"
SELECT count(*) = 0 AS xpj_no_other_sessions
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND backend_type = 'client backend';
\gset
\if :xpj_no_other_sessions
\else
\echo XPJ_TEST_POSTGRES_ACTIVE_CONSUMERS
\quit 88
\endif
"@
    }
    else {
        ''
    }
    $contract = @"
\set ON_ERROR_STOP on
SELECT
    lower(replace(current_setting('data_directory'), '/', E'\\')) =
        lower(replace(:'expected_data_directory', '/', E'\\'))
    AND (SELECT system_identifier::text FROM pg_control_system()) = :'expected_system_identifier'
    AND current_setting('port') = :'expected_port'
    AND current_setting('listen_addresses') = '127.0.0.1'
    AND current_setting('password_encryption') = 'scram-sha-256'
    AND current_setting('log_statement') = 'none'
    AND current_setting('log_min_error_statement') = 'panic'
    AS xpj_identity_ok
\gset
\if :xpj_identity_ok
$sessionGuard
$databaseProvision
\echo XPJ_TEST_POSTGRES_IDENTITY_OK
\else
\echo XPJ_TEST_POSTGRES_IDENTITY_MISMATCH
\quit 86
\endif
"@
    $contractPath = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText(
            $contractPath,
            $contract,
            (New-Object System.Text.UTF8Encoding($false))
        )
        $processTimeout = Get-XpjTestPostgresProcessTimeoutSeconds
        $statementTimeoutMs = [Math]::Max(1000, [Math]::Min(45000, ($processTimeout - 2) * 1000))
        $lockTimeoutMs = [Math]::Min(10000, $statementTimeoutMs)
        $timeoutOptions = "-c statement_timeout=$statementTimeoutMs -c lock_timeout=$lockTimeoutMs"
        $result = Invoke-XpjTestPostgresCredentialCommand `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDirectory `
            -Port $Port `
            -ArgumentList @(
                '--no-psqlrc',
                '--no-password',
                '--quiet',
                '--host', '127.0.0.1',
                '--port', [string]$Port,
                '--username', 'postgres',
                '--dbname', 'postgres',
                '--set', "expected_data_directory=$DataDirectory",
                '--set', "expected_system_identifier=$SystemIdentifier",
                '--set', "expected_port=$Port",
                '--file', $contractPath
            ) `
            -AdditionalEnvironment @{
                PGOPTIONS = $timeoutOptions
            }
        if ($result.TimedOut) {
            throw "Test PostgreSQL online identity/provisioning exceeded its $processTimeout second process budget."
        }
        $exitCode = $result.ExitCode
        $outputText = [string]$result.Output
    }
    finally {
        Remove-Item -LiteralPath $contractPath -Force -ErrorAction SilentlyContinue
    }
    if ($exitCode -ne 0 -or $outputText -notmatch '(?m)^XPJ_TEST_POSTGRES_IDENTITY_OK\s*$') {
        throw "Test PostgreSQL online identity/provisioning failed (exit=$exitCode): $outputText"
    }
}
