#Requires -Version 5.1

function Assert-TicketboxReleaseConfigInteger {
    param(
        [Parameter(Mandatory = $true)][object]$Config,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][long]$Minimum,
        [Parameter(Mandatory = $true)][long]$Maximum
    )

    $property = $Config.PSObject.Properties[$Name]
    if ($null -eq $property) {
        throw "Windows release config 缺少 $Name。"
    }
    $value = $property.Value
    if (
        ($value -isnot [int] -and $value -isnot [long]) -or
        [long]$value -lt $Minimum -or
        [long]$value -gt $Maximum
    ) {
        throw "Windows release config 的 $Name 必须是 $Minimum..$Maximum 整数。"
    }
    return [int]$value
}

function Assert-TicketboxReleaseConfigText {
    param(
        [Parameter(Mandatory = $true)][object]$Config,
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$Pattern = "",
        [int]$MaximumLength = 200
    )

    $property = $Config.PSObject.Properties[$Name]
    if ($null -eq $property) {
        throw "Windows release config 缺少 $Name。"
    }
    $value = [string]$property.Value
    if ($value.Trim().Length -eq 0 -or $value.Length -gt $MaximumLength) {
        throw "Windows release config 的 $Name 为空或过长。"
    }
    if ($Pattern.Length -gt 0 -and $value -notmatch $Pattern) {
        throw "Windows release config 的 $Name 格式无效。"
    }
    return $value
}

function Read-TicketboxWindowsReleaseConfig {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Path,
        [switch]$AllowLegacyMissingOwnerRecoveryChannel
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 Windows release config：$Path"
    }
    try {
        $config = Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "Windows release config 不是有效 JSON：$Path"
    }
    if ($config.schema -ne "ticketbox-windows-release-v1") {
        throw "Windows release config schema 不受支持：$($config.schema)"
    }

    Assert-TicketboxReleaseConfigText $config "pg_service_name" '^[A-Za-z][A-Za-z0-9_-]{0,63}$' 64 | Out-Null
    Assert-TicketboxReleaseConfigText $config "pg_recovery_service_name" '^[A-Za-z][A-Za-z0-9_-]{0,63}$' 64 | Out-Null
    Assert-TicketboxReleaseConfigText $config "backend_service_name" '^[A-Za-z][A-Za-z0-9_-]{0,63}$' 64 | Out-Null
    if ($null -eq $config.PSObject.Properties["owner_recovery_channel"]) {
        if (-not $AllowLegacyMissingOwnerRecoveryChannel) {
            throw "Windows release config 缺少 owner_recovery_channel。"
        }
        $config | Add-Member -NotePropertyName "owner_recovery_channel" -NotePropertyValue "managed_host"
    }
    Assert-TicketboxReleaseConfigText $config "owner_recovery_channel" '^managed_host$' 32 | Out-Null
    if ([string]$config.owner_recovery_channel -cne "managed_host") {
        throw "Windows release config 的 owner_recovery_channel 必须精确为 managed_host。"
    }
    Assert-TicketboxReleaseConfigText $config "db_name" '^[A-Za-z_][A-Za-z0-9_]*$' 64 | Out-Null
    Assert-TicketboxReleaseConfigText $config "db_role" '^[A-Za-z_][A-Za-z0-9_]*$' 64 | Out-Null
    foreach ($name in @("bootstrap_account_name", "bootstrap_ledger_name", "bootstrap_device_name", "default_timezone")) {
        Assert-TicketboxReleaseConfigText $config $name | Out-Null
    }

    foreach ($name in @("default_pg_port", "fallback_pg_port", "default_backend_port", "fallback_backend_port")) {
        Assert-TicketboxReleaseConfigInteger $config $name 1 65535 | Out-Null
    }
    foreach ($name in @(
        "stop_timeout_ms",
        "restart_delay_ms",
        "service_state_timeout_ms",
        "postgres_ready_timeout_ms",
        "pre_upgrade_postgres_ready_timeout_ms",
        "backend_ready_timeout_ms",
        "backend_health_request_timeout_ms",
        "bootstrap_request_timeout_ms"
    )) {
        Assert-TicketboxReleaseConfigInteger $config $name 1000 300000 | Out-Null
    }
    foreach ($name in @(
        "service_poll_interval_ms",
        "postgres_ready_poll_interval_ms",
        "pre_upgrade_postgres_ready_poll_interval_ms",
        "backend_ready_poll_interval_ms"
    )) {
        Assert-TicketboxReleaseConfigInteger $config $name 10 10000 | Out-Null
    }
    Assert-TicketboxReleaseConfigInteger $config "secret_byte_count" 32 1024 | Out-Null
    Assert-TicketboxReleaseConfigInteger $config "database_tool_timeout_ms" 10000 3600000 | Out-Null
    Assert-TicketboxReleaseConfigInteger $config "scm_failure_reset_seconds" 1 86400 | Out-Null

    $restartDelays = @($config.scm_restart_delays_ms)
    if ($restartDelays.Count -eq 0) {
        throw "Windows release config 至少需要一个 SCM restart delay。"
    }
    foreach ($delay in $restartDelays) {
        if (($delay -isnot [int] -and $delay -isnot [long]) -or $delay -lt 1000 -or $delay -gt 300000) {
            throw "Windows release config 的 SCM restart delay 必须是 1000..300000 整数。"
        }
    }
    if (
        $config.default_pg_port -eq $config.fallback_pg_port -or
        $config.default_backend_port -eq $config.fallback_backend_port
    ) {
        throw "Windows release config 的默认端口与回退端口不能相同。"
    }
    foreach ($pgPort in @($config.default_pg_port, $config.fallback_pg_port)) {
        foreach ($backendPort in @($config.default_backend_port, $config.fallback_backend_port)) {
            if ($pgPort -eq $backendPort) {
                throw "Windows release config 的 PostgreSQL 与后端端口候选不能重叠。"
            }
        }
    }
    $serviceNames = @(
        [string]$config.pg_service_name,
        [string]$config.pg_recovery_service_name,
        [string]$config.backend_service_name
    )
    if (@($serviceNames | Sort-Object -Unique).Count -ne $serviceNames.Count) {
        throw "Windows release config 的正式 PostgreSQL、恢复 PostgreSQL 与后端服务名必须互不相同。"
    }
    if (
        $config.service_poll_interval_ms -gt $config.service_state_timeout_ms -or
        $config.postgres_ready_poll_interval_ms -gt $config.postgres_ready_timeout_ms -or
        $config.pre_upgrade_postgres_ready_poll_interval_ms -gt $config.pre_upgrade_postgres_ready_timeout_ms -or
        $config.backend_ready_poll_interval_ms -gt $config.backend_ready_timeout_ms
    ) {
        throw "Windows release config 的轮询间隔不能大于对应超时。"
    }
    return $config
}

