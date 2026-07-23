#Requires -Version 5.1

. (Join-Path $PSScriptRoot 'test_pg_ownership_contract.ps1')

if (-not ('XpjNativeCommandLine' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class XpjNativeCommandLine
{
    [DllImport("shell32.dll", SetLastError = true)]
    private static extern IntPtr CommandLineToArgvW(
        [MarshalAs(UnmanagedType.LPWStr)] string commandLine,
        out int argumentCount);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    public static string[] Parse(string commandLine)
    {
        int count;
        IntPtr argv = CommandLineToArgvW(commandLine, out count);
        if (argv == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        try
        {
            string[] result = new string[count];
            for (int index = 0; index < count; index++)
            {
                IntPtr value = Marshal.ReadIntPtr(argv, index * IntPtr.Size);
                result[index] = Marshal.PtrToStringUni(value);
            }
            return result;
        }
        finally
        {
            LocalFree(argv);
        }
    }
}
'@
}

function Resolve-XpjFullyQualifiedWindowsPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $candidate = $Path.Trim()
    if (
        [string]::IsNullOrWhiteSpace($candidate) -or
        $candidate -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)'
    ) {
        throw "$Label must be a fully qualified Windows path: $Path"
    }
    try {
        return [IO.Path]::GetFullPath($candidate).TrimEnd('\', '/')
    }
    catch {
        throw "$Label is not a valid fully qualified Windows path: $Path"
    }
}

function Get-XpjPostgresDataArgument {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandLine,
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    $arguments = [XpjNativeCommandLine]::Parse($CommandLine)
    $dataArguments = New-Object 'System.Collections.Generic.List[string]'
    for ($index = 0; $index -lt $arguments.Count; $index++) {
        if ($arguments[$index] -ceq '-D') {
            if ($index + 1 -ge $arguments.Count) {
                throw "PostgreSQL PID $ProcessId has an incomplete -D argument"
            }
            $dataArguments.Add(
                (Resolve-XpjFullyQualifiedWindowsPath `
                    -Path $arguments[$index + 1] `
                    -Label "PostgreSQL PID $ProcessId -D argument")
            )
        }
    }
    if ($dataArguments.Count -ne 1) {
        throw "PostgreSQL PID $ProcessId must have exactly one -D argument"
    }
    return $dataArguments[0]
}

function Read-XpjPostmasterIdentityFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(0, 65535)][int]$Port
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $pidFile = Join-Path $resolvedDataDir 'postmaster.pid'
    if ((Get-TicketboxPathEntryKindNoFollow -Path $pidFile) -cne 'File') {
        throw "PostgreSQL identity file is missing or not a plain file: $pidFile"
    }
    $identityLines = @(Get-Content -Encoding UTF8 -LiteralPath $pidFile -TotalCount 4)
    $recordedPid = 0
    $recordedStartTime = [long]0
    $recordedPort = 0
    if (
        $identityLines.Count -lt 4 -or
        -not [int]::TryParse($identityLines[0], [ref]$recordedPid) -or
        $recordedPid -le 0 -or
        -not [long]::TryParse($identityLines[2], [ref]$recordedStartTime) -or
        $recordedStartTime -le 0 -or
        -not [int]::TryParse($identityLines[3], [ref]$recordedPort) -or
        $recordedPort -lt 1 -or
        $recordedPort -gt 65535 -or
        ($Port -ne 0 -and $recordedPort -ne $Port)
    ) {
        throw "PostgreSQL identity file has an invalid process generation or port: $pidFile"
    }
    $recordedDataDir = Resolve-XpjFullyQualifiedWindowsPath `
        -Path $identityLines[1] `
        -Label 'PostgreSQL identity data directory'
    if (-not [string]::Equals($recordedDataDir, $resolvedDataDir, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PostgreSQL identity file belongs to another data directory: $recordedDataDir"
    }
    return [pscustomobject]@{
        Path = $pidFile
        ProcessId = $recordedPid
        StartTimeEpochSeconds = $recordedStartTime
        Port = $recordedPort
        DataDir = $resolvedDataDir
    }
}

function Assert-XpjPostmasterProcessGeneration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Handle
    )

    $processStart = [DateTimeOffset]::new($Handle.StartTime.ToUniversalTime()).ToUnixTimeSeconds()
    $startupDelay = [long]$Identity.StartTimeEpochSeconds - $processStart
    if ($startupDelay -lt 0 -or $startupDelay -gt 10) {
        throw "PostgreSQL PID generation does not match postmaster.pid: $($Identity.ProcessId)"
    }
}

