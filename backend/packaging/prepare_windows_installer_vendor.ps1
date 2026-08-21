#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$ToolchainConfigPath = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
$BuildProvenanceScript = Join-Path $BackendRoot "scripts\windows_build_provenance.ps1"
if (-not (Test-Path -LiteralPath $BuildProvenanceScript -PathType Leaf)) {
    throw "缺少 Windows build provenance helper：$BuildProvenanceScript"
}
. $BuildProvenanceScript
$vendorRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir "vendor"))
$archiveRoot = Join-Path $vendorRoot "archives"
$processStagingRoot = Join-Path $vendorRoot (".vendor-staging-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
if ($ToolchainConfigPath.Trim().Length -eq 0) {
    $ToolchainConfigPath = Join-Path $ScriptDir "windows-build-toolchain.json"
}
if (-not (Test-Path -LiteralPath $ToolchainConfigPath -PathType Leaf)) {
    throw "缺少 Windows 构建工具链合同：$ToolchainConfigPath"
}
try {
    $toolchain = Get-Content -LiteralPath $ToolchainConfigPath -Encoding UTF8 -Raw | ConvertFrom-Json
    $postgresSource = $toolchain.installer_vendor_sources.postgresql
    $shawlSource = $toolchain.installer_vendor_sources.shawl
    $visualCppRuntimeSource = $toolchain.installer_vendor_sources.visual_cpp_runtime
}
catch {
    throw "Windows 构建工具链合同缺少安装器 vendor 来源。"
}
$shawlLegal = $shawlSource.legal
if (
    [string]$shawlLegal.archive_name -cne "shawl-v$($shawlSource.version)-legal.zip" -or
    [string]$shawlLegal.url -cne (
        "https://github.com/mtkennerly/shawl/releases/download/v{0}/{1}" -f `
            $shawlSource.version, $shawlLegal.archive_name
    ) -or
    [string]$shawlLegal.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
    [string]$shawlLegal.notice_name -cne "shawl-v$($shawlSource.version)-legal.txt" -or
    [string]$shawlLegal.notice_sha256 -notmatch '^[0-9a-fA-F]{64}$'
) {
    throw "Windows 构建工具链合同中的 Shawl legal 来源无效。"
}
$shawlLegalSource = [pscustomobject]@{
    version = [string]$shawlSource.version
    archive_name = [string]$shawlLegal.archive_name
    url = [string]$shawlLegal.url
    sha256 = [string]$shawlLegal.sha256
}

function Assert-TicketboxVendorSource([object]$Source, [string]$Label) {
    if (
        [string]$Source.version -notmatch '^\d+(?:\.\d+){1,3}(?:-\d+)?$' -or
        [string]$Source.archive_name -notmatch '^[A-Za-z0-9._-]+\.(?:zip|exe)$' -or
        [string]$Source.url -notmatch '^https://' -or
        [string]$Source.sha256 -notmatch '^[0-9a-fA-F]{64}$'
    ) {
        throw "$Label vendor 来源合同无效。"
    }
}

function Assert-TicketboxVisualCppRuntimeIdentity(
    [string]$Path,
    [object]$Source,
    [string]$Label
) {
    Assert-TicketboxVendorExecutableHash `
        $Path `
        ([string]$Source.sha256) `
        $Label
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $versionInfo = $item.VersionInfo
    if (
        [string]$Source.architecture -cne "x64" -or
        [string]$versionInfo.FileVersion -cne [string]$Source.file_version -or
        [string]$versionInfo.ProductVersion -cne [string]$Source.product_version -or
        [string]$versionInfo.OriginalFilename -cne [string]$Source.original_filename -or
        [string]$versionInfo.CompanyName -cne [string]$Source.company_name
    ) {
        throw "$Label 版本资源与工具链合同不一致。"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if (
        $signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        $null -eq $signature.SignerCertificate -or
        [string]$signature.SignerCertificate.Subject -cne [string]$Source.signer_subject -or
        [string]$signature.SignerCertificate.Thumbprint -ine [string]$Source.signer_thumbprint
    ) {
        throw "$Label Authenticode 身份与固定 Microsoft signer 合同不一致。"
    }
}

function Assert-TicketboxVendorExecutableHash(
    [string]$Path,
    [string]$ExpectedSha256,
    [string]$Label
) {
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "$Label executable hash pin 无效。"
    }
    $actualHash = Get-TicketboxPathSha256 $Path
    if ($actualHash -cne $ExpectedSha256.ToLowerInvariant()) {
        throw "$Label executable hash 与工具链合同不一致。"
    }
}

function Assert-TicketboxNoReparseAncestors([string]$Path, [string]$Label) {
    $cursor = [System.IO.Path]::GetFullPath($Path)
    while ($true) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label 路径含 reparse point：$cursor"
            }
        }
        $parent = [System.IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
}

function Assert-TicketboxNoReparseTree([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Assert-TicketboxNoReparseAncestors $Path $Label
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push([System.IO.Path]::GetFullPath($Path))
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        foreach ($item in @(Get-ChildItem -LiteralPath $current -Force -ErrorAction Stop)) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label 目录树含 reparse point：$($item.FullName)"
            }
            if ($item.PSIsContainer) { $pending.Push($item.FullName) }
        }
    }
}

