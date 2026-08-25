#Requires -Version 5.1
<#
vNext Windows 安装器构建脚本（唯一授权入口）。

模式：
  （默认）        构建 TicketboxLifecycle.exe + 编译 ticketbox.iss + 发布 publish unit
  -VerifyOnly     校验已发布 publish unit 的字节身份（-ExpectedInstallerSha256 必填，
                  可用 -VerifyPublishDirectory 指向下载副本）

前置：frozen backend（scripts\build_backend_exe.ps1）、frozen manager
（desktop\scripts\build_manager_exe.ps1）、PG bundle 与 shawl vendor
（packaging\prepare_windows_installer_vendor.ps1）、pinned Inno Setup
（packaging\prepare_windows_build_toolchain.ps1 -Component Inno）先行完成。
#>
param(
    [string]$InstallerHashOutputFile = "",
    [switch]$VerifyOnly,
    [string]$ExpectedInstallerSha256 = "",
    [string]$VerifyPublishDirectory = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WindowsRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $WindowsRoot "..\..")).Path
$BackendRoot = Join-Path $RepoRoot "backend"
$DesktopRoot = Join-Path $RepoRoot "desktop"

. (Join-Path $BackendRoot "scripts\windows_build_provenance.ps1")
. (Join-Path $DesktopRoot "scripts\windows_manager_build_provenance.ps1")

$IssPath = Join-Path $WindowsRoot "installer\ticketbox.iss"
$PayloadDir = Join-Path $WindowsRoot "payload"
$Version = Get-TicketboxBackendVersion $BackendRoot
$PublishRoot = Join-Path $BackendRoot "dist\installer"
$PublishDirName = "Ticketbox-Setup-$Version"
$InstallerFileName = "Ticketbox-Setup-$Version.exe"

function Write-InstallerBuildProvenance {
    param(
        [Parameter(Mandatory = $true)][object]$BuildInputs,
        [Parameter(Mandatory = $true)][object]$Recipe,
        [Parameter(Mandatory = $true)][object]$Git,
        [AllowNull()][object]$Compiler,
        [AllowEmptyCollection()][string[]]$CompilerDefines,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $compilerRecord = [ordered]@{ included = ($null -ne $Compiler) }
    if ($null -ne $Compiler) {
        $compilerRecord.product_name = [string]$Compiler.product_name
        $compilerRecord.product_version = [string]$Compiler.product_version
        $compilerRecord.file_version = [string]$Compiler.file_version
        $compilerRecord.engine_version = [string]$Compiler.engine_version
        $compilerRecord.version_policy = $Compiler.version_policy
        $compilerRecord.executable = $Compiler.executable
    }
    $manifest = [ordered]@{
        schema_version = 3
        artifact_type = "ticketbox-windows-installer-inputs"
        compiler_defines = @(Get-TicketboxNormalizedCompilerDefines $CompilerDefines)
        recipe = $Recipe
        git = $Git
        compiler = $compilerRecord
        backend = $BuildInputs.backend
        manager = $BuildInputs.manager
        postgresql = $BuildInputs.postgresql
        shawl = $BuildInputs.shawl
    }
    Write-TicketboxJsonFile $Path $manifest
    return $manifest
}

function Assert-InstallerPublishUnitBytes([string]$PublishDirectory, [string]$ExpectedSha256) {
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "VerifyOnly 需要 64 位十六进制 -ExpectedInstallerSha256。"
    }
    if (-not (Test-Path -LiteralPath $PublishDirectory -PathType Container)) {
        throw "安装器 publish unit 目录缺失：$PublishDirectory"
    }
    $exePath = Join-Path $PublishDirectory $InstallerFileName
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "安装器 publish unit 缺少 $InstallerFileName：$PublishDirectory"
    }
    $manifestPath = Join-Path $PublishDirectory "BUILD_PROVENANCE.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "安装器 publish unit 缺少 BUILD_PROVENANCE.json：$PublishDirectory"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($manifest.schema_version -ne 3 -or $manifest.artifact_type -cne "ticketbox-windows-installer-inputs") {
        throw "安装器 publish unit 的 provenance schema/artifact_type 不受支持。"
    }
    $actual = Get-TicketboxFileSha256 $exePath
    if ($actual -cne $ExpectedSha256.ToLowerInvariant()) {
        throw "安装器字节身份不一致：expected=$($ExpectedSha256.ToLowerInvariant()) actual=$actual"
    }
    return $actual
}

