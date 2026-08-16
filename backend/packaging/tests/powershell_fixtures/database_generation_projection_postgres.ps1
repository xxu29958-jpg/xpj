param(
    [Parameter(Mandatory = $true)][string]$ProjectionPath,
    [Parameter(Mandatory = $true)][string]$SafetyPath,
    [Parameter(Mandatory = $true)][string]$AdapterPath,
    [Parameter(Mandatory = $true)][string]$DatabasePolicyPath,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$BackendRoot,
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
    $sqlPath = Join-Path $WorkRoot ([IO.Path]::GetRandomFileName() + ".sql")
    [IO.File]::WriteAllText($sqlPath, $Sql, [Text.UTF8Encoding]::new($false))
    try {
        $output = & $psql --no-psqlrc --no-password --tuples-only --no-align `
            --set ON_ERROR_STOP=1 --dbname $connection --file $sqlPath 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw ($output -join [Environment]::NewLine)
        }
        return ([string]($output -join [Environment]::NewLine)).Trim()
    }
    finally {
        Remove-Item -LiteralPath $sqlPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-TestPythonRuntimeObservation {
    param([switch]$ExpectFailure)
    $connection = "postgresql+psycopg://ticketbox_runtime@127.0.0.1:$port/ticketbox`?sslmode=disable"
    $pythonCode = @'
import json
import sys

sys.path.insert(0, sys.argv[1])
from sqlalchemy import create_engine
from app.database._database_generation_runtime_admission import _observe_live_database

engine = create_engine(sys.argv[2])
try:
    binding, revisions, identity, runtime_acl_sha256 = _observe_live_database(engine)
    print(json.dumps({
        "binding": binding,
        "revisions": list(revisions),
        "identity": list(identity),
        "runtime_acl_sha256": runtime_acl_sha256,
    }, separators=(",", ":")))
finally:
    engine.dispose()
'@
    $previousErrorActionPreference = $ErrorActionPreference
    if ($ExpectFailure) { $ErrorActionPreference = "Continue" }
    $pythonScriptPath = Join-Path $WorkRoot ([IO.Path]::GetRandomFileName() + ".py")
    [IO.File]::WriteAllText(
        $pythonScriptPath,
        $pythonCode,
        [Text.UTF8Encoding]::new($false)
    )
    try {
        $output = & $PythonPath $pythonScriptPath $BackendRoot $connection 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Remove-Item -LiteralPath $pythonScriptPath -Force -ErrorAction SilentlyContinue
    }
    if ($ExpectFailure) {
        if ($exitCode -eq 0) { throw "runtime identity query unexpectedly succeeded" }
        return
    }
    if ($exitCode -ne 0) { throw ($output -join [Environment]::NewLine) }
    return ([string]($output -join [Environment]::NewLine)).Trim() | ConvertFrom-Json
}

. $DatabasePolicyPath

function Invoke-TicketboxC07Sql {
    param($Authority, $Database, $Role, $Password, $Label, $Sql)
    return Invoke-TestPsql -Database $Database -Sql ([string]$Sql)
}

. $SafetyPath
. $ProjectionPath
. $AdapterPath
function ConvertFrom-TicketboxC07SingleRow {
    param($Output, $FieldCount, $Label)
    $lines = @(
        ([string]$Output -split "`r?`n") |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_.Length -gt 0 }
    )
    if ($lines.Count -ne 1) { throw "$Label did not return exactly one row" }
    $fields = @($lines[0].Split([char]9))
    if ($fields.Count -ne $FieldCount) { throw "$Label returned the wrong field count" }
    return $fields
}
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