function Remove-TicketboxVendorPath([string]$Path) {
    $canonical = [System.IO.Path]::GetFullPath($Path)
    $vendorPrefix = $vendorRoot.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    if (-not $canonical.StartsWith($vendorPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理 Windows installer vendor root 之外的路径：$canonical"
    }
    Assert-TicketboxNoReparseAncestors $vendorRoot "Windows installer vendor root"
    if (Test-Path -LiteralPath $canonical) {
        Assert-TicketboxNoReparseTree $canonical "Windows installer vendor cleanup"
        Remove-Item -LiteralPath $canonical -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $canonical) {
        throw "Windows installer vendor 路径清理后仍然存在：$canonical"
    }
}

function Get-TicketboxStreamSha256([System.IO.Stream]$Stream) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Stream.Position = 0
        $hash = $sha256.ComputeHash($Stream)
        $Stream.Position = 0
        return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-TicketboxPathSha256([string]$Path) {
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try { return Get-TicketboxStreamSha256 $stream }
    finally { $stream.Dispose() }
}

function New-TicketboxVerifiedArchiveLease([string]$ArchivePath, [string]$ExpectedSha256, [string]$Label) {
    Assert-TicketboxNoReparseAncestors $ArchivePath "$Label cache"
    Assert-TicketboxNoReparseAncestors $processStagingRoot "$Label staging"
    $leaseRoot = Join-Path $processStagingRoot ("archive-{0}" -f [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $leaseRoot -ErrorAction Stop | Out-Null
    $privatePath = Join-Path $leaseRoot ([System.IO.Path]::GetFileName($ArchivePath))
    $sourceHandle = $null
    $destinationHandle = $null
    $readHandle = $null
    try {
        $sourceHandle = [System.IO.File]::Open(
            $ArchivePath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        $destinationHandle = [System.IO.File]::Open(
            $privatePath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $sourceHandle.CopyTo($destinationHandle)
        $destinationHandle.Flush($true)
        $destinationHandle.Dispose()
        $destinationHandle = $null
        $sourceHandle.Dispose()
        $sourceHandle = $null
        Assert-TicketboxNoReparseAncestors $privatePath "$Label private staging"
        $readHandle = [System.IO.File]::Open(
            $privatePath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        $actualHash = Get-TicketboxStreamSha256 $readHandle
        if ($actualHash -cne $ExpectedSha256.ToLowerInvariant()) {
            throw "$Label 私有 staging SHA-256 不匹配。"
        }
        return [pscustomobject]@{ Path = $privatePath; Handle = $readHandle }
    }
    catch {
        if ($null -ne $readHandle) { $readHandle.Dispose() }
        throw
    }
    finally {
        if ($null -ne $destinationHandle) { $destinationHandle.Dispose() }
        if ($null -ne $sourceHandle) { $sourceHandle.Dispose() }
    }
}

function Assert-TicketboxSafeZipEntry(
    [System.IO.Compression.ZipArchiveEntry]$Entry,
    [string]$Destination,
    [System.Collections.Generic.HashSet[string]]$Seen
) {
    $entryName = [string]$Entry.FullName
    $normalized = $entryName.Replace("\", "/").TrimEnd("/")
    $segments = @($normalized.Split("/"))
    if (
        $normalized.Length -eq 0 -or
        [System.IO.Path]::IsPathRooted($normalized.Replace("/", "\")) -or
        $normalized.Contains(":") -or
        @($segments | Where-Object { $_.Length -eq 0 -or $_ -eq "." -or $_ -eq ".." }).Count -gt 0
    ) {
        throw "Shawl ZIP 含不安全 entry 路径：$entryName"
    }
    $unixType = (($Entry.ExternalAttributes -shr 16) -band 0xF000)
    $windowsAttributes = ($Entry.ExternalAttributes -band 0xFFFF)
    if (
        $unixType -notin @(0, 0x4000, 0x8000) -or
        ($windowsAttributes -band [int][System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Shawl ZIP 含 symlink/reparse entry：$entryName"
    }
    $destinationRoot = [System.IO.Path]::GetFullPath($Destination)
    $destinationPrefix = $destinationRoot.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    $target = [System.IO.Path]::GetFullPath((Join-Path $destinationRoot $normalized.Replace("/", "\")))
    if (-not $target.StartsWith($destinationPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Shawl ZIP entry 逃逸 staging：$entryName"
    }
    if (-not $Seen.Add($target)) {
        throw "Shawl ZIP 含大小写冲突或重复 entry：$entryName"
    }
    return $target
}

function Expand-TicketboxVerifiedShawlZip([object]$Lease, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
    Assert-TicketboxNoReparseAncestors $Destination "Shawl staging"
    New-Item -ItemType Directory -Path $Destination -ErrorAction Stop | Out-Null
    Assert-TicketboxNoReparseAncestors $Destination "Shawl staging"
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $archive = New-Object System.IO.Compression.ZipArchive -ArgumentList @(
        $Lease.Handle,
        [System.IO.Compression.ZipArchiveMode]::Read,
        $true
    )
    try {
        foreach ($entry in $archive.Entries) {
            $target = Assert-TicketboxSafeZipEntry $entry $Destination $seen
            if ($entry.FullName.EndsWith("/", [System.StringComparison]::Ordinal) -or
                $entry.FullName.EndsWith("\", [System.StringComparison]::Ordinal)) {
                New-Item -ItemType Directory -Force -Path $target | Out-Null
                continue
            }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            $input = $entry.Open()
            $output = [System.IO.File]::Open(
                $target,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try { $input.CopyTo($output) }
            finally {
                $output.Dispose()
                $input.Dispose()
            }
        }
    }
    finally {
        $archive.Dispose()
    }
    Assert-TicketboxNoReparseTree $Destination "Shawl extracted payload"
}

function Get-TicketboxVerifiedVendorArchive([object]$Source, [string]$ArchiveDirectory) {
    Assert-TicketboxVendorSource $Source "Windows installer"
    Assert-TicketboxNoReparseAncestors $ArchiveDirectory "Windows installer archive cache"
    New-Item -ItemType Directory -Force -Path $ArchiveDirectory | Out-Null
    Assert-TicketboxNoReparseAncestors $ArchiveDirectory "Windows installer archive cache"
    $archivePath = Join-Path $ArchiveDirectory ([string]$Source.archive_name)
    $expectedHash = ([string]$Source.sha256).ToLowerInvariant()
    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        $currentHash = Get-TicketboxPathSha256 $archivePath
        if ($currentHash -eq $expectedHash) { return $archivePath }
        Remove-TicketboxVendorPath $archivePath
    }
    $partialPath = "$archivePath.part-$PID-$([Guid]::NewGuid().ToString('N'))"
    $previousProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri ([string]$Source.url) -OutFile $partialPath -UseBasicParsing
        $downloadHash = Get-TicketboxPathSha256 $partialPath
        if ($downloadHash -cne $expectedHash) {
            throw "vendor 下载 hash 不匹配：$($Source.archive_name)"
        }
        Move-Item -LiteralPath $partialPath -Destination $archivePath -Force
        $publishedHash = Get-TicketboxPathSha256 $archivePath
        if ($publishedHash -cne $expectedHash) {
            throw "vendor cache 发布后 hash 不匹配：$($Source.archive_name)"
        }
    }
    finally {
        $ProgressPreference = $previousProgress
        if (Test-Path -LiteralPath $partialPath) { Remove-TicketboxVendorPath $partialPath }
    }
    return $archivePath
}

$shawlStaging = Join-Path $processStagingRoot "shawl-extracted"
$shawlLegalStaging = Join-Path $processStagingRoot "shawl-legal-extracted"
$shawlOutput = Join-Path $vendorRoot "shawl"
$shawlArchiveLease = $null
$shawlLegalArchiveLease = $null
$shawlExecutableLock = $null
$shawlLegalNoticeLock = $null
$visualCppRuntimeOutput = Join-Path $vendorRoot "vc-runtime"
$visualCppRuntimeLease = $null
$BuildLock = $null
$PrimaryFailure = $null
$CleanupFailures = New-Object System.Collections.Generic.List[string]
Assert-TicketboxNoReparseAncestors $vendorRoot "Windows installer vendor root"
try {
    $BuildLock = Enter-TicketboxWindowsBuildLock $BackendRoot
    New-Item -ItemType Directory -Force -Path $vendorRoot, $processStagingRoot | Out-Null
    Assert-TicketboxNoReparseAncestors $processStagingRoot "Windows installer vendor staging"
    $postgresArchive = Get-TicketboxVerifiedVendorArchive $postgresSource $archiveRoot
    $pgBundleScript = Join-Path $ScriptDir "build_pg_bundle.ps1"
    & $pgBundleScript `
        -Zip $postgresArchive `
        -OutDir (Join-Path $vendorRoot "pg") `
        -ToolchainConfigPath $ToolchainConfigPath `
        -Force:$Force

    $shawlArchive = Get-TicketboxVerifiedVendorArchive $shawlSource $archiveRoot
    $shawlArchiveLease = New-TicketboxVerifiedArchiveLease `
        $shawlArchive ([string]$shawlSource.sha256) "Shawl archive"
    Expand-TicketboxVerifiedShawlZip $shawlArchiveLease $shawlStaging
    $shawlArchiveLease.Handle.Dispose()
    $shawlArchiveLease = $null
    $candidates = @(Get-ChildItem -LiteralPath $shawlStaging -Recurse -File -Filter "shawl.exe")
    if ($candidates.Count -ne 1) {
        throw "Shawl archive 必须且只能包含一个 shawl.exe。"
    }
    $shawlExecutableLock = [System.IO.File]::Open(
        $candidates[0].FullName,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $executableHash = Get-TicketboxStreamSha256 $shawlExecutableLock
    if ($executableHash -cne ([string]$shawlSource.executable_sha256).ToLowerInvariant()) {
        throw "Shawl executable hash 与工具链合同不一致。"
    }
    $versionOutput = @(& $candidates[0].FullName --version 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Shawl --version 探针失败（exit=$LASTEXITCODE）。"
    }
    $versionMatch = [regex]::Match(
        (($versionOutput | ForEach-Object { $_.ToString() }) -join "`n"),
        '(?m)^shawl\s+([0-9]+(?:\.[0-9]+){1,3})\s*$'
    )
    if (-not $versionMatch.Success -or $versionMatch.Groups[1].Value -cne [string]$shawlSource.version) {
        throw "Shawl 可执行版本与工具链合同不一致。"
    }
    $shawlLegalArchive = Get-TicketboxVerifiedVendorArchive `
        $shawlLegalSource `
        $archiveRoot
    $shawlLegalArchiveLease = New-TicketboxVerifiedArchiveLease `
        $shawlLegalArchive ([string]$shawlLegal.sha256) "Shawl legal archive"
    Expand-TicketboxVerifiedShawlZip $shawlLegalArchiveLease $shawlLegalStaging
    $shawlLegalArchiveLease.Handle.Dispose()
    $shawlLegalArchiveLease = $null
    $legalCandidates = @(Get-ChildItem -LiteralPath $shawlLegalStaging -Recurse -File)
    if (
        $legalCandidates.Count -ne 1 -or
        $legalCandidates[0].Name -cne [string]$shawlLegal.notice_name
    ) {
        throw "Shawl legal archive 必须且只能包含固定 legal notice。"
    }
    $shawlLegalNoticeLock = [System.IO.File]::Open(
        $legalCandidates[0].FullName,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $legalNoticeHash = Get-TicketboxStreamSha256 $shawlLegalNoticeLock
    if ($legalNoticeHash -cne ([string]$shawlLegal.notice_sha256).ToLowerInvariant()) {
        throw "Shawl legal notice hash 与工具链合同不一致。"
    }
    if (Test-Path -LiteralPath $shawlOutput) {
        Remove-TicketboxVendorPath $shawlOutput
    }
    New-Item -ItemType Directory -Path $shawlOutput | Out-Null
    $shawlOutputExe = Join-Path $shawlOutput "shawl.exe"
    Copy-Item -LiteralPath $candidates[0].FullName -Destination $shawlOutputExe
    $shawlOutputLegalNotice = Join-Path $shawlOutput ([string]$shawlLegal.notice_name)
    Copy-Item -LiteralPath $legalCandidates[0].FullName -Destination $shawlOutputLegalNotice
    Assert-TicketboxVendorExecutableHash `
        $shawlOutputExe `
        ([string]$shawlSource.executable_sha256) `
        "Published Shawl"
    Assert-TicketboxVendorExecutableHash `
        $shawlOutputLegalNotice `
        ([string]$shawlLegal.notice_sha256) `
        "Published Shawl legal notice"

    $visualCppRuntimeArchive = Get-TicketboxVerifiedVendorArchive `
        $visualCppRuntimeSource `
        $archiveRoot
    $visualCppRuntimeLease = New-TicketboxVerifiedArchiveLease `
        $visualCppRuntimeArchive `
        ([string]$visualCppRuntimeSource.sha256) `
        "Microsoft Visual C++ runtime"
    Assert-TicketboxVisualCppRuntimeIdentity `
        $visualCppRuntimeLease.Path `
        $visualCppRuntimeSource `
        "Microsoft Visual C++ runtime"
    if (Test-Path -LiteralPath $visualCppRuntimeOutput) {
        Remove-TicketboxVendorPath $visualCppRuntimeOutput
    }
    New-Item -ItemType Directory -Path $visualCppRuntimeOutput | Out-Null
    $visualCppRuntimeOutputExe = Join-Path `
        $visualCppRuntimeOutput `
        ([string]$visualCppRuntimeSource.archive_name)
    Copy-Item `
        -LiteralPath $visualCppRuntimeLease.Path `
        -Destination $visualCppRuntimeOutputExe
    Assert-TicketboxVisualCppRuntimeIdentity `
        $visualCppRuntimeOutputExe `
        $visualCppRuntimeSource `
        "Published Microsoft Visual C++ runtime"
}
catch { $PrimaryFailure = $_ }
finally {
    try {
        foreach ($cleanup in @(
            [pscustomobject]@{ Label = "Visual C++ runtime lease"; Action = { if ($null -ne $visualCppRuntimeLease) { $visualCppRuntimeLease.Handle.Dispose() } } },
            [pscustomobject]@{ Label = "Shawl legal notice lock"; Action = { if ($null -ne $shawlLegalNoticeLock) { $shawlLegalNoticeLock.Dispose() } } },
            [pscustomobject]@{ Label = "Shawl legal archive lease"; Action = { if ($null -ne $shawlLegalArchiveLease) { $shawlLegalArchiveLease.Handle.Dispose() } } },
            [pscustomobject]@{ Label = "Shawl executable lock"; Action = { if ($null -ne $shawlExecutableLock) { $shawlExecutableLock.Dispose() } } },
            [pscustomobject]@{ Label = "Shawl archive lease"; Action = { if ($null -ne $shawlArchiveLease) { $shawlArchiveLease.Handle.Dispose() } } },
            [pscustomobject]@{ Label = "vendor staging"; Action = { if (Test-Path -LiteralPath $processStagingRoot) { Remove-TicketboxVendorPath $processStagingRoot } } }
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
        Write-Warning "Vendor cleanup also failed after the primary error: $($CleanupFailures -join '; ')"
    }
    throw $PrimaryFailure
}
if ($CleanupFailures.Count -gt 0) {
    throw "Windows installer vendor cleanup failed: $($CleanupFailures -join '; ')"
}
Write-Host "Windows installer vendor inputs ready: $vendorRoot" -ForegroundColor Green
