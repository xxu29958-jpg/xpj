param(
    [Parameter(Mandatory = $true)][string]$ProjectionPath,
    [Parameter(Mandatory = $true)][string]$ContractPath,
    [Parameter(Mandatory = $true)][string]$CredentialsPath,
    [Parameter(Mandatory = $true)][string]$RetirementPath,
    [Parameter(Mandatory = $true)][string]$ReleaseConfigPath,
    [Parameter(Mandatory = $true)][string]$ServiceLifecyclePath,
    [Parameter(Mandatory = $true)][string]$SingleUserServicePath,
    [Parameter(Mandatory = $true)][string]$ShawlPath,
    [Parameter(Mandatory = $true)][string]$SafetyPath,
    [Parameter(Mandatory = $true)][string]$DatabaseSafetyPath,
    [Parameter(Mandatory = $true)][string]$PgRecoveryToolsPath,
    [Parameter(Mandatory = $true)][string]$DatabaseBindingPath,
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
$script:bootstrapPassword = "projection-admin-password-1234567890"
$script:runtimePassword = "projection-runtime-password-1234567890"
$script:singleUserDiagnosticAttempt = 0
New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null

function Invoke-TestPsql {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Sql,
        [string]$Role = "postgres",
        [string]$PlainPassword = ""
    )
    if ([string]::IsNullOrEmpty($PlainPassword)) {
        $PlainPassword = $script:bootstrapPassword
    }
    $escapedRole = [Uri]::EscapeDataString($Role)
    $escapedDatabase = [Uri]::EscapeDataString($Database)
    $connection = "postgresql://${escapedRole}@127.0.0.1:$port/${escapedDatabase}`?require_auth=scram-sha-256"
    $result = Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile `
        -PsqlPath $psql `
        -DatabaseUrl $connection `
        -Password $PlainPassword `
        -Sql $Sql `
        -Label "projection fixture SQL" `
        -TimeoutMilliseconds 30000
    if ([int]$result.ExitCode -ne 0) {
        throw (
            "projection fixture SQL failed (exit=$($result.ExitCode)):`n" +
            [string]$result.StandardError
        )
    }
    return ([string]$result.StandardOutput).Trim()
}

