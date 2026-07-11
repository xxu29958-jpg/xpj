#Requires -Version 5.1

function Write-TicketboxBootstrapEnabledEnvironment(
    [string]$DatabaseUrl,
    [string]$BootstrapSecret
) {
    $lines = (New-BaseEnvLines $DatabaseUrl) + @(
        "ENABLE_HTTP_BOOTSTRAP=true",
        "HTTP_BOOTSTRAP_SECRET=$BootstrapSecret"
    )
    Write-EnvNoBom -Path $EnvPath -Lines $lines
    $persisted = Read-EnvMap $EnvPath
    if (
        -not $persisted.ContainsKey("DATABASE_URL") -or
        $persisted["DATABASE_URL"] -cne $DatabaseUrl -or
        -not $persisted.ContainsKey("ENABLE_HTTP_BOOTSTRAP") -or
        $persisted["ENABLE_HTTP_BOOTSTRAP"] -cne "true" -or
        -not $persisted.ContainsKey("HTTP_BOOTSTRAP_SECRET") -or
        $persisted["HTTP_BOOTSTRAP_SECRET"] -cne $BootstrapSecret
    ) {
        throw "bootstrap 暴露恢复配置持久化校验失败。"
    }
}

function Write-TicketboxBootstrapQuarantineEnvironment([string]$DatabaseUrl) {
    Write-EnvNoBom -Path $EnvPath -Lines (New-BaseEnvLines $DatabaseUrl)
    $persisted = Read-EnvMap $EnvPath
    if (
        -not $persisted.ContainsKey("DATABASE_URL") -or
        $persisted["DATABASE_URL"] -cne $DatabaseUrl -or
        $persisted.ContainsKey("ENABLE_HTTP_BOOTSTRAP") -or
        $persisted.ContainsKey("HTTP_BOOTSTRAP_SECRET")
    ) {
        throw "bootstrap 暴露隔离配置持久化校验失败。"
    }
}

function Assert-TicketboxBootstrapExposureRecoveryGuard {
    if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath -PathType Leaf)) {
        throw "缺少 bootstrap 暴露恢复启动互锁标记。"
    }
    Assert-TicketboxExactFileAcl `
        -Path $BootstrapExposureRecoveryGuardPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
        -OwnerAccount "SYSTEM"
    $persisted = [System.IO.File]::ReadAllText(
        $BootstrapExposureRecoveryGuardPath,
        [System.Text.Encoding]::UTF8
    )
    if ($persisted -cne "STATE=pending$([Environment]::NewLine)") {
        throw "bootstrap 暴露恢复启动互锁标记已损坏。"
    }
}

function Write-TicketboxBootstrapExposureRecoveryGuard {
    if (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath) {
        Assert-TicketboxBootstrapExposureRecoveryGuard
        return
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $BootstrapExposureRecoveryGuardPath `
        -Text "STATE=pending$([Environment]::NewLine)" `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
        -OwnerAccount "SYSTEM"
    Assert-TicketboxBootstrapExposureRecoveryGuard
}

function Remove-TicketboxBootstrapExposureRecoveryGuard {
    if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath)) {
        return
    }
    Assert-TicketboxBootstrapExposureRecoveryGuard
    Remove-TicketboxSensitiveFile $BootstrapExposureRecoveryGuardPath
}

function Write-TicketboxBootstrapExposureRecoveryIntent(
    [string]$ExposedSecret,
    [string]$ReplacementSecret
) {
    if (Test-Path -LiteralPath $BootstrapExposureRecoveryPath) {
        Assert-TicketboxExactFileAcl `
            -Path $BootstrapExposureRecoveryPath `
            -Accounts @("SYSTEM", "BUILTIN\Administrators") `
            -OwnerAccount "SYSTEM"
        throw "已存在未解决的 bootstrap 暴露恢复 intent，拒绝覆盖。"
    }
    $intentText = [string]::Join([Environment]::NewLine, @(
        "STATE=pending",
        "EXPOSED_SECRET=$ExposedSecret",
        "REPLACEMENT_SECRET=$ReplacementSecret"
    )) + [Environment]::NewLine
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $BootstrapExposureRecoveryPath `
        -Text $intentText `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    $persisted = Read-TicketboxBootstrapExposureRecoveryIntent
    if (
        $persisted.ExposedSecret -cne $ExposedSecret -or
        $persisted.ReplacementSecret -cne $ReplacementSecret
    ) {
        throw "bootstrap 暴露恢复 intent 持久化校验失败。"
    }
}

