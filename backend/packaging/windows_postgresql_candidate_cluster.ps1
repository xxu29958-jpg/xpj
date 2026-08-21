#Requires -Version 5.1

<#
.SYNOPSIS
  Bounded PostgreSQL cluster mechanisms used by install and dataset restore.
.DESCRIPTION
  This adapter owns cluster initialization, loopback configuration, and the
  temporary recovery SCM projection.  Dataset identity and CURRENT publication
  remain outside this module.
#>

function Assert-TicketboxPostgresqlLoopbackConfigurationSafe {
    param([Parameter(Mandatory = $true)][string]$PgData)
    $autoConfigPath = Join-Path $PgData "postgresql.auto.conf"
    if (-not (Test-Path -LiteralPath $autoConfigPath -PathType Leaf)) { return }
    $autoConfig = [IO.File]::ReadAllText($autoConfigPath, [Text.Encoding]::ASCII)
    if ($autoConfig -match '(?m)^\s*(?:listen_addresses|port)\s*=') {
        throw "postgresql.auto.conf overrides the managed loopback/port boundary."
    }
}

function Set-TicketboxPostgresqlLoopbackConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$PgData,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )
    $configPath = Join-Path $PgData "postgresql.conf"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "PostgreSQL cluster lacks postgresql.conf."
    }
    $beginMarker = "# BEGIN Ticketbox installer overrides"
    $endMarker = "# END Ticketbox installer overrides"
    $legacyMarker = "# Ticketbox installer overrides"
    $newLine = [Environment]::NewLine
    $block = @(
        $beginMarker
        "listen_addresses = '127.0.0.1'"
        "port = $Port"
        $endMarker
    ) -join $newLine
    Assert-TicketboxPostgresqlLoopbackConfigurationSafe -PgData $PgData
    $content = [IO.File]::ReadAllText($configPath, [Text.Encoding]::ASCII)
    $markerIndex = $content.IndexOf($beginMarker, [StringComparison]::Ordinal)
    if ($markerIndex -ge 0) {
        if (
            $content.IndexOf(
                $beginMarker, $markerIndex + $beginMarker.Length,
                [StringComparison]::Ordinal
            ) -ge 0 -or
            $content.IndexOf($legacyMarker, [StringComparison]::Ordinal) -ge 0
        ) {
            throw "PostgreSQL managed configuration marker is ambiguous."
        }
        $endIndex = $content.IndexOf(
            $endMarker, $markerIndex + $beginMarker.Length,
            [StringComparison]::Ordinal
        )
        if ($endIndex -lt 0) {
            throw "PostgreSQL managed configuration block is truncated."
        }
        $without = $content.Substring(0, $markerIndex) +
            $content.Substring($endIndex + $endMarker.Length)
    }
    else {
        $legacyIndex = $content.IndexOf($legacyMarker, [StringComparison]::Ordinal)
        if ($legacyIndex -ge 0) {
            $escaped = [regex]::Escape($legacyMarker)
            $listen = "[ `t]*listen_addresses[ `t]*=[^`r`n]*`r?`n"
            $portLine = "[ `t]*port[ `t]*=[^`r`n]*(?:`r?`n)?"
            $legacyMatches = @(
                [regex]::Match($content, "(?m)^$escaped`r?`n$listen$portLine")
                [regex]::Match($content, "(?m)^$escaped`r?`n$portLine$listen")
            ) | Where-Object { $_.Success }
            if (
                $legacyMatches.Count -ne 1 -or
                $legacyMatches[0].Index -ne $legacyIndex
            ) {
                throw "PostgreSQL legacy managed configuration is ambiguous."
            }
            $without = $content.Substring(0, $legacyMatches[0].Index) +
                $content.Substring(
                    $legacyMatches[0].Index + $legacyMatches[0].Length
                )
        }
        else { $without = $content }
    }
    $updated = $without.TrimEnd() + $newLine + $newLine + $block + $newLine
    Write-TicketboxFileAtomically `
        -Path $configPath `
        -Bytes ([Text.Encoding]::ASCII.GetBytes($updated))
    $persisted = [IO.File]::ReadAllText($configPath, [Text.Encoding]::ASCII)
    if (-not $persisted.TrimEnd().EndsWith($block, [StringComparison]::Ordinal)) {
        throw "PostgreSQL managed configuration did not persist exactly."
    }
}

