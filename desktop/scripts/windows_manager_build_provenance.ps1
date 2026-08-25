#Requires -Version 5.1

$script:TicketboxManagerBuildManifestName = "BUILD_PROVENANCE.json"
$script:TicketboxManagerBuildManifestSchema = 1
$script:TicketboxManagerLockInputHeaderPattern = '(?m)^# ticketbox-lock-input-sha256: ([0-9a-f]{64})\r?$'

function Get-TicketboxManagerVersion([string]$RepoRoot) {
    $versionFile = Join-Path $RepoRoot "backend\app\version.py"
    if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf)) {
        throw "Missing backend version source for Desktop Manager: $versionFile"
    }
    $content = Get-Content -LiteralPath $versionFile -Encoding UTF8 -Raw
    $match = [regex]::Match($content, '(?m)^\s*BACKEND_VERSION\s*=\s*"([^"]+)"\s*$')
    if (-not $match.Success) {
        throw "Cannot read BACKEND_VERSION for Desktop Manager."
    }
    return $match.Groups[1].Value
}

function Get-TicketboxManagerLockInputSnapshot([string]$DesktopRoot) {
    return Get-TicketboxFileSetSnapshot $DesktopRoot @(
        (Join-Path $DesktopRoot "requirements.txt"),
        (Join-Path $DesktopRoot "requirements-build.txt")
    )
}

function Read-TicketboxManagerBuildContract([string]$RepoRoot) {
    $backendRoot = Join-Path $RepoRoot "backend"
    $desktopRoot = Join-Path $RepoRoot "desktop"
    $toolchain = Read-TicketboxWindowsBuildToolchain $backendRoot
    $lockPath = Join-Path $desktopRoot "requirements-build.lock"
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        throw "Desktop Manager build dependency lock is missing: $lockPath"
    }
    $lockText = Get-Content -LiteralPath $lockPath -Encoding UTF8 -Raw
    $inputMatch = [regex]::Match($lockText, $script:TicketboxManagerLockInputHeaderPattern)
    if (-not $inputMatch.Success) {
        throw "Desktop Manager build lock lacks its requirements input fingerprint."
    }
    $inputSnapshot = Get-TicketboxManagerLockInputSnapshot $desktopRoot
    if ($inputMatch.Groups[1].Value -cne $inputSnapshot.fingerprint) {
        throw "Desktop Manager build lock is stale for requirements.txt or requirements-build.txt."
    }
    $pyInstallerMatch = [regex]::Match(
        $lockText,
        '(?m)^pyinstaller==(\d+\.\d+\.\d+)(?:\s|$)'
    )
    if (
        -not $pyInstallerMatch.Success -or
        $pyInstallerMatch.Groups[1].Value -cne [string]$toolchain.pyinstaller_version
    ) {
        throw "Desktop Manager build lock does not match the contracted PyInstaller version."
    }
    return [pscustomobject]@{
        lock_path = $lockPath
        lock_input_snapshot = $inputSnapshot
        toolchain = $toolchain
    }
}

function Get-TicketboxManagerSourcePaths([string]$RepoRoot) {
    $requiredFiles = @(
        "backend\app\version.py",
        "backend\packaging\ticketbox.ico",
        "backend\packaging\windows-build-toolchain.json",
        "backend\packaging\prepare_windows_build_toolchain.ps1",
        "backend\scripts\windows_build_provenance.ps1",
        "backend\scripts\windows_backend_build_provenance.ps1",
        "backend\scripts\windows_python_build_environment.ps1",
        "desktop\pyproject.toml",
        "desktop\requirements.txt",
        "desktop\requirements-build.txt",
        "desktop\requirements-build.lock",
        "desktop\packaging\ticketbox-manager.spec",
        "desktop\scripts\build_manager_exe.ps1",
        "desktop\scripts\windows_manager_build_provenance.ps1"
    )
    $paths = @()
    foreach ($relativePath in $requiredFiles) {
        $path = Join-Path $RepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Frozen Desktop Manager source set is missing: $path"
        }
        $paths += (Resolve-Path -LiteralPath $path).Path
    }
    $managerPackage = Join-Path $RepoRoot "desktop\backend_manager"
    if (-not (Test-Path -LiteralPath $managerPackage -PathType Container)) {
        throw "Frozen Desktop Manager package is missing: $managerPackage"
    }
    $paths += @(
        Get-ChildItem -LiteralPath $managerPackage -Recurse -File |
            Where-Object {
                $_.Extension -notin @(".pyc", ".pyo") -and
                $_.FullName -notmatch '[\\/]__pycache__[\\/]'
            } |
            ForEach-Object { $_.FullName }
    )
    return @(Get-TicketboxOrdinalSortedPaths $paths)
}

function Get-TicketboxManagerSourceSnapshot([string]$RepoRoot) {
    return Get-TicketboxFileSetSnapshot $RepoRoot (Get-TicketboxManagerSourcePaths $RepoRoot)
}