function Assert-RuntimeObservation {
    param(
        [Parameter(Mandatory = $true)][object]$ExpectedIdentity,
        [Parameter(Mandatory = $true)][string]$ServerId,
        [Parameter(Mandatory = $true)][string]$DataGeneration,
        [Parameter(Mandatory = $true)][string]$ExpectedAclSha256,
        [switch]$ExpectCapabilityFailure
    )
    $observation = Invoke-TestPythonRuntimeObservation
    $identity = @($observation.identity)
    if ($identity.Count -ne 19) {
        throw "runtime generation identity returned the wrong field count"
    }
    $failedCapabilities = @($identity[6..18] | Where-Object { $_ -ne $true })
    if ($ExpectCapabilityFailure) {
        if ($failedCapabilities.Count -eq 0) {
            throw "runtime capability query accepted hostile role state"
        }
        return
    }
    if (
        $identity[0] -cne [string]$ExpectedIdentity.ClusterSystemIdentifier -or
        [uint32]$identity[1] -ne [uint32]$ExpectedIdentity.DatabaseOid -or
        $identity[2] -cne [string]$ExpectedIdentity.DatabaseName -or
        $identity[3] -cne "ticketbox_runtime" -or
        $identity[4] -cne $ServerId -or
        $identity[5] -cne $DataGeneration -or
        $failedCapabilities.Count -ne 0 -or
        [string]$observation.runtime_acl_sha256 -cne $ExpectedAclSha256
    ) {
        Write-Output ($observation | ConvertTo-Json -Compress -Depth 8)
        Write-Output "expected_acl=$ExpectedAclSha256"
        throw "runtime generation identity did not match final live authority"
    }
}

function Start-TestRoleSleeper {
    param([Parameter(Mandatory = $true)][string]$Role)
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $psql
    $start.Arguments = (
        "--no-psqlrc --no-password " +
        "--dbname=postgresql://$Role@127.0.0.1:$port/ticketbox?sslmode=disable " +
        "--command=SELECT/**/pg_sleep(120)"
    )
    $start.CreateNoWindow = $true
    $start.UseShellExecute = $false
    $process = [Diagnostics.Process]::Start($start)
    foreach ($attempt in 1..50) {
        $count = Invoke-TestPsql -Database "postgres" -Sql (
            "SELECT count(*) FROM pg_stat_activity WHERE usename = '$Role' AND datname = 'ticketbox'"
        )
        if ($count -ceq "1") { return $process }
        Start-Sleep -Milliseconds 100
    }
    $process.Kill()
    $process.WaitForExit()
    throw "$Role session did not become observable"
}

