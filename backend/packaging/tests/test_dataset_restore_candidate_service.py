from __future__ import annotations

from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
RUNTIME = PACKAGING / "windows_postgresql_candidate_runtime.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_candidate_service_executes_exact_scm_acl_and_readiness_contract(
    tmp_path: Path,
) -> None:
    starter = powershell_function(
        RUNTIME.read_text(encoding="utf-8-sig"),
        "Start-TicketboxPostgresqlRestoreCandidateService",
    )
    root = str(tmp_path.resolve()).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$root = Join-Path '{root}' "$($PSVersionTable.PSEdition)-$($PSVersionTable.PSVersion.Major)"
$candidatePg = Join-Path $root 'candidate\pgdata'
$install = Join-Path $root 'install'
$pgCtl = Join-Path $install 'pg\bin\pg_ctl.exe'
$pgIsReady = Join-Path $install 'pg\bin\pg_isready.exe'
$script:events = @()
$script:servicePresent = $false
$script:createCount = 0
function Assert-TicketboxLifecycleOperationLease {{
    param($Lock)
    if ([string]$Lock -cne 'lock') {{ throw 'wrong lifecycle lease' }}
    $script:events += 'lease'
}}
function New-TicketboxPgServiceImagePath {{
    param($PgCtlPath, $ServiceName, $DataRoot)
    if (
        [string]$PgCtlPath -cne $pgCtl -or
        [string]$ServiceName -cne 'TicketboxRestore' -or
        [string]$DataRoot -cne $candidatePg
    ) {{ throw 'service image authority drifted' }}
    return 'candidate-service-image'
}}
function Test-TicketboxServiceExists {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong service existence probe' }}
    return $script:servicePresent
}}
function Invoke-TicketboxScChecked {{
    $values = @($args[0])
    if (($values -join '|') -cne 'create|TicketboxRestore|binPath=|candidate-service-image|start=|demand|obj=|LocalSystem') {{
        throw "unexpected SCM create: $($values -join '|')"
    }}
    $script:events += 'scm-create'
    $script:servicePresent = $true
    $script:createCount += 1
}}
function Assert-TicketboxServiceOwnership {{
    param($Name, $ExpectedExecutable)
    if ([string]$Name -cne 'TicketboxRestore' -or [string]$ExpectedExecutable -cne $pgCtl) {{
        throw 'service ownership drifted'
    }}
    $script:events += 'ownership'
}}
function Assert-TicketboxPgServiceCommand {{
    param($Name, $ExpectedExecutable, $ExpectedServiceName, $ExpectedDataRoot)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        [string]$ExpectedExecutable -cne $pgCtl -or
        [string]$ExpectedServiceName -cne 'TicketboxRestore' -or
        [string]$ExpectedDataRoot -cne $candidatePg
    ) {{ throw 'service command drifted' }}
    $script:events += 'command'
}}
function Set-TicketboxServiceIdentityContract {{
    param($Name, $LogonAccount, $SidType)
    if ([string]$Name -cne 'TicketboxRestore' -or [string]$LogonAccount -cne 'LocalSystem' -or [string]$SidType -cne 'unrestricted') {{
        throw 'service identity drifted'
    }}
    $script:events += 'identity'
}}
function Assert-TicketboxServiceDependencies {{
    param($Name, $ExpectedDependencies)
    if ([string]$Name -cne 'TicketboxRestore' -or @($ExpectedDependencies).Count -ne 0) {{
        throw 'service dependencies drifted'
    }}
    $script:events += 'dependencies'
}}
function Get-TicketboxServiceSid {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong service SID probe' }}
    return 'NT SERVICE\TicketboxRestore'
}}
function Set-TicketboxExactDirectoryAcl {{
    param($Path, $Accounts, $OwnerAccount, [switch]$Recurse)
    if (
        [string]$Path -cne $candidatePg -or
        (@($Accounts) -join '|') -cne 'SYSTEM|BUILTIN\Administrators|NT SERVICE\TicketboxRestore' -or
        [string]$OwnerAccount -cne 'SYSTEM' -or
        -not $Recurse
    ) {{ throw 'candidate ACL drifted' }}
    $script:events += 'acl'
}}
function Start-TicketboxOwnedServiceIfExists {{
    param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        [string]$ExpectedExecutable -cne $pgCtl -or
        [int]$TimeoutMilliseconds -ne 1000 -or
        [int]$PollMilliseconds -ne 10
    ) {{ throw 'service start drifted' }}
    $script:events += 'start'
}}
function Wait-TicketboxPostgresqlCandidateReady {{
    param($PgIsReadyPath, $Port, $TimeoutMilliseconds, $PollMilliseconds)
    if (
        [string]$PgIsReadyPath -cne $pgIsReady -or
        [int]$Port -ne 5432 -or
        [int]$TimeoutMilliseconds -ne 2000 -or
        [int]$PollMilliseconds -ne 20
    ) {{ throw 'candidate readiness drifted' }}
    $script:events += 'ready'
}}
{starter}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = $install; PgPort = 5432 }}
    Release = [pscustomobject]@{{
        pg_recovery_service_name = 'TicketboxRestore'
        service_logon_account = 'LocalSystem'
        service_sid_type = 'unrestricted'
        service_state_timeout_ms = 1000
        service_poll_interval_ms = 10
        postgres_ready_timeout_ms = 2000
        postgres_ready_poll_interval_ms = 20
    }}
}}
$paths = [pscustomobject]@{{ candidate_pgdata = $candidatePg }}
Start-TicketboxPostgresqlRestoreCandidateService $subject $paths 'lock'
$expected = 'lease|scm-create|ownership|command|identity|dependencies|acl|start|ready'
if (($script:events -join '|') -cne $expected) {{
    throw "candidate service path incomplete: $($script:events -join '|')"
}}
if ($script:createCount -ne 1) {{ throw 'candidate service was not created exactly once' }}
$script:events = @()
Start-TicketboxPostgresqlRestoreCandidateService $subject $paths 'lock'
$retryExpected = 'lease|ownership|command|identity|dependencies|acl|start|ready'
if (($script:events -join '|') -cne $retryExpected -or $script:createCount -ne 1) {{
    throw "existing candidate service was recreated: $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-candidate-service.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_candidate_database_executes_absent_existing_and_secret_lifetime(
    tmp_path: Path,
) -> None:
    initializer = powershell_function(
        RUNTIME.read_text(encoding="utf-8-sig"),
        "Initialize-TicketboxPostgresqlRestoreCandidateDatabase",
    )
    root = str(tmp_path.resolve()).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$root = Join-Path '{root}' "$($PSVersionTable.PSEdition)-$($PSVersionTable.PSVersion.Major)"
$install = Join-Path $root 'install'
$script:events = @()
$script:commands = @()
$script:catalogExists = $false
$script:disposeCount = 0
$script:failLabel = ''
$script:activeSecret = $null
function Assert-TicketboxLifecycleOperationLease {{
    param($Lock)
    if ([string]$Lock -cne 'lock') {{ throw 'wrong lifecycle lease' }}
    $script:events += 'lease'
}}
function ConvertTo-TicketboxPostgresqlSecureString {{
    param($Text, $Label)
    if ([string]$Text -cne 'protected-secret' -or [string]$Label -cne 'restore candidate superuser password') {{
        throw 'superuser secret binding drifted'
    }}
    $secret = [pscustomobject]@{{ Value = [string]$Text }}
    $secret | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ $script:disposeCount += 1 }}
    $script:activeSecret = $secret
    return $secret
}}
function New-TicketboxDatabaseGenerationEmptyRoleSql {{
    param($OperationId, $RuntimeVerifier, $MigratorVerifier, $BackupVerifier, $MigratorValidUntilUtc)
    if (
        [string]$OperationId -cne '11111111-1111-4111-8111-111111111111' -or
        [string]$RuntimeVerifier -cne 'runtime-verifier' -or
        [string]$MigratorVerifier -cne 'migrator-verifier' -or
        [string]$BackupVerifier -cne 'backup-verifier' -or
        $MigratorValidUntilUtc -le [DateTime]::UtcNow
    ) {{ throw 'role SQL inputs drifted' }}
    return 'ROLE-SQL'
}}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{
        DatabaseName = 'ticketbox'
        OwnerRole = 'ticketbox_owner'
        RuntimeRole = 'ticketbox_runtime'
        MigratorRole = 'ticketbox_migrator'
    }}
}}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{
    param($Authority, $SuperuserPassword, $TargetDatabase)
    if ([int]$Authority.Port -ne 5432 -or $SuperuserPassword -ne $script:activeSecret -or [string]$TargetDatabase -cne 'ticketbox') {{
        throw 'catalog authority drifted'
    }}
    return [pscustomobject]@{{ Exists = $script:catalogExists }}
}}
function New-TicketboxDatabaseRuntimeAclSql {{
    param([switch]$PreserveRuntimeFence)
    if (-not $PreserveRuntimeFence) {{ throw 'runtime fence was not preserved' }}
    return 'ACL-SQL'
}}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    param($Authority, $Database, $Role, $Password, $Label, $Sql)
    if (
        [string]$Authority.Schema -cne 'ticketbox-postgresql-host-authority-v1' -or
        [int]$Authority.Port -ne 5432 -or
        [string]$Authority.PsqlPath -cne (Join-Path $install 'pg\bin\psql.exe') -or
        [string]$Role -cne 'postgres' -or
        $Password -ne $script:activeSecret
    ) {{ throw 'database command authority drifted' }}
    if ([string]$Label -ceq $script:failLabel) {{ throw 'expected database command failure' }}
    $script:commands += [pscustomobject]@{{ Database = [string]$Database; Label = [string]$Label; Sql = [string]$Sql }}
}}
function Assert-TicketboxDatabaseRolePolicy {{
    param($Authority, $SuperuserPassword, $Phase)
    if ([int]$Authority.Port -ne 5432 -or $SuperuserPassword -ne $script:activeSecret -or [string]$Phase -cne 'fenced') {{
        throw 'role policy drifted'
    }}
    $script:events += 'policy'
}}
{initializer}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = $install; PgPort = 5432 }}
    Release = [pscustomobject]@{{ pg_recovery_service_name = 'TicketboxRestore' }}
}}
$credentials = [pscustomobject]@{{
    RuntimeVerifier = 'runtime-verifier'
    MigratorVerifier = 'migrator-verifier'
    BackupVerifier = 'backup-verifier'
}}
$bootstrap = [pscustomobject]@{{ SuperuserPassword = 'protected-secret' }}
$result = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
    $subject '11111111-1111-4111-8111-111111111111' $credentials $bootstrap 'lock'