function Remove-XpjStalePostmasterIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDir,
        [Parameter(Mandatory = $true)]
        [string]$PostgresExe
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $null = Assert-XpjTestPostgresOwnership -DataDir $resolvedDataDir
    $resolvedPostgresExe = [IO.Path]::GetFullPath($PostgresExe)
    $pidFile = Join-Path $resolvedDataDir 'postmaster.pid'
    if ((Get-TicketboxPathEntryKindNoFollow -Path $pidFile) -eq 'Missing') {
        return
    }
    $identity = Read-XpjPostmasterIdentityFile -DataDir $resolvedDataDir -Port 0
    $recordedPid = [int]$identity.ProcessId

    $recordedPostgresSnapshot = $null
    $postgresProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'postgres.exe'" -ErrorAction Stop)
    foreach ($candidate in $postgresProcesses) {
        if (
            [string]::IsNullOrWhiteSpace([string]$candidate.ExecutablePath) -or
            [string]::IsNullOrWhiteSpace([string]$candidate.CommandLine)
        ) {
            if ([int]$candidate.ProcessId -eq $recordedPid) {
                throw "Cannot disprove that PostgreSQL PID $recordedPid still owns $resolvedDataDir"
            }
            continue
        }
        try {
            $candidateDataDir = Get-XpjPostgresDataArgument -CommandLine ([string]$candidate.CommandLine) -ProcessId ([int]$candidate.ProcessId)
        }
        catch {
            if ([int]$candidate.ProcessId -eq $recordedPid) {
                throw
            }
            continue
        }
        if ([string]::Equals($candidateDataDir, $resolvedDataDir, [StringComparison]::OrdinalIgnoreCase)) {
            $candidateExecutable = [IO.Path]::GetFullPath([string]$candidate.ExecutablePath)
            if (-not [string]::Equals($candidateExecutable, $resolvedPostgresExe, [StringComparison]::OrdinalIgnoreCase)) {
                throw "PostgreSQL data directory is owned by another installed binary: $candidateExecutable"
            }
            throw "PostgreSQL data directory is still owned by live PID $($candidate.ProcessId): $resolvedDataDir"
        }
        if ([int]$candidate.ProcessId -eq $recordedPid) {
            $recordedPostgresSnapshot = $candidate
        }
    }

    $recordedProcess = Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
    if ($null -ne $recordedProcess) {
        try {
            $null = $recordedProcess.Handle
            if ($null -ne $recordedPostgresSnapshot) {
                $fresh = Get-XpjVerifiedProcessSnapshot `
                    -Snapshot $recordedPostgresSnapshot `
                    -Handle $recordedProcess
                if ([string]::IsNullOrWhiteSpace([string]$fresh.CommandLine)) {
                    throw "Cannot verify the reused PostgreSQL PID command line: $recordedPid"
                }
                $freshDataDir = Get-XpjPostgresDataArgument `
                    -CommandLine ([string]$fresh.CommandLine) `
                    -ProcessId $recordedPid
                if ([string]::Equals($freshDataDir, $resolvedDataDir, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "PostgreSQL data directory became owned during stale identity verification: $resolvedDataDir"
                }
            }
            else {
                $recordedExecutable = [IO.Path]::GetFullPath($recordedProcess.MainModule.FileName)
                if ([string]::Equals($recordedExecutable, $resolvedPostgresExe, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Cannot safely classify live PostgreSQL PID $recordedPid as stale"
                }
            }
        }
        finally {
            $recordedProcess.Close()
        }
    }

    Remove-Item -Force -LiteralPath $pidFile
    Write-Host "Removed stale PostgreSQL identity after proving no live process owns $resolvedDataDir"
}

function Get-XpjProcessTree {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [int]$RootProcessId
    )

    $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $root = $all | Where-Object { [int]$_.ProcessId -eq $RootProcessId } | Select-Object -First 1
    if ($null -eq $root) {
        return @()
    }
    $selected = New-Object 'System.Collections.Generic.List[object]'
    $pending = New-Object 'System.Collections.Generic.Queue[object]'
    $visited = New-Object 'System.Collections.Generic.HashSet[int]'
    $pending.Enqueue($root)
    while ($pending.Count -gt 0) {
        $process = $pending.Dequeue()
        $processId = [int]$process.ProcessId
        if (-not $visited.Add($processId)) {
            continue
        }
        $selected.Add($process)
        $processStarted = ([DateTime]$process.CreationDate).ToUniversalTime()
        foreach ($child in $all | Where-Object { [int]$_.ParentProcessId -eq $processId }) {
            $childStarted = ([DateTime]$child.CreationDate).ToUniversalTime()
            if ($childStarted -ge $processStarted -and -not $visited.Contains([int]$child.ProcessId)) {
                $pending.Enqueue($child)
            }
        }
    }
    return $selected.ToArray()
}