function Invoke-TestPythonRuntimeObservation {
    param([switch]$ExpectFailure)
    $connection = "postgresql+psycopg://ticketbox_runtime:$script:runtimePassword@127.0.0.1:$port/ticketbox`?sslmode=disable&require_auth=scram-sha-256"
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

. $SafetyPath
. $DatabaseSafetyPath
. $PgRecoveryToolsPath
. $ContractPath
. $CredentialsPath
. $ReleaseConfigPath
. $ServiceLifecyclePath
. $SingleUserServicePath
. $DatabasePolicyPath
. $RetirementPath
. $ProjectionPath
. $DatabaseBindingPath
$script:TicketboxC07DatabaseName = "ticketbox"
$script:TicketboxC07OwnerRole = "ticketbox_owner"
$script:TicketboxC07MigratorRole = "ticketbox_migrator"
$secret = ConvertTo-TicketboxPostgresqlSecureString `
    $script:bootstrapPassword "projection fixture bootstrap password"
$authority = [pscustomobject]@{
    Schema = "ticketbox-postgresql-host-authority-v1"
    PsqlPath = $psql
    PgData = $dataDir
    Port = 0
}

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
        [AllowEmptyString()][string]$ExpectedBootstrapRetirement = '',
        [switch]$ExpectCapabilityFailure
    )
    $observation = Invoke-TestPythonRuntimeObservation
    $identity = @($observation.identity)
    if ($identity.Count -ne 20) {
        throw "runtime generation identity returned the wrong field count"
    }
    $failedCapabilities = @($identity[7..19] | Where-Object { $_ -ne $true })
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
        $identity[6] -cne $ExpectedBootstrapRetirement -or
        $failedCapabilities.Count -ne 0 -or
        [string]$observation.runtime_acl_sha256 -cne $ExpectedAclSha256
    ) {
        Write-Output ($observation | ConvertTo-Json -Compress -Depth 8)
        Write-Output "expected_acl=$ExpectedAclSha256"
        throw "runtime generation identity did not match final live authority"
    }
}

function Start-TestRoleSleeper {
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [string]$PlainPassword = $script:runtimePassword
    )
    $escapedRole = [Uri]::EscapeDataString($Role)
    $escapedPassword = [Uri]::EscapeDataString($PlainPassword)
    $applicationName = "ticketbox_test_role_sleeper_$Role"
    $escapedApplicationName = [Uri]::EscapeDataString($applicationName)
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $psql
    $start.Arguments = (
        "--no-psqlrc --no-password " +
        "--dbname=postgresql://${escapedRole}:${escapedPassword}@127.0.0.1:$port/ticketbox?sslmode=disable&require_auth=scram-sha-256&application_name=$escapedApplicationName " +
        "--command=SELECT/**/pg_sleep(120)"
    )
    $start.CreateNoWindow = $true
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($start)
    foreach ($attempt in 1..50) {
        $count = Invoke-TestPsql -Database "postgres" -Sql (
            "SELECT count(*) FROM pg_stat_activity WHERE " +
            "application_name = '$applicationName' AND usename = '$Role' AND datname = 'ticketbox'"
        )
        if ($count -ceq "1") { return $process }
        Start-Sleep -Milliseconds 100
    }
    if (-not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit()
    }
    $failure = $process.StandardError.ReadToEnd().Trim()
    throw "$Role session did not become observable: $failure"
}

function Stop-TestRoleSleeper {
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process
    )
    $applicationName = "ticketbox_test_role_sleeper_$Role"
    $terminated = Invoke-TestPsql -Database "postgres" -Sql (
        "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity " +
        "WHERE application_name = '$applicationName' AND usename = '$Role' AND pid <> pg_backend_pid()"
    )
    if ($terminated -cne "t") { throw "$Role backend termination was not acknowledged: $terminated" }
    if (-not $Process.WaitForExit(10000)) { throw "$Role psql frontend did not exit" }
}

function Stop-TestPostgresForSingleUser {
    $output = & $pgCtl stop -D $dataDir -m fast -w -t 30 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "could not stop PostgreSQL before single-user retirement: $output"
    }
}

function Start-TestPostgresAfterSingleUser {
    $stdout = Join-Path $WorkRoot "pg-ctl-restart.stdout"
    $stderr = Join-Path $WorkRoot "pg-ctl-restart.stderr"
    $process = Start-Process -FilePath $pgCtl -ArgumentList @(
        "start", "-D", $dataDir, "-l", $logPath, "-w", "-t", "30"
    ) -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if (-not $process.WaitForExit(45000)) {
        $process.Kill()
        throw "pg_ctl restart timed out after single-user retirement"
    }
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        & $pgCtl status -D $dataDir 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw (
                "could not restart PostgreSQL after single-user retirement: " +
                ((Get-Content -LiteralPath $stdout, $stderr -Raw) -join `
                    [Environment]::NewLine)
            )
        }
    }
}

function Invoke-TestSingleUserRetirement {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate
    )
    $serviceName = "TicketboxProjection-$PID"
    $helper = [IO.Path]::GetFullPath($script:singleUserHelper)
    $postgres = [IO.Path]::GetFullPath((Join-Path $PgBin "postgres.exe"))
    $shawl = [IO.Path]::GetFullPath($ShawlPath)
    $powershell = Get-TicketboxWindowsPowerShellExecutable
    $script:singleUserDiagnosticAttempt += 1
    $diagnosticName = "single-user-diagnostic-$($script:singleUserDiagnosticAttempt)"
    $diagnosticPath = Join-Path $WorkRoot ($diagnosticName + ".txt")
    $wrapperPath = Join-Path $installedHelperRoot ($diagnosticName + ".ps1")
    $wrapper = @'
