#Requires -Version 5.1
<#
Freeze the backend into dist\ticketbox-backend using the checked-in Windows
toolchain contract. The final dist path is removed before validation and only
recreated after a staged payload and provenance manifest both pass.
#>
[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = "Stop"
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location $BackendRoot
$BuildRoot = Join-Path $BackendRoot "build"
$BuildNonce = "{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N")
$LegacyBuildVenv = Join-Path $BackendRoot ".venv-build"
$BuildVenv = Join-Path $BuildRoot (".ticketbox-backend-venv-{0}" -f $BuildNonce)
$PyBuild = Join-Path $BuildVenv "Scripts\python.exe"
$PyInstaller = Join-Path $BuildVenv "Scripts\pyinstaller.exe"
$PyInstallerArchiveViewer = Join-Path $BuildVenv "Scripts\pyi-archive_viewer.exe"
$ProvenanceScript = Join-Path $PSScriptRoot "windows_build_provenance.ps1"
$ToolchainPrepScript = Join-Path $BackendRoot "packaging\prepare_windows_build_toolchain.ps1"
$ToolchainRoot = Join-Path $BackendRoot "build\windows-toolchain"
$DistRoot = Join-Path $BackendRoot "dist"
$FinalDir = Join-Path $DistRoot "ticketbox-backend"
$BackupDir = Join-Path $DistRoot ".ticketbox-backend.last-known-good"
$PublishReceipt = Join-Path $DistRoot ".ticketbox-backend.publish-receipt.json"
$StagingRoot = Join-Path $DistRoot (".ticketbox-backend-staging-{0}" -f $BuildNonce)
$StagingDir = Join-Path $StagingRoot "ticketbox-backend"
$WorkRoot = Join-Path $BuildRoot (".ticketbox-backend-work-{0}" -f $BuildNonce)
$InputSnapshotRoot = Join-Path $BuildRoot (".ticketbox-backend-inputs-{0}" -f $BuildNonce)
$LockSnapshotPath = Join-Path $InputSnapshotRoot "requirements-build.lock"
$InputLocks = $null
$ToolchainLocks = $null
$C07SmokePayloadLocks = $null
$ToolchainSnapshot = $null
$ToolchainPaths = @()
$BuildLock = $null
$PrimaryFailure = $null
$CleanupFailures = New-Object System.Collections.Generic.List[string]
$PreviousUvPythonDownloads = [Environment]::GetEnvironmentVariable("UV_PYTHON_DOWNLOADS", "Process")
$PreviousPythonNoUserSite = [Environment]::GetEnvironmentVariable("PYTHONNOUSERSITE", "Process")
$PreviousPythonDontWriteBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")

