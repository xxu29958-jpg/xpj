#Requires -Version 5.1

function Get-TicketboxWindowsPowerShellExecutable {
    $windows = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $path = Join-Path $windows "System32\WindowsPowerShell\v1.0\powershell.exe"
    if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
        throw "Windows PowerShell 5.1 executable 不存在：$path"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    return [IO.Path]::GetFullPath($path)
}

function New-TicketboxPostgresqlSingleUserServiceImagePath {
    param(
        [Parameter(Mandatory = $true)][string]$ShawlPath,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$PowerShellPath,
        [Parameter(Mandatory = $true)][string]$HelperPath,
        [Parameter(Mandatory = $true)][string]$PostgresPath,
        [Parameter(Mandatory = $true)][string]$PhysicalPgData,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$IntentSha256,
        [Parameter(Mandatory = $true)][string]$CandidateSha256,
        [Parameter(Mandatory = $true)][string]$CommittedRevision,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 600000)][int]$StopTimeoutMilliseconds,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 3600000)][int]$OperationTimeoutMilliseconds
    )
    return Join-TicketboxWindowsCommandLine @(
        (ConvertTo-TicketboxFullPath $ShawlPath),
        "run", "--name", $ServiceName, "--no-restart", "--no-log",
        "--kill-process-tree", "--stop-timeout", [string]$StopTimeoutMilliseconds,
        "--cwd", (ConvertTo-TicketboxFullPath $WorkingDirectory), "--",
        (ConvertTo-TicketboxFullPath $PowerShellPath),
        "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", (ConvertTo-TicketboxFullPath $HelperPath),
        "-PostgresPath", (ConvertTo-TicketboxFullPath $PostgresPath),
        "-PhysicalPgData", (ConvertTo-TicketboxFullPath $PhysicalPgData),
        "-OperationId", ([guid]$OperationId).ToString("D"),
        "-IntentSha256", $IntentSha256,
        "-CandidateSha256", $CandidateSha256,
        "-CommittedRevision", $CommittedRevision,
        "-TimeoutMilliseconds", [string]$OperationTimeoutMilliseconds
    )
}

function Assert-TicketboxPostgresqlSingleUserServiceCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedImagePath
    )
    Assert-TicketboxServiceDependencies -Name $Name -ExpectedDependencies @()
    Assert-TicketboxServiceHasNoFailureActions $Name
    Assert-TicketboxServiceStartMode -Name $Name -ExpectedStartMode "Manual"
    $actual = Get-TicketboxServiceImagePath $Name
    if ($actual -cne $ExpectedImagePath) {
        throw "PostgreSQL single-user one-shot ImagePath 与 durable transition 漂移。"
    }
    $arguments = @(Split-TicketboxWindowsCommandLine $actual)
    if (
        $arguments.Count -ne 34 -or
        $arguments[1] -cne "run" -or $arguments[2] -cne "--name" -or
        $arguments[4] -cne "--no-restart" -or $arguments[5] -cne "--no-log" -or
        $arguments[6] -cne "--kill-process-tree" -or
        $arguments[7] -cne "--stop-timeout" -or
        $arguments[9] -cne "--cwd" -or $arguments[11] -cne "--" -or
        $arguments[13] -cne "-NoLogo" -or $arguments[14] -cne "-NoProfile" -or
        $arguments[15] -cne "-NonInteractive" -or
        $arguments[16] -cne "-ExecutionPolicy" -or $arguments[17] -cne "Bypass" -or
        $arguments[18] -cne "-File" -or
        $arguments[20] -cne "-PostgresPath" -or
        $arguments[22] -cne "-PhysicalPgData" -or
        $arguments[24] -cne "-OperationId" -or
        $arguments[26] -cne "-IntentSha256" -or
        $arguments[28] -cne "-CandidateSha256" -or
        $arguments[30] -cne "-CommittedRevision" -or
        $arguments[32] -cne "-TimeoutMilliseconds"
    ) {
        throw "PostgreSQL single-user one-shot 含未知、缺失或多余参数。"
    }
}

