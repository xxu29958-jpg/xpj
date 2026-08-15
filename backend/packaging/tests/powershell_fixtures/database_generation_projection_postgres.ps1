param(
    [Parameter(Mandatory = $true)][string]$ProjectionPath,
    [Parameter(Mandatory = $true)][string]$PgBin,
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [switch]$PauseAfterStart,
    [string]$ServerReadyPath = ""
)

$ErrorActionPreference = "Stop"
$dataDir = Join-Path $WorkRoot "pgdata"
$logPath = Join-Path $WorkRoot "postgres.log"
$initdb = Join-Path $PgBin "initdb.exe"
$pgCtl = Join-Path $PgBin "pg_ctl.exe"
$psql = Join-Path $PgBin "psql.exe"
New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null

function Invoke-TestPsql {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Sql
    )
    $connection = "postgresql://postgres@127.0.0.1:$port/$Database`?sslmode=disable"
    $output = & $psql --no-psqlrc --no-password --tuples-only --no-align `
        --set ON_ERROR_STOP=1 --dbname $connection --command $Sql 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($output -join [Environment]::NewLine)
    }
    return ([string]($output -join [Environment]::NewLine)).Trim()
}

function Invoke-TicketboxC07Sql {
    param($Authority, $Database, $Role, $Password, $Label, $Sql)
    return Invoke-TestPsql -Database "postgres" -Sql ([string]$Sql)
}

. $ProjectionPath
$script:TicketboxC07DatabaseName = "ticketbox"
$script:TicketboxC07OwnerRole = "ticketbox_owner"
$script:TicketboxC07MigratorRole = "ticketbox_migrator"
$secret = New-Object Security.SecureString
$secret.AppendChar("x")
$secret.MakeReadOnly()
$authority = [pscustomobject]@{ PsqlPath = $psql; Port = 0 }

function Assert-MigratorState {
    param([Parameter(Mandatory = $true)][string]$Expected)
    if ($Expected -ceq "reject") {
        $rejected = $false
        try {
            Get-TicketboxDatabaseGenerationMigratorAuthorityState $authority $secret | Out-Null
        }
        catch {
            $rejected = $true
        }
        if (-not $rejected) {
            throw "partial migrator authority was accepted"
        }
        return
    }
    $actual = Get-TicketboxDatabaseGenerationMigratorAuthorityState $authority $secret
    if ($actual -cne $Expected) {
        throw "expected $Expected, observed $actual"
    }
}

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = ([Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()
$authority.Port = $port

$sleeper = $null
$serverStarted = $false
$startAttempted = $false
$primaryFailure = $null
$cleanupFailure = $null
try {
    $initOutput = & $initdb -D $dataDir -U postgres --auth-local=trust --auth-host=trust `
        --encoding=UTF8 --no-locale 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($initOutput -join [Environment]::NewLine)
    }
    Add-Content -LiteralPath (Join-Path $dataDir "postgresql.conf") -Encoding ASCII -Value @"
listen_addresses = '127.0.0.1'
port = $port
"@
    $startStdout = Join-Path $WorkRoot "pg-ctl-start.stdout"
    $startStderr = Join-Path $WorkRoot "pg-ctl-start.stderr"
    $startAttempted = $true
    $startProcess = Start-Process -FilePath $pgCtl -ArgumentList @(
        "start", "-D", $dataDir, "-l", $logPath, "-w", "-t", "30"
    ) -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $startStdout -RedirectStandardError $startStderr
    if (-not $startProcess.WaitForExit(45000)) {
        $startProcess.Kill()
        throw "pg_ctl start timed out"
    }
    $startProcess.WaitForExit()
    if ($startProcess.ExitCode -ne 0) {
        & $pgCtl status -D $dataDir 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw ((Get-Content -LiteralPath $startStdout, $startStderr -Raw) -join [Environment]::NewLine)
        }
    }
    $serverStarted = $true
    if ($PauseAfterStart) {
        if ([string]::IsNullOrWhiteSpace($ServerReadyPath)) {
            throw "ServerReadyPath is required when PauseAfterStart is set"
        }
        [IO.File]::WriteAllText($ServerReadyPath, "ready", [Text.UTF8Encoding]::new($false))
        Start-Sleep -Seconds 120
    }

    $validUntil = [DateTime]::UtcNow.AddMinutes(30).ToString("o")
    Invoke-TestPsql -Database "postgres" -Sql @"
