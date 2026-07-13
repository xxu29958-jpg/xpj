#Requires -Version 5.1

function Initialize-TicketboxCommandLineNativeMethods {
    if ("TicketboxCommandLineNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class TicketboxCommandLineNativeMethods
{
    [DllImport("shell32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern IntPtr CommandLineToArgvW(string commandLine, out int argumentCount);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr LocalFree(IntPtr memory);
}
'@
}

function Split-TicketboxWindowsCommandLine([string]$CommandLine) {
    Initialize-TicketboxCommandLineNativeMethods
    $argumentCount = 0
    $argumentList = [TicketboxCommandLineNativeMethods]::CommandLineToArgvW($CommandLine, [ref]$argumentCount)
    if ($argumentList -eq [IntPtr]::Zero) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "无法按 Windows 规则解析服务命令行（Win32=$errorCode）。"
    }
    try {
        $arguments = @()
        for ($i = 0; $i -lt $argumentCount; $i++) {
            $valuePointer = [Runtime.InteropServices.Marshal]::ReadIntPtr($argumentList, $i * [IntPtr]::Size)
            $arguments += [Runtime.InteropServices.Marshal]::PtrToStringUni($valuePointer)
        }
        return $arguments
    }
    finally {
        [TicketboxCommandLineNativeMethods]::LocalFree($argumentList) | Out-Null
    }
}

function ConvertTo-TicketboxWindowsCommandLineArgument([string]$Value) {
    if ($Value.IndexOf([char]0) -ge 0 -or $Value.Contains("`r") -or $Value.Contains("`n")) {
        throw "Windows 服务参数不能包含 NUL 或换行。"
    }
    if ($Value.Contains('"')) {
        throw "Windows 服务参数不能包含双引号。"
    }
    if ($Value.Length -gt 0 -and $Value -notmatch '\s') {
        return $Value
    }
    $trailingBackslashes = $Value.Length - $Value.TrimEnd([char]'\').Length
    $bodyLength = $Value.Length - $trailingBackslashes
    $body = if ($bodyLength -gt 0) { $Value.Substring(0, $bodyLength) } else { "" }
    return '"' + $body + ('\' * ($trailingBackslashes * 2)) + '"'
}

function Join-TicketboxWindowsCommandLine([string[]]$Arguments) {
    if ($Arguments.Count -eq 0) {
        throw "Windows 服务命令行不能为空。"
    }
    return (@($Arguments | ForEach-Object {
        ConvertTo-TicketboxWindowsCommandLineArgument ([string]$_)
    }) -join " ")
}

function New-TicketboxPgServiceImagePath {
    param(
        [Parameter(Mandatory = $true)][string]$PgCtlPath,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$DataRoot
    )
    return Join-TicketboxWindowsCommandLine @(
        (ConvertTo-TicketboxFullPath $PgCtlPath),
        "runservice",
        "-N",
        $ServiceName,
        "-D",
        (ConvertTo-TicketboxFullPath $DataRoot),
        "-w"
    )
}

function New-TicketboxShawlServiceImagePath {
    param(
        [Parameter(Mandatory = $true)][string]$ShawlPath,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$LogDirectory,
        [Parameter(Mandatory = $true)][string]$BackendPath,
        [Parameter(Mandatory = $true)][string]$PgDumpPath,
        [Parameter(Mandatory = $true)][string]$PgRestorePath,
        [Parameter(Mandatory = $true)][string]$BootstrapRecoveryGuardPath,
        [Parameter(Mandatory = $true)][string]$InstallerRecoveryGuardPath,
        [Parameter(Mandatory = $true)][string]$DataRootMarkerPath,
        [Parameter(Mandatory = $true)][string]$DataVolumeIdentity,
        [Parameter(Mandatory = $true)][int]$StopTimeoutMs,
        [Parameter(Mandatory = $true)][int]$RestartDelayMs
    )
    if ($DataVolumeIdentity -notmatch '^\\\\\?\\Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}\\$') {
        throw "Shawl 服务需要规范的 Windows Volume GUID identity。"
    }
    return Join-TicketboxWindowsCommandLine @(
        (ConvertTo-TicketboxFullPath $ShawlPath),
        "run",
        "--name",
        $ServiceName,
        "--stop-timeout",
        [string]$StopTimeoutMs,
        "--restart",
        "--kill-process-tree",
        "--restart-delay",
        [string]$RestartDelayMs,
        "--cwd",
        (ConvertTo-TicketboxFullPath $WorkingDirectory),
        "--log-dir",
        (ConvertTo-TicketboxFullPath $LogDirectory),
        "--env",
        "TICKETBOX_DATA_DIR=$(ConvertTo-TicketboxFullPath $WorkingDirectory)",
        "--env",
        "PG_DUMP_PATH=$(ConvertTo-TicketboxFullPath $PgDumpPath)",
        "--env",
        "PG_RESTORE_PATH=$(ConvertTo-TicketboxFullPath $PgRestorePath)",
        "--env",
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH=$(ConvertTo-TicketboxFullPath $BootstrapRecoveryGuardPath)",
        "--env",
        "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH=$(ConvertTo-TicketboxFullPath $InstallerRecoveryGuardPath)",
        "--env",
        "TICKETBOX_DATA_ROOT_MARKER_PATH=$(ConvertTo-TicketboxFullPath $DataRootMarkerPath)",
        "--env",
        "TICKETBOX_DATA_VOLUME_IDENTITY=$($DataVolumeIdentity.ToUpperInvariant())",
        "--",
        (ConvertTo-TicketboxFullPath $BackendPath)
    )
}

function ConvertTo-TicketboxFullPath([string]$Path) {
    $expanded = [Environment]::ExpandEnvironmentVariables($Path).Trim()
    if ($expanded.StartsWith('\??\')) {
        $expanded = $expanded.Substring(4)
    }
    return [System.IO.Path]::GetFullPath($expanded)
}

function Get-TicketboxServiceImagePath([string]$Name) {
    $escaped = $Name.Replace("'", "''")
    $record = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escaped'" -ErrorAction Stop
    if ($null -eq $record -or [string]::IsNullOrWhiteSpace([string]$record.PathName)) {
        throw "无法读取 Windows 服务 $Name 的 ImagePath。"
    }
    return [Environment]::ExpandEnvironmentVariables([string]$record.PathName).Trim()
}

function Get-TicketboxServiceDependencies([string]$Name) {
    $escaped = $Name.Replace("'", "''")
    $record = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escaped'" -ErrorAction Stop
    if ($null -eq $record) {
        throw "无法读取 Windows 服务 $Name 的依赖。"
    }
    return @($record.Dependencies | ForEach-Object { [string]$_ })
}

function Assert-TicketboxServiceDependencies(
    [string]$Name,
    [string[]]$ExpectedDependencies = @()
) {
    $actualDependencies = @(
        Get-TicketboxServiceDependencies $Name |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
    $expected = @(
        $ExpectedDependencies |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
    if ($actualDependencies.Count -ne $expected.Count) {
        throw "Windows 服务 $Name 的 SCM 依赖与安装配置不一致。"
    }
    for ($index = 0; $index -lt $expected.Count; $index++) {
        if (-not [string]::Equals(
            $actualDependencies[$index],
            $expected[$index],
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Windows 服务 $Name 的 SCM 依赖与安装配置不一致。"
        }
    }
}

function Initialize-TicketboxServiceFailurePolicyNativeMethods {
    if ("TicketboxServiceFailurePolicyNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class TicketboxServiceFailurePolicyNativeMethods
{
    [StructLayout(LayoutKind.Sequential)]
    private struct SERVICE_FAILURE_ACTIONS
    {
        public uint ResetPeriod;
        public IntPtr RebootMessage;
        public IntPtr Command;
        public uint ActionCount;
        public IntPtr Actions;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SC_ACTION
    {
        public int Type;
        public uint Delay;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr OpenSCManager(string machine, string database, uint access);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr OpenService(IntPtr manager, string name, uint access);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryServiceConfig2(
        IntPtr service,
        uint infoLevel,
        IntPtr buffer,
        uint bufferSize,
        out uint bytesNeeded);

    [DllImport("advapi32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseServiceHandle(IntPtr handle);

    public static string ReadPolicy(string serviceName)
    {
        IntPtr manager = OpenSCManager(null, null, 0x0001);
        if (manager == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        IntPtr service = IntPtr.Zero;
        IntPtr buffer = IntPtr.Zero;
        try
        {
            service = OpenService(manager, serviceName, 0x0001);
            if (service == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            uint needed;
            QueryServiceConfig2(service, 2, IntPtr.Zero, 0, out needed);
            if (needed == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            buffer = Marshal.AllocHGlobal(checked((int)needed));
            if (!QueryServiceConfig2(service, 2, buffer, needed, out needed))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            SERVICE_FAILURE_ACTIONS policy =
                (SERVICE_FAILURE_ACTIONS)Marshal.PtrToStructure(buffer, typeof(SERVICE_FAILURE_ACTIONS));
            var actions = new List<string>();
            int actionSize = Marshal.SizeOf(typeof(SC_ACTION));
            if (policy.ActionCount > 0 && policy.Actions == IntPtr.Zero)
                throw new InvalidOperationException("Service failure action pointer is null.");
            for (int index = 0; index < policy.ActionCount; index++)
            {
                IntPtr actionPointer = IntPtr.Add(policy.Actions, checked(index * actionSize));
                SC_ACTION action = (SC_ACTION)Marshal.PtrToStructure(actionPointer, typeof(SC_ACTION));
                actions.Add(action.Type.ToString() + ":" + action.Delay.ToString());
            }
            return policy.ResetPeriod.ToString() + "|" + string.Join(",", actions.ToArray());
        }
        finally
        {
            if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer);
            if (service != IntPtr.Zero) CloseServiceHandle(service);
            CloseServiceHandle(manager);
        }
    }
}
'@
}

function Assert-TicketboxServiceFailurePolicy {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateRange(1, 86400)][int]$ExpectedResetSeconds,
        [Parameter(Mandatory = $true)][int[]]$ExpectedRestartDelaysMs
    )
    Initialize-TicketboxServiceFailurePolicyNativeMethods
    $expectedActions = @(
        $ExpectedRestartDelaysMs | ForEach-Object { "1:$([uint32]$_)" }
    ) -join ","
    $expected = "${ExpectedResetSeconds}|${expectedActions}"
    $actual = [TicketboxServiceFailurePolicyNativeMethods]::ReadPolicy($Name)
    if ($actual -cne $expected) {
        throw "Windows 服务 $Name 的 SCM failure policy 与安装配置不一致。"
    }
}

function ConvertTo-TicketboxServiceExecutablePath([string]$ImagePath) {
    $expanded = [Environment]::ExpandEnvironmentVariables($ImagePath).Trim()
    if (-not $expanded.StartsWith('"') -and $expanded -match '^(.*?\.exe)(?:\s|$)' -and $Matches[1] -match '\s') {
        throw "拒绝未加引号且含空格的 Windows 服务 ImagePath：$ImagePath"
    }
    $arguments = @(Split-TicketboxWindowsCommandLine $expanded)
    if ($arguments.Count -eq 0 -or -not $arguments[0].EndsWith(".exe", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "无法解析 Windows 服务 ImagePath：$ImagePath"
    }
    return ConvertTo-TicketboxFullPath $arguments[0]
}

function Get-TicketboxServiceExecutablePath([string]$Name) {
    return ConvertTo-TicketboxServiceExecutablePath (Get-TicketboxServiceImagePath $Name)
}

function Get-TicketboxCommandArgumentValues([string]$ImagePath, [string]$ArgumentName) {
    $arguments = @(Split-TicketboxWindowsCommandLine $ImagePath)
    $values = @()
    for ($i = 1; $i -lt $arguments.Count; $i++) {
        if ([string]::Equals($arguments[$i], $ArgumentName, [System.StringComparison]::OrdinalIgnoreCase)) {
            if ($i + 1 -ge $arguments.Count) {
                throw "Windows 服务 ImagePath 中参数 $ArgumentName 缺少值。"
            }
            $values += $arguments[$i + 1]
            $i++
        }
        elseif ($arguments[$i].StartsWith("$ArgumentName=", [System.StringComparison]::OrdinalIgnoreCase)) {
            $values += $arguments[$i].Substring($ArgumentName.Length + 1)
        }
    }
    return $values
}

function Get-TicketboxCommandArgumentValue([string]$ImagePath, [string]$ArgumentName) {
    $values = @(Get-TicketboxCommandArgumentValues $ImagePath $ArgumentName)
    if ($values.Count -ne 1) {
        throw "Windows 服务 ImagePath 中参数 $ArgumentName 必须且只能出现一次（实际：$($values.Count)）。"
    }
    return [string]$values[0]
}

function Get-TicketboxServiceArgumentValue([string]$Name, [string]$ArgumentName) {
    try {
        return Get-TicketboxCommandArgumentValue (Get-TicketboxServiceImagePath $Name) $ArgumentName
    }
    catch {
        throw "Windows 服务 $Name 的 ImagePath 参数无效：$($_.Exception.Message)"
    }
}

function Assert-TicketboxServiceArgumentValue(
    [string]$Name,
    [string]$ArgumentName,
    [string]$ExpectedValue
) {
    $actual = Get-TicketboxServiceArgumentValue $Name $ArgumentName
    if (-not [string]::Equals($actual, $ExpectedValue, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作配置不匹配的服务 $Name：参数 $ArgumentName 为 $actual，预期为 $ExpectedValue。"
    }
}

function Assert-TicketboxServiceArgumentPath(
    [string]$Name,
    [string]$ArgumentName,
    [string]$ExpectedPath
) {
    $actual = ConvertTo-TicketboxFullPath (Get-TicketboxServiceArgumentValue $Name $ArgumentName)
    $expected = ConvertTo-TicketboxFullPath $ExpectedPath
    if (-not [string]::Equals($actual, $expected, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作配置不匹配的服务 $Name：参数 $ArgumentName 指向 $actual，预期为 $expected。"
    }
}

function Assert-TicketboxPgServiceCommand {
    param(
        [string]$Name,
        [string]$ExpectedExecutable,
        [string]$ExpectedServiceName,
        [string]$ExpectedDataRoot
    )

    Assert-TicketboxServiceDependencies -Name $Name -ExpectedDependencies @()
    $arguments = @(Split-TicketboxWindowsCommandLine (Get-TicketboxServiceImagePath $Name))
    if ($arguments.Count -ne 7) {
        throw "PostgreSQL 服务 $Name 含有未知、缺失或多余参数。"
    }
    $actualExecutable = ConvertTo-TicketboxFullPath $arguments[0]
    $expectedExecutablePath = ConvertTo-TicketboxFullPath $ExpectedExecutable
    $actualDataRoot = ConvertTo-TicketboxFullPath $arguments[5]
    $expectedDataRootPath = ConvertTo-TicketboxFullPath $ExpectedDataRoot
    if (
        -not [string]::Equals($actualExecutable, $expectedExecutablePath, [System.StringComparison]::OrdinalIgnoreCase) -or
        $arguments[1] -ne "runservice" -or
        $arguments[2] -ne "-N" -or
        -not [string]::Equals($arguments[3], $ExpectedServiceName, [System.StringComparison]::OrdinalIgnoreCase) -or
        $arguments[4] -ne "-D" -or
        -not [string]::Equals($actualDataRoot, $expectedDataRootPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        $arguments[6] -ne "-w"
    ) {
        throw "拒绝操作命令契约不匹配的 PostgreSQL 服务 $Name。"
    }
}

function Assert-TicketboxShawlServiceCommand {
    param(
        [string]$Name,
        [string]$ExpectedExecutable,
        [string]$ExpectedServiceName,
        [string]$ExpectedCwd,
        [string]$ExpectedPayload,
        [string]$ExpectedDependency,
        [string]$ExpectedLogDir,
        [string]$ExpectedPgDumpPath,
        [string]$ExpectedPgRestorePath,
        [string]$ExpectedBootstrapRecoveryGuardPath,
        [string]$ExpectedInstallerRecoveryGuardPath,
        [string]$ExpectedDataRootMarkerPath = "",
        [string]$ExpectedDataVolumeIdentity = "",
        [int]$ExpectedStopTimeoutMs,
        [int]$ExpectedRestartDelayMs,
        [switch]$AllowMissingInstallerRecoveryGuard,
        [switch]$AllowMissingRuntimeDataAuthority
    )

    Assert-TicketboxServiceDependencies -Name $Name -ExpectedDependencies @($ExpectedDependency)
    $arguments = @(Split-TicketboxWindowsCommandLine (Get-TicketboxServiceImagePath $Name))
    $separatorIndexes = @()
    for ($i = 0; $i -lt $arguments.Count; $i++) {
        if ($arguments[$i] -eq "--") {
            $separatorIndexes += $i
        }
    }
    if ($separatorIndexes.Count -ne 1) {
        throw "Shawl 服务 $Name 的命令分隔符 -- 必须且只能出现一次。"
    }
    $separatorIndex = $separatorIndexes[0]
    if ($arguments.Count -ne $separatorIndex + 2) {
        throw "Shawl 服务 $Name 的 payload 必须且只能包含后端可执行文件。"
    }
    $actualExecutable = ConvertTo-TicketboxFullPath $arguments[0]
    $actualPayload = ConvertTo-TicketboxFullPath $arguments[$separatorIndex + 1]
    if (
        -not [string]::Equals(
            $actualExecutable,
            (ConvertTo-TicketboxFullPath $ExpectedExecutable),
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        $arguments[1] -ne "run" -or
        -not [string]::Equals(
            $actualPayload,
            (ConvertTo-TicketboxFullPath $ExpectedPayload),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "拒绝操作可执行文件或 payload 不匹配的 Shawl 服务 $Name。"
    }

    $options = @{}
    $environmentValues = @()
    $restartSeen = $false
    $killProcessTreeSeen = $false
    for ($i = 2; $i -lt $separatorIndex; $i++) {
        $option = $arguments[$i].ToLowerInvariant()
        if ($option -in @("--restart", "--kill-process-tree")) {
            if ($option -eq "--restart") {
                if ($restartSeen) {
                    throw "Shawl 服务 $Name 重复声明 --restart。"
                }
                $restartSeen = $true
            }
            else {
                if ($killProcessTreeSeen) {
                    throw "Shawl 服务 $Name 重复声明 --kill-process-tree。"
                }
                $killProcessTreeSeen = $true
            }
            continue
        }
        if ($option -notin @("--name", "--stop-timeout", "--restart-delay", "--cwd", "--log-dir", "--env")) {
            throw "Shawl 服务 $Name 含有未授权参数：$($arguments[$i])"
        }
        if ($i + 1 -ge $separatorIndex) {
            throw "Shawl 服务 $Name 的参数 $option 缺少值。"
        }
        $value = $arguments[$i + 1]
        $i++
        if ($option -eq "--env") {
            $environmentValues += $value
            continue
        }
        if ($options.ContainsKey($option)) {
            throw "Shawl 服务 $Name 重复声明参数 $option。"
        }
        $options[$option] = $value
    }

    $expectedOptions = @{
        "--name" = $ExpectedServiceName
        "--stop-timeout" = [string]$ExpectedStopTimeoutMs
        "--restart-delay" = [string]$ExpectedRestartDelayMs
    }
    foreach ($option in $expectedOptions.Keys) {
        if (
            -not $options.ContainsKey($option) -or
            -not [string]::Equals($options[$option], $expectedOptions[$option], [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "Shawl 服务 $Name 的参数 $option 与安装配置不一致。"
        }
    }
    foreach ($pathOption in @{
        "--cwd" = $ExpectedCwd
        "--log-dir" = $ExpectedLogDir
    }.GetEnumerator()) {
        if (
            -not $options.ContainsKey($pathOption.Key) -or
            -not [string]::Equals(
                (ConvertTo-TicketboxFullPath $options[$pathOption.Key]),
                (ConvertTo-TicketboxFullPath $pathOption.Value),
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "Shawl 服务 $Name 的路径参数 $($pathOption.Key) 与安装配置不一致。"
        }
    }
    if ($options.Count -ne 5 -or -not $restartSeen -or -not $killProcessTreeSeen) {
        throw "Shawl 服务 $Name 缺少安装器要求的唯一参数集合。"
    }

    $expectedEnvironment = @{
        "TICKETBOX_DATA_DIR" = $ExpectedCwd
        "PG_DUMP_PATH" = $ExpectedPgDumpPath
        "PG_RESTORE_PATH" = $ExpectedPgRestorePath
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH" = $ExpectedBootstrapRecoveryGuardPath
        "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH" = $ExpectedInstallerRecoveryGuardPath
        "TICKETBOX_DATA_ROOT_MARKER_PATH" = $ExpectedDataRootMarkerPath
        "TICKETBOX_DATA_VOLUME_IDENTITY" = $ExpectedDataVolumeIdentity
    }
    $allowedMissingEnvironment = @()
    if ($AllowMissingInstallerRecoveryGuard) {
        $allowedMissingEnvironment += "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH"
    }
    if ($AllowMissingRuntimeDataAuthority) {
        $allowedMissingEnvironment += @(
            "TICKETBOX_DATA_ROOT_MARKER_PATH",
            "TICKETBOX_DATA_VOLUME_IDENTITY"
        )
    }
    if (
        $environmentValues.Count -gt $expectedEnvironment.Count -or
        $environmentValues.Count -lt ($expectedEnvironment.Count - $allowedMissingEnvironment.Count)
    ) {
        throw "Shawl 服务 $Name 的环境变量数量不匹配。"
    }
    $runtimeAuthorityValuesSeen = 0
    foreach ($entry in $environmentValues) {
        $parts = $entry.Split(@("="), 2, [System.StringSplitOptions]::None)
        if ($parts.Count -ne 2 -or -not $expectedEnvironment.ContainsKey($parts[0])) {
            throw "Shawl 服务 $Name 含有未授权环境变量。"
        }
        $expectedValue = $expectedEnvironment[$parts[0]]
        if ($parts[0] -eq "TICKETBOX_DATA_VOLUME_IDENTITY") {
            if (
                $parts[1] -notmatch '^\\\\\?\\Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}\\$' -or
                -not [string]::Equals(
                    $parts[1],
                    $expectedValue,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            ) {
                throw "Shawl 服务 $Name 的 DataRoot Volume GUID 不匹配。"
            }
            $runtimeAuthorityValuesSeen++
        }
        else {
            if (
                -not [string]::Equals(
                    (ConvertTo-TicketboxFullPath $parts[1]),
                    (ConvertTo-TicketboxFullPath $expectedValue),
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            ) {
                throw "Shawl 服务 $Name 的环境变量 $($parts[0]) 指向错误路径。"
            }
            if ($parts[0] -eq "TICKETBOX_DATA_ROOT_MARKER_PATH") {
                $runtimeAuthorityValuesSeen++
            }
        }
        $expectedEnvironment.Remove($parts[0])
    }
    if ($runtimeAuthorityValuesSeen -notin @(0, 2)) {
        throw "Shawl 服务 $Name 的 runtime DataRoot authority 必须成对出现。"
    }
    $unexpectedMissing = @($expectedEnvironment.Keys | Where-Object {
        $_ -notin $allowedMissingEnvironment
    })
    if ($unexpectedMissing.Count -ne 0) {
        throw "Shawl 服务 $Name 缺少安装器要求的环境变量。"
    }
}