function New-TicketboxManagerBuildToolchainProvenance {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][object]$Contract,
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][string]$PythonSourcePath,
        [Parameter(Mandatory = $true)][string]$PythonVersion,
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][string]$UvVersion,
        [Parameter(Mandatory = $true)][string]$PyInstallerPath,
        [Parameter(Mandatory = $true)][string]$PyInstallerVersion,
        [Parameter(Mandatory = $true)][string[]]$InstalledDistributions,
        [Parameter(Mandatory = $true)][object]$PythonExecutionTree
    )
    $toolchain = $Contract.toolchain
    if (
        $PythonVersion -cne $toolchain.python_version -or
        $UvVersion -cne $toolchain.uv_version -or
        $PyInstallerVersion -cne $toolchain.pyinstaller_version
    ) {
        throw "Actual Desktop Manager build tool versions do not match the checked-in contract."
    }
    if (
        (Get-TicketboxFileSha256 $PythonSourcePath) -cne
            ([string]$toolchain.python_source.executable_sha256).ToLowerInvariant() -or
        (Get-TicketboxFileSha256 $UvPath) -cne
            ([string]$toolchain.uv_source.executable_sha256).ToLowerInvariant()
    ) {
        throw "Actual Desktop Manager build tools do not match their pinned source payload hashes."
    }
    $distributionSnapshot = Get-TicketboxInstalledDistributionSnapshot $InstalledDistributions
    if (@($distributionSnapshot.entries | Where-Object {
        $_ -ieq "pyinstaller==$PyInstallerVersion"
    }).Count -ne 1) {
        throw "Desktop Manager distribution snapshot lacks the contracted PyInstaller version."
    }
    Assert-TicketboxExecutionTreeEvidence $PythonExecutionTree
    $desktopRoot = Join-Path $RepoRoot "desktop"
    return [ordered]@{
        contract = Get-TicketboxFileEvidence $RepoRoot $toolchain.path
        python = [ordered]@{
            version = $PythonVersion
            source = Get-TicketboxNormalizedBackendToolSource $toolchain.python_source "python"
            executable = Get-TicketboxFileEvidence $RepoRoot $PythonPath
        }
        uv = [ordered]@{
            version = $UvVersion
            source = Get-TicketboxNormalizedBackendToolSource $toolchain.uv_source "uv"
            executable = Get-TicketboxFileEvidence $RepoRoot $UvPath
        }
        pyinstaller = [ordered]@{
            version = $PyInstallerVersion
            executable = Get-TicketboxFileEvidence $RepoRoot $PyInstallerPath
        }
        requirements = [ordered]@{
            input = Get-TicketboxFileEvidence $desktopRoot (Join-Path $desktopRoot "requirements-build.txt")
            lock = Get-TicketboxFileEvidence $desktopRoot $Contract.lock_path
            input_snapshot = $Contract.lock_input_snapshot
        }
        installed_distributions = $distributionSnapshot
        python_execution_tree = Get-TicketboxCompactExecutionTreeEvidence $PythonExecutionTree
        reproducibility_scope = "exact-build-tool-identities-and-complete-interpreter-execution-tree; frozen-bytes-not-claimed-reproducible"
    }
}

