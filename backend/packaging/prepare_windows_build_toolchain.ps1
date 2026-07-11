#Requires -Version 5.1
<#
.SYNOPSIS
  Materialize the exact Windows build tools declared by windows-build-toolchain.json.

.DESCRIPTION
  Downloads only pinned HTTPS artifacts, verifies their SHA-256 before parsing or
  executing them, expands into process-private staging directories, validates the
  critical executable payloads, and then publishes a clean local tool directory.
#>
[CmdletBinding()]
param(
    [ValidateSet("Backend", "Inno", "All")][string]$Component = "All",
    [string]$ToolchainRoot = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
$BuildProvenanceScript = Join-Path $BackendRoot "scripts\windows_build_provenance.ps1"
$BackendBuildProvenanceScript = Join-Path $BackendRoot "scripts\windows_backend_build_provenance.ps1"
foreach ($path in @($BuildProvenanceScript, $BackendBuildProvenanceScript)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "缺少 Windows 构建工具链解析脚本：$path"
    }
    . $path
}

if ($ToolchainRoot.Trim().Length -eq 0) {
    $ToolchainRoot = Join-Path $BackendRoot "build\windows-toolchain"
}
$ToolchainRoot = [System.IO.Path]::GetFullPath($ToolchainRoot)
$BuildRoot = [System.IO.Path]::GetFullPath((Join-Path $BackendRoot "build"))
$buildPrefix = $BuildRoot.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
if (-not $ToolchainRoot.StartsWith($buildPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows 构建工具目录必须位于 backend\build 下：$ToolchainRoot"
}
$ArchiveRoot = Join-Path $ToolchainRoot "archives"
$StagingRoot = Join-Path $ToolchainRoot (".staging-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
$toolchain = Read-TicketboxWindowsBuildToolchain $BackendRoot

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

function Remove-TicketboxToolchainPath([string]$Path) {
    $canonical = [System.IO.Path]::GetFullPath($Path)
    $prefix = $ToolchainRoot.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    if (-not $canonical.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理 Windows 构建工具目录之外的路径：$canonical"
    }
    Assert-TicketboxNoReparseAncestors $ToolchainRoot "Windows build root"
    if (Test-Path -LiteralPath $canonical) {
        Assert-TicketboxNoReparseTree $canonical "Windows build cleanup"
        Remove-Item -LiteralPath $canonical -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $canonical) {
        throw "Windows 构建工具路径清理后仍然存在：$canonical"
    }
}

function Assert-TicketboxSha256([string]$Path, [string]$Expected, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label 不存在：$Path"
    }
    $actual = Get-TicketboxPathSha256 $Path
    if ($actual -cne $Expected.ToLowerInvariant()) {
        throw "$Label SHA-256 不匹配：actual=$actual expected=$($Expected.ToLowerInvariant())"
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
    Assert-TicketboxNoReparseAncestors $StagingRoot "$Label staging"
    $leaseRoot = Join-Path $StagingRoot ("archive-{0}" -f [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $leaseRoot -ErrorAction Stop | Out-Null
    Assert-TicketboxNoReparseAncestors $leaseRoot "$Label staging"
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
        $actual = Get-TicketboxStreamSha256 $readHandle
        if ($actual -cne $ExpectedSha256.ToLowerInvariant()) {
            throw "$Label 私有 staging SHA-256 不匹配：actual=$actual expected=$($ExpectedSha256.ToLowerInvariant())"
        }
        return [pscustomobject]@{
            Path = $privatePath
            Handle = $readHandle
        }
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

function Get-TicketboxPinnedArchive([object]$Source) {
    Assert-TicketboxNoReparseAncestors $ArchiveRoot "Windows build archive cache"
    $archivePath = Join-Path $ArchiveRoot ([string]$Source.archive_name)
    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        try {
            Assert-TicketboxSha256 $archivePath ([string]$Source.sha256) "缓存归档"
            return $archivePath
        }
        catch {
            Remove-TicketboxToolchainPath $archivePath
        }
    }

    New-Item -ItemType Directory -Force -Path $ArchiveRoot | Out-Null
    $partialPath = "$archivePath.part-$PID-$([Guid]::NewGuid().ToString('N'))"
    try {
        $previousProtocol = [Net.ServicePointManager]::SecurityProtocol
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest `
                -UseBasicParsing `
                -Uri ([string]$Source.url) `
                -OutFile $partialPath `
                -MaximumRedirection 5
        }
        finally {
            [Net.ServicePointManager]::SecurityProtocol = $previousProtocol
        }
        Assert-TicketboxSha256 $partialPath ([string]$Source.sha256) "下载归档"
        Move-Item -LiteralPath $partialPath -Destination $archivePath -Force
        Assert-TicketboxSha256 $archivePath ([string]$Source.sha256) "发布归档"
        return $archivePath
    }
    finally {
        if (Test-Path -LiteralPath $partialPath) {
            Remove-TicketboxToolchainPath $partialPath
        }
    }
}

function Assert-TicketboxRelativeArchivePath([string]$Value, [string]$Label) {
    $normalized = $Value.Replace("/", "\").TrimEnd("\")
    if (
        $normalized.Length -eq 0 -or
        [System.IO.Path]::IsPathRooted($normalized) -or
        $normalized.Contains(":") -or
        @($normalized.Split("\") | Where-Object { $_ -eq ".." -or $_ -eq "." }).Count -gt 0
    ) {
        throw "$Label 含不安全归档路径：$Value"
    }
    return $normalized
}

function Expand-TicketboxPinnedZip([string]$ArchivePath, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
    Assert-TicketboxNoReparseAncestors $Destination "ZIP staging"
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Assert-TicketboxNoReparseAncestors $Destination "ZIP staging"
    $destinationPrefix = [System.IO.Path]::GetFullPath($Destination).TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $archive.Entries) {
            $relative = Assert-TicketboxRelativeArchivePath $entry.FullName "ZIP entry"
            $unixType = (($entry.ExternalAttributes -shr 16) -band 0xF000)
            $windowsAttributes = ($entry.ExternalAttributes -band 0xFFFF)
            if (
                $unixType -notin @(0, 0x4000, 0x8000) -or
                ($windowsAttributes -band [int][System.IO.FileAttributes]::ReparsePoint) -ne 0
            ) {
                throw "ZIP 归档包含链接、reparse 或特殊 entry，拒绝提取：$($entry.FullName)"
            }
            $target = [System.IO.Path]::GetFullPath((Join-Path $Destination $relative))
            if (-not $target.StartsWith($destinationPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "ZIP entry 逃逸目标目录：$($entry.FullName)"
            }
            if (-not $seen.Add($target)) {
                throw "ZIP 归档包含大小写冲突或重复路径：$($entry.FullName)"
            }
            if ($entry.FullName.EndsWith("/", [System.StringComparison]::Ordinal)) {
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
}

function Expand-TicketboxPinnedTar([string]$ArchivePath, [string]$Destination) {
    $tar = Join-Path ([Environment]::GetFolderPath("System")) "tar.exe"
    if (-not (Test-Path -LiteralPath $tar -PathType Leaf)) {
        throw "当前 Windows 缺少系统 tar.exe，无法展开固定 Python 运行时。"
    }
    $entries = @(& $tar -tf $ArchivePath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $entries.Count -eq 0) {
        throw "无法读取固定 Python 归档目录（exit=$LASTEXITCODE）。"
    }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $entries) {
        $relative = Assert-TicketboxRelativeArchivePath ([string]$entry) "TAR entry"
        if (-not $seen.Add($relative)) {
            throw "TAR 归档包含大小写冲突或重复路径：$entry"
        }
    }
    $verboseEntries = @(& $tar -tvf $ArchivePath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $verboseEntries.Count -eq 0) {
        throw "无法读取固定 Python 归档类型（exit=$LASTEXITCODE）。"
    }
    foreach ($entry in $verboseEntries) {
        $entryType = ([string]$entry).Substring(0, 1)
        if ($entryType -notin @("-", "d")) {
            throw "TAR 归档包含链接或特殊 entry，拒绝提取：$entry"
        }
    }
    Assert-TicketboxNoReparseAncestors $Destination "TAR staging"
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Assert-TicketboxNoReparseAncestors $Destination "TAR staging"
    & $tar -xf $ArchivePath -C $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "固定 Python 归档提取失败（exit=$LASTEXITCODE）。"
    }
    Assert-TicketboxNoReparseTree $Destination "TAR extracted payload"
}

function Assert-TicketboxBackendToolPayload([string]$UvRoot, [string]$PythonRoot) {
    Assert-TicketboxSha256 `
        (Join-Path $UvRoot ([string]$toolchain.uv_source.executable_relative_path)) `
        ([string]$toolchain.uv_source.executable_sha256) `
        "uv.exe"
    Assert-TicketboxSha256 `
        (Join-Path $PythonRoot ([string]$toolchain.python_source.executable_relative_path)) `
        ([string]$toolchain.python_source.executable_sha256) `
        "python.exe"
    Assert-TicketboxSha256 `
        (Join-Path $PythonRoot ([string]$toolchain.python_source.runtime_relative_path)) `
        ([string]$toolchain.python_source.runtime_sha256) `
        "Python runtime DLL"
}

function Install-TicketboxBackendTools {
    $uvFinal = Join-Path $ToolchainRoot "uv"
    $pythonFinal = Join-Path $ToolchainRoot "python"
    if (-not $Force) {
        try {
            Assert-TicketboxBackendToolPayload $uvFinal $pythonFinal
            return
        }
        catch { }
    }
    $uvArchive = Get-TicketboxPinnedArchive $toolchain.uv_source
    $pythonArchive = Get-TicketboxPinnedArchive $toolchain.python_source
    $uvStaging = Join-Path $StagingRoot "uv"
    $pythonArchiveStaging = Join-Path $StagingRoot "python-archive"
    $pythonStaging = Join-Path $StagingRoot "python"
    $uvLease = $null
    $pythonLease = $null
    try {
        $uvLease = New-TicketboxVerifiedArchiveLease `
            $uvArchive ([string]$toolchain.uv_source.sha256) "uv archive"
        $pythonLease = New-TicketboxVerifiedArchiveLease `
            $pythonArchive ([string]$toolchain.python_source.sha256) "Python archive"
        Expand-TicketboxPinnedZip $uvLease.Path $uvStaging
        Expand-TicketboxPinnedTar $pythonLease.Path $pythonArchiveStaging
    }
    finally {
        if ($null -ne $pythonLease) { $pythonLease.Handle.Dispose() }
        if ($null -ne $uvLease) { $uvLease.Handle.Dispose() }
    }
    $payloadRoot = Join-Path $pythonArchiveStaging ([string]$toolchain.python_source.archive_payload_root)
    if (-not (Test-Path -LiteralPath $payloadRoot -PathType Container)) {
        throw "固定 Python 归档缺少声明的 payload root：$payloadRoot"
    }
    Move-Item -LiteralPath $payloadRoot -Destination $pythonStaging
    Assert-TicketboxBackendToolPayload $uvStaging $pythonStaging
    Remove-TicketboxToolchainPath $uvFinal
    Remove-TicketboxToolchainPath $pythonFinal
    Move-Item -LiteralPath $uvStaging -Destination $uvFinal
    Move-Item -LiteralPath $pythonStaging -Destination $pythonFinal
    Assert-TicketboxBackendToolPayload $uvFinal $pythonFinal
}

function Install-TicketboxInnoCompiler {
    $innoFinal = Join-Path $ToolchainRoot "inno"
    $compilerPath = Join-Path $innoFinal ([string]$toolchain.inno_source.compiler_relative_path)
    if (-not $Force) {
        try {
            Assert-TicketboxSha256 $compilerPath ([string]$toolchain.inno_source.compiler_sha256) "ISCC.exe"
            return
        }
        catch { }
    }
    $installer = Get-TicketboxPinnedArchive $toolchain.inno_source
    $installStaging = Join-Path $StagingRoot "inno-installed"
    $publishStaging = Join-Path $StagingRoot "inno-publish"
    New-Item -ItemType Directory -Force -Path $installStaging, $publishStaging | Out-Null
    $uninstaller = $null
    $installerLease = $null
    try {
        $installerLease = New-TicketboxVerifiedArchiveLease `
            $installer ([string]$toolchain.inno_source.sha256) "Inno Setup archive"
        $arguments = @(
            "/CURRENTUSER",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/NOICONS",
            "/DIR=`"$installStaging`""
        )
        $process = Start-Process `
            -FilePath $installerLease.Path `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($process.ExitCode -ne 0) {
            throw "固定 Inno Setup 安装器提取失败（exit=$($process.ExitCode)）。"
        }
        $installedCompiler = Join-Path $installStaging ([string]$toolchain.inno_source.compiler_relative_path)
        Assert-TicketboxSha256 $installedCompiler ([string]$toolchain.inno_source.compiler_sha256) "提取的 ISCC.exe"
        $uninstaller = Get-ChildItem -LiteralPath $installStaging -Filter "unins*.exe" -File |
            Select-Object -First 1
        if ($null -eq $uninstaller) {
            throw "固定 Inno Setup 安装未生成可清理的卸载程序。"
        }
        Get-ChildItem -LiteralPath $installStaging -Force |
            Where-Object { $_.Name -notmatch '^unins\d+\.(?:exe|dat|msg)$' } |
            Copy-Item -Destination $publishStaging -Recurse -Force
        Assert-TicketboxSha256 `
            (Join-Path $publishStaging ([string]$toolchain.inno_source.compiler_relative_path)) `
            ([string]$toolchain.inno_source.compiler_sha256) `
            "staged ISCC.exe"
        $uninstallProcess = Start-Process `
            -FilePath $uninstaller.FullName `
            -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($uninstallProcess.ExitCode -ne 0) {
            throw "固定 Inno Setup 临时安装清理失败（exit=$($uninstallProcess.ExitCode)）。"
        }
        $uninstaller = $null
        Remove-TicketboxToolchainPath $innoFinal
        Move-Item -LiteralPath $publishStaging -Destination $innoFinal
        Assert-TicketboxSha256 `
            (Join-Path $innoFinal ([string]$toolchain.inno_source.compiler_relative_path)) `
            ([string]$toolchain.inno_source.compiler_sha256) `
            "发布的 ISCC.exe"
    }
    finally {
        if ($null -ne $uninstaller -and (Test-Path -LiteralPath $uninstaller.FullName -PathType Leaf)) {
            try {
                Start-Process `
                    -FilePath $uninstaller.FullName `
                    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
                    -WindowStyle Hidden `
                    -Wait | Out-Null
            }
            catch { }
        }
        if ($null -ne $installerLease) { $installerLease.Handle.Dispose() }
    }
}

Assert-TicketboxNoReparseAncestors $BuildRoot "backend build root"
Assert-TicketboxNoReparseAncestors $ToolchainRoot "Windows build root"
$BuildLock = $null
$PrimaryFailure = $null
$CleanupFailures = New-Object System.Collections.Generic.List[string]
try {
    $BuildLock = Enter-TicketboxWindowsBuildLock $BackendRoot
    New-Item -ItemType Directory -Force -Path $ToolchainRoot, $StagingRoot | Out-Null
    Assert-TicketboxNoReparseAncestors $StagingRoot "Windows build staging"
    if ($Component -in @("Backend", "All")) { Install-TicketboxBackendTools }
    if ($Component -in @("Inno", "All")) { Install-TicketboxInnoCompiler }
    Write-Host "Windows build toolchain ready: $ToolchainRoot" -ForegroundColor Green
}
catch { $PrimaryFailure = $_ }
finally {
    try {
        try { Remove-TicketboxToolchainPath $StagingRoot }
        catch { $CleanupFailures.Add("toolchain staging: $($_.Exception.Message)") }
    }
    finally {
        try { Exit-TicketboxWindowsBuildLock $BuildLock }
        catch { $CleanupFailures.Add("Windows build lock: $($_.Exception.Message)") }
    }
}
if ($null -ne $PrimaryFailure) {
    if ($CleanupFailures.Count -gt 0) {
        Write-Warning "Toolchain cleanup also failed after the primary error: $($CleanupFailures -join '; ')"
    }
    throw $PrimaryFailure
}
if ($CleanupFailures.Count -gt 0) {
    throw "Windows toolchain cleanup failed: $($CleanupFailures -join '; ')"
}