function Assert-TicketboxReleaseIdentityCompatible {
    param(
        [Parameter(Mandatory = $true)][object]$InstalledConfig,
        [Parameter(Mandatory = $true)][object]$TargetConfig
    )

    foreach ($name in @("pg_service_name", "pg_recovery_service_name", "backend_service_name")) {
        if (-not [string]::Equals(
            [string]$InstalledConfig.$name,
            [string]$TargetConfig.$name,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Windows release config 的安装身份 $name 已变化；必须先提供显式服务迁移，拒绝直接覆盖升级。"
        }
    }
    foreach ($name in @("db_name", "db_role")) {
        if (-not [string]::Equals(
            [string]$InstalledConfig.$name,
            [string]$TargetConfig.$name,
            [System.StringComparison]::Ordinal
        )) {
            throw "Windows release config 的安装身份 $name 已变化；必须先提供显式数据库迁移，拒绝直接覆盖升级。"
        }
    }
}

function New-TicketboxWaitDeadline([int]$TimeoutMilliseconds) {
    if ($TimeoutMilliseconds -le 0) {
        throw "等待超时必须大于 0 ms。"
    }
    return [System.Diagnostics.Stopwatch]::StartNew()
}

function Wait-TicketboxPollBeforeDeadline {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Stopwatch]$Deadline,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [scriptblock]$SleepAction = { param($Milliseconds) Start-Sleep -Milliseconds $Milliseconds }
    )

    $remaining = [long]$TimeoutMilliseconds - $Deadline.ElapsedMilliseconds
    if ($remaining -le 0) {
        return $false
    }
    $sleepMilliseconds = [int][Math]::Min([long][Math]::Max(1, $PollMilliseconds), $remaining)
    & $SleepAction $sleepMilliseconds | Out-Null
    return $Deadline.ElapsedMilliseconds -lt $TimeoutMilliseconds
}

function ConvertTo-TicketboxTimeoutSeconds([int]$Milliseconds) {
    return [Math]::Max(1, [int][Math]::Ceiling($Milliseconds / 1000.0))
}