function Assert-TicketboxManagerToolchainEvidence([string]$RepoRoot, [object]$Recorded) {
    if ($null -eq $Recorded) { throw "Frozen Desktop Manager manifest lacks build toolchain evidence." }
    $contract = Read-TicketboxManagerBuildContract $RepoRoot
    $toolchain = $contract.toolchain
    if (
        [string]$Recorded.python.version -cne $toolchain.python_version -or
        [string]$Recorded.uv.version -cne $toolchain.uv_version -or
        [string]$Recorded.pyinstaller.version -cne $toolchain.pyinstaller_version
    ) {
        throw "Frozen Desktop Manager toolchain versions do not match the checked-in contract."
    }
    Assert-TicketboxStructuredEvidence `
        "Frozen Desktop Manager toolchain contract" `
        $Recorded.contract `
        (Get-TicketboxFileEvidence $RepoRoot $toolchain.path)
    $desktopRoot = Join-Path $RepoRoot "desktop"
    $expectedRequirements = [ordered]@{
        input = Get-TicketboxFileEvidence $desktopRoot (Join-Path $desktopRoot "requirements-build.txt")
        lock = Get-TicketboxFileEvidence $desktopRoot $contract.lock_path
        input_snapshot = $contract.lock_input_snapshot
    }
    Assert-TicketboxStructuredEvidence `
        "Frozen Desktop Manager build requirements" `
        $Recorded.requirements `
        $expectedRequirements
    Assert-TicketboxStructuredEvidence `
        "Frozen Desktop Manager Python source contract" `
        $Recorded.python.source `
        (Get-TicketboxNormalizedBackendToolSource $toolchain.python_source "python")
    Assert-TicketboxStructuredEvidence `
        "Frozen Desktop Manager uv source contract" `
        $Recorded.uv.source `
        (Get-TicketboxNormalizedBackendToolSource $toolchain.uv_source "uv")
    foreach ($name in @("python", "uv", "pyinstaller")) {
        $evidence = $Recorded.$name.executable
        if (
            $null -eq $evidence -or
            [int64]$evidence.size -le 0 -or
            [string]$evidence.sha256 -notmatch '^[0-9a-f]{64}$'
        ) {
            throw "Frozen Desktop Manager $name executable evidence is malformed."
        }
    }
    $entries = @($Recorded.installed_distributions.entries | ForEach-Object { [string]$_ })
    Assert-TicketboxStructuredEvidence `
        "Frozen Desktop Manager installed distributions" `
        $Recorded.installed_distributions `
        (Get-TicketboxInstalledDistributionSnapshot $entries)
    if (@($entries | Where-Object {
        $_ -ieq "pyinstaller==$($toolchain.pyinstaller_version)"
    }).Count -ne 1) {
        throw "Frozen Desktop Manager distribution evidence lacks the contracted PyInstaller version."
    }
    Assert-TicketboxExecutionTreeEvidence $Recorded.python_execution_tree
}

function Get-TicketboxManagerPayloadSnapshot([string]$DistDir) {
    if (-not (Test-Path -LiteralPath $DistDir -PathType Container)) {
        throw "Frozen Desktop Manager directory does not exist: $DistDir"
    }
    $manifestPath = Join-Path $DistDir $script:TicketboxManagerBuildManifestName
    $paths = @(
        Get-ChildItem -LiteralPath $DistDir -Recurse -File |
            Where-Object { $_.FullName -ne $manifestPath } |
            ForEach-Object { $_.FullName }
    )
    if ($paths.Count -eq 0) {
        throw "Frozen Desktop Manager payload is empty: $DistDir"
    }
    return Get-TicketboxFileSetSnapshot $DistDir $paths
}

function Write-TicketboxManagerBuildManifest(
    [string]$RepoRoot,
    [string]$DistDir,
    [object]$ToolchainProvenance,
    [object]$SourceSnapshot
) {
    if ($null -eq $ToolchainProvenance -or $null -eq $SourceSnapshot) {
        throw "Frozen Desktop Manager manifest requires toolchain and source evidence."
    }
    $payload = Get-TicketboxManagerPayloadSnapshot $DistDir
    $manifest = [ordered]@{
        schema_version = $script:TicketboxManagerBuildManifestSchema
        artifact_type = "ticketbox-frozen-desktop-manager"
        version = Get-TicketboxManagerVersion $RepoRoot
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        toolchain = $ToolchainProvenance
        source = $SourceSnapshot
        payload = [ordered]@{
            algorithm = $payload.algorithm
            fingerprint = $payload.fingerprint
            files = @($payload.files)
            executable = Get-TicketboxFileEvidence $DistDir (Join-Path $DistDir "ticketbox-manager.exe")
        }
    }
    $manifestPath = Join-Path $DistDir $script:TicketboxManagerBuildManifestName
    Write-TicketboxJsonFile $manifestPath $manifest
    return $manifestPath
}

function Assert-TicketboxManagerBuildManifest([string]$RepoRoot, [string]$DistDir) {
    $manifestPath = Join-Path $DistDir $script:TicketboxManagerBuildManifestName
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Frozen Desktop Manager lacks build provenance; rebuild it before packaging."
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "Frozen Desktop Manager build provenance is not valid JSON: $manifestPath"
    }
    if (
        $manifest.schema_version -ne $script:TicketboxManagerBuildManifestSchema -or
        $manifest.artifact_type -cne "ticketbox-frozen-desktop-manager" -or
        $manifest.version -cne (Get-TicketboxManagerVersion $RepoRoot)
    ) {
        throw "Frozen Desktop Manager provenance schema, artifact type, or version is stale."
    }
    Assert-TicketboxManagerToolchainEvidence $RepoRoot $manifest.toolchain
    try {
        Assert-TicketboxFileSetSnapshot `
            "Frozen Desktop Manager source" `
            $manifest.source `
            (Get-TicketboxManagerSourceSnapshot $RepoRoot)
    }
    catch {
        throw "Frozen Desktop Manager source evidence is stale; rebuild before packaging. $($_.Exception.Message)"
    }
    try {
        Assert-TicketboxFileSetSnapshot `
            "Frozen Desktop Manager payload" `
            $manifest.payload `
            (Get-TicketboxManagerPayloadSnapshot $DistDir)
    }
    catch {
        throw "Frozen Desktop Manager payload evidence is stale or modified. $($_.Exception.Message)"
    }
    $executable = Get-TicketboxFileEvidence $DistDir (Join-Path $DistDir "ticketbox-manager.exe")
    Assert-TicketboxStructuredEvidence "Frozen Desktop Manager executable" $manifest.payload.executable $executable
    return $manifest
}
