#Requires -Version 5.1

<#
.SYNOPSIS
  Bounded SCM and PostgreSQL adapters for an isolated restore candidate.
.DESCRIPTION
  Contains only the physical service/database mutations selected by the
  candidate cluster owner. It does not classify restore state or publish
  Dataset/Generation authority.
#>

function Get-TicketboxPostgresqlRestoreCandidateDatabaseBudget {
    $database = [int64]$script:TicketboxPostgresqlDatabaseCommandTimeoutMs
    $catalog = [int64]$script:TicketboxPostgresqlDatabaseCatalogTimeoutMs
    if ($database -lt 1 -or $catalog -lt 1) {
        throw "restore candidate database budget dependencies are unavailable."
    }
    # The optional CREATE is included because a fresh candidate is the longest
    # legal path. Other entries map one-for-one to the calls below.
    $components = [ordered]@{
        role_authority_ms = $database
        catalog_observation_ms = $catalog
        database_creation_ms = $database
        database_admission_ms = $database
        managed_acl_ms = $database
        role_policy_verification_ms = $database
    }
    $total = [int64]0
    foreach ($value in $components.Values) { $total += [int64]$value }
    return [pscustomobject][ordered]@{
        Schema = "ticketbox-postgresql-restore-candidate-database-budget-v1"
        Components = $components
        TotalMilliseconds = $total
    }
}

function Start-TicketboxPostgresqlRestoreCandidateService {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $identity = $Subject.Identity
    $release = $Subject.Release
    $pgBin = Join-Path ([string]$identity.InstallDir) "pg\bin"
    $serviceName = [string]$release.pg_recovery_service_name
    $pgCtl = Join-Path $pgBin "pg_ctl.exe"
    $imagePath = New-TicketboxPgServiceImagePath `
        -PgCtlPath $pgCtl `
        -ServiceName $serviceName `
        -DataRoot ([string]$Paths.candidate_pgdata)
    if (-not (Test-TicketboxServiceExists $serviceName)) {
        Invoke-TicketboxScChecked @(
            "create", $serviceName, "binPath=", $imagePath,
            "start=", "demand", "obj=", ([string]$release.service_logon_account)
        ) | Out-Null
    }
    Assert-TicketboxServiceOwnership $serviceName $pgCtl | Out-Null
    Assert-TicketboxPgServiceCommand `
        -Name $serviceName `
        -ExpectedExecutable $pgCtl `
        -ExpectedServiceName $serviceName `
        -ExpectedDataRoot ([string]$Paths.candidate_pgdata)
    Set-TicketboxServiceIdentityContract `
        -Name $serviceName `
        -LogonAccount ([string]$release.service_logon_account) `
        -SidType ([string]$release.service_sid_type)
    Assert-TicketboxServiceDependencies -Name $serviceName -ExpectedDependencies @()
    $serviceSid = Get-TicketboxServiceSid $serviceName
    Set-TicketboxExactDirectoryAcl `
        -Path ([string]$Paths.candidate_pgdata) `
        -Accounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
        -OwnerAccount "SYSTEM" `
        -Recurse
    Start-TicketboxOwnedServiceIfExists `
        -Name $serviceName `
        -ExpectedExecutable $pgCtl `
        -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$release.service_poll_interval_ms) | Out-Null
    Wait-TicketboxPostgresqlCandidateReady `
        -PgIsReadyPath (Join-Path ([string]$identity.InstallDir) "pg\bin\pg_isready.exe") `
        -Port ([int]$identity.PgPort) `
        -TimeoutMilliseconds ([int]$release.postgres_ready_timeout_ms) `
        -PollMilliseconds ([int]$release.postgres_ready_poll_interval_ms)
}

