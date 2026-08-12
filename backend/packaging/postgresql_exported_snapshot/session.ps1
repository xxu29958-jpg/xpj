#Requires -Version 5.1

function Get-TicketboxPostgresqlExportedSnapshotShutdownRemainingMilliseconds {
    param(
        [Parameter(Mandatory = $true)][Diagnostics.Stopwatch]$Stopwatch,
        [Parameter(Mandatory = $true)][int]$WaitTimeoutMilliseconds,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $remaining = [int64]$WaitTimeoutMilliseconds -
        [int64][Math]::Ceiling($Stopwatch.Elapsed.TotalMilliseconds)
    if ($remaining -lt 1) {
        throw "PostgreSQL exported-snapshot $Label 超过 shutdown deadline。"
    }
    return [int][Math]::Min([int64][int]::MaxValue, $remaining)
}

function Start-TicketboxPostgresqlExportedSnapshotSession {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$ProtectedDatabaseUrl,
        [Parameter(Mandatory = $true)][string[]]$SqlCommands,
        [string[]]$ExecutablePrefixArguments = @()
    )

    Assert-TicketboxPostgresqlExportedSnapshotDependencies
    if (
        [string]::IsNullOrWhiteSpace($PsqlPath) -or
        [string]::IsNullOrWhiteSpace($ProtectedDatabaseUrl) -or
        $SqlCommands.Count -lt 1 -or
        @($SqlCommands | Where-Object {
            [string]::IsNullOrWhiteSpace($_)
        }).Count -gt 0 -or
        @($ExecutablePrefixArguments | Where-Object {
            [string]::IsNullOrWhiteSpace($_)
        }).Count -gt 0
    ) {
        throw "PostgreSQL exported-snapshot 启动参数无效。"
    }
    Assert-NoTicketboxAncestorReparsePoints $PsqlPath
    if ((Get-TicketboxPathEntryKindNoFollow $PsqlPath) -cne "File") {
        throw "PostgreSQL exported-snapshot psql 不是可信普通文件：$PsqlPath"
    }

    $arguments = [Collections.Generic.List[string]]::new()
    foreach ($argument in $ExecutablePrefixArguments) {
        $arguments.Add([string]$argument)
    }
    foreach ($argument in @(
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--quiet",
        "--set",
        "ON_ERROR_STOP=1",
        "--dbname",
        $ProtectedDatabaseUrl
    )) {
        $arguments.Add([string]$argument)
    }
    foreach ($sqlCommand in $SqlCommands) {
        $arguments.Add("--command")
        $arguments.Add([string]$sqlCommand)
    }
    $arguments.Add("--file")
    $arguments.Add("-")
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $PsqlPath
    $info.Arguments = [string]::Join(
        " ",
        @($arguments | ForEach-Object {
            ConvertTo-TicketboxNativeCommandLineArgument ([string]$_)
        })
    )
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.RedirectStandardInput = $true
    $info.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $info.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    $started = $false
    $outputReader = $null
    $errorReader = $null
    $errorDrainTask = $null
    try {
        if (-not $process.Start()) {
            throw "PostgreSQL exported-snapshot session 无法启动。"
        }
        $started = $true
        $outputReader = $process.StandardOutput
        $errorReader = $process.StandardError
        $errorDrainTask = $errorReader.BaseStream.CopyToAsync(
            [IO.Stream]::Null
        )
        $streamResources = [pscustomobject]@{
            OutputReader = $outputReader
            ErrorReader = $errorReader
            ErrorDrainTask = $errorDrainTask
        }
        $process | Add-Member `
            -NotePropertyName TicketboxStreamResources `
            -NotePropertyValue $streamResources
        return $process
    }
    catch {
        if ($started) {
            try {
                if (-not $process.HasExited) {
                    $process.Kill()
                    [void]$process.WaitForExit(10000)
                }
            }
            catch { }
        }
        if ($null -ne $outputReader) { $outputReader.Dispose() }
        if ($null -ne $errorReader) { $errorReader.Dispose() }
        if ($null -ne $errorDrainTask -and $errorDrainTask.IsCompleted) {
            $errorDrainTask.Dispose()
        }
        $process.Dispose()
        throw
    }
}