function Get-XpjVerifiedProcessSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Snapshot,
        [Parameter(Mandatory = $true)]
        [Diagnostics.Process]$Handle
    )

    $processId = [int]$Snapshot.ProcessId
    $fresh = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
    if ($null -eq $fresh -or [int]$fresh.ProcessId -ne $processId) {
        throw "PostgreSQL PID exited during identity verification: $processId"
    }
    $snapshotTicks = ([DateTime]$Snapshot.CreationDate).ToUniversalTime().Ticks
    $freshTicks = ([DateTime]$fresh.CreationDate).ToUniversalTime().Ticks
    $handleTicks = $Handle.StartTime.ToUniversalTime().Ticks
    $handleMicrosecondTicks = $handleTicks - ($handleTicks % 10)
    if ($snapshotTicks -ne $freshTicks -or $freshTicks -ne $handleMicrosecondTicks) {
        throw "PostgreSQL PID generation changed during identity verification: $processId"
    }
    if ([int]$Snapshot.ParentProcessId -ne [int]$fresh.ParentProcessId) {
        throw "PostgreSQL PID parent changed during identity verification: $processId"
    }
    return $fresh
}

function Assert-XpjOwnedPostgresProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDir,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$PostgresExe,
        [switch]$AllowUnmarkedLegacy,
        [switch]$AllowNoListener
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    if (-not $AllowUnmarkedLegacy) {
        $null = Assert-XpjTestPostgresOwnership -DataDir $resolvedDataDir
    }
    $resolvedPostgresExe = [IO.Path]::GetFullPath($PostgresExe)
    $identity = Read-XpjPostmasterIdentityFile -DataDir $resolvedDataDir -Port $Port
    $postmasterId = [int]$identity.ProcessId

    $processTree = @(Get-XpjProcessTree -RootProcessId $postmasterId)
    $root = $processTree | Where-Object { [int]$_.ProcessId -eq $postmasterId } | Select-Object -First 1
    if ($null -eq $root) {
        throw "PostgreSQL postmaster PID is not alive: $postmasterId"
    }
    if ([string]::IsNullOrWhiteSpace([string]$root.ExecutablePath)) {
        throw "Cannot verify PostgreSQL executable for PID $postmasterId"
    }
    $actualExecutable = [IO.Path]::GetFullPath([string]$root.ExecutablePath)
    if (-not [string]::Equals($actualExecutable, $resolvedPostgresExe, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PostgreSQL PID $postmasterId uses an unexpected executable: $actualExecutable"
    }
    $handles = New-Object 'System.Collections.Generic.List[System.Diagnostics.Process]'
    $hostAddress = ''
    try {
        foreach ($item in $processTree) {
            if ([string]::IsNullOrWhiteSpace([string]$item.ExecutablePath)) {
                throw "Cannot verify PostgreSQL child executable for PID $($item.ProcessId)"
            }
            $snapshotExecutable = [IO.Path]::GetFullPath([string]$item.ExecutablePath)
            if (-not [string]::Equals($snapshotExecutable, $resolvedPostgresExe, [StringComparison]::OrdinalIgnoreCase)) {
                throw "PostgreSQL process tree contains a foreign executable: $snapshotExecutable"
            }
            $handle = Get-Process -Id ([int]$item.ProcessId) -ErrorAction Stop
            $null = $handle.Handle
            $handles.Add($handle)
            if ($handle.HasExited) {
                throw "PostgreSQL PID exited during identity verification: $($item.ProcessId)"
            }
            $fresh = Get-XpjVerifiedProcessSnapshot -Snapshot $item -Handle $handle
            if ([string]::IsNullOrWhiteSpace([string]$fresh.ExecutablePath)) {
                throw "Cannot revalidate PostgreSQL executable for PID $($item.ProcessId)"
            }
            $freshExecutable = [IO.Path]::GetFullPath([string]$fresh.ExecutablePath)
            $handleExecutable = [IO.Path]::GetFullPath($handle.MainModule.FileName)
            if (
                -not [string]::Equals($freshExecutable, $snapshotExecutable, [StringComparison]::OrdinalIgnoreCase) -or
                -not [string]::Equals($handleExecutable, $freshExecutable, [StringComparison]::OrdinalIgnoreCase)
            ) {
                throw "PostgreSQL PID was reused during identity verification: $($item.ProcessId)"
            }
            if ([int]$item.ProcessId -eq $postmasterId) {
                Assert-XpjPostmasterProcessGeneration -Identity $identity -Handle $handle
                if ([string]::IsNullOrWhiteSpace([string]$fresh.CommandLine)) {
                    throw "PostgreSQL PID $postmasterId has no readable command line"
                }
                $processDataDir = Get-XpjPostgresDataArgument -CommandLine ([string]$fresh.CommandLine) -ProcessId $postmasterId
                if (-not [string]::Equals($processDataDir, $resolvedDataDir, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "PostgreSQL PID $postmasterId command line does not own $resolvedDataDir"
                }
            }
        }
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 0) {
            if (-not $AllowNoListener) {
                throw "PostgreSQL postmaster PID $postmasterId has no listener on port $Port"
            }
        }
        elseif (@($listeners | Where-Object { [int]$_.OwningProcess -ne $postmasterId }).Count -gt 0) {
            throw "PostgreSQL listener changed during identity verification: $Port"
        }
        else {
            $listenerAddresses = @(
                $listeners |
                    ForEach-Object { [Net.IPAddress]::Parse([string]$_.LocalAddress) } |
                    Where-Object { [Net.IPAddress]::IsLoopback($_) }
            )
            if ($listenerAddresses.Count -ne $listeners.Count) {
                throw "PostgreSQL port $Port is not bound exclusively to loopback"
            }
            $hostAddress = [string](
                $listenerAddresses |
                    Sort-Object { if ($_.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) { 0 } else { 1 } } |
                    Select-Object -First 1
            )
        }
    }
    catch {
        foreach ($handle in $handles) { $handle.Close() }
        throw
    }
    return [pscustomobject]@{
        DataDir = $resolvedDataDir
        HostAddress = $hostAddress
        PostmasterId = $postmasterId
        Processes = @($handles)
    }
}

