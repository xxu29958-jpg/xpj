#Requires -Version 5.1

$serviceIdentityScript = Join-Path $PSScriptRoot "windows_service_identity.ps1"
if (-not (Test-Path -LiteralPath $serviceIdentityScript -PathType Leaf)) {
    throw "Missing Windows service identity contract: $serviceIdentityScript"
}
. $serviceIdentityScript

$script:TicketboxLegacyWindowsReleaseSchema = "ticketbox-windows-release-v1"
$script:TicketboxCurrentWindowsReleaseSchema = "ticketbox-windows-release-v2"

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
    if ([string]$config.schema -notin @(
        $script:TicketboxLegacyWindowsReleaseSchema,
        $script:TicketboxCurrentWindowsReleaseSchema
    )) {
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
    if ([string]$config.schema -ceq $script:TicketboxCurrentWindowsReleaseSchema) {
        Assert-TicketboxReleaseConfigText `
            $config `
            "service_logon_account" `
            '^NT AUTHORITY\\LocalService$' `
            64 | Out-Null
        Assert-TicketboxReleaseConfigText `
            $config `
            "service_sid_type" `
            '^(unrestricted|restricted)$' `
            32 | Out-Null
        $canonicalAccount = ConvertTo-TicketboxServiceLogonAccount `
            -Name ([string]$config.pg_service_name) `
            -Account ([string]$config.service_logon_account)
        if ([string]$config.service_logon_account -cne $canonicalAccount) {
            throw "Windows release config 的 service_logon_account 必须使用 SCM 规范名称。"
        }
        $canonicalSidType = ConvertFrom-TicketboxServiceSidTypeValue `
            (ConvertTo-TicketboxServiceSidTypeValue ([string]$config.service_sid_type))
        if ([string]$config.service_sid_type -cne $canonicalSidType) {
            throw "Windows release config 的 service_sid_type 必须使用规范小写值。"
        }
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

function Get-TicketboxReleaseServiceLogonAccount {
    param(
        [Parameter(Mandatory = $true)][object]$Config,
        [Parameter(Mandatory = $true)][string]$ServiceName
    )

    if ([string]$Config.schema -ceq $script:TicketboxLegacyWindowsReleaseSchema) {
        return Get-TicketboxServiceResourcePrincipal $ServiceName
    }
    if ([string]$Config.schema -cne $script:TicketboxCurrentWindowsReleaseSchema) {
        throw "Windows release config schema 不受支持：$($Config.schema)"
    }
    $property = $Config.PSObject.Properties["service_logon_account"]
    if ($null -eq $property) {
        throw "Windows release config 缺少 service_logon_account。"
    }
    return ConvertTo-TicketboxServiceLogonAccount `
        -Name $ServiceName `
        -Account ([string]$property.Value)
}

function Get-TicketboxReleaseServiceSidType([object]$Config) {
    if ([string]$Config.schema -ceq $script:TicketboxLegacyWindowsReleaseSchema) {
        return "none"
    }
    if ([string]$Config.schema -cne $script:TicketboxCurrentWindowsReleaseSchema) {
        throw "Windows release config schema 不受支持：$($Config.schema)"
    }
    $property = $Config.PSObject.Properties["service_sid_type"]
    if ($null -eq $property) {
        throw "Windows release config 缺少 service_sid_type。"
    }
    $sidType = ConvertFrom-TicketboxServiceSidTypeValue `
        (ConvertTo-TicketboxServiceSidTypeValue ([string]$property.Value))
    if ($sidType -ceq "none") {
        throw "当前 Windows release config 不允许关闭服务 SID。"
    }
    return $sidType
}

function Get-TicketboxReleaseServiceIdentityTransition {
    param(
        [Parameter(Mandatory = $true)][object]$InstalledConfig,
        [Parameter(Mandatory = $true)][object]$TargetConfig
    )

    $installedSchema = [string]$InstalledConfig.schema
    $targetSchema = [string]$TargetConfig.schema
    if (
        $installedSchema -ceq $script:TicketboxLegacyWindowsReleaseSchema -and
        $targetSchema -ceq $script:TicketboxLegacyWindowsReleaseSchema
    ) {
        return "legacy_virtual_unchanged"
    }
    if (
        $installedSchema -ceq $script:TicketboxLegacyWindowsReleaseSchema -and
        $targetSchema -ceq $script:TicketboxCurrentWindowsReleaseSchema
    ) {
        Get-TicketboxReleaseServiceLogonAccount `
            -Config $TargetConfig `
            -ServiceName ([string]$TargetConfig.pg_service_name) | Out-Null
        Get-TicketboxReleaseServiceSidType $TargetConfig | Out-Null
        return "legacy_virtual_to_service_sid"
    }
    if (
        $installedSchema -ceq $script:TicketboxCurrentWindowsReleaseSchema -and
        $targetSchema -ceq $script:TicketboxCurrentWindowsReleaseSchema
    ) {
        $installedAccount = Get-TicketboxReleaseServiceLogonAccount `
            -Config $InstalledConfig `
            -ServiceName ([string]$InstalledConfig.pg_service_name)
        $targetAccount = Get-TicketboxReleaseServiceLogonAccount `
            -Config $TargetConfig `
            -ServiceName ([string]$TargetConfig.pg_service_name)
        $installedSidType = Get-TicketboxReleaseServiceSidType $InstalledConfig
        $targetSidType = Get-TicketboxReleaseServiceSidType $TargetConfig
        if (
            $installedAccount -cne $targetAccount -or
            $installedSidType -cne $targetSidType
        ) {
            throw "Windows 服务身份策略已变化；必须先提供显式服务身份迁移。"
        }
        return "current_unchanged"
    }
    if (
        $installedSchema -ceq $script:TicketboxCurrentWindowsReleaseSchema -and
        $targetSchema -ceq $script:TicketboxLegacyWindowsReleaseSchema
    ) {
        throw "拒绝把当前 Windows 服务身份策略降级为旧虚拟登录账户。"
    }
    throw "Windows release config schema 转换不受支持。"
}

function Get-TicketboxReleaseServiceIdentityShapes {
    param(
        [Parameter(Mandatory = $true)][object]$InstalledConfig,
        [Parameter(Mandatory = $true)][object]$TargetConfig,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [switch]$AllowTargetSidTypePending
    )

    $transition = Get-TicketboxReleaseServiceIdentityTransition `
        -InstalledConfig $InstalledConfig `
        -TargetConfig $TargetConfig
    $installedAccount = Get-TicketboxReleaseServiceLogonAccount `
        -Config $InstalledConfig `
        -ServiceName $ServiceName
    $installedSidType = Get-TicketboxReleaseServiceSidType $InstalledConfig
    $targetAccount = Get-TicketboxReleaseServiceLogonAccount `
        -Config $TargetConfig `
        -ServiceName $ServiceName
    $targetSidType = Get-TicketboxReleaseServiceSidType $TargetConfig
    $shapes = @(
        New-TicketboxServiceIdentityShape `
            -Name $ServiceName `
            -LogonAccount $installedAccount `
            -SidType $installedSidType `
            -AllowLegacyVirtualAccount
    )
    if ($transition -ceq "legacy_virtual_to_service_sid") {
        $shapes += New-TicketboxServiceIdentityShape `
            -Name $ServiceName `
            -LogonAccount $installedAccount `
            -SidType $targetSidType `
            -AllowLegacyVirtualAccount
        $shapes += New-TicketboxServiceIdentityShape `
            -Name $ServiceName `
            -LogonAccount $targetAccount `
            -SidType $targetSidType
    }
    if ($AllowTargetSidTypePending -and $targetSidType -cne "none") {
        $shapes += New-TicketboxServiceIdentityShape `
            -Name $ServiceName `
            -LogonAccount $targetAccount `
            -SidType "none"
    }
    $deduplicated = @()
    $seen = @{}
    foreach ($shape in $shapes) {
        $key = "$([string]$shape.LogonAccount.ToLowerInvariant())|$([string]$shape.SidType)"
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $deduplicated += $shape
    }
    return [object[]]$deduplicated
}

function Assert-TicketboxReleaseServiceIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object]$InstalledConfig,
        [Parameter(Mandatory = $true)][object]$TargetConfig,
        [switch]$AllowTargetSidTypePending
    )

    $shapes = @(Get-TicketboxReleaseServiceIdentityShapes `
        -InstalledConfig $InstalledConfig `
        -TargetConfig $TargetConfig `
        -ServiceName $Name `
        -AllowTargetSidTypePending:$AllowTargetSidTypePending)
    return Assert-TicketboxServiceIdentityShape `
        -Name $Name `
        -AllowedShapes $shapes
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
    Get-TicketboxReleaseServiceIdentityTransition `
        -InstalledConfig $InstalledConfig `
        -TargetConfig $TargetConfig | Out-Null
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