function Read-TicketboxPostgresqlExportedSnapshotLine {
    param(
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][DateTimeOffset]$AbsoluteDeadlineUtc,
        [Parameter(Mandatory = $true)][Diagnostics.Stopwatch]$BudgetStopwatch,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 2147483647)]
        [int]$MaximumElapsedMilliseconds
    )

    if (-not $BudgetStopwatch.IsRunning) {
        throw "PostgreSQL exported-snapshot read budget 未运行。"
    }
    $wallRemaining = [int64][Math]::Floor(
        ($AbsoluteDeadlineUtc - [DateTimeOffset]::UtcNow).TotalMilliseconds
    )
    $monotonicRemaining = [int64]$MaximumElapsedMilliseconds -
        [int64][Math]::Ceiling($BudgetStopwatch.Elapsed.TotalMilliseconds)
    $remainingRaw = [int64][Math]::Min($wallRemaining, $monotonicRemaining)
    if ($remainingRaw -lt 1) {
        throw "PostgreSQL exported-snapshot evidence 超过绝对 deadline。"
    }
    $remaining = [int][Math]::Min([int64][int]::MaxValue, $remainingRaw)
    $outputProperty = $Process.PSObject.Properties[
        "TicketboxStreamResources"
    ]
    if (
        $null -eq $outputProperty -or
        $null -eq $outputProperty.Value.OutputReader
    ) {
        throw "PostgreSQL exported-snapshot stdout reader 不可用。"
    }
    $readTask = $outputProperty.Value.OutputReader.ReadLineAsync()
    if (-not $readTask.Wait($remaining)) {
        throw "PostgreSQL exported-snapshot evidence 超时。"
    }
    $line = $readTask.Result
    if ($null -eq $line) {
        throw "PostgreSQL exported-snapshot session 提前退出。"
    }
    return $line
}

function Assert-TicketboxPostgresqlExportedSnapshotSessionAlive {
    param([Parameter(Mandatory = $true)][Diagnostics.Process]$Process)

    if ($Process.HasExited) {
        throw "PostgreSQL exported-snapshot holder 已退出。"
    }
}

function Stop-TicketboxPostgresqlExportedSnapshotSession {
    param(
        [AllowNull()][Diagnostics.Process]$Process,
        [ValidateRange(1000, 300000)][int]$WaitTimeoutMilliseconds = 10000
    )

    if ($null -eq $Process) { return }
    $resourceProperty = $Process.PSObject.Properties[
        "TicketboxStreamResources"
    ]
    $resources = if ($null -eq $resourceProperty) {
        $null
    }
    else { $resourceProperty.Value }
    $outputReader = if ($null -eq $resources) { $null } else {
        $resources.OutputReader
    }
    $errorReader = if ($null -eq $resources) { $null } else {
        $resources.ErrorReader
    }
    $errorDrainTask = if ($null -eq $resources) { $null } else {
        $resources.ErrorDrainTask
    }
    $shutdownClock = [Diagnostics.Stopwatch]::StartNew()
    try {
        if (-not $Process.HasExited) {
            try { $Process.Kill() }
            catch [InvalidOperationException] {
                if (-not $Process.HasExited) { throw }
            }
            $processWait =
                Get-TicketboxPostgresqlExportedSnapshotShutdownRemainingMilliseconds `
                    -Stopwatch $shutdownClock `
                    -WaitTimeoutMilliseconds $WaitTimeoutMilliseconds `
                    -Label "process wait"
            if (-not $Process.WaitForExit($processWait)) {
                throw "PostgreSQL exported-snapshot session 无法在有界时间内退出。"
            }
        }
        if ($null -ne $errorDrainTask -and -not $errorDrainTask.IsCompleted) {
            $drainWait =
                Get-TicketboxPostgresqlExportedSnapshotShutdownRemainingMilliseconds `
                    -Stopwatch $shutdownClock `
                    -WaitTimeoutMilliseconds $WaitTimeoutMilliseconds `
                    -Label "stderr drain"
            if (-not $errorDrainTask.Wait($drainWait)) {
                throw "PostgreSQL exported-snapshot stderr 无法在有界时间内清空。"
            }
        }
        if ($null -ne $errorDrainTask -and $errorDrainTask.IsFaulted) {
            throw "PostgreSQL exported-snapshot stderr drain 失败。"
        }
    }
    finally {
        $shutdownClock.Stop()
        if ($null -ne $outputReader) { $outputReader.Dispose() }
        if ($null -ne $errorReader) { $errorReader.Dispose() }
        $Process.Dispose()
        if ($null -ne $errorDrainTask -and $errorDrainTask.IsCompleted) { $errorDrainTask.Dispose() }
    }
}
