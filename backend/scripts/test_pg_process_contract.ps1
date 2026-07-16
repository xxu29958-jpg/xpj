#Requires -Version 5.1

if ($null -eq ('XpjTestProcessJob' -as [type])) {
    Add-Type -Path @(
        (Join-Path $PSScriptRoot 'test_pg_process_job.cs')
        (Join-Path $PSScriptRoot 'test_pg_process_native.cs')
    )
}

function Invoke-XpjTestPostgresBoundedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [AllowNull()][string]$StandardInput = $null,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 60
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    $job = [XpjTestProcessJob]::new()
    try {
        if ($null -eq $StandardInput) {
            [void]$job.StartProcess(
                $FilePath,
                $ArgumentList,
                $stdoutPath,
                $stderrPath
            )
        }
        else {
            [void]$job.StartProcess(
                $FilePath,
                $ArgumentList,
                $stdoutPath,
                $stderrPath,
                $StandardInput
            )
        }
        $timedOut = -not $job.WaitForStartedProcess($TimeoutSeconds * 1000)
        if ($timedOut) {
            $job.Terminate(1)
            if (-not $job.WaitForStartedProcess(5000)) {
                throw 'Timed out terminating the PostgreSQL lifecycle process job.'
            }
        }
        $exitCode = if ($timedOut) { -1 } else { $job.GetStartedProcessExitCode() }
        $stdout = Get-Content -LiteralPath $stdoutPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        $stderr = Get-Content -LiteralPath $stderrPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        return [pscustomobject]@{
            ExitCode = $exitCode
            TimedOut = $timedOut
            Output = (@($stdout, $stderr) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join [Environment]::NewLine
        }
    }
    finally {
        $job.Dispose()
        Remove-Item `
            -LiteralPath $stdoutPath, $stderrPath `
            -Force `
            -ErrorAction SilentlyContinue
    }
}

function Get-XpjTestPostgresUncommittedOutput {
    param([Parameter(Mandatory = $true)]$Transaction)

    return (@(
        Get-Content -LiteralPath $Transaction.TargetStdoutPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        Get-Content -LiteralPath $Transaction.TargetStderrPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join [Environment]::NewLine
}

function Start-XpjTestPostgresUncommittedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$TargetPidSourcePath,
        [Parameter(Mandatory = $true)][string]$TargetStdoutPath,
        [Parameter(Mandatory = $true)][string]$TargetStderrPath,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 60
    )

    $job = [XpjTestProcessJob]::new()
    $transferred = $false
    try {
        $targetProcessId = $job.StartProcess(
            $FilePath,
            $ArgumentList,
            $TargetStdoutPath,
            $TargetStderrPath
        )
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        $recordedPid = 0
        while ($true) {
            if (-not $job.IsStartedProcessRunning()) {
                $transaction = [pscustomobject]@{
                    TargetStdoutPath = $TargetStdoutPath
                    TargetStderrPath = $TargetStderrPath
                }
                $output = Get-XpjTestPostgresUncommittedOutput $transaction
                throw "Uncommitted PostgreSQL exited before publishing its process id: $output"
            }
            if (Test-Path -LiteralPath $TargetPidSourcePath -PathType Leaf) {
                $pidLine = Get-Content `
                    -LiteralPath $TargetPidSourcePath `
                    -Encoding UTF8 `
                    -TotalCount 1 `
                    -ErrorAction SilentlyContinue
                if (
                    $null -ne $pidLine -and
                    [int]::TryParse(([string]$pidLine).Trim(), [ref]$recordedPid) -and
                    $recordedPid -gt 0
                ) {
                    break
                }
            }
            if ([DateTime]::UtcNow -ge $deadline) {
                throw 'Timed out waiting for the uncommitted PostgreSQL process to publish a valid process id.'
            }
            Start-Sleep -Milliseconds 50
        }
        if ($recordedPid -ne $targetProcessId) {
            throw 'PostgreSQL postmaster.pid does not identify the atomically started process.'
        }
        if (-not $job.ContainsStartedProcess()) {
            throw 'Uncommitted PostgreSQL process escaped its kill-on-close job.'
        }
        $transaction = [pscustomobject]@{
            Job = $job
            TargetProcessId = $targetProcessId
            TargetStdoutPath = $TargetStdoutPath
            TargetStderrPath = $TargetStderrPath
            Committed = $false
        }
        $transferred = $true
        return $transaction
    }
    finally {
        if (-not $transferred) {
            try { $job.Terminate(1) } catch {}
            $job.Dispose()
        }
    }
}

function Complete-XpjTestPostgresUncommittedProcess {
    param([Parameter(Mandatory = $true)]$Transaction)

    if ($Transaction.Committed) {
        throw 'Uncommitted PostgreSQL process was already committed.'
    }
    if (-not $Transaction.Job.ContainsStartedProcess()) {
        throw 'PostgreSQL process left its lifecycle job before commit.'
    }
    if (
        -not $Transaction.Job.IsStartedProcessRunning() -or
        -not $Transaction.Job.ContainsStartedProcess()
    ) {
        throw 'PostgreSQL process exited or escaped before lifecycle commit.'
    }
    $Transaction.Job.PreserveProcessesOnClose()
    $Transaction.Committed = $true
    $Transaction.Job.Dispose()
    $Transaction.Job = $null
}

function Stop-XpjTestPostgresUncommittedProcess {
    param([Parameter(Mandatory = $true)]$Transaction)

    if (-not $Transaction.Committed -and $null -ne $Transaction.Job) {
        try { $Transaction.Job.Terminate(1) } catch {}
        $Transaction.Job.Dispose()
        $Transaction.Job = $null
    }
}

function Get-XpjTestPostgresProcessTimeoutSeconds {
    if (
        $null -ne $script:XpjTestPostgresProcessTimeoutSeconds -and
        [int]$script:XpjTestPostgresProcessTimeoutSeconds -ge 1
    ) {
        return [int]$script:XpjTestPostgresProcessTimeoutSeconds
    }
    return 60
}

function Remove-XpjTestPostgresDirectoryBounded {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$ExpectedDirectoryIdentity,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = (Get-XpjTestPostgresProcessTimeoutSeconds)
    )

    $worker = Join-Path $PSScriptRoot 'test_pg_remove_tree.ps1'
    $hostExecutable = (Get-Process -Id $PID -ErrorAction Stop).Path
    $result = Invoke-XpjTestPostgresBoundedProcess `
        -FilePath $hostExecutable `
        -ArgumentList @(
            '-NoLogo',
            '-NoProfile',
            '-NonInteractive',
            '-ExecutionPolicy', 'Bypass',
            '-File', $worker,
            '-TargetDirectory', $Directory,
            '-ExpectedDirectoryIdentity', $ExpectedDirectoryIdentity
        ) `
        -TimeoutSeconds $TimeoutSeconds
    if ($result.TimedOut) {
        throw "PostgreSQL lifecycle deletion exceeded its $TimeoutSeconds second process budget: $Directory"
    }
    if ($result.ExitCode -ne 0) {
        throw "PostgreSQL lifecycle deletion failed (exit=$($result.ExitCode)): $($result.Output)"
    }
}