function Get-TicketboxInstallerShipmentPaths([string]$Root) {
    $directories = @(
        (Join-Path $Root "backend\dist\ticketbox-backend"),
        (Join-Path $Root "desktop\dist\ticketbox-manager"),
        (Join-Path $Root "backend\packaging\vendor\pg")
    )
    $paths = @()
    foreach ($directory in $directories) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            throw "安装器 shipment 输入目录缺失：$directory"
        }
        Assert-TicketboxNoReparsePath -Path $directory -AllowedRoot $Root -InspectTree | Out-Null
        $paths += @(
            Get-ChildItem -LiteralPath $directory -Recurse -File -Force |
                ForEach-Object { $_.FullName }
        )
    }
    $paths += @(
        (Join-Path $Root "backend\packaging\vendor\vc-runtime\vc_redist.x64.exe"),
        (Join-Path $Root "backend\packaging\vendor\shawl\shawl.exe")
    )
    return @(Get-TicketboxOrdinalSortedPaths $paths)
}

if ($VerifyOnly) {
    $verifyDirectory = if ($VerifyPublishDirectory) {
        $VerifyPublishDirectory
    }
    else {
        Join-Path $PublishRoot $PublishDirName
    }
    $verified = Assert-InstallerPublishUnitBytes $verifyDirectory $ExpectedInstallerSha256
    Write-Host "安装器 publish unit 字节身份校验通过：$verified"
    exit 0
}

