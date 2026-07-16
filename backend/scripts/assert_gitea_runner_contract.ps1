#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$RunnerExecutable = '',
    [version]$MinimumVersion = [version]'2.0.0'
)

$ErrorActionPreference = 'Stop'

function Find-XpjGiteaRunnerExecutable {
    $processId = $PID
    for ($depth = 0; $depth -lt 16; $depth++) {
        $process = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $processId" `
            -ErrorAction Stop
        if ($null -eq $process -or [int]$process.ParentProcessId -le 0) {
            break
        }
        $parent = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $([int]$process.ParentProcessId)" `
            -ErrorAction Stop
        if ($null -eq $parent) {
            break
        }
        if (
            [string]$parent.Name -match '^(?:act|gitea)[_-]?runner(?:\.exe)?$' -and
            -not [string]::IsNullOrWhiteSpace([string]$parent.ExecutablePath)
        ) {
            return [System.IO.Path]::GetFullPath([string]$parent.ExecutablePath)
        }
        $processId = [int]$parent.ProcessId
    }
    throw 'Cannot prove the Gitea runner executable from this job process tree.'
}

if ([string]::IsNullOrWhiteSpace($RunnerExecutable)) {
    $RunnerExecutable = Find-XpjGiteaRunnerExecutable
}
elseif (-not [System.IO.Path]::IsPathRooted($RunnerExecutable)) {
    throw 'Gitea runner executable must be an absolute path.'
}
else {
    $RunnerExecutable = [System.IO.Path]::GetFullPath($RunnerExecutable)
}

if (-not (Test-Path -LiteralPath $RunnerExecutable -PathType Leaf)) {
    throw "Gitea runner executable does not exist: $RunnerExecutable"
}

$versionOutput = @(& $RunnerExecutable --version 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Gitea runner version probe failed (exit=$LASTEXITCODE)."
}
$match = [regex]::Match(
    (($versionOutput | ForEach-Object { [string]$_ }) -join "`n"),
    '(?i)\bv?(\d+\.\d+\.\d+)\b'
)
if (-not $match.Success) {
    throw 'Gitea runner version output did not contain a semantic version.'
}
$actualVersion = [version]$match.Groups[1].Value
if ($actualVersion -lt $MinimumVersion) {
    throw "Gitea runner $actualVersion is below required $MinimumVersion; timeout and always() cleanup are not reliable."
}

Write-Host "Gitea runner contract OK: $actualVersion (minimum $MinimumVersion)"
