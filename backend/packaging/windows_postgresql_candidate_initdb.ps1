#Requires -Version 5.1

<#
.SYNOPSIS
  Bounded initdb capability and reconcile loop for a restore candidate cluster.
.DESCRIPTION
  This adapter owns only the temporary initdb SCM capability and its cleanup.
  Cluster observation/policy and runtime service projection remain separate.
#>

function Reset-TicketboxPostgresqlRestoreCandidateInitdbAttempt {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observation = Get-TicketboxPostgresqlRestoreCandidateClusterObservation `
        $Subject $OperationId $Paths
    if (
        [string]$observation.service_kind -notin @("absent", "owned_initdb") -or
        [string]$observation.pgdata_state -ceq "complete" -or
        (
            [string]$observation.service_kind -ceq "absent" -and
            [string]$observation.password_kind -cne "missing"
        )
    ) {
        throw "restore candidate stale attempt is not safe to reset."
    }
    $release = $Subject.Release
    $serviceName = [string]$release.pg_recovery_service_name
    if ([string]$observation.service_kind -ceq "owned_initdb") {
        $serviceSid = Get-TicketboxServiceSid $serviceName
        if ([string]$observation.password_kind -ceq "file") {
            Remove-TicketboxProtectedUtf8Artifact `
                -Path (Join-Path ([string]$Paths.candidate_root) ".initdb-password") `
                -FullControlAccounts @(
                    "SYSTEM", "BUILTIN\Administrators", $serviceSid
                ) `
                -OwnerAccount "SYSTEM"
        }
        Remove-TicketboxOwnedServiceIfExists `
            -Name $serviceName `
            -ExpectedExecutable ([string]$observation.service_executable) `
            -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
            -PollMilliseconds ([int]$release.service_poll_interval_ms)
    }
    if ([string]$observation.pgdata_state -cne "missing") {
        Remove-TicketboxDataRootExact -Path ([string]$Paths.candidate_pgdata)
    }
}

function Initialize-TicketboxPostgresqlRestoreCandidateInitdbCapability {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$BootstrapState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observation = Get-TicketboxPostgresqlRestoreCandidateClusterObservation `
        $Subject $OperationId $Paths
    if (
        (Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction $observation) -cne
            "prepare_initdb"
    ) { throw "restore candidate initdb capability is not authorized." }
    $identity = $Subject.Identity
    $release = $Subject.Release
    $pgBin = Join-Path ([string]$identity.InstallDir) "pg\bin"
    $initdb = Join-Path $pgBin "initdb.exe"
    $shawl = Join-Path ([string]$identity.InstallDir) "shawl\shawl.exe"
    $serviceName = [string]$release.pg_recovery_service_name
    $pwfile = Join-Path ([string]$Paths.candidate_root) ".initdb-password"
    $initdbImage = New-TicketboxInitdbServiceImagePath `
        -ShawlPath $shawl -ServiceName $serviceName -WorkingDirectory $pgBin `
        -InitdbPath $initdb -DataRoot ([string]$Paths.candidate_pgdata) `
        -PasswordFile $pwfile -StopTimeoutMs ([int]$release.stop_timeout_ms)
    [IO.Directory]::CreateDirectory([string]$Paths.candidate_root) | Out-Null
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
        -Name $serviceName -ExpectedShawl $shawl `
        -ExpectedServiceName $serviceName -ExpectedWorkingDirectory $pgBin `
        -ExpectedInitdb $initdb -ExpectedDataRoot ([string]$Paths.candidate_pgdata) `
        -ExpectedPasswordFile $pwfile `
        -ExpectedStopTimeoutMs ([int]$release.stop_timeout_ms) `
        -ExpectedImagePath $initdbImage
    $serviceSid = Get-TicketboxServiceSid $serviceName
    Set-TicketboxExactDirectoryAcl `
        -Path ([string]$Paths.candidate_root) `
        -Accounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
        -OwnerAccount "SYSTEM" `
        -Recurse
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $pwfile `
        -Text ([string]$BootstrapState.SuperuserPassword) `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
        -OwnerAccount "SYSTEM"
}

function Invoke-TicketboxPostgresqlRestoreCandidateInitdbOneShot {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observation = Get-TicketboxPostgresqlRestoreCandidateClusterObservation `
        $Subject $OperationId $Paths
    if (
        (Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction $observation) -cne
            "run_prepared_initdb"
    ) { throw "restore candidate initdb execution is not authorized." }
    $release = $Subject.Release
    $pgBin = Join-Path ([string]$Subject.Identity.InstallDir) "pg\bin"
    $snapshot = Invoke-TicketboxOwnedOneShotService `
        -Name ([string]$release.pg_recovery_service_name) `
        -ExpectedExecutable ([string]$observation.service_executable) `
        -ExpectedRuntimeExecutables @(
            [string]$observation.service_executable,
            (Join-Path $pgBin "initdb.exe")
        ) `
        -TimeoutMilliseconds ([int]$release.database_tool_timeout_ms) `
        -PollMilliseconds ([int]$release.service_poll_interval_ms)
    if (
        [uint32]$snapshot.ExitCode -ne 0 -or
        [uint32]$snapshot.ServiceSpecificExitCode -ne 0
    ) {
        $failure = [InvalidOperationException]::new(
            "restore candidate initdb failed under its service identity."
        )
        $cleanup = @()
        try {
            Reset-TicketboxPostgresqlRestoreCandidateInitdbAttempt `
                $Subject $OperationId $Paths $LifecycleLock
        }
        catch { $cleanup += $_ }
        Throw-TicketboxOperationFailure $failure $cleanup
    }
}