function Initialize-TicketboxPostgresqlRestoreCandidateDatabase {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][ValidatePattern(
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$BootstrapState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $identity = $Subject.Identity
    $release = $Subject.Release
    $pgBin = Join-Path ([string]$identity.InstallDir) "pg\bin"
    $serviceName = [string]$release.pg_recovery_service_name
    $pgCtl = Join-Path $pgBin "pg_ctl.exe"
    $superuser = ConvertTo-TicketboxPostgresqlSecureString `
        ([string]$BootstrapState.SuperuserPassword) `
        "restore candidate superuser password"
    $authority = [pscustomobject][ordered]@{
        Schema = "ticketbox-postgresql-host-authority-v1"
        PsqlPath = Join-Path ([string]$identity.InstallDir) "pg\bin\psql.exe"
        Port = [int]$identity.PgPort
    }
    try {
        Invoke-TicketboxPostgresqlDatabaseCommand `
            -Authority $authority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $superuser `
            -Label "restore candidate role authority" `
            -Sql (New-TicketboxDatabaseGenerationEmptyRoleSql `
                -OperationId $OperationId `
                -RuntimeVerifier ([string]$Credentials.RuntimeVerifier) `
                -MigratorVerifier ([string]$Credentials.MigratorVerifier) `
                -BackupVerifier ([string]$Credentials.BackupVerifier) `
                -MigratorValidUntilUtc ([DateTime]::UtcNow.AddHours(1))) | Out-Null
        $policy = Get-TicketboxDatabaseAuthorizationContract
        $catalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $superuser `
            -TargetDatabase ([string]$policy.DatabaseName)
        if (-not $catalog.Exists) {
            Invoke-TicketboxPostgresqlDatabaseCommand `
                -Authority $authority `
                -Database "postgres" `
                -Role "postgres" `
                -Password $superuser `
                -Label "restore candidate database creation" `
                -Sql "CREATE DATABASE `"$($policy.DatabaseName)`" OWNER `"$($policy.OwnerRole)`" TEMPLATE template0 ENCODING 'UTF8';" | Out-Null
        }
        Invoke-TicketboxPostgresqlDatabaseCommand `
            -Authority $authority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $superuser `
            -Label "restore candidate database admission" `
            -Sql @"
BEGIN;
REVOKE ALL ON DATABASE "$($policy.DatabaseName)" FROM PUBLIC;
REVOKE ALL ON DATABASE "$($policy.DatabaseName)"
    FROM "$($policy.RuntimeRole)", "$($policy.MigratorRole)";
GRANT CONNECT ON DATABASE "$($policy.DatabaseName)"
    TO "$($policy.MigratorRole)";
COMMIT;
"@ | Out-Null
        Invoke-TicketboxPostgresqlDatabaseCommand `
            -Authority $authority `
            -Database ([string]$policy.DatabaseName) `
            -Role "postgres" `
            -Password $superuser `
            -Label "restore candidate managed ACL" `
            -Sql (New-TicketboxDatabaseRuntimeAclSql -PreserveRuntimeFence) | Out-Null
        Assert-TicketboxDatabaseRolePolicy `
            -Authority $authority `
            -SuperuserPassword $superuser `
            -Phase "fenced"
    }
    catch {
        $superuser.Dispose()
        throw
    }
    return [pscustomobject][ordered]@{
        Authority = $authority
        SuperuserPassword = $superuser
        ServiceName = $serviceName
        PgCtlPath = $pgCtl
    }
}

function Remove-TicketboxPostgresqlRestoreCandidateService {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Paths
    )
    $serviceName = [string]$Subject.Release.pg_recovery_service_name
    if (-not (Test-TicketboxServiceExists $serviceName)) { return }
    $pgCtl = Join-Path ([string]$Subject.Identity.InstallDir) "pg\bin\pg_ctl.exe"
    Assert-TicketboxPgServiceCommand `
        -Name $serviceName `
        -ExpectedExecutable $pgCtl `
        -ExpectedServiceName $serviceName `
        -ExpectedDataRoot ([string]$Paths.candidate_pgdata)
    Assert-TicketboxReleaseServiceIdentity `
        -Name $serviceName `
        -InstalledConfig $Subject.Release `
        -TargetConfig $Subject.Release `
        -AllowTargetSidTypePending | Out-Null
    Remove-TicketboxOwnedServiceIfExists `
        -Name $serviceName `
        -ExpectedExecutable $pgCtl `
        -TimeoutMilliseconds ([int]$Subject.Release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$Subject.Release.service_poll_interval_ms)
}
