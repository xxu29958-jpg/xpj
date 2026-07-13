#Requires -Version 5.1
<#
Freeze the ordinary-user Desktop Manager into dist\ticketbox-manager with the
same pinned Windows Python/uv/PyInstaller toolchain used by the backend build.
#>
[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = "Stop"
$DesktopRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $DesktopRoot "..")).Path
$BackendRoot = Join-Path $RepoRoot "backend"
$BuildRoot = Join-Path $DesktopRoot "build"
$DistRoot = Join-Path $DesktopRoot "dist"
$BuildNonce = "{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N")
$BuildVenv = Join-Path $BuildRoot (".ticketbox-manager-venv-{0}" -f $BuildNonce)
$LegacyBuildVenv = Join-Path $DesktopRoot ".venv-build"
$PyBuild = Join-Path $BuildVenv "Scripts\python.exe"
$PyInstaller = Join-Path $BuildVenv "Scripts\pyinstaller.exe"
$ToolchainPrepScript = Join-Path $BackendRoot "packaging\prepare_windows_build_toolchain.ps1"
$ToolchainRoot = Join-Path $BackendRoot "build\windows-toolchain"
$BuildProvenanceScript = Join-Path $BackendRoot "scripts\windows_build_provenance.ps1"
$BackendBuildProvenanceScript = Join-Path $BackendRoot "scripts\windows_backend_build_provenance.ps1"
$ManagerBuildProvenanceScript = Join-Path $PSScriptRoot "windows_manager_build_provenance.ps1"
$InputSnapshotRoot = Join-Path $BuildRoot (".ticketbox-manager-inputs-{0}" -f $BuildNonce)
$LockSnapshotPath = Join-Path $InputSnapshotRoot "desktop\requirements-build.lock"
$StagingRoot = Join-Path $DistRoot (".ticketbox-manager-staging-{0}" -f $BuildNonce)
$StagingDir = Join-Path $StagingRoot "ticketbox-manager"
$WorkRoot = Join-Path $BuildRoot (".ticketbox-manager-work-{0}" -f $BuildNonce)
$FinalDir = Join-Path $DistRoot "ticketbox-manager"
$BackupDir = Join-Path $DistRoot ".ticketbox-manager.last-known-good"
$PublishReceipt = Join-Path $DistRoot ".ticketbox-manager.publish-receipt.json"
$BuildLock = $null
$InputLocks = $null
$ToolchainLocks = $null
$PrimaryFailure = $null
$CleanupFailures = New-Object System.Collections.Generic.List[string]
$PreviousUvPythonDownloads = [Environment]::GetEnvironmentVariable("UV_PYTHON_DOWNLOADS", "Process")
$PreviousPythonNoUserSite = [Environment]::GetEnvironmentVariable("PYTHONNOUSERSITE", "Process")
$PreviousPythonDontWriteBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")

. $BuildProvenanceScript
. $BackendBuildProvenanceScript
. $ManagerBuildProvenanceScript

function Remove-TicketboxManagerBuildDirectory([string]$Path, [string]$AllowedRoot) {
    $canonical = Assert-TicketboxNoReparsePath -Path $Path -AllowedRoot $AllowedRoot -InspectTree
    if (Test-Path -LiteralPath $canonical) {
        Remove-Item -LiteralPath $canonical -Recurse -Force -ErrorAction Stop
    }
}