function Replace-TicketboxBootstrapExposureRecoveryIntent(
    [string]$ExpectedExposedSecret,
    [string]$ExpectedReplacementSecret,
    [string]$ReplacementSecret
) {
    $current = Read-TicketboxBootstrapExposureRecoveryIntent
    if (
        $null -eq $current -or
        $current.ExposedSecret -cne $ExpectedExposedSecret -or
        $current.ReplacementSecret -cne $ExpectedReplacementSecret -or
        $ReplacementSecret -ceq $ExpectedExposedSecret
    ) {
        throw "bootstrap 暴露恢复 intent 换代前置状态不匹配。"
    }
    $intentText = [string]::Join([Environment]::NewLine, @(
        "STATE=pending",
        "EXPOSED_SECRET=$ExpectedExposedSecret",
        "REPLACEMENT_SECRET=$ReplacementSecret"
    )) + [Environment]::NewLine
    $replacementPath = "$BootstrapExposureRecoveryPath.$([Guid]::NewGuid().ToString('N')).replacement"
    try {
        Write-TicketboxProtectedUtf8FileDurable `
            -Path $replacementPath `
            -Text $intentText `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -OwnerAccount "SYSTEM"
        Move-TicketboxFileDurable `
            -Source $replacementPath `
            -Destination $BootstrapExposureRecoveryPath `
            -ReplaceExisting
    }
    finally {
        if (Test-Path -LiteralPath $replacementPath) {
            Assert-TicketboxExactFileAcl `
                -Path $replacementPath `
                -Accounts @("SYSTEM", "BUILTIN\Administrators") `
                -OwnerAccount "SYSTEM"
            Remove-TicketboxSensitiveFile $replacementPath
        }
    }
    $persisted = Read-TicketboxBootstrapExposureRecoveryIntent
    if (
        $persisted.ExposedSecret -cne $ExpectedExposedSecret -or
        $persisted.ReplacementSecret -cne $ReplacementSecret
    ) {
        throw "bootstrap 暴露恢复 intent 换代持久化校验失败。"
    }
}

function Read-TicketboxBootstrapExposureRecoveryIntent {
    if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryPath -PathType Leaf)) {
        return $null
    }
    Assert-TicketboxExactFileAcl `
        -Path $BootstrapExposureRecoveryPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    $intent = Read-EnvMap $BootstrapExposureRecoveryPath
    if (
        $intent.Count -ne 3 -or
        -not $intent.ContainsKey("STATE") -or
        $intent["STATE"] -cne "pending" -or
        -not $intent.ContainsKey("EXPOSED_SECRET") -or
        -not $intent.ContainsKey("REPLACEMENT_SECRET") -or
        [string]::IsNullOrWhiteSpace($intent["EXPOSED_SECRET"]) -or
        [string]::IsNullOrWhiteSpace($intent["REPLACEMENT_SECRET"]) -or
        $intent["EXPOSED_SECRET"] -ceq $intent["REPLACEMENT_SECRET"]
    ) {
        throw "bootstrap 暴露恢复 intent 不完整或已损坏。"
    }
    Get-TicketboxBootstrapCredentials $intent["EXPOSED_SECRET"] | Out-Null
    Get-TicketboxBootstrapCredentials $intent["REPLACEMENT_SECRET"] | Out-Null
    return [pscustomobject]@{
        ExposedSecret = [string]$intent["EXPOSED_SECRET"]
        ReplacementSecret = [string]$intent["REPLACEMENT_SECRET"]
    }
}

function Remove-TicketboxBootstrapExposureRecoveryIntent {
    if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryPath)) {
        return
    }
    Assert-TicketboxExactFileAcl `
        -Path $BootstrapExposureRecoveryPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    Remove-TicketboxSensitiveFile $BootstrapExposureRecoveryPath
}

function Read-TicketboxBootstrapExposureMaintenanceResult([string]$OperationId) {
    if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryResultPath -PathType Leaf)) {
        throw "backend bootstrap 暴露恢复未生成持久诊断结果。"
    }
    Assert-NoTicketboxAncestorReparsePoints $BootstrapExposureRecoveryResultPath
    $item = Get-Item -LiteralPath $BootstrapExposureRecoveryResultPath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "backend bootstrap 暴露恢复诊断结果不能是重解析点。"
    }
    if ($item.Length -le 0 -or $item.Length -gt 4096) {
        throw "backend bootstrap 暴露恢复诊断结果大小不合法。"
    }
    $result = [System.IO.File]::ReadAllText(
        $BootstrapExposureRecoveryResultPath,
        [System.Text.Encoding]::UTF8
    ) | ConvertFrom-Json -ErrorAction Stop
    $propertyNames = @($result.PSObject.Properties.Name | Sort-Object)
    $expectedNames = @(
        "action",
        "error_code",
        "error_type",
        "operation_id",
        "recorded_at_utc",
        "schema",
        "state"
    ) | Sort-Object
    if (($propertyNames -join "|") -cne ($expectedNames -join "|")) {
        throw "backend bootstrap 暴露恢复诊断结果字段不完整。"
    }
    if (
        [string]$result.schema -cne "ticketbox-maintenance-result-v1" -or
        [string]$result.action -cne "rotate-exposed-bootstrap" -or
        [string]$result.operation_id -cne $OperationId -or
        [string]$result.state -notin @("running", "succeeded", "failed") -or
        [string]$result.error_code -notmatch '^[A-Za-z0-9:_-]{0,100}$' -or
        [string]$result.error_type -notmatch '^[A-Za-z0-9_.]{0,100}$'
    ) {
        throw "backend bootstrap 暴露恢复诊断结果内容不合法。"
    }
    [DateTimeOffset]$recordedAt = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$result.recorded_at_utc, [ref]$recordedAt)) {
        throw "backend bootstrap 暴露恢复诊断结果时间不合法。"
    }
    return $result
}

function Invoke-TicketboxBootstrapExposureMaintenance(
    [string]$ExposedSecret,
    [string]$ReplacementSecret
) {
    $environmentNames = @(
        "TICKETBOX_DATA_DIR",
        "TICKETBOX_MAINTENANCE_ACTION",
        "TICKETBOX_MAINTENANCE_OPERATION_ID",
        "TICKETBOX_EXPOSED_BOOTSTRAP_SECRET",
        "TICKETBOX_REPLACEMENT_BOOTSTRAP_SECRET"
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = if (Test-Path "Env:$name") {
            [pscustomobject]@{ Present = $true; Value = (Get-Item "Env:$name").Value }
        }
        else {
            [pscustomobject]@{ Present = $false; Value = "" }
        }
    }
    $operationId = [Guid]::NewGuid().ToString("D")
    try {
        Assert-NoTicketboxAncestorReparsePoints $BootstrapExposureRecoveryResultPath
        if (Test-Path -LiteralPath $BootstrapExposureRecoveryResultPath) {
            Remove-TicketboxSensitiveFile $BootstrapExposureRecoveryResultPath
        }
        $env:TICKETBOX_DATA_DIR = $AppData
        $env:TICKETBOX_MAINTENANCE_ACTION = "rotate-exposed-bootstrap"
        $env:TICKETBOX_MAINTENANCE_OPERATION_ID = $operationId
        $env:TICKETBOX_EXPOSED_BOOTSTRAP_SECRET = $ExposedSecret
        $env:TICKETBOX_REPLACEMENT_BOOTSTRAP_SECRET = $ReplacementSecret
        & $BackendExe
        $backendExitCode = $LASTEXITCODE
        $result = Read-TicketboxBootstrapExposureMaintenanceResult $operationId
        if ($backendExitCode -ne 0) {
            $code = if ([string]::IsNullOrWhiteSpace([string]$result.error_code)) {
                "runtime_error"
            }
            else { [string]$result.error_code }
            if ($code -ceq "replacement_credential_collision") {
                return $result
            }
            throw "backend bootstrap 暴露恢复动作失败（exit=$backendExitCode，诊断=$code）。"
        }
        if ([string]$result.state -cne "succeeded") {
            throw "backend bootstrap 暴露恢复未提交成功结果（state=$($result.state)）。"
        }
        return $result
    }
    finally {
        foreach ($name in $environmentNames) {
            $previous = $previousEnvironment[$name]
            if ($previous.Present) {
                Set-Item -Path "Env:$name" -Value $previous.Value
            }
            else {
                Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
            }
        }
    }
}

function Invoke-TicketboxBootstrapExposureRecovery(
    [string]$DatabaseUrl,
    [string]$ExposedSecret,
    [bool]$StartBackendAfterRecovery = $true
) {
    $replacementSecret = New-HttpBootstrapSecret
    if ($replacementSecret -ceq $ExposedSecret) {
        throw "bootstrap 暴露恢复生成了重复 secret。"
    }

    Write-TicketboxBootstrapExposureRecoveryGuard
    Write-TicketboxBootstrapExposureRecoveryIntent $ExposedSecret $replacementSecret
    return Resolve-TicketboxBootstrapExposureRecoveryIntent `
        -DatabaseUrl $DatabaseUrl `
        -StartBackendAfterRecovery $StartBackendAfterRecovery
}

function Protect-TicketboxBootstrapAfterRepeatedListenerFailure(
    [string]$DatabaseUrl,
    [string]$ExposedSecret
) {
    $replacementSecret = New-HttpBootstrapSecret
    if ($replacementSecret -ceq $ExposedSecret) {
        throw "bootstrap 二次暴露恢复生成了重复 secret。"
    }

    # The prior recovery completed before the replacement listener failed, so
    # arm a new durable recovery generation before removing that replacement
    # secret from runtime configuration. Do not attempt another live rotation
    # in this untrusted-listener process.
    Write-TicketboxBootstrapExposureRecoveryGuard
    Write-TicketboxBootstrapExposureRecoveryIntent $ExposedSecret $replacementSecret
    Write-TicketboxBootstrapQuarantineEnvironment $DatabaseUrl
    Disable-TicketboxOwnedServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable $ShawlExe `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments
    Wait-TicketboxBackendRuntimeStopped `
        -Name $BackendServiceName `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments
}