$labels = @($script:commands | ForEach-Object {{ $_.Label }}) -join '|'
if ($labels -cne 'restore candidate role authority|restore candidate database creation|restore candidate database admission|restore candidate managed ACL') {{
    throw "absent catalog path drifted: $labels"
}}
$databases = @($script:commands | ForEach-Object {{ $_.Database }}) -join '|'
if ($databases -cne 'postgres|postgres|postgres|ticketbox') {{
    throw "absent catalog database routing drifted: $databases"
}}
$creation = @($script:commands | Where-Object {{ $_.Label -ceq 'restore candidate database creation' }})[0]
if ($creation.Sql -cnotlike '*CREATE DATABASE*OWNER*ticketbox_owner*TEMPLATE template0*') {{ throw 'creation SQL drifted' }}
$admission = @($script:commands | Where-Object {{ $_.Label -ceq 'restore candidate database admission' }})[0]
if ($admission.Sql -cnotlike '*REVOKE ALL ON DATABASE*GRANT CONNECT*ticketbox_migrator*') {{ throw 'admission SQL drifted' }}
if (
    [string]$result.ServiceName -cne 'TicketboxRestore' -or
    [string]$result.PgCtlPath -cne (Join-Path $install 'pg\bin\pg_ctl.exe') -or
    [int]$result.Authority.Port -ne 5432 -or
    $result.SuperuserPassword -ne $script:activeSecret -or
    $script:disposeCount -ne 0
) {{ throw 'candidate database result or secret lifetime drifted' }}
$result.SuperuserPassword.Dispose()
if ($script:disposeCount -ne 1) {{ throw 'caller could not retire returned secret' }}

$script:commands = @()
$script:catalogExists = $true
$existing = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
    $subject '11111111-1111-4111-8111-111111111111' $credentials $bootstrap 'lock'
$existingLabels = @($script:commands | ForEach-Object {{ $_.Label }}) -join '|'
if ($existingLabels -cne 'restore candidate role authority|restore candidate database admission|restore candidate managed ACL') {{
    throw "existing catalog path drifted: $existingLabels"
}}
$existingDatabases = @($script:commands | ForEach-Object {{ $_.Database }}) -join '|'
if ($existingDatabases -cne 'postgres|postgres|ticketbox') {{
    throw "existing catalog database routing drifted: $existingDatabases"
}}
$existing.SuperuserPassword.Dispose()
if ($script:disposeCount -ne 2) {{ throw 'existing-path secret lifetime drifted' }}

$script:commands = @()
$script:catalogExists = $true
$script:failLabel = 'restore candidate database admission'
$failed = $false
try {{
    Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
        $subject '11111111-1111-4111-8111-111111111111' $credentials $bootstrap 'lock' | Out-Null
}} catch {{ $failed = $true }}
if (-not $failed -or $script:disposeCount -ne 3) {{ throw 'failed database initialization leaked its secret' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-candidate-database.ps1",
    )