param(
    [Parameter(Mandatory = $true)][string]$PostgresPath,
    [Parameter(Mandatory = $true)][string]$PhysicalPgData,
    [Parameter(Mandatory = $true)][string]$OperationId,
    [Parameter(Mandatory = $true)][string]$IntentSha256,
    [Parameter(Mandatory = $true)][string]$CandidateSha256,
    [Parameter(Mandatory = $true)][string]$CommittedRevision,
    [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds
)
$ErrorActionPreference = 'Stop'
try {
    & '__HELPER__' @PSBoundParameters
    exit 0
}
catch {
    $rendered = ($_ | Format-List * -Force | Out-String)
    [IO.File]::WriteAllText(
        '__DIAGNOSTIC__', $rendered, [Text.UTF8Encoding]::new($false)
    )
    exit 1
}
'@
    $wrapper = $wrapper.Replace("__HELPER__", $helper.Replace("'", "''"))
    $wrapper = $wrapper.Replace(
        "__DIAGNOSTIC__", $diagnosticPath.Replace("'", "''")
    )
    [IO.File]::WriteAllText(
        $wrapperPath, $wrapper, [Text.UTF8Encoding]::new($true)
    )
    Set-TicketboxExactFileAcl `
        -Path $wrapperPath `
        -Accounts @($currentAccount, "NT AUTHORITY\LocalService") `
        -OwnerAccount $currentAccount
    $imagePath = New-TicketboxPostgresqlSingleUserServiceImagePath `
        -ShawlPath $shawl `
        -ServiceName $serviceName `
        -WorkingDirectory (Split-Path -Parent $wrapperPath) `
        -PowerShellPath $powershell `
        -HelperPath $wrapperPath `
        -PostgresPath $postgres `
        -PhysicalPgData $dataDir `
        -OperationId ([string]$Intent.Payload.operation_id) `
        -IntentSha256 ([string]$Intent.PayloadSha256) `
        -CandidateSha256 ([string]$Candidate.PayloadSha256) `
        -CommittedRevision ([string]$Candidate.Payload.target_revision) `
        -StopTimeoutMilliseconds 30000 `
        -OperationTimeoutMilliseconds 30000
    if (Test-TicketboxServiceExists $serviceName) {
        throw "projection one-shot service already exists: $serviceName"
    }
    $created = $false
    $snapshot = $null
    try {
        Invoke-TicketboxScChecked @(
            "create", $serviceName,
            "binPath=", $imagePath,
            "start=", "demand",
            "obj=", "NT AUTHORITY\LocalService"
        ) | Out-Null
        $created = $true
        Set-TicketboxServiceIdentityContract `
            -Name $serviceName `
            -LogonAccount "NT AUTHORITY\LocalService" `
            -SidType "unrestricted"
        Assert-TicketboxPostgresqlSingleUserServiceCommand `
            -Name $serviceName `
            -ExpectedImagePath $imagePath
        $snapshot = Invoke-TicketboxOwnedOneShotService `
            -Name $serviceName `
            -ExpectedExecutable $shawl `
            -ExpectedRuntimeExecutables @($shawl, $postgres) `
            -TimeoutMilliseconds 45000 `
            -PollMilliseconds 100
        if ([uint32]$snapshot.ExitCode -ne 0) {
            $diagnosticText = try {
                if ((Get-TicketboxPathEntryKindNoFollow $diagnosticPath) -cne "File") {
                    "single invocation returned without an error envelope"
                }
                else { [IO.File]::ReadAllText($diagnosticPath) }
            }
            catch { "diagnostic collection failed: " + [string]$_ }
            try {
                $snapshot | Add-Member `
                    -NotePropertyName DiagnosticText `
                    -NotePropertyValue $diagnosticText `
                    -Force
            }
            catch {}
        }
    }
    finally {
        if ($created) {
            Remove-TicketboxOwnedServiceIfExists `
                -Name $serviceName `
                -ExpectedExecutable $shawl `
                -ExpectedRuntimeExecutables @($shawl, $postgres) `
                -TimeoutMilliseconds 45000 `
                -PollMilliseconds 100
        }
    }
    return $snapshot
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
    $bootstrapPasswordPath = Join-Path $WorkRoot "bootstrap-password.txt"
    [IO.File]::WriteAllText(
        $bootstrapPasswordPath,
        $script:bootstrapPassword,
        [Text.UTF8Encoding]::new($false)
    )
    $initOutput = & $initdb -D $dataDir -U postgres --auth-local=trust `
        --auth-host=scram-sha-256 --pwfile=$bootstrapPasswordPath `
        --encoding=UTF8 --no-locale 2>&1
    Remove-Item -LiteralPath $bootstrapPasswordPath -Force
    if ($LASTEXITCODE -ne 0) {
        throw ($initOutput -join [Environment]::NewLine)
    }
    $installedHelperRoot = Join-Path $WorkRoot "installed\installer"
    New-Item -ItemType Directory -Path $installedHelperRoot -Force | Out-Null
    $packagingRoot = Split-Path -Parent ([IO.Path]::GetFullPath($RetirementPath))
    foreach ($name in @(
        "windows_database_generation_single_user.ps1",
        "windows_installation_safety.ps1",
        "windows_security_primitives.ps1",
        "windows_database_safety.ps1",
        "windows_pg_recovery_tools.ps1",
        "windows_database_generation_contract.ps1"
    )) {
        Copy-Item `
            -LiteralPath (Join-Path $packagingRoot $name) `
            -Destination (Join-Path $installedHelperRoot $name)
    }
    $installedSecurityRoot = Join-Path $installedHelperRoot "security_primitives"
    New-Item -ItemType Directory -Path $installedSecurityRoot -Force | Out-Null
    foreach ($name in @(
        "byte_array.ps1",
        "token_privilege_native.ps1",
        "token_privilege.ps1",
        "descriptor_comparison.ps1",
        "descriptor_diagnostic.ps1",
        "file_security.ps1"
    )) {
        Copy-Item `
            -LiteralPath (Join-Path $packagingRoot "security_primitives\$name") `
            -Destination (Join-Path $installedSecurityRoot $name)
    }
    $script:singleUserHelper = Join-Path `
        $installedHelperRoot "windows_database_generation_single_user.ps1"
    $currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    Set-TicketboxExactDirectoryAcl `
        -Path $WorkRoot `
        -Accounts @($currentAccount, "NT AUTHORITY\LocalService") `
        -OwnerAccount $currentAccount `
        -Recurse
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
    $env:PGPASSWORD = $script:bootstrapPassword
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
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1 PASSWORD '$script:runtimePassword'
    VALID UNTIL '$validUntil';
CREATE ROLE ticketbox_runtime NOLOGIN PASSWORD '$script:runtimePassword';
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
        @{ Mutation = "ALTER ROLE ticketbox_migrator PASSWORD NULL"; Cleanup = "ALTER ROLE ticketbox_migrator PASSWORD '$script:runtimePassword'" },
        @{ Mutation = "ALTER ROLE ticketbox_migrator NOLOGIN PASSWORD '$script:runtimePassword'"; Cleanup = "ALTER ROLE ticketbox_migrator LOGIN PASSWORD '$script:runtimePassword'" },
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
        @{ Mutation = "ALTER ROLE ticketbox_owner LOGIN PASSWORD '$script:runtimePassword'"; Cleanup = "ALTER ROLE ticketbox_owner NOLOGIN PASSWORD NULL" },
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
    Invoke-TestPsql -Database "postgres" -Sql (
        "ALTER ROLE ticketbox_owner LOGIN PASSWORD '$script:runtimePassword'"
    ) | Out-Null
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

    $intent = [pscustomobject]@{
        PayloadSha256 = ('a' * 64)
        Payload = [pscustomobject]@{
            operation_id = '33333333-3333-4333-8333-333333333333'
            target_revision = '20260809_0001'
        }
    }
    $candidate = [pscustomobject]@{
        PayloadSha256 = ('c' * 64)
        Payload = [pscustomobject]@{
            operation_id = '33333333-3333-4333-8333-333333333333'
            intent_sha256 = ('a' * 64)
            target_revision = '20260809_0001'
        }
    }
    function Assert-TicketboxLifecycleOperationLease { param($LifecycleLock) }
    $adminSecret = ConvertTo-TicketboxPostgresqlSecureString `
        $script:bootstrapPassword "projection bootstrap password"
    $runtimeSecret = ConvertTo-TicketboxPostgresqlSecureString `
        $script:runtimePassword "projection runtime password"
    try {
        $foreignRetirement = '{"schema":"foreign-generation-retirement-v1"}'
        $foreignRetirementLiteral = ConvertTo-TicketboxC07SqlLiteral $foreignRetirement
        Invoke-TestPsql `
            -Database "postgres" `
            -Sql "COMMENT ON ROLE postgres IS $foreignRetirementLiteral" | Out-Null
        $runtimeCouldForgeRetirement = $false
        try {
            Invoke-TestPsql `
                -Database "postgres" `
                -Sql "COMMENT ON ROLE postgres IS 'forged-runtime-retirement'" `
                -Role "ticketbox_runtime" `
                -PlainPassword $script:runtimePassword | Out-Null
            $runtimeCouldForgeRetirement = $true
        }
        catch {}
        if ($runtimeCouldForgeRetirement) {
            throw "runtime role forged the bootstrap retirement authority"
        }

        Invoke-TestPsql `
            -Database "postgres" `
            -Sql "SELECT 1" `
            -Role "postgres" `
            -PlainPassword $script:bootstrapPassword | Out-Null
        Stop-TestPostgresForSingleUser
        $serverStarted = $false
        $foreignSnapshot = Invoke-TestSingleUserRetirement `
            -Intent $intent -Candidate $candidate
        if (
            [uint32]$foreignSnapshot.ExitCode -ne 1066 -or
            [uint32]$foreignSnapshot.ServiceSpecificExitCode -eq 0 -or
            ([string]$foreignSnapshot.DiagnosticText).IndexOf(
                "bootstrap retirement marker conflict",
                [StringComparison]::Ordinal
            ) -lt 0
        ) {
            throw (
                "foreign retirement marker returned the wrong SCM exit shape: " +
                [uint32]$foreignSnapshot.ExitCode + "/" +
                [uint32]$foreignSnapshot.ServiceSpecificExitCode + "`n" +
                [string]$foreignSnapshot.DiagnosticText
            )
        }
        Start-TestPostgresAfterSingleUser
        $serverStarted = $true
        $observedForeign = Invoke-TestPsql -Database "postgres" -Sql @"
SELECT COALESCE(pg_catalog.shobj_description(role.oid, 'pg_authid'), '')
FROM pg_catalog.pg_roles AS role
WHERE role.rolname = 'postgres';
"@
        if ($observedForeign -cne $foreignRetirement) {
            throw "failed single-user retirement changed the foreign marker"
        }
        Invoke-TestPsql `
            -Database "postgres" `
            -Sql "SELECT 1" `
            -Role "postgres" `
            -PlainPassword $script:bootstrapPassword | Out-Null
        Invoke-TestPsql -Database "postgres" -Sql "COMMENT ON ROLE postgres IS NULL" | Out-Null
        Stop-TestPostgresForSingleUser
        $serverStarted = $false
        $retirementSnapshot = Invoke-TestSingleUserRetirement `
            -Intent $intent -Candidate $candidate
        if (
            [uint32]$retirementSnapshot.ExitCode -ne 0 -or
            [uint32]$retirementSnapshot.ServiceSpecificExitCode -ne 0
        ) {
            throw (
                "single-user retirement service failed: exit=" +
                [uint32]$retirementSnapshot.ExitCode + "/" +
                [uint32]$retirementSnapshot.ServiceSpecificExitCode + "`n" +
                [string]$retirementSnapshot.DiagnosticText
            )
        }
        Start-TestPostgresAfterSingleUser
        $serverStarted = $true
        if (-not (Test-TicketboxDatabaseGenerationBootstrapRetirement `
            $intent $candidate $authority $runtimeSecret)) {
            throw "runtime role did not observe bootstrap retirement"
        }
        Assert-RuntimeObservation `
            $liveIdentity $serverId $dataGeneration $expectedRuntimeAclSha256 `
            -ExpectedBootstrapRetirement (
                Get-TicketboxDatabaseGenerationBootstrapRetirementJson `
                    $intent $candidate
            )
    }
    finally {
        $adminSecret.Dispose()
        $runtimeSecret.Dispose()
    }
    $oldBootstrapPasswordRejected = $false
    try {
        Invoke-TestPsql `
            -Database "postgres" `
            -Sql "SELECT 1" `
            -Role "postgres" `
            -PlainPassword $script:bootstrapPassword | Out-Null
    }
    catch {
        $oldBootstrapPasswordRejected = $true
    }
    if (-not $oldBootstrapPasswordRejected) {
        throw "retired PostgreSQL bootstrap password still authenticated"
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
    $secret.Dispose()
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