function Resolve-TicketboxBootstrapExposureRecoveryIntent(
    [string]$DatabaseUrl,
    [bool]$StartBackendAfterRecovery
) {
    $intent = Read-TicketboxBootstrapExposureRecoveryIntent
    if ($null -eq $intent) {
        if (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath) {
            Assert-TicketboxBootstrapExposureRecoveryGuard
            $environment = Read-EnvMap $EnvPath
            if (
                -not $environment.ContainsKey("HTTP_BOOTSTRAP_SECRET") -or
                [string]::IsNullOrWhiteSpace([string]$environment["HTTP_BOOTSTRAP_SECRET"])
            ) {
                throw "bootstrap 暴露恢复互锁存在，但缺少可恢复 intent 与旧 secret。"
            }
            return Invoke-TicketboxBootstrapExposureRecovery `
                -DatabaseUrl $DatabaseUrl `
                -ExposedSecret ([string]$environment["HTTP_BOOTSTRAP_SECRET"]) `
                -StartBackendAfterRecovery $StartBackendAfterRecovery
        }
        return $null
    }

    Write-TicketboxBootstrapExposureRecoveryGuard
    Disable-TicketboxOwnedServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable $ShawlExe `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments
    Write-TicketboxBootstrapQuarantineEnvironment $DatabaseUrl
    $collisionRetries = 0
    while ($true) {
        $maintenance = Invoke-TicketboxBootstrapExposureMaintenance `
            $intent.ExposedSecret `
            $intent.ReplacementSecret
        if (
            $null -eq $maintenance -or
            [string]$maintenance.state -ceq "succeeded"
        ) {
            break
        }
        if ([string]$maintenance.error_code -cne "replacement_credential_collision") {
            throw "backend bootstrap 暴露恢复返回了未知失败结果。"
        }
        $collisionRetries += 1
        if ($collisionRetries -gt 5) {
            throw "bootstrap 暴露恢复 replacement credential 连续碰撞，保持隔离等待修复。"
        }
        $nextReplacementSecret = New-HttpBootstrapSecret
        if ($nextReplacementSecret -ceq $intent.ExposedSecret) {
            throw "bootstrap 暴露恢复换代生成了重复 secret。"
        }
        Replace-TicketboxBootstrapExposureRecoveryIntent `
            -ExpectedExposedSecret $intent.ExposedSecret `
            -ExpectedReplacementSecret $intent.ReplacementSecret `
            -ReplacementSecret $nextReplacementSecret
        $intent = Read-TicketboxBootstrapExposureRecoveryIntent
    }
    Write-TicketboxBootstrapEnabledEnvironment $DatabaseUrl $intent.ReplacementSecret

    Remove-TicketboxBootstrapExposureRecoveryGuard
    Remove-TicketboxBootstrapExposureRecoveryIntent
    Set-TicketboxOwnedServiceStartPolicyIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable $ShawlExe `
        -StartPolicy "delayed_auto"
    if ($StartBackendAfterRecovery) {
        Start-TicketboxOwnedServiceIfExists `
            -Name $BackendServiceName `
            -ExpectedExecutable $ShawlExe `
            @ServiceWaitArguments | Out-Null
        Wait-BackendHealth
    }
    return $intent.ReplacementSecret
}