CREATE ROLE ticketbox_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS;
CREATE ROLE ticketbox_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1 PASSWORD 'projection-test'
    VALID UNTIL '$validUntil';
CREATE ROLE ticketbox_runtime NOLOGIN;
CREATE ROLE ticketbox_foreign NOLOGIN;
GRANT ticketbox_owner TO ticketbox_migrator WITH INHERIT FALSE, SET TRUE;
"@ | Out-Null
    Invoke-TestPsql -Database "postgres" `
        -Sql "CREATE DATABASE ticketbox OWNER ticketbox_owner" | Out-Null
    Invoke-TestPsql -Database "postgres" -Sql @"
REVOKE CONNECT ON DATABASE ticketbox FROM PUBLIC;
GRANT CONNECT ON DATABASE ticketbox TO ticketbox_migrator;
"@ | Out-Null
    Assert-MigratorState -Expected "active"

    foreach ($scenario in @(
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator SUPERUSER"
            Cleanup = "ALTER ROLE ticketbox_migrator NOSUPERUSER"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator CREATEDB"
            Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEDB"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator CREATEROLE"
            Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEROLE"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator REPLICATION"
            Cleanup = "ALTER ROLE ticketbox_migrator NOREPLICATION"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator BYPASSRLS"
            Cleanup = "ALTER ROLE ticketbox_migrator NOBYPASSRLS"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator INHERIT"
            Cleanup = "ALTER ROLE ticketbox_migrator NOINHERIT"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 2"
            Cleanup = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 1"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator PASSWORD NULL"
            Cleanup = "ALTER ROLE ticketbox_migrator PASSWORD 'projection-test'"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD 'projection-test'"
            Cleanup = "ALTER ROLE ticketbox_migrator LOGIN PASSWORD 'projection-test'"
        },
        [pscustomobject]@{
            Mutation = "GRANT ticketbox_foreign TO ticketbox_migrator"
            Cleanup = "REVOKE ticketbox_foreign FROM ticketbox_migrator"
        },
        [pscustomobject]@{
            Mutation = "REVOKE CONNECT ON DATABASE ticketbox FROM ticketbox_migrator"
            Cleanup = "GRANT CONNECT ON DATABASE ticketbox TO ticketbox_migrator"
        },
        [pscustomobject]@{
            Mutation = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN TRUE, INHERIT FALSE, SET TRUE"
            Cleanup = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
        },
        [pscustomobject]@{
            Mutation = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
            Cleanup = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
        },
        [pscustomobject]@{
            Mutation = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET FALSE"
            Cleanup = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator VALID UNTIL '2000-01-01T00:00:00Z'"
            Cleanup = "ALTER ROLE ticketbox_migrator VALID UNTIL '$validUntil'"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator VALID UNTIL '2100-01-01T00:00:00Z'"
            Cleanup = "ALTER ROLE ticketbox_migrator VALID UNTIL '$validUntil'"
        }
    )) {
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Mutation | Out-Null
        Assert-MigratorState -Expected "reject"
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Cleanup | Out-Null
        Assert-MigratorState -Expected "active"
    }

    $sleeperStart = New-Object Diagnostics.ProcessStartInfo
    $sleeperStart.FileName = $psql
    $sleeperStart.Arguments = (
        "--no-psqlrc --no-password " +
        "--dbname=postgresql://ticketbox_migrator@127.0.0.1:$port/ticketbox?sslmode=disable " +
        "--command=SELECT/**/pg_sleep(120)"
    )
    $sleeperStart.CreateNoWindow = $true
    $sleeperStart.UseShellExecute = $false
    $sleeper = [Diagnostics.Process]::Start($sleeperStart)
    $sessionObserved = $false
    foreach ($attempt in 1..50) {
        $count = Invoke-TestPsql -Database "postgres" -Sql (
            "SELECT count(*) FROM pg_stat_activity " +
            "WHERE usename = 'ticketbox_migrator' AND datname = 'ticketbox'"
        )
        if ($count -ceq "1") {
            $sessionObserved = $true
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $sessionObserved) {
        throw "migrator session did not become observable"
    }
    Invoke-TestPsql -Database "postgres" -Sql @"
REVOKE CONNECT ON DATABASE ticketbox FROM ticketbox_migrator;
REVOKE ticketbox_owner FROM ticketbox_migrator;
ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD NULL;
"@ | Out-Null
    Assert-MigratorState -Expected "retired_pending_sessions"

    foreach ($scenario in @(
        [pscustomobject]@{
            Mutation = "GRANT ticketbox_foreign TO ticketbox_migrator"
            Cleanup = "REVOKE ticketbox_foreign FROM ticketbox_migrator"
        },
        [pscustomobject]@{
            Mutation = "GRANT CONNECT ON DATABASE ticketbox TO ticketbox_migrator"
            Cleanup = "REVOKE CONNECT ON DATABASE ticketbox FROM ticketbox_migrator"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator SUPERUSER"
            Cleanup = "ALTER ROLE ticketbox_migrator NOSUPERUSER"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator INHERIT"
            Cleanup = "ALTER ROLE ticketbox_migrator NOINHERIT"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator CREATEDB"
            Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEDB"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator CREATEROLE"
            Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEROLE"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator REPLICATION"
            Cleanup = "ALTER ROLE ticketbox_migrator NOREPLICATION"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator BYPASSRLS"
            Cleanup = "ALTER ROLE ticketbox_migrator NOBYPASSRLS"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 2"
            Cleanup = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 1"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator LOGIN PASSWORD NULL"
            Cleanup = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD NULL"
        },
        [pscustomobject]@{
            Mutation = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD 'partial-state'"
            Cleanup = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD NULL"
        }
    )) {
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Mutation | Out-Null
        Assert-MigratorState -Expected "reject"
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Cleanup | Out-Null
    }
    Assert-MigratorState -Expected "retired_pending_sessions"
    $terminated = Invoke-TestPsql -Database "postgres" -Sql (
        "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity " +
        "WHERE usename = 'ticketbox_migrator' AND pid <> pg_backend_pid()"
    )
    if ($terminated -cne "t") {
        throw "migrator backend termination was not acknowledged: $terminated"
    }
    if (-not $sleeper.WaitForExit(10000)) {
        throw "migrator psql frontend did not exit after backend termination"
    }
    $sleeper = $null
    Assert-MigratorState -Expected "retired"
}
catch {
    $primaryFailure = $_
}
finally {
    if ($null -ne $sleeper -and -not $sleeper.HasExited) {
        $sleeper.Kill()
        $sleeper.WaitForExit()
    }
    $mustStop = $serverStarted -or ($startAttempted -and (Test-Path -LiteralPath (Join-Path $dataDir "postmaster.pid")))
    if ($mustStop) {
        $stopOutput = & $pgCtl stop -D $dataDir -m fast -w -t 30 2>&1
        $stopExitCode = $LASTEXITCODE
        $statusOutput = & $pgCtl status -D $dataDir 2>&1
        $statusExitCode = $LASTEXITCODE
        if ($stopExitCode -ne 0 -or $statusExitCode -ne 3) {
            $cleanupFailure = (
                "projection PostgreSQL cleanup failed: stop=$stopExitCode, " +
                "status=$statusExitCode`n" +
                (($stopOutput + $statusOutput) -join [Environment]::NewLine)
            )
        }
    }
}
if ($null -ne $primaryFailure) {
    if ($null -ne $cleanupFailure) {
        throw "$primaryFailure`n$cleanupFailure"
    }
    throw $primaryFailure
}
if ($null -ne $cleanupFailure) {
    throw $cleanupFailure
}
