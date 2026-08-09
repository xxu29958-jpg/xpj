#Requires -Version 5.1

$serviceIdentityScript = Join-Path $PSScriptRoot "windows_service_identity.ps1"
if (-not (Test-Path -LiteralPath $serviceIdentityScript -PathType Leaf)) {
    throw "Missing Windows service identity contract: $serviceIdentityScript"
}
. $serviceIdentityScript

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
        },
        [scriptblock]$RuntimeProcessReader = {
            param($ExpectedExecutables, $SnapshotReader)
            Get-TicketboxExpectedRuntimeProcessIds `
                -ExpectedExecutables $ExpectedExecutables `
                -ProcessSnapshotReader $SnapshotReader
        }
    )
    $listeners = @(
        if ($RuntimePort -gt 0) {
            & $ListenerReader $RuntimePort |
                Where-Object { [int]$_ -gt 0 } |
                Sort-Object -Unique
        }
    )
    $runtimeProcesses = @(
        & $RuntimeProcessReader $ExpectedRuntimeExecutables $ProcessSnapshotReader
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

function Get-TicketboxServiceRuntimeSnapshot([string]$Name) {
    $escaped = $Name.Replace("'", "''")
    $service = Get-CimInstance `
        -ClassName Win32_Service `
        -Filter "Name='$escaped'" `
        -ErrorAction Stop
    if ($null -eq $service) {
        throw "Windows 服务 $Name 不存在，无法读取 one-shot 退出状态。"
    }
    return [pscustomobject]@{
        State = ([string]$service.State).ToLowerInvariant()
        ProcessId = [uint32]$service.ProcessId
        ExitCode = [uint32]$service.ExitCode
        ServiceSpecificExitCode = [uint32]$service.ServiceSpecificExitCode
    }
}

function New-TicketboxRuntimeAbsentAssertion {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [ValidateRange(0, 65535)][int]$RuntimePort = 0,
        [string[]]$ExpectedRuntimeExecutables = @()
    )

    $functionBodies = @{}
    foreach ($functionName in @(
        "Assert-TicketboxRuntimeAbsent",
        "Get-TicketboxListeningProcessIds",
        "Get-TicketboxExpectedRuntimeProcessIds"
    )) {
        $commands = @(
            Get-Command `
                -Name $functionName `
                -CommandType Function `
                -ErrorAction SilentlyContinue
        )
        if (
            $commands.Count -ne 1 -or
            -not ($commands[0] -is [Management.Automation.FunctionInfo]) -or
            $null -eq $commands[0].ScriptBlock
        ) {
            throw "运行时缺失断言无法唯一捕获函数实现：$functionName"
        }
        $functionBodies[$functionName] = [scriptblock]$commands[0].ScriptBlock
    }

    $boundName = [string]$Name
    $boundRuntimePort = [int]$RuntimePort
    $boundExpectedExecutables = [string[]]@(
        $ExpectedRuntimeExecutables | ForEach-Object { [string]$_ }
    )
    $listeningProcessIdsBody =
        [scriptblock]$functionBodies["Get-TicketboxListeningProcessIds"]
    $expectedRuntimeProcessIdsBody =
        [scriptblock]$functionBodies["Get-TicketboxExpectedRuntimeProcessIds"]
    $runtimeAbsentBody =
        [scriptblock]$functionBodies["Assert-TicketboxRuntimeAbsent"]

    $listenerReader = {
        param($Port)
        & $listeningProcessIdsBody -Port $Port
    }.GetNewClosure()
    $runtimeProcessReader = {
        param($ExpectedExecutables, $SnapshotReader)
        & $expectedRuntimeProcessIdsBody `
            -ExpectedExecutables $ExpectedExecutables `
            -ProcessSnapshotReader $SnapshotReader
    }.GetNewClosure()
    $assertion = {
        & $runtimeAbsentBody `
            -Name $boundName `
            -RuntimePort $boundRuntimePort `
            -ExpectedRuntimeExecutables $boundExpectedExecutables `
            -ListenerReader $listenerReader `
            -RuntimeProcessReader $runtimeProcessReader
    }.GetNewClosure()
    return $assertion
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

function ConvertFrom-TicketboxScCreateArguments([string[]]$ScArgs) {
    if (
        $null -eq $ScArgs -or
        $ScArgs.Count -lt 8 -or
        -not [string]::Equals(
            [string]$ScArgs[0],
            "create",
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "sc.exe create 策略边界只接受完整参数。"
    }
    $serviceName = [string]$ScArgs[1]
    if (
        [string]::IsNullOrWhiteSpace($serviceName) -or
        $serviceName.Length -gt 256 -or
        $serviceName.IndexOfAny([char[]]@(0, 47, 92)) -ge 0
    ) {
        throw "sc.exe create 策略边界收到无效服务名。"
    }
    $options = @{}
    for ($index = 2; $index -lt $ScArgs.Count; $index += 2) {
        if ($index + 1 -ge $ScArgs.Count) {
            throw "sc.exe create 选项缺少值：$($ScArgs[$index])"
        }
        $name = ([string]$ScArgs[$index]).ToLowerInvariant()
        if ($name -notin @(
            "binpath=",
            "start=",
            "obj=",
            "depend=",
            "displayname="
        )) {
            throw "sc.exe create 策略边界拒绝不受支持的选项：$name"
        }
        if ($options.ContainsKey($name)) {
            throw "sc.exe create 选项重复：$name"
        }
        $value = [string]$ScArgs[$index + 1]
        if ($value.IndexOf([char]0) -ge 0) {
            throw "sc.exe create 选项包含 NUL：$name"
        }
        $options[$name] = $value
    }
    foreach ($required in @("binpath=", "start=", "obj=")) {
        if (-not $options.ContainsKey($required)) {
            throw "sc.exe create 缺少必要选项：$required"
        }
    }
    if ([string]::IsNullOrWhiteSpace([string]$options["binpath="])) {
        throw "sc.exe create 的 binPath 不能为空。"
    }
    $serviceStartName = ConvertTo-TicketboxServiceLogonAccount `
        -Name $serviceName `
        -Account ([string]$options["obj="])
    $startType = switch ([string]$options["start="]) {
        "auto" { [uint32]2; break }
        "demand" { [uint32]3; break }
        "disabled" { [uint32]4; break }
        default { throw "sc.exe create 策略边界不支持启动类型：$($options['start='])" }
    }
    $dependencies = @()
    if ($options.ContainsKey("depend=")) {
        $dependencies = @(
            ([string]$options["depend="]).Split([char]47) |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        if ($dependencies.Count -eq 0) {
            throw "sc.exe create 策略边界收到空依赖列表。"
        }
    }
    $displayName = if ($options.ContainsKey("displayname=")) {
        [string]$options["displayname="]
    }
    else {
        $serviceName
    }
    if ([string]::IsNullOrWhiteSpace($displayName) -or $displayName.Length -gt 256) {
        throw "sc.exe create 策略边界收到无效显示名。"
    }
    return [pscustomobject]@{
        ServiceName = $serviceName
        DisplayName = $displayName
        BinaryPath = [string]$options["binpath="]
        StartType = [uint32]$startType
        ServiceStartName = $serviceStartName
        Dependencies = [string[]]$dependencies
    }
}

function ConvertFrom-TicketboxScConfigArguments([string[]]$ScArgs) {
    if (
        $null -eq $ScArgs -or
        $ScArgs.Count -lt 4 -or
        -not [string]::Equals(
            [string]$ScArgs[0],
            "config",
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "sc.exe config 策略边界只接受完整参数。"
    }
    $serviceName = [string]$ScArgs[1]
    if (
        [string]::IsNullOrWhiteSpace($serviceName) -or
        $serviceName.Length -gt 256 -or
        $serviceName.IndexOfAny([char[]]@(0, 47, 92)) -ge 0
    ) {
        throw "sc.exe config 策略边界收到无效服务名。"
    }
    $options = @{}
    for ($index = 2; $index -lt $ScArgs.Count; $index += 2) {
        if ($index + 1 -ge $ScArgs.Count) {
            throw "sc.exe config 选项缺少值：$($ScArgs[$index])"
        }
        $name = ([string]$ScArgs[$index]).ToLowerInvariant()
        if ($name -notin @(
            "binpath=",
            "start=",
            "obj=",
            "depend=",
            "displayname="
        )) {
            throw "sc.exe config 策略边界拒绝不受支持的选项：$name"
        }
        if ($options.ContainsKey($name)) {
            throw "sc.exe config 选项重复：$name"
        }
        $value = [string]$ScArgs[$index + 1]
        if ($value.IndexOf([char]0) -ge 0) {
            throw "sc.exe config 选项包含 NUL：$name"
        }
        $options[$name] = $value
    }
    $changeBinaryPath = $options.ContainsKey("binpath=")
    $binaryPath = if ($changeBinaryPath) {
        [string]$options["binpath="]
    }
    else {
        ""
    }
    if ($changeBinaryPath -and [string]::IsNullOrWhiteSpace($binaryPath)) {
        throw "sc.exe config 的 binPath 不能为空。"
    }
    $changeStartType = $options.ContainsKey("start=")
    $startType = [uint32]0
    if ($changeStartType) {
        $startType = switch ([string]$options["start="]) {
            "auto" { [uint32]2; break }
            "delayed-auto" { [uint32]2; break }
            "demand" { [uint32]3; break }
            "disabled" { [uint32]4; break }
            default {
                throw "sc.exe config 策略边界不支持启动类型：$($options['start='])"
            }
        }
    }
    $changeServiceStartName = $options.ContainsKey("obj=")
    $serviceStartName = ""
    if ($changeServiceStartName) {
        $serviceStartName = ConvertTo-TicketboxServiceLogonAccount `
            -Name $serviceName `
            -Account ([string]$options["obj="])
    }
    $changeDependencies = $options.ContainsKey("depend=")
    $dependencies = @()
    if ($changeDependencies) {
        $dependencyText = [string]$options["depend="]
        if ($dependencyText.Length -gt 0) {
            $dependencies = @(
                $dependencyText.Split([char]47) |
                    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
            )
            if ($dependencies.Count -eq 0) {
                throw "sc.exe config 策略边界收到无效依赖列表。"
            }
        }
    }
    $changeDisplayName = $options.ContainsKey("displayname=")
    $displayName = if ($changeDisplayName) {
        [string]$options["displayname="]
    }
    else {
        ""
    }
    if (
        $changeDisplayName -and
        ([string]::IsNullOrWhiteSpace($displayName) -or $displayName.Length -gt 256)
    ) {
        throw "sc.exe config 策略边界收到无效显示名。"
    }
    return [pscustomobject]@{
        ServiceName = $serviceName
        ChangeBinaryPath = [bool]$changeBinaryPath
        BinaryPath = $binaryPath
        ChangeStartType = [bool]$changeStartType
        StartType = [uint32]$startType
        ChangeServiceStartName = [bool]$changeServiceStartName
        ServiceStartName = $serviceStartName
        ChangeDependencies = [bool]$changeDependencies
        Dependencies = [string[]]$dependencies
        ChangeDisplayName = [bool]$changeDisplayName
        DisplayName = $displayName
    }
}

function Invoke-TicketboxScProcess([string[]]$ScArgs) {
    if ($null -eq $ScArgs -or $ScArgs.Count -eq 0) {
        throw "Windows 服务控制器参数不能为空。"
    }
    foreach ($argument in $ScArgs) {
        $value = [string]$argument
        if (
            $value.IndexOf([char]0) -ge 0 -or
            $value.Contains("`r") -or
            $value.Contains("`n")
        ) {
            throw "Windows 服务控制器参数不能包含 NUL 或换行。"
        }
    }

    $verb = [string]$ScArgs[0]
    if ([string]::Equals(
        $verb,
        "create",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        ConvertFrom-TicketboxScCreateArguments $ScArgs | Out-Null
    }
    elseif ([string]::Equals(
        $verb,
        "config",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        ConvertFrom-TicketboxScConfigArguments $ScArgs | Out-Null
    }

    # PowerShell 7.3 changed native argument passing relative to Windows
    # PowerShell 5.1. Keep sc.exe argv construction inside the shared
    # CreateProcessW boundary so both supported hosts reach identical SCM input.
    $scExecutable = Get-TicketboxTrustedScExecutable
    if ($null -eq (Get-Command `
        Invoke-TicketboxBoundedNativeProcess `
        -CommandType Function `
        -ErrorAction SilentlyContinue)) {
        throw "Windows 服务控制器缺少统一的有界原生进程执行器。"
    }
    return Invoke-TicketboxBoundedNativeProcess `
        -FilePath $scExecutable `
        -Arguments $ScArgs `
        -TimeoutMilliseconds 30000 `
        -Label "Windows 服务控制器"
}

function Format-TicketboxScOperationForLog([string[]]$ScArgs) {
    if ($null -eq $ScArgs -or $ScArgs.Count -eq 0) {
        return "sc.exe"
    }
    $verb = [string]$ScArgs[0]
    $serviceName = if ($ScArgs.Count -gt 1) { [string]$ScArgs[1] } else { "<missing>" }
    $optionNames = @(
        for ($index = 2; $index -lt $ScArgs.Count; $index++) {
            $candidate = [string]$ScArgs[$index]
            if ($candidate.EndsWith("=", [System.StringComparison]::Ordinal)) {
                $candidate.ToLowerInvariant()
            }
        }
    )
    $optionSummary = if ($optionNames.Count -gt 0) {
        " options=" + ($optionNames -join ",")
    }
    else {
        ""
    }
    return "sc.exe $verb $serviceName$optionSummary"
}

function Invoke-TicketboxScChecked([string[]]$ScArgs) {
    $result = Invoke-TicketboxScProcess $ScArgs
    if (
        $null -eq $result -or
        $null -eq $result.PSObject.Properties["ExitCode"] -or
        $null -eq $result.PSObject.Properties["StandardOutput"] -or
        $null -eq $result.PSObject.Properties["StandardError"]
    ) {
        throw "Windows 服务控制器返回了无效结果。"
    }
    $output = @(
        [string]$result.StandardOutput
        [string]$result.StandardError
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $outputText = ($output -join "`n").Trim()
    if ([int]$result.ExitCode -ne 0) {
        $operation = Format-TicketboxScOperationForLog $ScArgs
        throw "$operation 失败（exit=$($result.ExitCode)）：`n$outputText"
    }
    if ([string]::IsNullOrWhiteSpace($outputText)) {
        return "[SC] $([string]$ScArgs[0]) SUCCESS (exit=0)"
    }
    return $outputText
}

function Get-TicketboxServiceSid([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name)) {
        throw "服务 SID 查询需要非空服务名。"
    }
    $output = Invoke-TicketboxScChecked @("showsid", $Name)
    $matches = [regex]::Matches(
        $output,
        '(?<![0-9A-Za-z-])S-1-5-80-(?:[0-9]+-){4}[0-9]+(?![0-9A-Za-z-])'
    )
    if ($matches.Count -ne 1) {
        throw "Windows 服务控制器未返回唯一服务 SID：$Name"
    }
    return (New-Object System.Security.Principal.SecurityIdentifier(
        $matches[0].Value
    )).Value
}

function Set-TicketboxServiceIdentityContract {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$LogonAccount,
        [Parameter(Mandatory = $true)][string]$SidType
    )

    $targetShape = New-TicketboxServiceIdentityShape `
        -Name $Name `
        -LogonAccount $LogonAccount `
        -SidType $SidType
    $snapshot = Get-TicketboxServiceIdentitySnapshot $Name
    if ([string]$snapshot.SidType -cne [string]$targetShape.SidType) {
        Set-TicketboxServiceSidType `
            -Name $Name `
            -SidType ([string]$targetShape.SidType)
    }
    if (-not [string]::Equals(
        [string]$snapshot.LogonAccount,
        [string]$targetShape.LogonAccount,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        Invoke-TicketboxScChecked @(
            "config",
            $Name,
            "obj=",
            [string]$targetShape.LogonAccount
        ) | Out-Null
    }
    Assert-TicketboxServiceIdentityShape `
        -Name $Name `
        -AllowedShapes @($targetShape) | Out-Null
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

function Invoke-TicketboxOwnedOneShotService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][string[]]$ExpectedRuntimeExecutables,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [scriptblock]$SnapshotReader = {
            param($ServiceName)
            Get-TicketboxServiceRuntimeSnapshot $ServiceName
        },
        [scriptblock]$StartAction = {
            param($ServiceName)
            Invoke-TicketboxScChecked @("start", $ServiceName) | Out-Null
        },
        [scriptblock]$SleepAction = {
            param($Milliseconds)
            Start-Sleep -Milliseconds $Milliseconds
        }
    )

    if (-not (Assert-TicketboxServiceOwnership $Name $ExpectedExecutable)) {
        throw "Windows one-shot 服务 $Name 不存在。"
    }
    & $StartAction $Name
    $deadline = New-TicketboxWaitDeadline $TimeoutMilliseconds
    $snapshot = $null
    do {
        $snapshot = & $SnapshotReader $Name
        if ([string]$snapshot.State -ceq "stopped") {
            break
        }
        if ([string]$snapshot.State -ceq "paused") {
            throw "Windows one-shot 服务 $Name 意外进入 paused。"
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds `
        -SleepAction $SleepAction)
    if ($null -eq $snapshot -or [string]$snapshot.State -cne "stopped") {
        throw "Windows one-shot 服务 $Name 未在 $TimeoutMilliseconds ms 内停止。"
    }
    Wait-TicketboxBackendRuntimeStopped `
        -Name $Name `
        -ExpectedRuntimeExecutables $ExpectedRuntimeExecutables `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds `
        -SleepAction $SleepAction
    $snapshot = & $SnapshotReader $Name
    if (
        [string]$snapshot.State -cne "stopped" -or
        [uint32]$snapshot.ProcessId -ne 0
    ) {
        throw "Windows one-shot 服务 $Name 的终态或进程身份不可信。"
    }
    return $snapshot
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