function Stop-TestRoleSleeper {
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process
    )
    $terminated = Invoke-TestPsql -Database "postgres" -Sql (
        "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity " +
        "WHERE usename = '$Role' AND pid <> pg_backend_pid()"
    )
    if ($terminated -cne "t") { throw "$Role backend termination was not acknowledged: $terminated" }
    if (-not $Process.WaitForExit(10000)) { throw "$Role psql frontend did not exit" }
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
ALTER ROLE ticketbox_runtime SET search_path = pg_catalog, public;
"@ | Out-Null
    Invoke-TestPsql -Database "postgres" `
        -Sql "CREATE DATABASE ticketbox OWNER ticketbox_owner" | Out-Null
    Invoke-TestPsql -Database "postgres" -Sql @"
REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE ticketbox FROM PUBLIC;
GRANT CONNECT ON DATABASE ticketbox TO ticketbox_migrator;
"@ | Out-Null
    $serverId = "11111111-1111-4111-8111-111111111111"
    $dataGeneration = "22222222-2222-4222-8222-222222222222"
    Invoke-TestPsql -Database "ticketbox" -Sql @"
CREATE TABLE public.app_meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE public.alembic_version (version_num varchar(32) PRIMARY KEY);
CREATE SEQUENCE public.runtime_acl_probe_seq;
CREATE FUNCTION public.runtime_acl_probe() RETURNS integer LANGUAGE sql AS 'SELECT 1';
ALTER SCHEMA public OWNER TO ticketbox_owner;
ALTER TABLE public.app_meta OWNER TO ticketbox_owner;
ALTER TABLE public.alembic_version OWNER TO ticketbox_owner;
ALTER SEQUENCE public.runtime_acl_probe_seq OWNER TO ticketbox_owner;
ALTER FUNCTION public.runtime_acl_probe() OWNER TO ticketbox_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.runtime_acl_probe_seq FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.runtime_acl_probe() FROM PUBLIC;
INSERT INTO public.app_meta (key, value) VALUES
    ('server_id', '$serverId'),
    ('data_generation', '$dataGeneration'),
    ('database_generation_binding', '{}');
INSERT INTO public.alembic_version (version_num) VALUES ('20260809_0001');
REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO ticketbox_runtime;
GRANT USAGE ON SCHEMA public TO ticketbox_runtime;
GRANT SELECT ON public.app_meta, public.alembic_version TO ticketbox_runtime;
"@ | Out-Null
    Invoke-TestPsql -Database "postgres" -Sql @"
ALTER ROLE ticketbox_runtime LOGIN;
GRANT CONNECT ON DATABASE ticketbox TO ticketbox_runtime;
"@ | Out-Null
    $liveIdentity = Get-TicketboxDatabaseGenerationLiveIdentity $authority $secret
    $expectedRuntimeAclSha256 = Get-TicketboxC07RuntimeAclSha256 $authority $secret
    Assert-MigratorState -Expected "active"

    foreach ($scenario in @(
        @{ Mutation = "ALTER ROLE ticketbox_migrator SUPERUSER"; Cleanup = "ALTER ROLE ticketbox_migrator NOSUPERUSER" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator CREATEDB"; Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEDB" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator CREATEROLE"; Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEROLE" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator REPLICATION"; Cleanup = "ALTER ROLE ticketbox_migrator NOREPLICATION" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator BYPASSRLS"; Cleanup = "ALTER ROLE ticketbox_migrator NOBYPASSRLS" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator INHERIT"; Cleanup = "ALTER ROLE ticketbox_migrator NOINHERIT" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 2"; Cleanup = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 1" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator PASSWORD NULL"; Cleanup = "ALTER ROLE ticketbox_migrator PASSWORD 'projection-test'" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD 'projection-test'"; Cleanup = "ALTER ROLE ticketbox_migrator LOGIN PASSWORD 'projection-test'" },
        @{ Mutation = "GRANT ticketbox_foreign TO ticketbox_migrator"; Cleanup = "REVOKE ticketbox_foreign FROM ticketbox_migrator" },
        @{ Mutation = "REVOKE CONNECT ON DATABASE ticketbox FROM ticketbox_migrator"; Cleanup = "GRANT CONNECT ON DATABASE ticketbox TO ticketbox_migrator" },
        @{ Mutation = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN TRUE, INHERIT FALSE, SET TRUE"; Cleanup = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET TRUE" },
        @{ Mutation = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"; Cleanup = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET TRUE" },
        @{ Mutation = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET FALSE"; Cleanup = "GRANT ticketbox_owner TO ticketbox_migrator WITH ADMIN FALSE, INHERIT FALSE, SET TRUE" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator VALID UNTIL '2000-01-01T00:00:00Z'"; Cleanup = "ALTER ROLE ticketbox_migrator VALID UNTIL '$validUntil'" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator VALID UNTIL '2100-01-01T00:00:00Z'"; Cleanup = "ALTER ROLE ticketbox_migrator VALID UNTIL '$validUntil'" }
    )) {
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Mutation | Out-Null
        Assert-MigratorState -Expected "reject"
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Cleanup | Out-Null
        Assert-MigratorState -Expected "active"
    }

    $sleeper = Start-TestRoleSleeper -Role "ticketbox_migrator"
    Invoke-TestPsql -Database "postgres" -Sql @"
REVOKE CONNECT ON DATABASE ticketbox FROM ticketbox_migrator;
REVOKE ticketbox_owner FROM ticketbox_migrator;
ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD NULL;
"@ | Out-Null
    Assert-MigratorState -Expected "retired_pending_sessions"
    Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256 -ExpectCapabilityFailure
    Stop-TestRoleSleeper -Role "ticketbox_migrator" -Process $sleeper
    $sleeper = $null
    Assert-MigratorState -Expected "retired"

    Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256
    Invoke-TestPsql -Database "ticketbox" -Sql (
        "REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system() FROM ticketbox_runtime"
    ) | Out-Null
    Invoke-TestPythonRuntimeObservation -ExpectFailure
    Invoke-TestPsql -Database "ticketbox" -Sql (
        "GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO ticketbox_runtime"
    ) | Out-Null

    foreach ($scenario in @(
        @{ Mutation = "ALTER ROLE ticketbox_runtime SUPERUSER"; Cleanup = "ALTER ROLE ticketbox_runtime NOSUPERUSER" },
        @{ Mutation = "ALTER ROLE ticketbox_runtime CREATEDB"; Cleanup = "ALTER ROLE ticketbox_runtime NOCREATEDB" },
        @{ Mutation = "ALTER ROLE ticketbox_runtime CREATEROLE"; Cleanup = "ALTER ROLE ticketbox_runtime NOCREATEROLE" },
        @{ Mutation = "ALTER ROLE ticketbox_runtime REPLICATION"; Cleanup = "ALTER ROLE ticketbox_runtime NOREPLICATION" },
        @{ Mutation = "ALTER ROLE ticketbox_runtime BYPASSRLS"; Cleanup = "ALTER ROLE ticketbox_runtime NOBYPASSRLS" },
        @{ Mutation = "ALTER ROLE ticketbox_runtime NOINHERIT"; Cleanup = "ALTER ROLE ticketbox_runtime INHERIT" },
        @{ Mutation = "ALTER ROLE ticketbox_runtime CONNECTION LIMIT 2"; Cleanup = "ALTER ROLE ticketbox_runtime CONNECTION LIMIT -1" },
        @{ Mutation = "ALTER ROLE ticketbox_runtime SET search_path = public"; Cleanup = "ALTER ROLE ticketbox_runtime SET search_path = pg_catalog, public" },
        @{ Mutation = "GRANT ticketbox_foreign TO ticketbox_runtime"; Cleanup = "REVOKE ticketbox_foreign FROM ticketbox_runtime" }
    )) {
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Mutation | Out-Null
        Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256 -ExpectCapabilityFailure
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Cleanup | Out-Null
        Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256
    }
    Invoke-TestPsql -Database "postgres" -Sql "ALTER ROLE ticketbox_runtime NOLOGIN" | Out-Null
    Invoke-TestPythonRuntimeObservation -ExpectFailure
    Invoke-TestPsql -Database "postgres" -Sql "ALTER ROLE ticketbox_runtime LOGIN" | Out-Null

    foreach ($scenario in @(
        @{ Mutation = "ALTER ROLE ticketbox_owner LOGIN PASSWORD 'hostile-owner'"; Cleanup = "ALTER ROLE ticketbox_owner NOLOGIN PASSWORD NULL" },
        @{ Mutation = "ALTER ROLE ticketbox_owner INHERIT"; Cleanup = "ALTER ROLE ticketbox_owner NOINHERIT" },
        @{ Mutation = "ALTER ROLE ticketbox_owner SUPERUSER"; Cleanup = "ALTER ROLE ticketbox_owner NOSUPERUSER" },
        @{ Mutation = "ALTER ROLE ticketbox_owner CREATEDB"; Cleanup = "ALTER ROLE ticketbox_owner NOCREATEDB" },
        @{ Mutation = "ALTER ROLE ticketbox_owner CREATEROLE"; Cleanup = "ALTER ROLE ticketbox_owner NOCREATEROLE" },
        @{ Mutation = "ALTER ROLE ticketbox_owner REPLICATION"; Cleanup = "ALTER ROLE ticketbox_owner NOREPLICATION" },
        @{ Mutation = "ALTER ROLE ticketbox_owner BYPASSRLS"; Cleanup = "ALTER ROLE ticketbox_owner NOBYPASSRLS" },
        @{ Mutation = "ALTER ROLE ticketbox_owner CONNECTION LIMIT 2"; Cleanup = "ALTER ROLE ticketbox_owner CONNECTION LIMIT -1" },
        @{ Mutation = "GRANT ticketbox_owner TO ticketbox_foreign"; Cleanup = "REVOKE ticketbox_owner FROM ticketbox_foreign" },
        @{ Mutation = "GRANT ticketbox_foreign TO ticketbox_owner"; Cleanup = "REVOKE ticketbox_foreign FROM ticketbox_owner" }
    )) {
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Mutation | Out-Null
        Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256 -ExpectCapabilityFailure
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Cleanup | Out-Null
        Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256
    }
    Invoke-TestPsql -Database "postgres" -Sql "ALTER ROLE ticketbox_owner LOGIN" | Out-Null
    $sleeper = Start-TestRoleSleeper -Role "ticketbox_owner"
    Invoke-TestPsql -Database "postgres" -Sql "ALTER ROLE ticketbox_owner NOLOGIN" | Out-Null
    Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256 -ExpectCapabilityFailure
    Stop-TestRoleSleeper -Role "ticketbox_owner" -Process $sleeper
    $sleeper = $null
    Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256

    foreach ($scenario in @(
        @{ Mutation = "GRANT TRUNCATE ON public.app_meta TO ticketbox_runtime"; Cleanup = "REVOKE TRUNCATE ON public.app_meta FROM ticketbox_runtime" },
        @{ Mutation = "GRANT UPDATE ON public.app_meta TO ticketbox_runtime"; Cleanup = "REVOKE UPDATE ON public.app_meta FROM ticketbox_runtime" },
        @{ Mutation = "GRANT DELETE ON public.app_meta TO ticketbox_runtime"; Cleanup = "REVOKE DELETE ON public.app_meta FROM ticketbox_runtime" },
        @{ Mutation = "GRANT UPDATE ON SEQUENCE public.runtime_acl_probe_seq TO ticketbox_runtime"; Cleanup = "REVOKE UPDATE ON SEQUENCE public.runtime_acl_probe_seq FROM ticketbox_runtime" },
        @{ Mutation = "GRANT EXECUTE ON FUNCTION public.runtime_acl_probe() TO ticketbox_runtime"; Cleanup = "REVOKE EXECUTE ON FUNCTION public.runtime_acl_probe() FROM ticketbox_runtime" },
        @{ Mutation = "GRANT CREATE ON DATABASE ticketbox TO ticketbox_runtime"; Cleanup = "REVOKE CREATE ON DATABASE ticketbox FROM ticketbox_runtime" },
        @{ Mutation = "GRANT TEMPORARY ON DATABASE ticketbox TO ticketbox_runtime"; Cleanup = "REVOKE TEMPORARY ON DATABASE ticketbox FROM ticketbox_runtime" },
        @{ Mutation = "GRANT CREATE ON SCHEMA public TO ticketbox_runtime"; Cleanup = "REVOKE CREATE ON SCHEMA public FROM ticketbox_runtime" }
    )) {
        Invoke-TestPsql -Database "ticketbox" -Sql $scenario.Mutation | Out-Null
        $runtimeAclMutation = Invoke-TestPythonRuntimeObservation
        if ([string]$runtimeAclMutation.runtime_acl_sha256 -ceq $expectedRuntimeAclSha256) {
            throw "runtime ACL digest accepted privilege drift: $($scenario.Mutation)"
        }
        Invoke-TestPsql -Database "ticketbox" -Sql $scenario.Cleanup | Out-Null
        Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256
    }

    foreach ($scenario in @(
        @{ Mutation = "GRANT ticketbox_foreign TO ticketbox_migrator"; Cleanup = "REVOKE ticketbox_foreign FROM ticketbox_migrator" },
        @{ Mutation = "GRANT CONNECT ON DATABASE ticketbox TO ticketbox_migrator"; Cleanup = "REVOKE CONNECT ON DATABASE ticketbox FROM ticketbox_migrator" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator SUPERUSER"; Cleanup = "ALTER ROLE ticketbox_migrator NOSUPERUSER" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator INHERIT"; Cleanup = "ALTER ROLE ticketbox_migrator NOINHERIT" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator CREATEDB"; Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEDB" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator CREATEROLE"; Cleanup = "ALTER ROLE ticketbox_migrator NOCREATEROLE" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator REPLICATION"; Cleanup = "ALTER ROLE ticketbox_migrator NOREPLICATION" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator BYPASSRLS"; Cleanup = "ALTER ROLE ticketbox_migrator NOBYPASSRLS" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 2"; Cleanup = "ALTER ROLE ticketbox_migrator CONNECTION LIMIT 1" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator LOGIN PASSWORD NULL"; Cleanup = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD NULL" },
        @{
            Mutation = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD 'partial-state'"
            Cleanup = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD NULL"
            RuntimeObservable = $false
        }
    )) {
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Mutation | Out-Null
        Assert-MigratorState -Expected "reject"
        if ($scenario.RuntimeObservable -cne $false) {
            Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256 -ExpectCapabilityFailure
        }
        Invoke-TestPsql -Database "postgres" -Sql $scenario.Cleanup | Out-Null
        Assert-MigratorState -Expected "retired"
        Assert-RuntimeObservation $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256
    }
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