function Stop-XpjOwnedPostgresProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDir,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$PostgresExe
    )

    $identity = Assert-XpjOwnedPostgresProcess `
        -DataDir $DataDir `
        -Port $Port `
        -PostgresExe $PostgresExe `
        -AllowNoListener
    $pgCtlExe = Join-Path (Split-Path -Parent $PostgresExe) 'pg_ctl.exe'
    try {
        & $pgCtlExe stop -D $identity.DataDir -m fast -w -t 15
        $pgCtlExit = $LASTEXITCODE
        $allExited = $true
        foreach ($process in $identity.Processes) {
            if (-not $process.HasExited -and -not $process.WaitForExit(2000)) {
                $allExited = $false
            }
        }
        $listenerGone = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -eq 0
        if ($pgCtlExit -eq 0 -and $listenerGone -and $allExited) {
            Write-Host "Stopped ephemeral PostgreSQL with pg_ctl (postmaster PID $($identity.PostmasterId))"
            return
        }

        # pg_ctl can time out while shutdown continues. Keep the already-pinned
        # process generation and finish only that exact verified process tree.
        foreach ($process in $identity.Processes) {
            if (-not $process.HasExited) {
                Stop-Process -InputObject $process -Force -ErrorAction Stop
            }
        }
        foreach ($process in $identity.Processes) {
            if (-not $process.HasExited -and -not $process.WaitForExit(10000)) {
                throw "Verified PostgreSQL PID did not exit: $($process.Id)"
            }
        }
        if (@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -gt 0) {
            throw "PostgreSQL port $Port is still listening after stopping the owned process tree"
        }
        Write-Host "Completed verified PostgreSQL shutdown after pg_ctl did not finish cleanly (postmaster PID $($identity.PostmasterId))"
    }
    finally {
        foreach ($process in $identity.Processes) { $process.Close() }
    }
}