function Invoke-TicketboxManagerVersionProbe(
    [string]$Executable,
    [string[]]$Arguments,
    [string]$Pattern,
    [string]$Label
) {
    $output = @(& $Executable @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    if ($exitCode -ne 0) { throw "$Label probe failed (exit=$exitCode): $text" }
    $match = [regex]::Match($text.Trim(), $Pattern)
    if (-not $match.Success) { throw "Cannot parse $Label version: $text" }
    return $match.Groups[1].Value
}

try {
    $BuildLock = Enter-TicketboxWindowsBuildLock $BackendRoot
    Assert-TicketboxNoReparsePath -Path $BuildRoot -AllowedRoot $DesktopRoot | Out-Null
    Assert-TicketboxNoReparsePath -Path $DistRoot -AllowedRoot $DesktopRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot | Out-Null
    Recover-TicketboxDirectoryPublication `
        -TargetDirectory $FinalDir `
        -BackupDirectory $BackupDir `
        -ReceiptPath $PublishReceipt `
        -PublishRoot $DistRoot
    Remove-TicketboxManagerBuildDirectory $StagingRoot $DistRoot
    Remove-TicketboxManagerBuildDirectory $WorkRoot $BuildRoot
    Remove-TicketboxManagerBuildDirectory $InputSnapshotRoot $BuildRoot
    Remove-TicketboxManagerBuildDirectory $BuildVenv $BuildRoot
    if ($Clean -and (Test-Path -LiteralPath $LegacyBuildVenv)) {
        Remove-TicketboxManagerBuildDirectory $LegacyBuildVenv $DesktopRoot
    }

    $contract = Read-TicketboxManagerBuildContract $RepoRoot
    $toolchain = $contract.toolchain
    & $ToolchainPrepScript -Component Backend -ToolchainRoot $ToolchainRoot -Force
    $UvPath = Join-Path $ToolchainRoot ("uv\{0}" -f [string]$toolchain.uv_source.executable_relative_path)
    $SourcePython = Join-Path $ToolchainRoot ("python\{0}" -f [string]$toolchain.python_source.executable_relative_path)
    $SourcePythonRuntime = Join-Path $ToolchainRoot ("python\{0}" -f [string]$toolchain.python_source.runtime_relative_path)
    if (
        (Get-TicketboxFileSha256 $UvPath) -cne ([string]$toolchain.uv_source.executable_sha256).ToLowerInvariant() -or
        (Get-TicketboxFileSha256 $SourcePython) -cne ([string]$toolchain.python_source.executable_sha256).ToLowerInvariant() -or
        (Get-TicketboxFileSha256 $SourcePythonRuntime) -cne ([string]$toolchain.python_source.runtime_sha256).ToLowerInvariant()
    ) {
        throw "Prepared Desktop Manager build tools do not match the pinned archive payload contract."
    }
    $toolchainPaths = @(
        Get-ChildItem -LiteralPath (Join-Path $ToolchainRoot "uv") -Recurse -File -Force |
            ForEach-Object { $_.FullName }
        Get-ChildItem -LiteralPath (Join-Path $ToolchainRoot "python") -Recurse -File -Force |
            ForEach-Object { $_.FullName }
    )
    $toolchainSnapshot = Get-TicketboxFileSetSnapshot $ToolchainRoot $toolchainPaths
    $ToolchainLocks = @(Enter-TicketboxFileSetReadLocks -Root $ToolchainRoot -Snapshot $toolchainSnapshot)

    $sourceBeforeFreeze = Get-TicketboxManagerSourceSnapshot $RepoRoot
    New-Item -ItemType Directory -Force -Path $InputSnapshotRoot | Out-Null
    Copy-TicketboxFileSetSnapshot `
        -SourceRoot $RepoRoot `
        -DestinationRoot $InputSnapshotRoot `
        -Snapshot $sourceBeforeFreeze | Out-Null
    $InputLocks = @(Enter-TicketboxFileSetReadLocks -Root $InputSnapshotRoot -Snapshot $sourceBeforeFreeze)

    $env:UV_PYTHON_DOWNLOADS = "never"
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $UvPath venv $BuildVenv --python $SourcePython
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed (exit=$LASTEXITCODE)" }
    & $UvPath pip sync --strict --require-hashes --python $PyBuild $LockSnapshotPath
    if ($LASTEXITCODE -ne 0) { throw "uv pip sync failed (exit=$LASTEXITCODE)" }

    $pythonVersion = Invoke-TicketboxManagerVersionProbe `
        $PyBuild @("-c", "import platform; print(platform.python_version())") `
        '^(\d+\.\d+\.\d+)$' "Python"
    $uvVersion = Invoke-TicketboxManagerVersionProbe $UvPath @("--version") '^uv\s+(\d+\.\d+\.\d+)\b' "uv"
    $pyInstallerVersion = Invoke-TicketboxManagerVersionProbe `
        $PyBuild @("-I", "-B", "-m", "PyInstaller", "--version") `
        '^(\d+\.\d+\.\d+)$' "PyInstaller"
    $installedDistributions = @(& $UvPath pip freeze --python $PyBuild)
    if ($LASTEXITCODE -ne 0) { throw "uv pip freeze failed (exit=$LASTEXITCODE)" }
    $executionTreeBeforeFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild
    $toolchainProvenance = New-TicketboxManagerBuildToolchainProvenance `
        -RepoRoot $RepoRoot `
        -Contract $contract `
        -PythonPath $PyBuild `
        -PythonSourcePath $SourcePython `
        -PythonVersion $pythonVersion `
        -UvPath $UvPath `
        -UvVersion $uvVersion `
        -PyInstallerPath $PyInstaller `
        -PyInstallerVersion $pyInstallerVersion `
        -InstalledDistributions $installedDistributions `
        -PythonExecutionTree $executionTreeBeforeFreeze

    & $PyBuild -I -B -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $StagingRoot `
        --workpath $WorkRoot `
        (Join-Path $InputSnapshotRoot "desktop\packaging\ticketbox-manager.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit=$LASTEXITCODE)." }
    $executionTreeAfterFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild
    Assert-TicketboxStructuredEvidence `
        "Desktop Manager PyInstaller execution tree" `
        $executionTreeBeforeFreeze `
        $executionTreeAfterFreeze
    Assert-TicketboxFileSetSnapshot `
        "Frozen Desktop Manager source during build" `
        $sourceBeforeFreeze `
        (Get-TicketboxManagerSourceSnapshot $RepoRoot)
    Assert-TicketboxFileSetSnapshot `
        "Pinned Windows toolchain during Manager build" `
        $toolchainSnapshot `
        (Get-TicketboxFileSetSnapshot $ToolchainRoot $toolchainPaths)

    $stagedExecutable = Join-Path $StagingDir "ticketbox-manager.exe"
    if (-not (Test-Path -LiteralPath $stagedExecutable -PathType Leaf)) {
        throw "PyInstaller completed without ticketbox-manager.exe."
    }
    Write-TicketboxManagerBuildManifest `
        -RepoRoot $InputSnapshotRoot `
        -DistDir $StagingDir `
        -ToolchainProvenance $toolchainProvenance `
        -SourceSnapshot $sourceBeforeFreeze | Out-Null
    Assert-TicketboxManagerBuildManifest $RepoRoot $StagingDir | Out-Null
    $validateManagerPublish = {
        param([string]$PublishedDirectory)
        Assert-TicketboxManagerBuildManifest $RepoRoot $PublishedDirectory | Out-Null
    }
    Publish-TicketboxRecoverableDirectory `
        -StagingDirectory $StagingDir `
        -TargetDirectory $FinalDir `
        -BackupDirectory $BackupDir `
        -ReceiptPath $PublishReceipt `
        -PublishRoot $DistRoot `
        -ValidatePublished $validateManagerPublish
    $sizeMb = [math]::Round(((Get-ChildItem -Recurse -File $FinalDir | Measure-Object Length -Sum).Sum) / 1MB, 1)
    Write-Host "OK  ->  $FinalDir  (folder $sizeMb MB)"
}
catch {
    $PrimaryFailure = $_
}
finally {
    foreach ($cleanup in @(
        [pscustomobject]@{ Label = "input read locks"; Action = { Exit-TicketboxFileSetReadLocks $InputLocks } },
        [pscustomobject]@{ Label = "toolchain read locks"; Action = { Exit-TicketboxFileSetReadLocks $ToolchainLocks } },
        [pscustomobject]@{ Label = "UV_PYTHON_DOWNLOADS"; Action = {
            if ($null -eq $PreviousUvPythonDownloads) { Remove-Item Env:UV_PYTHON_DOWNLOADS -ErrorAction SilentlyContinue }
            else { $env:UV_PYTHON_DOWNLOADS = $PreviousUvPythonDownloads }
        } },
        [pscustomobject]@{ Label = "PYTHONNOUSERSITE"; Action = {
            if ($null -eq $PreviousPythonNoUserSite) { Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue }
            else { $env:PYTHONNOUSERSITE = $PreviousPythonNoUserSite }
        } },
        [pscustomobject]@{ Label = "PYTHONDONTWRITEBYTECODE"; Action = {
            if ($null -eq $PreviousPythonDontWriteBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
            else { $env:PYTHONDONTWRITEBYTECODE = $PreviousPythonDontWriteBytecode }
        } },
        [pscustomobject]@{ Label = "dist staging"; Action = { Remove-TicketboxManagerBuildDirectory $StagingRoot $DistRoot } },
        [pscustomobject]@{ Label = "PyInstaller work"; Action = { Remove-TicketboxManagerBuildDirectory $WorkRoot $BuildRoot } },
        [pscustomobject]@{ Label = "input snapshot"; Action = { Remove-TicketboxManagerBuildDirectory $InputSnapshotRoot $BuildRoot } },
        [pscustomobject]@{ Label = "build venv"; Action = { Remove-TicketboxManagerBuildDirectory $BuildVenv $BuildRoot } },
        [pscustomobject]@{ Label = "Windows build lock"; Action = { Exit-TicketboxWindowsBuildLock $BuildLock } }
    )) {
        try { & $cleanup.Action }
        catch { $CleanupFailures.Add("$($cleanup.Label): $($_.Exception.Message)") }
    }
}

if ($null -ne $PrimaryFailure) {
    if ($CleanupFailures.Count -gt 0) {
        throw "$($PrimaryFailure.Exception.Message) Cleanup failures: $($CleanupFailures -join '; ')"
    }
    throw $PrimaryFailure
}
if ($CleanupFailures.Count -gt 0) {
    throw "Desktop Manager build cleanup failed: $($CleanupFailures -join '; ')"
}