function Remove-TicketboxPostgresqlRestoreCandidateInitdbCapability {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observation = Get-TicketboxPostgresqlRestoreCandidateClusterObservation `
        $Subject $OperationId $Paths
    if (
        (Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction $observation) -cne
            "retire_initdb_capability"
    ) { throw "restore candidate initdb retirement is not authorized." }
    $release = $Subject.Release
    $serviceName = [string]$release.pg_recovery_service_name
    $serviceSid = Get-TicketboxServiceSid $serviceName
    if ([string]$observation.password_kind -ceq "file") {
        Remove-TicketboxProtectedUtf8Artifact `
            -Path (Join-Path ([string]$Paths.candidate_root) ".initdb-password") `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators", $serviceSid) `
            -OwnerAccount "SYSTEM"
    }
    Remove-TicketboxOwnedServiceIfExists `
        -Name $serviceName `
        -ExpectedExecutable ([string]$observation.service_executable) `
        -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$release.service_poll_interval_ms)
}

function Wait-TicketboxPostgresqlRestoreCandidateInitdbTerminal {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $release = $Subject.Release
    $serviceName = [string]$release.pg_recovery_service_name
    $deadline = New-TicketboxWaitDeadline ([int]$release.database_tool_timeout_ms)
    do {
        $snapshot = Get-TicketboxServiceRuntimeSnapshot $serviceName
        if ([string]$snapshot.State -ceq "stopped") { return }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds ([int]$release.database_tool_timeout_ms) `
        -PollMilliseconds ([int]$release.service_poll_interval_ms))
    throw "restore candidate initdb service did not reach a terminal state."
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
    while ($true) {
        $observation = Get-TicketboxPostgresqlRestoreCandidateClusterObservation `
            $Subject $OperationId $Paths
        $action = Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction `
            $observation
        switch ($action) {
            "wait_initdb_terminal" {
                Wait-TicketboxPostgresqlRestoreCandidateInitdbTerminal `
                    $Subject $LifecycleLock
            }
            "reset_stale_attempt" {
                Reset-TicketboxPostgresqlRestoreCandidateInitdbAttempt `
                    $Subject $OperationId $Paths $LifecycleLock
            }
            "prepare_initdb" {
                Initialize-TicketboxPostgresqlRestoreCandidateInitdbCapability `
                    $Subject $OperationId $Paths $BootstrapState $LifecycleLock
            }
            "run_prepared_initdb" {
                Invoke-TicketboxPostgresqlRestoreCandidateInitdbOneShot `
                    $Subject $OperationId $Paths $LifecycleLock
            }
            "retire_initdb_capability" {
                Remove-TicketboxPostgresqlRestoreCandidateInitdbCapability `
                    $Subject $OperationId $Paths $LifecycleLock
            }
            "reconcile_loopback" {
                Set-TicketboxPostgresqlLoopbackConfiguration `
                    -PgData ([string]$Paths.candidate_pgdata) `
                    -Port ([int]$Subject.Identity.PgPort)
                return
            }
            default { throw "unknown restore candidate cluster action: $action" }
        }
    }
}