$BuildLock = $null
$RecipeLocks = $null
$ShipmentLocks = $null
$CompilerLocks = $null
$InputSnapshotRoot = Join-Path $BackendRoot ("build\.ticketbox-installer-inputs-{0}" -f $PID)
$PrimaryFailure = $null
$CleanupFailures = @()
try {
    $BuildLock = Enter-TicketboxWindowsBuildLock $BackendRoot
    $git = Get-TicketboxGitProvenance $BackendRoot
    if ([bool]$git.dirty) {
        throw "immutable Setup.exe 只能从 clean exact HEAD 构建。"
    }
    Assert-TicketboxNoReparsePath -Path $InputSnapshotRoot -AllowedRoot $BackendRoot | Out-Null
    if (Test-Path -LiteralPath $InputSnapshotRoot) {
        Remove-Item -LiteralPath $InputSnapshotRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $InputSnapshotRoot | Out-Null

# ===== 只读源预检 =====
& (Join-Path $ScriptDir "check_source_inputs.ps1") | Out-Null

# ===== 锁定并复制唯一构建输入快照 =====
$recipe = Get-TicketboxInstallerRecipeSnapshot $BackendRoot
try {
    $RecipeLocks = Enter-TicketboxFileSetReadLocks -Root $RepoRoot -Snapshot $recipe
    Copy-TicketboxFileSetSnapshot `
        -SourceRoot $RepoRoot `
        -DestinationRoot $InputSnapshotRoot `
        -Snapshot $recipe | Out-Null
}
finally {
    Exit-TicketboxFileSetReadLocks $RecipeLocks
    $RecipeLocks = $null
}

$shipmentPaths = Get-TicketboxInstallerShipmentPaths $RepoRoot
$shipment = Get-TicketboxFileSetSnapshot $RepoRoot $shipmentPaths
try {
    $ShipmentLocks = Enter-TicketboxFileSetReadLocks -Root $RepoRoot -Snapshot $shipment
    Assert-TicketboxFileSetSnapshot `
        "已锁定 installer shipment" `
        $shipment `
        (Get-TicketboxFileSetSnapshot $RepoRoot (Get-TicketboxInstallerShipmentPaths $RepoRoot))
    Copy-TicketboxFileSetSnapshot `
        -SourceRoot $RepoRoot `
        -DestinationRoot $InputSnapshotRoot `
        -Snapshot $shipment | Out-Null
}
finally {
    Exit-TicketboxFileSetReadLocks $ShipmentLocks
    $ShipmentLocks = $null
}

$StagedBackendRoot = Join-Path $InputSnapshotRoot "backend"
$StagedDesktopRoot = Join-Path $InputSnapshotRoot "desktop"
$StagedWindowsRoot = Join-Path $InputSnapshotRoot "distribution\windows"
$StagedScriptDir = Join-Path $StagedWindowsRoot "build"
$StagedPayloadDir = Join-Path $StagedWindowsRoot "payload"
$StagedIssPath = Join-Path $StagedWindowsRoot "installer\ticketbox.iss"

# ===== 输入 provenance（fail-closed）=====
$backendDist = Join-Path $StagedBackendRoot "dist\ticketbox-backend"
$backendManifest = Assert-TicketboxBackendBuildManifest $BackendRoot $backendDist
$managerDist = Join-Path $StagedDesktopRoot "dist\ticketbox-manager"
$managerManifest = Assert-TicketboxManagerBuildManifest $RepoRoot $managerDist

$pgDir = Join-Path $StagedBackendRoot "packaging\vendor\pg"
$pgManifest = Read-TicketboxPgBundleManifest (Join-Path $pgDir "BUNDLE_MANIFEST.txt")

$toolchainConfigPath = Join-Path $StagedBackendRoot "packaging\windows-build-toolchain.json"
$toolchainConfig = Get-Content -LiteralPath $toolchainConfigPath -Encoding UTF8 -Raw | ConvertFrom-Json
$shawlSource = $toolchainConfig.installer_vendor_sources.shawl
$shawlExe = Join-Path $StagedBackendRoot "packaging\vendor\shawl\shawl.exe"
if (-not (Test-Path -LiteralPath $shawlExe -PathType Leaf)) {
    throw "缺少 shawl vendor 载荷：$shawlExe（先运行 prepare_windows_installer_vendor.ps1）"
}
$shawlSha = Get-TicketboxFileSha256 $shawlExe
if ($shawlSha -cne ([string]$shawlSource.executable_sha256).ToLowerInvariant()) {
    throw "shawl.exe 与 pinned executable_sha256 不一致。"
}

$BuildInputs = [ordered]@{
    backend = [ordered]@{
        version = [string]$backendManifest.backend_version
        fingerprint = [string]$backendManifest.payload.fingerprint
    }
    manager = [ordered]@{
        version = [string]$managerManifest.version
        fingerprint = [string]$managerManifest.payload.fingerprint
    }
    postgresql = [ordered]@{
        version = [string]$pgManifest["pg_version"]
        fingerprint = [string]$pgManifest["payload_fingerprint"]
    }
    shawl = [ordered]@{
        version = [string]$shawlSource.version
        fingerprint = $shawlSha
    }
}

# ===== TicketboxLifecycle.exe（pinned lock 的 PyInstaller onefile）=====
$pythonCommand = Get-Command python -ErrorAction Stop
$pythonVersionText = (& $pythonCommand.Source --version 2>&1) -join " "
$expectedPythonPrefix = "Python " + (([string]$toolchainConfig.python_version) -replace '^(\d+\.\d+)\..*$', '$1')
if (-not $pythonVersionText.StartsWith($expectedPythonPrefix)) {
    throw "lifecycle 构建需要 $expectedPythonPrefix.x，当前：$pythonVersionText"
}
$lifecycleVenv = Join-Path $BackendRoot ("build\.ticketbox-lifecycle-venv-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
$lifecycleWork = Join-Path $BackendRoot ("build\.ticketbox-lifecycle-work-{0}" -f $PID)
$lifecycleExe = Join-Path $StagedPayloadDir "TicketboxLifecycle.exe"
try {
    & $pythonCommand.Source -m venv $lifecycleVenv
    if ($LASTEXITCODE -ne 0) { throw "lifecycle venv 创建失败（exit=$LASTEXITCODE）。" }
    $venvPython = Join-Path $lifecycleVenv "Scripts\python.exe"
    & $venvPython -m pip install --quiet --require-hashes -r (Join-Path $StagedBackendRoot "requirements-build.lock")
    if ($LASTEXITCODE -ne 0) { throw "lifecycle 构建依赖安装失败（exit=$LASTEXITCODE）。" }
    if (Test-Path -LiteralPath $lifecycleExe) {
        Remove-Item -LiteralPath $lifecycleExe -Force
    }
    & (Join-Path $lifecycleVenv "Scripts\pyinstaller.exe") `
        --noconfirm `
        --distpath $StagedPayloadDir `
        --workpath $lifecycleWork `
        (Join-Path $StagedScriptDir "ticketbox-lifecycle.spec")
    if ($LASTEXITCODE -ne 0) { throw "TicketboxLifecycle.exe 冻结失败（exit=$LASTEXITCODE）。" }
    if (-not (Test-Path -LiteralPath $lifecycleExe -PathType Leaf)) {
        throw "PyInstaller 未产出 $lifecycleExe。"
    }
}
finally {
    Remove-Item -LiteralPath $lifecycleVenv -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $lifecycleWork -Recurse -Force -ErrorAction SilentlyContinue
}

# ===== validate release-manifest against frozen generation program head =====
$generationProgramPath = Join-Path $backendDist "DATABASE_GENERATION_PROGRAM.json"
if (-not (Test-Path -LiteralPath $generationProgramPath -PathType Leaf)) {
    throw "frozen backend lacks DATABASE_GENERATION_PROGRAM.json"
}
$generationProgram = Get-Content -LiteralPath $generationProgramPath -Encoding UTF8 -Raw | ConvertFrom-Json
$schemaHead = [string]$generationProgram.target_revision
if ([string]::IsNullOrWhiteSpace($schemaHead) -or $schemaHead -eq "99991231_9999") {
    throw "frozen generation program target_revision is unbound"
}
$manifestTemplatePath = Join-Path $StagedPayloadDir "release-manifest.json"
$manifestTemplate = Get-Content -LiteralPath $manifestTemplatePath -Encoding UTF8 -Raw | ConvertFrom-Json
if (
    [string]$manifestTemplate.schema -cne "ticketbox-release-manifest-v1" -or
    [string]$manifestTemplate.release_id -cne $Version -or
    [string]$manifestTemplate.product_version -cne $Version -or
    [string]$manifestTemplate.max_schema_revision -cne $schemaHead -or
    [string]$manifestTemplate.signing_state -cne "release-bound" -or
    [string]::IsNullOrWhiteSpace([string]$manifestTemplate.min_schema_revision) -or
    [string]::IsNullOrWhiteSpace([string]$manifestTemplate.min_semantic_revision) -or
    -not (@($manifestTemplate.lifecycle_compatibility) -ccontains "ticketbox-lifecycle-request-v1")
) {
    throw "release-manifest.json 未与 exact release/generation program 预先冻结。"
}
Write-Host "release-manifest validated max_schema_revision=$schemaHead"

# ===== pinned ISCC 编译 =====
$innoSource = $toolchainConfig.build_tool_sources.inno_setup
$IsccPath = Join-Path $BackendRoot ("build\windows-toolchain\inno\" + [string]$innoSource.compiler_relative_path)
$isccActualSha = Get-TicketboxFileSha256 $IsccPath
if ($isccActualSha -cne ([string]$innoSource.compiler_sha256).ToLowerInvariant()) {
    throw "ISCC identity 与固定官方归档合同不一致：$IsccPath"
}
$isccProvenance = Get-TicketboxIsccProvenance $IsccPath
$releaseConfigPath = Join-Path $StagedBackendRoot "packaging\windows-release-config.json"
$releaseConfig = Get-Content -LiteralPath $releaseConfigPath -Encoding UTF8 -Raw | ConvertFrom-Json
$isccPolicy = Assert-TicketboxVendorVersionAllowed $releaseConfig "iscc" $isccProvenance.engine_version
$compiler = [pscustomobject]@{
    product_name = $isccProvenance.product_name
    product_version = $isccProvenance.product_version
    file_version = $isccProvenance.file_version
    engine_version = $isccProvenance.engine_version
    version_policy = $isccPolicy
    executable = $isccProvenance.executable
}

$defines = @(
    "/DAppVersion=$Version",
    "/DReleaseId=$Version"
)
$stagingDir = Join-Path $BackendRoot ("build\.ticketbox-installer-staging-{0}" -f $PID)
try {
    if (Test-Path -LiteralPath $stagingDir) {
        Remove-Item -LiteralPath $stagingDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $stagingDir | Out-Null

    $compilerRoot = Split-Path -Parent $IsccPath
    $compilerSnapshot = Get-TicketboxFileSetSnapshot $compilerRoot @($IsccPath)
    try {
        $CompilerLocks = Enter-TicketboxFileSetReadLocks `
            -Root $compilerRoot `
            -Snapshot $compilerSnapshot
        & $IsccPath "/O$stagingDir" "/FTicketbox-Setup-$Version" @defines $StagedIssPath
        if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败（exit=$LASTEXITCODE）。" }
    }
    finally {
        Exit-TicketboxFileSetReadLocks $CompilerLocks
        $CompilerLocks = $null
    }
    $stagedInstaller = Join-Path $stagingDir $InstallerFileName
    if (-not (Test-Path -LiteralPath $stagedInstaller -PathType Leaf)) {
        throw "本轮 ISCC staging 安装包输出缺失：$stagedInstaller"
    }

    # ===== publish unit（目录 = 原子发布单位）=====
    $publishDirectory = Join-Path $PublishRoot $PublishDirName
    if (Test-Path -LiteralPath $publishDirectory) {
        Remove-Item -LiteralPath $publishDirectory -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $publishDirectory | Out-Null
    Copy-Item -LiteralPath $stagedInstaller -Destination (Join-Path $publishDirectory $InstallerFileName)

    $manifestPath = Join-Path $publishDirectory "BUILD_PROVENANCE.json"
    Write-InstallerBuildProvenance $BuildInputs $recipe $git $compiler $defines $manifestPath | Out-Null
    Assert-TicketboxInstallerBuildProvenance $BackendRoot $manifestPath $compiler $BuildInputs $defines | Out-Null

    $installerSha = Get-TicketboxFileSha256 (Join-Path $publishDirectory $InstallerFileName)
    Write-Host "安装器已发布：$publishDirectory"
    Write-Host "installer_sha256=$installerSha"
    if ($InstallerHashOutputFile) {
        [System.IO.File]::AppendAllText(
            $InstallerHashOutputFile,
            "installer_sha256=$installerSha" + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
        )
    }
}
finally {
    Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
}
}
catch {
    $PrimaryFailure = $_
}
finally {
    foreach ($entry in @(
        [pscustomobject]@{ Name = "compiler input locks"; Value = $CompilerLocks },
        [pscustomobject]@{ Name = "shipment input locks"; Value = $ShipmentLocks },
        [pscustomobject]@{ Name = "recipe input locks"; Value = $RecipeLocks }
    )) {
        try { Exit-TicketboxFileSetReadLocks $entry.Value }
        catch { $CleanupFailures += "$($entry.Name): $($_.Exception.Message)" }
    }
    try {
        if (Test-Path -LiteralPath $InputSnapshotRoot) {
            Remove-Item -LiteralPath $InputSnapshotRoot -Recurse -Force
        }
    }
    catch { $CleanupFailures += "installer input snapshot: $($_.Exception.Message)" }
    try { Exit-TicketboxWindowsBuildLock $BuildLock }
    catch { $CleanupFailures += "Windows build lock: $($_.Exception.Message)" }
}

if ($null -ne $PrimaryFailure) {
    foreach ($failure in $CleanupFailures) { Write-Warning "cleanup failure after primary failure: $failure" }
    throw $PrimaryFailure
}
if ($CleanupFailures.Count -gt 0) {
    throw "安装器构建完成路径存在 cleanup failure：$($CleanupFailures -join '; ')"
}