function Wait-TicketboxPostgresqlCandidateReady {
    param(
        [Parameter(Mandatory = $true)][string]$PgIsReadyPath,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds
    )
    $deadline = New-TicketboxWaitDeadline $TimeoutMilliseconds
    do {
        $remaining = [Math]::Max(
            1000, $TimeoutMilliseconds - $deadline.ElapsedMilliseconds
        )
        $probe = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $PgIsReadyPath `
            -Arguments @("-h", "127.0.0.1", "-p", [string]$Port, "-q") `
            -TimeoutMilliseconds ([int][Math]::Min(5000, $remaining)) `
            -Label "restore candidate PostgreSQL readiness" `
            -ChildEnvironment @{}
        if ([int]$probe.ExitCode -eq 0) { return }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds)
    throw "restore candidate PostgreSQL did not become ready."
}

function Initialize-TicketboxPostgresqlRestoreCandidateCluster {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][ValidatePattern(
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$BootstrapState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $identity = $Subject.Identity
    $release = $Subject.Release
    $expectedPaths = Get-TicketboxInstalledDatasetRestorePaths `
        ([string]$identity.DataRoot) $OperationId
    if (
        -not (Test-TicketboxPathEquals $Paths.candidate_pgdata $expectedPaths.candidate_pgdata) -or
        -not (Test-TicketboxPathEquals $Paths.candidate_uploads $expectedPaths.candidate_uploads)
    ) {
        throw "restore candidate paths escaped the exact operation root."
    }
    [IO.Directory]::CreateDirectory([string]$Paths.candidate_root) | Out-Null
    $candidateKind = Get-TicketboxPathEntryKindNoFollow $Paths.candidate_pgdata
    if ($candidateKind -notin @("Missing", "Directory")) {
        throw "restore candidate PGDATA is not a plain directory."
    }
    $pgBin = Join-Path ([string]$identity.InstallDir) "pg\bin"
    $initdb = Join-Path $pgBin "initdb.exe"
    $shawl = Join-Path ([string]$identity.InstallDir) "shawl\shawl.exe"
    $serviceName = [string]$release.pg_recovery_service_name
    $pwfile = Join-Path ([string]$Paths.candidate_root) ".initdb-password"
    $pgVersion = Join-Path ([string]$Paths.candidate_pgdata) "PG_VERSION"
    $initdbImage = New-TicketboxInitdbServiceImagePath `
        -ShawlPath $shawl `
        -ServiceName $serviceName `
        -WorkingDirectory $pgBin `
        -InitdbPath $initdb `
        -DataRoot ([string]$Paths.candidate_pgdata) `
        -PasswordFile $pwfile `
        -StopTimeoutMs ([int]$release.stop_timeout_ms)
    $initdbServicePresent = Test-TicketboxServiceExists $serviceName
    $ownedServiceExecutable = $null
    if ($initdbServicePresent) {
        $actualExecutable = Get-TicketboxServiceExecutablePath $serviceName
        if (Test-TicketboxPathEquals $actualExecutable $shawl) {
            $ownedServiceExecutable = $shawl
            Assert-TicketboxInitdbServiceCommand `
                -Name $serviceName `
                -ExpectedShawl $shawl `
                -ExpectedServiceName $serviceName `
                -ExpectedWorkingDirectory $pgBin `
                -ExpectedInitdb $initdb `
                -ExpectedDataRoot ([string]$Paths.candidate_pgdata) `
                -ExpectedPasswordFile $pwfile `
                -ExpectedStopTimeoutMs ([int]$release.stop_timeout_ms) `
                -ExpectedImagePath $initdbImage
            Assert-TicketboxReleaseServiceIdentity `
                -Name $serviceName `
                -InstalledConfig $release `
                -TargetConfig $release `
                -AllowTargetSidTypePending | Out-Null
            Set-TicketboxServiceIdentityContract `
                -Name $serviceName `
                -LogonAccount ([string]$release.service_logon_account) `
                -SidType ([string]$release.service_sid_type)
            Assert-TicketboxServiceStartMode `
                -Name $serviceName -ExpectedStartMode "Manual"
            Assert-TicketboxServiceHasNoFailureActions $serviceName
            $snapshot = Get-TicketboxServiceRuntimeSnapshot $serviceName
            if ([string]$snapshot.State -cne "stopped") {
                $deadline = New-TicketboxWaitDeadline `
                    ([int]$release.database_tool_timeout_ms)
                do {
                    $snapshot = Get-TicketboxServiceRuntimeSnapshot $serviceName
                    if ([string]$snapshot.State -ceq "stopped") { break }
                } while (Wait-TicketboxPollBeforeDeadline `
                    -Deadline $deadline `
                    -TimeoutMilliseconds ([int]$release.database_tool_timeout_ms) `
                    -PollMilliseconds ([int]$release.service_poll_interval_ms))
                if ([string]$snapshot.State -cne "stopped") {
                    throw "restore candidate initdb service did not reach a terminal state."
                }
            }
            if (
                [uint32]$snapshot.ExitCode -ne 0 -or
                [uint32]$snapshot.ServiceSpecificExitCode -ne 0
            ) {
                $failedServiceSid = Get-TicketboxServiceSid $serviceName
                if ((Get-TicketboxPathEntryKindNoFollow $pwfile) -ceq "File") {
                    Remove-TicketboxProtectedUtf8Artifact `
                        -Path $pwfile `
                        -FullControlAccounts @(
                            "SYSTEM", "BUILTIN\Administrators", $failedServiceSid
                        ) `
                        -OwnerAccount "SYSTEM"
                }
                Remove-TicketboxOwnedServiceIfExists `
                    -Name $serviceName `
                    -ExpectedExecutable $shawl `
                    -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
                    -PollMilliseconds ([int]$release.service_poll_interval_ms)
                if ($candidateKind -ceq "Directory") {
                    Remove-TicketboxDataRootExact -Path ([string]$Paths.candidate_pgdata)
                    $candidateKind = "Missing"
                }
                $initdbServicePresent = $false
            }
        }
        else {
            $pgCtl = Join-Path $pgBin "pg_ctl.exe"
            if (-not (Test-TicketboxPathEquals $actualExecutable $pgCtl)) {
                throw "restore candidate recovery service executable is foreign."
            }
            Assert-TicketboxPgServiceCommand `
                -Name $serviceName `
                -ExpectedExecutable $pgCtl `
                -ExpectedServiceName $serviceName `
                -ExpectedDataRoot ([string]$Paths.candidate_pgdata)
            Assert-TicketboxReleaseServiceIdentity `
                -Name $serviceName `
                -InstalledConfig $release `
                -TargetConfig $release `
                -AllowTargetSidTypePending | Out-Null
            $ownedServiceExecutable = $pgCtl
        }
    }
    if ((Get-TicketboxPathEntryKindNoFollow $pgVersion) -cne "File") {
        if ($initdbServicePresent) {
            Remove-TicketboxOwnedServiceIfExists `
                -Name $serviceName `
                -ExpectedExecutable $ownedServiceExecutable `
                -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
                -PollMilliseconds ([int]$release.service_poll_interval_ms)
            $initdbServicePresent = $false
        }
        if ((Get-TicketboxPathEntryKindNoFollow $Paths.candidate_pgdata) -ceq "Directory") {
            Remove-TicketboxDataRootExact -Path ([string]$Paths.candidate_pgdata)
        }
        Invoke-TicketboxScChecked @(
            "create", $serviceName, "binPath=", $initdbImage,
            "start=", "demand", "obj=", ([string]$release.service_logon_account)
        ) | Out-Null
        Set-TicketboxServiceIdentityContract `
            -Name $serviceName `
            -LogonAccount ([string]$release.service_logon_account) `
            -SidType ([string]$release.service_sid_type)
        Assert-TicketboxServiceStartMode -Name $serviceName -ExpectedStartMode "Manual"
        Assert-TicketboxServiceHasNoFailureActions $serviceName
        Assert-TicketboxInitdbServiceCommand `
            -Name $serviceName `
            -ExpectedShawl $shawl `
            -ExpectedServiceName $serviceName `
            -ExpectedWorkingDirectory $pgBin `
            -ExpectedInitdb $initdb `
            -ExpectedDataRoot ([string]$Paths.candidate_pgdata) `
            -ExpectedPasswordFile $pwfile `
            -ExpectedStopTimeoutMs ([int]$release.stop_timeout_ms) `
            -ExpectedImagePath $initdbImage
        $serviceSid = Get-TicketboxServiceSid $serviceName
        Set-TicketboxExactDirectoryAcl `
            -Path ([string]$Paths.candidate_root) `
            -Accounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
            -OwnerAccount "SYSTEM" `
            -Recurse
        $pwfileKind = Get-TicketboxPathEntryKindNoFollow $pwfile
        if ($pwfileKind -ceq "File") {
            Remove-TicketboxProtectedUtf8Artifact `
                -Path $pwfile `
                -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
                -OwnerAccount "SYSTEM"
        }
        elseif ($pwfileKind -cne "Missing") {
            throw "restore candidate initdb password path is not a protected file."
        }
        Write-TicketboxProtectedUtf8FileDurable `
            -Path $pwfile `
            -Text ([string]$BootstrapState.SuperuserPassword) `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
            -OwnerAccount "SYSTEM"
        $snapshot = Invoke-TicketboxOwnedOneShotService `
            -Name $serviceName `
            -ExpectedExecutable $shawl `
            -ExpectedRuntimeExecutables @($shawl, $initdb) `
            -TimeoutMilliseconds ([int]$release.database_tool_timeout_ms) `
            -PollMilliseconds ([int]$release.service_poll_interval_ms)
        if (
            [uint32]$snapshot.ExitCode -ne 0 -or
            [uint32]$snapshot.ServiceSpecificExitCode -ne 0
        ) {
            $failure = [InvalidOperationException]::new(
                "restore candidate initdb failed under its service identity."
            )
            $cleanupFailures = @()
            try {
                if ((Get-TicketboxPathEntryKindNoFollow $pwfile) -ceq "File") {
                    Remove-TicketboxProtectedUtf8Artifact `
                        -Path $pwfile `
                        -FullControlAccounts @(
                            "SYSTEM", "BUILTIN\Administrators", $serviceSid
                        ) `
                        -OwnerAccount "SYSTEM"
                }
            }
            catch { $cleanupFailures += $_ }
            try {
                Remove-TicketboxOwnedServiceIfExists `
                    -Name $serviceName `
                    -ExpectedExecutable $shawl `
                    -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
                    -PollMilliseconds ([int]$release.service_poll_interval_ms)
            }
            catch { $cleanupFailures += $_ }
            try {
                if ((Get-TicketboxPathEntryKindNoFollow $Paths.candidate_pgdata) -ceq "Directory") {
                    Remove-TicketboxDataRootExact -Path ([string]$Paths.candidate_pgdata)
                }
            }
            catch { $cleanupFailures += $_ }
            Throw-TicketboxDatabaseGenerationOperationFailure $failure $cleanupFailures
        }
    }
    foreach ($required in @(
        $pgVersion,
        (Join-Path ([string]$Paths.candidate_pgdata) "global\pg_control"),
        (Join-Path ([string]$Paths.candidate_pgdata) "postgresql.conf"),
        (Join-Path ([string]$Paths.candidate_pgdata) "pg_hba.conf")
    )) {
        if ((Get-TicketboxPathEntryKindNoFollow $required) -cne "File") {
            throw "restore candidate initdb did not publish a complete cluster."
        }
    }
    if ((Get-TicketboxPathEntryKindNoFollow $pwfile) -ceq "File") {
        $serviceSid = Get-TicketboxServiceSid $serviceName
        Remove-TicketboxProtectedUtf8Artifact `
            -Path $pwfile `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
            -OwnerAccount "SYSTEM"
    }
    if (Test-TicketboxServiceExists $serviceName) {
        $actualExecutable = Get-TicketboxServiceExecutablePath $serviceName
        if (Test-TicketboxPathEquals $actualExecutable $shawl) {
            Remove-TicketboxOwnedServiceIfExists `
                -Name $serviceName `
                -ExpectedExecutable $shawl `
                -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
                -PollMilliseconds ([int]$release.service_poll_interval_ms)
        }
    }
    Set-TicketboxPostgresqlLoopbackConfiguration `
        -PgData ([string]$Paths.candidate_pgdata) `
        -Port ([int]$identity.PgPort)
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
