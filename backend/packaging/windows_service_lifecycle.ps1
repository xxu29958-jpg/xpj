#Requires -Version 5.1

$serviceContractScript = Join-Path $PSScriptRoot "windows_service_contract.ps1"
if (-not (Test-Path -LiteralPath $serviceContractScript -PathType Leaf)) {
    throw "缺少 Windows 服务命令契约脚本：$serviceContractScript"
}
. $serviceContractScript

function Test-TicketboxServiceExists([string]$Name) {
    return $null -ne (Get-Service -Name $Name -ErrorAction SilentlyContinue)
}

function Assert-TicketboxServiceOwnership([string]$Name, [string]$ExpectedExecutable) {
    if (-not (Test-TicketboxServiceExists $Name)) {
        return $false
    }

    $actual = Get-TicketboxServiceExecutablePath $Name
    $expected = [System.IO.Path]::GetFullPath($ExpectedExecutable)
    if (-not [string]::Equals($actual, $expected, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作同名外部服务 $Name：ImagePath 为 $actual，预期为 $expected。请先更改服务名或修复原安装。"
    }
    return $true
}

function Assert-TicketboxServiceAccount([string]$Name, [string]$ExpectedAccount) {
    $escaped = $Name.Replace("'", "''")
    $record = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escaped'" -ErrorAction Stop
    $actual = [string]$record.StartName
    if (-not [string]::Equals($actual, $ExpectedAccount, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作账户不匹配的服务 $Name：运行账户为 $actual，预期为 $ExpectedAccount。"
    }
}

function Get-TicketboxServiceStartMode([string]$Name) {
    $escaped = $Name.Replace("'", "''")
    $record = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escaped'" -ErrorAction Stop
    return [string]$record.StartMode
}

function Get-TicketboxServiceStartPolicy([string]$Name) {
    $startMode = Get-TicketboxServiceStartMode $Name
    switch ($startMode.ToLowerInvariant()) {
        "disabled" { return "disabled" }
        "manual" { return "manual" }
        "auto" {
            $serviceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$Name"
            $properties = Get-ItemProperty `
                -LiteralPath $serviceKey `
                -Name "DelayedAutoStart" `
                -ErrorAction SilentlyContinue
            if (
                $null -ne $properties -and
                $null -ne $properties.PSObject.Properties["DelayedAutoStart"] -and
                [int]$properties.DelayedAutoStart -eq 1
            ) {
                return "delayed_auto"
            }
            return "auto"
        }
        default { throw "Windows 服务 $Name 使用不受支持的启动模式：$startMode。" }
    }
}

function Get-TicketboxServiceProcessId([string]$Name) {
    $escaped = $Name.Replace("'", "''")
    $record = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escaped'" -ErrorAction Stop
    if ($null -eq $record) {
        return 0
    }
    return [int]$record.ProcessId
}

function Get-TicketboxListeningProcessIds {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [scriptblock]$ConnectionReader = {
            param([int]$ListeningPort)
            Get-NetTCPConnection `
                -State Listen `
                -LocalPort $ListeningPort `
                -ErrorAction Stop
        }
    )

    try {
        $connections = @(& $ConnectionReader $Port)
    }
    catch {
        if (
            [string]$_.FullyQualifiedErrorId -eq
            "CmdletizationQuery_NotFound,Get-NetTCPConnection"
        ) {
            return @()
        }
        throw
    }
    return @(
        $connections |
            ForEach-Object { [int]$_.OwningProcess } |
            Where-Object { $_ -gt 0 } |
            Sort-Object -Unique
    )
}

function Get-TicketboxExpectedRuntimeProcessIds {
    param(
        [string[]]$ExpectedExecutables = @(),
        [scriptblock]$ProcessSnapshotReader = {
            Get-CimInstance -ClassName Win32_Process -ErrorAction Stop
        }
    )

    $expectedPaths = @(
        $ExpectedExecutables |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { [System.IO.Path]::GetFullPath($_) } |
            Sort-Object -Unique
    )
    if ($expectedPaths.Count -eq 0) { return @() }
    $expectedNames = @($expectedPaths | ForEach-Object { [System.IO.Path]::GetFileName($_) })
    return @(
        foreach ($record in @(& $ProcessSnapshotReader)) {
            $processId = [int]$record.ProcessId
            if ($processId -le 0) { continue }
            $name = [string]$record.Name
            $executablePath = [string]$record.ExecutablePath
            if ([string]::IsNullOrWhiteSpace($executablePath)) {
                if ($expectedNames -contains $name) { $processId }
                continue
            }
            $canonicalPath = [System.IO.Path]::GetFullPath($executablePath)
            foreach ($expectedPath in $expectedPaths) {
                if ([string]::Equals(
                    $canonicalPath,
                    $expectedPath,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                    $processId
                    break
                }
            }
        }
    ) | Sort-Object -Unique
}

function Assert-TicketboxRuntimeAbsent {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [ValidateRange(0, 65535)][int]$RuntimePort = 0,
        [string[]]$ExpectedRuntimeExecutables = @(),
        [scriptblock]$ListenerReader = {
            param($Port)
            Get-TicketboxListeningProcessIds $Port
        },
        [scriptblock]$ProcessSnapshotReader = {
            Get-CimInstance -ClassName Win32_Process -ErrorAction Stop
        }
    )
    $listeners = if ($RuntimePort -gt 0) {
        @(& $ListenerReader $RuntimePort | Where-Object { [int]$_ -gt 0 } | Sort-Object -Unique)
    }
    else {
        @()
    }
    $runtimeProcesses = @(
        Get-TicketboxExpectedRuntimeProcessIds `
            -ExpectedExecutables $ExpectedRuntimeExecutables `
            -ProcessSnapshotReader $ProcessSnapshotReader
    )
    if ($listeners.Count -gt 0 -or $runtimeProcesses.Count -gt 0) {
        throw "Windows 服务 $Name 缺失，但运行时仍存在（端口 PID：$($listeners -join ',')；安装路径 PID：$($runtimeProcesses -join ',')）。"
    }
}

function Assert-TicketboxServiceStartMode([string]$Name, [string]$ExpectedStartMode) {
    $actual = Get-TicketboxServiceStartMode $Name
    if (-not [string]::Equals($actual, $ExpectedStartMode, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Windows 服务 $Name 的启动模式为 $actual，预期为 $ExpectedStartMode。"
    }
}

function Assert-TicketboxServiceDelayedAutoStart([string]$Name) {
    Assert-TicketboxServiceStartMode -Name $Name -ExpectedStartMode "Auto"
    $serviceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$Name"
    $delayed = (Get-ItemProperty `
        -LiteralPath $serviceKey `
        -Name "DelayedAutoStart" `
        -ErrorAction Stop).DelayedAutoStart
    if ([int]$delayed -ne 1) {
        throw "Windows 服务 $Name 未配置 delayed-auto。"
    }
}

function Assert-TicketboxServiceStartPolicy {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet(
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        )][string]$ExpectedStartPolicy
    )

    $actual = Get-TicketboxServiceStartPolicy $Name
    if (-not [string]::Equals($actual, $ExpectedStartPolicy, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Windows 服务 $Name 的启动策略为 $actual，预期为 $ExpectedStartPolicy。"
    }
}

function Get-TicketboxServiceState([string]$Name) {
    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        return "absent"
    }
    return $service.Status.ToString().ToLowerInvariant()
}

function Wait-TicketboxServiceSettledState {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [scriptblock]$StateReader = { param($ServiceName) Get-TicketboxServiceState $ServiceName },
        [scriptblock]$SleepAction = { param($Milliseconds) Start-Sleep -Milliseconds $Milliseconds }
    )

    $deadline = New-TicketboxWaitDeadline $TimeoutMilliseconds
    $lastState = "unknown"
    do {
        $lastState = [string](& $StateReader $Name)
        if ($lastState -in @("running", "stopped", "absent")) {
            return $lastState
        }
        if ($lastState -eq "paused") {
            throw "Windows 服务 $Name 处于 paused；请先恢复或停止服务后重试。"
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds `
        -SleepAction $SleepAction)
    throw "Windows 服务 $Name 未在 $TimeoutMilliseconds ms 内离开过渡状态（当前：$lastState）。"
}

function Wait-TicketboxServiceState {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("running", "stopped", "absent")][string]$DesiredState,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [scriptblock]$StateReader = { param($ServiceName) Get-TicketboxServiceState $ServiceName },
        [scriptblock]$SleepAction = { param($Milliseconds) Start-Sleep -Milliseconds $Milliseconds }
    )

    $deadline = New-TicketboxWaitDeadline $TimeoutMilliseconds
    $lastState = "unknown"
    do {
        $lastState = [string](& $StateReader $Name)
        if ($lastState -eq $DesiredState) {
            return
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds `
        -SleepAction $SleepAction)
    throw "Windows 服务 $Name 未在 $TimeoutMilliseconds ms 内进入 $DesiredState（当前：$lastState）。"
}

function Get-TicketboxTrustedScExecutable {
    $systemDirectory = [Environment]::SystemDirectory
    if (
        [string]::IsNullOrWhiteSpace($systemDirectory) -or
        -not [System.IO.Path]::IsPathRooted($systemDirectory)
    ) {
        throw "Windows 系统目录不可用，拒绝调用服务控制器。"
    }
    $scExecutable = [System.IO.Path]::GetFullPath((Join-Path $systemDirectory "sc.exe"))
    if (-not (Test-Path -LiteralPath $scExecutable -PathType Leaf)) {
        throw "Windows 服务控制器不存在或不是普通文件：$scExecutable"
    }
    $scItem = Get-Item -LiteralPath $scExecutable -Force -ErrorAction Stop
    if (($scItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Windows 服务控制器是重解析点，拒绝执行：$scExecutable"
    }
    return $scExecutable
}

function Invoke-TicketboxScChecked([string[]]$ScArgs) {
    $scExecutable = Get-TicketboxTrustedScExecutable
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $scExecutable @ScArgs 2>&1
        $rc = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($rc -ne 0) {
        throw "$scExecutable $($ScArgs -join ' ') 失败（exit=$rc）：`n$out"
    }
    return ($out | Out-String).Trim()
}

function Set-TicketboxOwnedServiceDemandStartIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable
    )

    if (-not (Assert-TicketboxServiceOwnership $Name $ExpectedExecutable)) {
        return
    }
    Invoke-TicketboxScChecked @("config", $Name, "start=", "demand") | Out-Null
    Assert-TicketboxServiceStartMode -Name $Name -ExpectedStartMode "Manual"
}

