#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AdbPath,
    [Parameter(Mandatory = $true)][string]$AvdName,
    [AllowEmptyString()][string]$Serial = '',
    [ValidateRange(0, 2147483647)][int]$ProcessId = 0,
    [long]$ProcessStartFileTimeUtc = 0,
    [ValidateRange(1, 60)][int]$TimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'

function Invoke-XpjAdb {
    param([Parameter(Mandatory = $true)][string[]]$ArgumentList)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $AdbPath @ArgumentList 2>$null)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = @($output | ForEach-Object { [string]$_ })
    }
}

function Test-XpjSerialPresent {
    param([Parameter(Mandatory = $true)][string]$ExpectedSerial)

    $devices = Invoke-XpjAdb @('devices')
    if ($devices.ExitCode -ne 0) {
        throw "adb devices failed during emulator cleanup (exit=$($devices.ExitCode))."
    }
    return @(
        $devices.Output |
            Where-Object { $_ -match '^emulator-\d+\s' } |
            ForEach-Object { ($_ -split '\s+')[0] }
    ) -contains $ExpectedSerial
}

$failures = [System.Collections.Generic.List[string]]::new()
if (-not [string]::IsNullOrWhiteSpace($Serial)) {
    $name = Invoke-XpjAdb @('-s', $Serial, 'emu', 'avd', 'name')
    $reportedName = if ($name.Output.Count -gt 0) {
        [string]$name.Output[0].Trim()
    }
    else {
        ''
    }
    if ($name.ExitCode -eq 0 -and $reportedName -ceq $AvdName) {
        [void](Invoke-XpjAdb @('-s', $Serial, 'emu', 'kill'))
    }
    elseif ($name.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($reportedName)) {
        $failures.Add(
            "Refusing to stop emulator serial $Serial because it reports AVD $reportedName."
        )
    }
}

if ($ProcessId -gt 0) {
    if ($ProcessStartFileTimeUtc -le 0) {
        $failures.Add('Emulator process cleanup is missing its creation generation.')
    }
    else {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            try {
                [void]$process.Handle
                $actualStart = $process.StartTime.ToUniversalTime().ToFileTimeUtc()
                if ($actualStart -ne $ProcessStartFileTimeUtc) {
                    $failures.Add(
                        "Refusing to stop reused emulator PID $ProcessId with another generation."
                    )
                }
                else {
                    $process.Refresh()
                    if (-not $process.HasExited) {
                        try {
                            $process.Kill()
                        }
                        catch {
                            $process.Refresh()
                            if (-not $process.HasExited) {
                                throw
                            }
                        }
                    }
                    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
                        $failures.Add(
                            "Exact emulator process $ProcessId did not exit within $TimeoutSeconds seconds."
                        )
                    }
                }
            }
            catch {
                $failures.Add(
                    "Exact emulator process $ProcessId cleanup failed: $($_.Exception.Message)"
                )
            }
            finally {
                $process.Dispose()
            }
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($Serial)) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $serialPresent = $true
    while ($serialPresent -and [DateTime]::UtcNow -lt $deadline) {
        try {
            $serialPresent = Test-XpjSerialPresent $Serial
        }
        catch {
            $failures.Add($_.Exception.Message)
            break
        }
        if ($serialPresent) {
            Start-Sleep -Milliseconds 250
        }
    }
    if ($serialPresent) {
        $failures.Add("Emulator serial $Serial remains after cleanup.")
    }
}

if ($failures.Count -gt 0) {
    throw "Owned emulator cleanup failed: $($failures -join ' | ')"
}
Write-Host "Owned emulator cleanup complete (serial=$Serial, pid=$ProcessId)."
