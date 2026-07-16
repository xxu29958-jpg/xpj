#Requires -Version 5.1

if ($null -eq ('XpjTestProtectedFile' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'test_pg_protected_file.cs')
}

if ($null -eq ('XpjTestProcessJob' -as [type])) {
    Add-Type -Path @(
        (Join-Path $PSScriptRoot 'test_pg_process_job.cs')
        (Join-Path $PSScriptRoot 'test_pg_process_command_line.cs')
        (Join-Path $PSScriptRoot 'test_pg_process_native.cs')
        (Join-Path $PSScriptRoot 'test_pg_process_security.cs')
    )
}

function Start-XpjTestPostgresProtectedProcess {
    param(
        [Parameter(Mandatory = $true)]$Job,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$StdoutPath,
        [Parameter(Mandatory = $true)][string]$StderrPath,
        [AllowNull()][string]$StandardInput = $null,
        [switch]$RestrictWindowsAdminAuthority
    )

    $stdoutStream = $null
    $stderrStream = $null
    $stdoutCreated = $false
    $stderrCreated = $false
    $started = $false
    try {
        $stdoutStream = [XpjTestProtectedFile]::CreateNewInheritableProcessOutput(
            [System.IO.Path]::GetFullPath($StdoutPath)
        )
        $stdoutCreated = $true
        $stderrStream = [XpjTestProtectedFile]::CreateNewInheritableProcessOutput(
            [System.IO.Path]::GetFullPath($StderrPath)
        )
        $stderrCreated = $true
        $processId = if ($RestrictWindowsAdminAuthority) {
            if ($null -eq $StandardInput) {
                $Job.StartRestrictedProcess(
                    $FilePath,
                    $ArgumentList,
                    $stdoutStream,
                    $stderrStream
                )
            }
            else {
                $Job.StartRestrictedProcess(
                    $FilePath,
                    $ArgumentList,
                    $stdoutStream,
                    $stderrStream,
                    $StandardInput
                )
            }
        }
        else {
            if ($null -eq $StandardInput) {
                $Job.StartProcess(
                    $FilePath,
                    $ArgumentList,
                    $stdoutStream,
                    $stderrStream
                )
            }
            else {
                $Job.StartProcess(
                    $FilePath,
                    $ArgumentList,
                    $stdoutStream,
                    $stderrStream,
                    $StandardInput
                )
            }
        }
        $started = $true
        return $processId
    }
    finally {
        if ($null -ne $stderrStream) {
            $stderrStream.Dispose()
        }
        if ($null -ne $stdoutStream) {
            $stdoutStream.Dispose()
        }
        if (-not $started) {
            if ($stderrCreated) {
                Remove-Item -LiteralPath $StderrPath -Force -ErrorAction SilentlyContinue
            }
            if ($stdoutCreated) {
                Remove-Item -LiteralPath $StdoutPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Remove-XpjTestPostgresProcessOutput {
    param(
        [Parameter(Mandatory = $true)][string[]]$Path,
        [ValidateRange(1, 30000)][int]$TimeoutMilliseconds = 5000
    )

    foreach ($candidate in $Path) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $fullPath = [System.IO.Path]::GetFullPath($candidate)
        $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
        while ($true) {
            $probe = $null
            try {
                $probe = [System.IO.File]::Open(
                    $fullPath,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::ReadWrite,
                    [System.IO.FileShare]::None
                )
                break
            }
            catch [System.IO.FileNotFoundException] {
                break
            }
            catch [System.IO.IOException] {
                if ([DateTime]::UtcNow -ge $deadline) {
                    throw (
                        'PostgreSQL process output handle did not close within ' +
                        "$TimeoutMilliseconds ms: $fullPath"
                    )
                }
                Start-Sleep -Milliseconds 10
            }
            finally {
                if ($null -ne $probe) {
                    $probe.Dispose()
                }
            }
        }
        if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
            Assert-XpjTestPostgresProtectedAuthorityFile `
                -Path $fullPath `
                -Label 'PostgreSQL process output'
            Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        }
    }
}

function Invoke-XpjTestPostgresBoundedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [AllowNull()][string]$StandardInput = $null,
        [switch]$RestrictWindowsAdminAuthority,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 60
    )

    $temporaryRoot = [System.IO.Path]::GetTempPath()
    $processId = [Guid]::NewGuid().ToString('N')
    $stdoutPath = Join-Path $temporaryRoot ".xpj-pg-process-$processId.stdout"
    $stderrPath = Join-Path $temporaryRoot ".xpj-pg-process-$processId.stderr"
    $job = [XpjTestProcessJob]::new()
    try {
        [void](Start-XpjTestPostgresProtectedProcess `
            -Job $job `
            -FilePath $FilePath `
            -ArgumentList $ArgumentList `
            -StdoutPath $stdoutPath `
            -StderrPath $stderrPath `
            -StandardInput $StandardInput `
            -RestrictWindowsAdminAuthority:$RestrictWindowsAdminAuthority)
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
        Remove-XpjTestPostgresProcessOutput `
            -Path @($stdoutPath, $stderrPath)
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
        [switch]$RestrictWindowsAdminAuthority,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 60
    )

    $job = [XpjTestProcessJob]::new()
    $transferred = $false
    try {
        $targetProcessId = Start-XpjTestPostgresProtectedProcess `
            -Job $job `
            -FilePath $FilePath `
            -ArgumentList $ArgumentList `
            -StdoutPath $TargetStdoutPath `
            -StderrPath $TargetStderrPath `
            -RestrictWindowsAdminAuthority:$RestrictWindowsAdminAuthority
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