function Set-TicketboxOwnedServiceDelayedAutoStartIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable
    )

    if (-not (Assert-TicketboxServiceOwnership $Name $ExpectedExecutable)) {
        return
    }
    Invoke-TicketboxScChecked @("config", $Name, "start=", "delayed-auto") | Out-Null
    Assert-TicketboxServiceDelayedAutoStart $Name
}

function Set-TicketboxOwnedServiceStartPolicyIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][ValidateSet(
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        )][string]$StartPolicy
    )

    if (-not (Assert-TicketboxServiceOwnership $Name $ExpectedExecutable)) {
        return
    }
    $scStartMode = switch ($StartPolicy) {
        "disabled" { "disabled" }
        "manual" { "demand" }
        "auto" { "auto" }
        "delayed_auto" { "delayed-auto" }
    }
    Invoke-TicketboxScChecked @("config", $Name, "start=", $scStartMode) | Out-Null
    Assert-TicketboxServiceStartPolicy -Name $Name -ExpectedStartPolicy $StartPolicy
}

function Wait-TicketboxBackendRuntimeStopped {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [ValidateRange(0, 65535)][int]$BackendPort = 0,
        [string[]]$ExpectedRuntimeExecutables = @(),
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [scriptblock]$ListenerReader = {
            param($Port)
            Get-TicketboxListeningProcessIds $Port
        },
        [scriptblock]$RuntimeProcessReader = {
            Get-CimInstance -ClassName Win32_Process -ErrorAction Stop
        },
        [scriptblock]$SleepAction = { param($Milliseconds) Start-Sleep -Milliseconds $Milliseconds }
    )

    if (
        $BackendPort -eq 0 -and
        @($ExpectedRuntimeExecutables | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -eq 0
    ) {
        throw "Windows 服务 $Name 的运行时停止证明缺少监听端口和精确可执行文件。"
    }
    $deadline = New-TicketboxWaitDeadline $TimeoutMilliseconds
    $lastListeners = @()
    $lastRuntimeProcesses = @()
    do {
        $lastListeners = if ($BackendPort -gt 0) {
            @(& $ListenerReader $BackendPort | Where-Object { [int]$_ -gt 0 } | Sort-Object -Unique)
        }
        else {
            @()
        }
        $lastRuntimeProcesses = @(
            Get-TicketboxExpectedRuntimeProcessIds `
                -ExpectedExecutables $ExpectedRuntimeExecutables `
                -ProcessSnapshotReader $RuntimeProcessReader
        )
        if (
            $lastListeners.Count -eq 0 -and
            $lastRuntimeProcesses.Count -eq 0
        ) {
            return
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds `
        -SleepAction $SleepAction)
    throw "Windows 服务 $Name 已停止或缺失，但运行时仍残留（监听 PID：$($lastListeners -join ',')；安装路径 PID：$($lastRuntimeProcesses -join ',')）。"
}

function Disable-TicketboxOwnedServiceIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [ValidateRange(0, 65535)][int]$BackendPort = 0,
        [string[]]$ExpectedRuntimeExecutables = @()
    )

    Stop-TicketboxOwnedServiceIfExists `
        -Name $Name `
        -ExpectedExecutable $ExpectedExecutable `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables $ExpectedRuntimeExecutables
    if (-not (Assert-TicketboxServiceOwnership $Name $ExpectedExecutable)) {
        return
    }
    Invoke-TicketboxScChecked @("config", $Name, "start=", "disabled") | Out-Null
    Assert-TicketboxServiceStartMode -Name $Name -ExpectedStartMode "Disabled"
}

function Stop-TicketboxOwnedServiceIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [ValidateRange(0, 65535)][int]$BackendPort = 0,
        [string[]]$ExpectedRuntimeExecutables = @()
    )

    $serviceExists = Assert-TicketboxServiceOwnership $Name $ExpectedExecutable
    if (-not $serviceExists) {
        Wait-TicketboxBackendRuntimeStopped `
            -Name $Name `
            -BackendPort $BackendPort `
            -ExpectedRuntimeExecutables $ExpectedRuntimeExecutables `
            -TimeoutMilliseconds $TimeoutMilliseconds `
            -PollMilliseconds $PollMilliseconds
        return
    }
    $waitArguments = @{
        Name = $Name
        TimeoutMilliseconds = $TimeoutMilliseconds
        PollMilliseconds = $PollMilliseconds
    }
    if ((Wait-TicketboxServiceSettledState @waitArguments) -ne "stopped") {
        Stop-Service -Name $Name -Force -ErrorAction Stop
        Wait-TicketboxServiceState @waitArguments -DesiredState "stopped"
    }
    Wait-TicketboxBackendRuntimeStopped `
        -Name $Name `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables $ExpectedRuntimeExecutables `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds
}

function Start-TicketboxOwnedServiceIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds
    )

    if (-not (Assert-TicketboxServiceOwnership $Name $ExpectedExecutable)) {
        return $false
    }
    $waitArguments = @{
        Name = $Name
        TimeoutMilliseconds = $TimeoutMilliseconds
        PollMilliseconds = $PollMilliseconds
    }
    if ((Wait-TicketboxServiceSettledState @waitArguments) -ne "running") {
        Start-Service -Name $Name -ErrorAction Stop
        Wait-TicketboxServiceState @waitArguments -DesiredState "running"
    }
    return $true
}

function Restart-TicketboxOwnedServiceIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [ValidateRange(0, 65535)][int]$BackendPort = 0,
        [string[]]$ExpectedRuntimeExecutables = @()
    )

    if (-not (Assert-TicketboxServiceOwnership $Name $ExpectedExecutable)) {
        return $false
    }
    $arguments = @{
        Name = $Name
        ExpectedExecutable = $ExpectedExecutable
        TimeoutMilliseconds = $TimeoutMilliseconds
        PollMilliseconds = $PollMilliseconds
        BackendPort = $BackendPort
        ExpectedRuntimeExecutables = $ExpectedRuntimeExecutables
    }
    Stop-TicketboxOwnedServiceIfExists @arguments
    $arguments.Remove("BackendPort") | Out-Null
    $arguments.Remove("ExpectedRuntimeExecutables") | Out-Null
    Start-TicketboxOwnedServiceIfExists @arguments | Out-Null
    return $true
}

function Remove-TicketboxOwnedServiceIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [ValidateRange(0, 65535)][int]$BackendPort = 0,
        [string[]]$ExpectedRuntimeExecutables = @()
    )

    if (-not (Test-TicketboxServiceExists $Name)) {
        Wait-TicketboxBackendRuntimeStopped `
            -Name $Name `
            -BackendPort $BackendPort `
            -ExpectedRuntimeExecutables $ExpectedRuntimeExecutables `
            -TimeoutMilliseconds $TimeoutMilliseconds `
            -PollMilliseconds $PollMilliseconds
        return
    }
    $arguments = @{
        Name = $Name
        ExpectedExecutable = $ExpectedExecutable
        TimeoutMilliseconds = $TimeoutMilliseconds
        PollMilliseconds = $PollMilliseconds
        BackendPort = $BackendPort
        ExpectedRuntimeExecutables = $ExpectedRuntimeExecutables
    }
    Stop-TicketboxOwnedServiceIfExists @arguments
    Invoke-TicketboxScChecked @("delete", $Name) | Out-Null
    $arguments.Remove("ExpectedExecutable") | Out-Null
    $arguments.Remove("BackendPort") | Out-Null
    $arguments.Remove("ExpectedRuntimeExecutables") | Out-Null
    Wait-TicketboxServiceState @arguments -DesiredState "absent"
}