function Enter-TicketboxPostgresqlStoppedHostAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][string]$ExpectedFormalImagePath
    )
    $serviceName = [string]$HostContract.pg_service_name
    $pgCtl = [IO.Path]::GetFullPath([string]$HostContract.pg_ctl_path)
    if (
        [string]$HostAuthority.ServiceName -cne $serviceName -or
        -not (Test-TicketboxPathEquals ([string]$HostAuthority.PgCtlPath) $pgCtl)
    ) {
        throw "PostgreSQL stopped-host 拒绝漂移的 live host authority。"
    }
    $postgres = Join-Path (Split-Path -Parent $pgCtl) "postgres.exe"
    Assert-TicketboxPgServiceCommand `
        -Name $serviceName -ExpectedExecutable $pgCtl `
        -ExpectedServiceName $serviceName `
        -ExpectedDataRoot ([string]$HostAuthority.PgData)
    if ((Get-TicketboxServiceImagePathExact $serviceName) -cne $ExpectedFormalImagePath) {
        throw "PostgreSQL stopped-host 的完整 SCM ImagePath 与 durable transition 漂移。"
    }
    Stop-TicketboxOwnedServiceIfExists `
        -Name $serviceName -ExpectedExecutable $pgCtl `
        -TimeoutMilliseconds ([int]$HostContract.release_config.service_state_timeout_ms) `
        -PollMilliseconds ([int]$HostContract.release_config.service_poll_interval_ms) `
        -BackendPort ([int]$HostAuthority.Port) `
        -ExpectedRuntimeExecutables @($pgCtl, $postgres)
    $snapshot = Get-TicketboxServiceRuntimeSnapshot $serviceName
    if ([string]$snapshot.State -cne "stopped" -or [uint32]$snapshot.ProcessId -ne 0) {
        throw "PostgreSQL stopped-host 仍有服务进程。"
    }
    return [pscustomobject][ordered]@{
        Schema = "ticketbox-postgresql-stopped-host-v1"
        ServiceName = $serviceName
        PgCtlPath = $pgCtl
        PostgresPath = [IO.Path]::GetFullPath($postgres)
        PgData = [IO.Path]::GetFullPath([string]$HostAuthority.PgData)
        PhysicalPgData = [IO.Path]::GetFullPath([string]$HostAuthority.PhysicalPgData)
        Port = [int]$HostAuthority.Port
        FormalImagePath = $ExpectedFormalImagePath
    }
}

function Set-TicketboxPostgresqlSingleUserServiceCommand {
    param(
        [Parameter(Mandatory = $true)][object]$StoppedHost,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][string]$ImagePath
    )
    $serviceName = [string]$StoppedHost.ServiceName
    Invoke-TicketboxScChecked @("failure", $serviceName, "reset=", "0", "actions=", "") | Out-Null
    Invoke-TicketboxScChecked @("config", $serviceName, "binPath=", $ImagePath, "start=", "demand") | Out-Null
    Set-TicketboxServiceIdentityContract `
        -Name $serviceName `
        -LogonAccount ([string]$HostContract.release_config.service_logon_account) `
        -SidType ([string]$HostContract.release_config.service_sid_type)
    Assert-TicketboxPostgresqlSingleUserServiceCommand `
        -Name $serviceName -ExpectedImagePath $ImagePath
}

function Restore-TicketboxPostgresqlFormalServiceCommand {
    param(
        [Parameter(Mandatory = $true)][object]$StoppedHost,
        [Parameter(Mandatory = $true)][object]$HostContract
    )
    $serviceName = [string]$StoppedHost.ServiceName
    Invoke-TicketboxScChecked @(
        "config", $serviceName, "binPath=", [string]$StoppedHost.FormalImagePath,
        "start=", "demand"
    ) | Out-Null
    $restartActions = @(
        $HostContract.release_config.scm_restart_delays_ms |
            ForEach-Object { "restart/$([int]$_)" }
    ) -join "/"
    Invoke-TicketboxScChecked @(
        "failure", $serviceName,
        "reset=", [string]$HostContract.release_config.scm_failure_reset_seconds,
        "actions=", $restartActions
    ) | Out-Null
    Set-TicketboxServiceIdentityContract `
        -Name $serviceName `
        -LogonAccount ([string]$HostContract.release_config.service_logon_account) `
        -SidType ([string]$HostContract.release_config.service_sid_type)
    Assert-TicketboxPgServiceCommand `
        -Name $serviceName `
        -ExpectedExecutable ([string]$StoppedHost.PgCtlPath) `
        -ExpectedServiceName $serviceName `
        -ExpectedDataRoot ([string]$StoppedHost.PgData)
    if ((Get-TicketboxServiceImagePathExact $serviceName) -cne
        [string]$StoppedHost.FormalImagePath) {
        throw "PostgreSQL formal service 的完整 SCM ImagePath 未 exact 恢复。"
    }
    Assert-TicketboxServiceFailurePolicy `
        -Name $serviceName `
        -ExpectedResetSeconds ([int]$HostContract.release_config.scm_failure_reset_seconds) `
        -ExpectedRestartDelaysMs @($HostContract.release_config.scm_restart_delays_ms)
    Assert-TicketboxServiceStartMode -Name $serviceName -ExpectedStartMode "Manual"
}