function Remove-TicketboxBuildDirectory([string]$Path, [string]$AllowedRoot) {
    $canonicalPath = Assert-TicketboxNoReparsePath `
        -Path $Path `
        -AllowedRoot $AllowedRoot `
        -InspectTree
    if (Test-Path -LiteralPath $canonicalPath) {
        Remove-Item -LiteralPath $canonicalPath -Recurse -Force -ErrorAction Stop
    }
}

function Invoke-TicketboxVersionProbe(
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

if (-not (Test-Path -LiteralPath $ProvenanceScript -PathType Leaf)) {
    throw "Missing build provenance helper: $ProvenanceScript"
}
. $ProvenanceScript
if (-not (Test-Path -LiteralPath $ToolchainPrepScript -PathType Leaf)) {
    throw "Missing pinned Windows build toolchain preparer: $ToolchainPrepScript"
}

try {
    $BuildLock = Enter-TicketboxWindowsBuildLock $BackendRoot
    Assert-TicketboxNoReparsePath -Path $DistRoot -AllowedRoot $BackendRoot | Out-Null
    Assert-TicketboxNoReparsePath -Path $BuildRoot -AllowedRoot $BackendRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $DistRoot, $BuildRoot | Out-Null
    Recover-TicketboxDirectoryPublication `
        -TargetDirectory $FinalDir `
        -BackupDirectory $BackupDir `
        -ReceiptPath $PublishReceipt `
        -PublishRoot $DistRoot
    Remove-TicketboxBuildDirectory $StagingRoot $DistRoot
    Remove-TicketboxBuildDirectory $WorkRoot $BuildRoot
    Remove-TicketboxBuildDirectory $InputSnapshotRoot $BuildRoot
    Remove-TicketboxBuildDirectory $BuildVenv $BuildRoot
    $toolchain = Read-TicketboxWindowsBuildToolchain $BackendRoot
    & $ToolchainPrepScript -Component Backend -ToolchainRoot $ToolchainRoot -Force
    $UvPath = Join-Path $ToolchainRoot ("uv\{0}" -f [string]$toolchain.uv_source.executable_relative_path)
    $SourcePython = Join-Path $ToolchainRoot ("python\{0}" -f [string]$toolchain.python_source.executable_relative_path)
    $SourcePythonRuntime = Join-Path $ToolchainRoot ("python\{0}" -f [string]$toolchain.python_source.runtime_relative_path)
    if (
        (Get-TicketboxFileSha256 $UvPath) -cne ([string]$toolchain.uv_source.executable_sha256).ToLowerInvariant() -or
        (Get-TicketboxFileSha256 $SourcePython) -cne ([string]$toolchain.python_source.executable_sha256).ToLowerInvariant() -or
        (Get-TicketboxFileSha256 $SourcePythonRuntime) -cne ([string]$toolchain.python_source.runtime_sha256).ToLowerInvariant()
    ) {
        throw "Prepared Windows backend build tools do not match the pinned archive payload contract."
    }
    $ToolchainPaths = @(
        Get-ChildItem -LiteralPath (Join-Path $ToolchainRoot "uv") -Recurse -File -Force |
            ForEach-Object { $_.FullName }
        Get-ChildItem -LiteralPath (Join-Path $ToolchainRoot "python") -Recurse -File -Force |
            ForEach-Object { $_.FullName }
    )
    $ToolchainSnapshot = Get-TicketboxFileSetSnapshot $ToolchainRoot $ToolchainPaths
    $ToolchainLocks = @(Enter-TicketboxFileSetReadLocks `
        -Root $ToolchainRoot `
        -Snapshot $ToolchainSnapshot)
    $env:UV_PYTHON_DOWNLOADS = "never"
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $uvVersion = Invoke-TicketboxVersionProbe $UvPath @("--version") '^uv\s+(\d+\.\d+\.\d+)\b' "uv"
    if ($uvVersion -cne $toolchain.uv_version) {
        throw "uv version mismatch: actual=$uvVersion expected=$($toolchain.uv_version)"
    }

    if ($Clean -and (Test-Path -LiteralPath $LegacyBuildVenv)) {
        Remove-TicketboxBuildDirectory $LegacyBuildVenv $BackendRoot
    }
    Write-Host "Creating process-private exact build venv ($BuildVenv) ..."
    & $UvPath venv $BuildVenv --python $SourcePython
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed (exit=$LASTEXITCODE)" }

    $pythonVersion = Invoke-TicketboxVersionProbe $PyBuild @("-c", "import platform; print(platform.python_version())") '^(\d+\.\d+\.\d+)$' "Python"
    if ($pythonVersion -cne $toolchain.python_version) {
        throw "Build venv Python mismatch: actual=$pythonVersion expected=$($toolchain.python_version). Re-run with -Clean."
    }

    $sourceBeforeFreeze = Get-TicketboxBackendSourceSnapshot $BackendRoot
    New-Item -ItemType Directory -Force -Path $InputSnapshotRoot | Out-Null
    Copy-TicketboxFileSetSnapshot `
        -SourceRoot $BackendRoot `
        -DestinationRoot $InputSnapshotRoot `
        -Snapshot $sourceBeforeFreeze | Out-Null
    $InputLocks = @(Enter-TicketboxFileSetReadLocks `
        -Root $InputSnapshotRoot `
        -Snapshot $sourceBeforeFreeze)
    Assert-TicketboxFileSetSnapshot `
        "Frozen backend source before dependency sync" `
        $sourceBeforeFreeze `
        (Get-TicketboxBackendSourceSnapshot $BackendRoot)
    $sourceLockHash = Get-TicketboxFileSha256 $toolchain.lock_path
    $snapshotLockHash = Get-TicketboxFileSha256 $LockSnapshotPath
    if ($sourceLockHash -cne $snapshotLockHash) {
        throw "Immutable dependency lock snapshot differs from the attested source lock."
    }

    Write-Host "Synchronizing runtime dependencies and contracted PyInstaller from immutable lock snapshot ..."
    & $UvPath pip sync --strict --require-hashes --python $PyBuild $LockSnapshotPath
    if ($LASTEXITCODE -ne 0) { throw "uv pip sync failed (exit=$LASTEXITCODE)" }
    $postSyncSnapshotLockHash = Get-TicketboxFileSha256 $LockSnapshotPath
    if ($postSyncSnapshotLockHash -cne $sourceLockHash) {
        throw "Immutable dependency lock snapshot changed while uv consumed it."
    }
    Assert-TicketboxFileSetSnapshot `
        "Frozen backend source during dependency sync" `
        $sourceBeforeFreeze `
        (Get-TicketboxBackendSourceSnapshot $BackendRoot)
    if (-not (Test-Path -LiteralPath $PyInstaller -PathType Leaf)) {
        throw "Contracted PyInstaller executable is missing: $PyInstaller"
    }
    if (-not (Test-Path -LiteralPath $PyInstallerArchiveViewer -PathType Leaf)) {
        throw "Contracted PyInstaller archive viewer is missing: $PyInstallerArchiveViewer"
    }
    $pyInstallerVersion = Invoke-TicketboxVersionProbe $PyBuild @("-I", "-B", "-m", "PyInstaller", "--version") '^(\d+\.\d+\.\d+)$' "PyInstaller"
    if ($pyInstallerVersion -cne $toolchain.pyinstaller_version) {
        throw "PyInstaller mismatch: actual=$pyInstallerVersion expected=$($toolchain.pyinstaller_version)"
    }
    $installedDistributions = @(& $UvPath pip freeze --python $PyBuild)
    if ($LASTEXITCODE -ne 0) { throw "uv pip freeze failed (exit=$LASTEXITCODE)" }
    Write-Host "Freezing into staging ..."
    $executionTreeBeforeFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild
    & $PyBuild -I -B -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $StagingRoot `
        --workpath $WorkRoot `
        (Join-Path $InputSnapshotRoot "packaging\ticketbox-backend.spec")
    $pyInstallerExitCode = $LASTEXITCODE
    $executionTreeAfterFreeze = Get-TicketboxPythonExecutionTreeSnapshot $PyBuild
    Assert-TicketboxStructuredEvidence "PyInstaller interpreter and site-packages during freeze" $executionTreeBeforeFreeze $executionTreeAfterFreeze
    $toolchainProvenance = New-TicketboxBackendBuildToolchainProvenance -BackendRoot $BackendRoot -Config $toolchain -PythonPath $PyBuild -PythonSourcePath $SourcePython -PythonVersion $pythonVersion -UvPath $UvPath -UvVersion $uvVersion -PyInstallerPath $PyInstaller -PyInstallerVersion $pyInstallerVersion -InstalledDistributions $installedDistributions -PythonExecutionTree $executionTreeBeforeFreeze
    if ($pyInstallerExitCode -ne 0) {
        throw "PyInstaller failed (exit=$pyInstallerExitCode); no final frozen payload was published."
    }
    $stagedExe = Join-Path $StagingDir "ticketbox-backend.exe"
    if (-not (Test-Path -LiteralPath $stagedExe -PathType Leaf)) {
        throw "PyInstaller completed without the staged backend executable."
    }
    $stagedC07Helper = Join-Path $StagingDir "ticketbox-c07-migrator.exe"
    if (-not (Test-Path -LiteralPath $stagedC07Helper -PathType Leaf)) {
        throw "PyInstaller completed without the staged C07 migration helper."
    }
    $archiveListing = @(& $PyBuild -I -B -m PyInstaller.utils.cliutils.archive_viewer -r $stagedExe 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller archive inspection failed (exit=$LASTEXITCODE)."
    }
    $archiveModules = @(
        $archiveListing |
            ForEach-Object { $_.ToString() } |
            Where-Object { $_.Trim().Length -gt 0 }
    )
    foreach ($requiredModule in @(
        "app.app_meta_observation",
        "app.canonical_money_facts",
        "app.canonical_money_facts_contract",
        "app.database_model_registry",
        "app.tenant_contract"
    )) {
        if (-not @($archiveModules | Where-Object {
            $_ -match ("'" + [regex]::Escape($requiredModule) + "'$" )
        })) {
            throw "Frozen backend archive omitted required app module: $requiredModule"
        }
    }
    Assert-TicketboxPostgresOnlyFrozenPayload `
        -DistDir $StagingDir `
        -ArchiveListing $archiveModules
    $c07SmokePayloadSnapshot = Get-TicketboxBackendPayloadSnapshot $StagingDir
    $C07SmokePayloadLocks = @(Enter-TicketboxFileSetReadLocks `
        -Root $StagingDir `
        -Snapshot $c07SmokePayloadSnapshot)
    $c07MigrationHelperSmoke = Invoke-TicketboxC07MigrationHelperSmoke `
        -DistDir $StagingDir `
        -HelperPath $stagedC07Helper `
        -PayloadSnapshot $c07SmokePayloadSnapshot
    Assert-TicketboxFileSetSnapshot "Frozen backend source during build" $sourceBeforeFreeze (Get-TicketboxBackendSourceSnapshot $BackendRoot)
    $currentPythonVersion = Invoke-TicketboxVersionProbe $PyBuild @("-c", "import platform; print(platform.python_version())") '^(\d+\.\d+\.\d+)$' "Python"
    $currentUvVersion = Invoke-TicketboxVersionProbe $UvPath @("--version") '^uv\s+(\d+\.\d+\.\d+)\b' "uv"
    $currentPyInstallerVersion = Invoke-TicketboxVersionProbe $PyBuild @("-I", "-B", "-m", "PyInstaller", "--version") '^(\d+\.\d+\.\d+)$' "PyInstaller"
    $currentDistributions = @(& $UvPath pip freeze --python $PyBuild)
    if ($LASTEXITCODE -ne 0) { throw "post-build uv pip freeze failed (exit=$LASTEXITCODE)" }
    $currentToolchainProvenance = New-TicketboxBackendBuildToolchainProvenance -BackendRoot $BackendRoot -Config $toolchain -PythonPath $PyBuild -PythonSourcePath $SourcePython -PythonVersion $currentPythonVersion -UvPath $UvPath -UvVersion $currentUvVersion -PyInstallerPath $PyInstaller -PyInstallerVersion $currentPyInstallerVersion -InstalledDistributions $currentDistributions -PythonExecutionTree $executionTreeAfterFreeze
    Assert-TicketboxStructuredEvidence "Frozen backend toolchain during build" $toolchainProvenance $currentToolchainProvenance
    Assert-TicketboxFileSetSnapshot `
        "Pinned Windows backend toolchain during build" `
        $ToolchainSnapshot `
        (Get-TicketboxFileSetSnapshot $ToolchainRoot $ToolchainPaths)
    $manifestPath = Write-TicketboxBackendBuildManifest `
        -BackendRoot $InputSnapshotRoot `
        -DistDir $StagingDir `
        -ToolchainProvenance $currentToolchainProvenance `
        -SourceSnapshot $sourceBeforeFreeze `
        -C07MigrationHelperSmokeEvidence $c07MigrationHelperSmoke
    Assert-TicketboxBackendBuildManifest $BackendRoot $StagingDir | Out-Null
    Exit-TicketboxFileSetReadLocks $C07SmokePayloadLocks
    $C07SmokePayloadLocks = $null
    $validateBackendPublish = {
        param([string]$PublishedDirectory)
        Assert-TicketboxBackendBuildManifest $BackendRoot $PublishedDirectory | Out-Null
    }
    Publish-TicketboxRecoverableDirectory `
        -StagingDirectory $StagingDir `
        -TargetDirectory $FinalDir `
        -BackupDirectory $BackupDir `
        -ReceiptPath $PublishReceipt `
        -PublishRoot $DistRoot `
        -ValidatePublished $validateBackendPublish
    $sizeMb = [math]::Round(((Get-ChildItem -Recurse -File $FinalDir | Measure-Object Length -Sum).Sum) / 1MB, 1)
    Write-Host "OK  ->  $FinalDir  (folder $sizeMb MB)"
    Write-Host "Provenance -> $(Join-Path $FinalDir (Split-Path -Leaf $manifestPath))"
}
catch {
    $PrimaryFailure = $_
}
finally {
    try {
        foreach ($cleanup in @(
            [pscustomobject]@{ Label = "C07 smoke payload read locks"; Action = { Exit-TicketboxFileSetReadLocks $C07SmokePayloadLocks } },
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
            [pscustomobject]@{ Label = "dist staging"; Action = { Remove-TicketboxBuildDirectory $StagingRoot $DistRoot } },
            [pscustomobject]@{ Label = "PyInstaller work"; Action = { Remove-TicketboxBuildDirectory $WorkRoot $BuildRoot } },
            [pscustomobject]@{ Label = "input snapshot"; Action = { Remove-TicketboxBuildDirectory $InputSnapshotRoot $BuildRoot } },
            [pscustomobject]@{ Label = "build venv"; Action = { Remove-TicketboxBuildDirectory $BuildVenv $BuildRoot } }
        )) {
            try { & $cleanup.Action }
            catch { $CleanupFailures.Add("$($cleanup.Label): $($_.Exception.Message)") }
        }
    }
    finally {
        try { Exit-TicketboxWindowsBuildLock $BuildLock }
        catch { $CleanupFailures.Add("Windows build lock: $($_.Exception.Message)") }
    }
}
if ($null -ne $PrimaryFailure) {
    if ($CleanupFailures.Count -gt 0) {
        Write-Warning "Build cleanup also failed after the primary error: $($CleanupFailures -join '; ')"
    }
    throw $PrimaryFailure
}
if ($CleanupFailures.Count -gt 0) {
    throw "Backend build cleanup failed after publication: $($CleanupFailures -join '; ')"
}
