#Requires -Version 5.1

# vNext 安装器配方闭包：新 ISS + TicketboxLifecycle CLI + 构建/装配脚本。
# 旧 pre-copy 执行图（install/uninstall owner、generation 小城、dataset 管道、
# receipt/lease 城）已随旧 ISS 同刀退役，不再列入配方。
$script:TicketboxInstallerRecipeRelativePaths = @(
    "backend\scripts\windows_build_provenance.ps1",
    "backend\scripts\windows_backend_build_provenance.ps1",
    "backend\scripts\windows_python_build_environment.ps1",
    "backend\requirements-build.lock",
    "backend\packaging\windows-build-toolchain.json",
    "backend\packaging\prepare_windows_build_toolchain.ps1",
    "backend\packaging\prepare_windows_installer_vendor.ps1",
    "backend\packaging\build_pg_bundle.ps1",
    "backend\packaging\languages\ChineseSimplified.isl",
    "backend\packaging\ticketbox.ico",
    "backend\packaging\windows-release-config.json",
    "distribution\windows\installer\ticketbox.iss",
    "distribution\windows\installer\setup_security.iss",
    "distribution\windows\installer\setup_lease.iss",
    "distribution\windows\installer\setup_private_result.iss",
    "distribution\windows\build\build_installer.ps1",
    "distribution\windows\build\check_source_inputs.ps1",
    "distribution\windows\build\installed_payload_manifest.ps1",
    "distribution\windows\build\ticketbox-lifecycle.spec",
    "distribution\windows\payload\release-manifest.json",
    "distribution\windows\lifecycle\ticketbox_lifecycle\__init__.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\__main__.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\cli.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\errors.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\schemas.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\adapters\__init__.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\adapters\ports.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\domain\__init__.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\domain\binding.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\domain\install.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\domain\planner.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\policy\__init__.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\policy\health_attestation.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\policy\postgres_roles.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\policy\windows_scm_contract.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\__init__.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\command.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_process.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_account.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\durable_files.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\postgres_connection.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\layout.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\mutex.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\filesystem_stores.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_adapters.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_credentials.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_alembic.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_dataset.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_installation_health.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_dacl.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_file_security.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_files.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_known_folders.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_postgres.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_pgdata_security.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_postgres_identity.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_scm.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_scm_observation.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_security.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_security_native.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_shipment.py",
    "distribution\windows\lifecycle\ticketbox_lifecycle\runtime\windows_services.py"
)

function Get-TicketboxSha256HexFromText([string]$Value) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Value)
        return ([System.BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}
function Get-TicketboxFileSha256([string]$Path) {
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}
function Get-TicketboxRelativePath([string]$Root, [string]$Path) {
    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $prefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "路径不在预期根目录下：$fullPath（root=$rootPath）"
    }
    return $fullPath.Substring($prefix.Length).Replace("\", "/")
}
function Get-TicketboxFileEvidence([string]$Root, [string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "构建 provenance 缺少文件：$Path"
    }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = Get-TicketboxRelativePath $Root $item.FullName
        size = [int64]$item.Length
        sha256 = Get-TicketboxFileSha256 $item.FullName
    }
}
function Get-TicketboxOrdinalSortedPaths([string[]]$Paths) {
    $sortedPaths = [string[]]@(
        $Paths | ForEach-Object { [System.IO.Path]::GetFullPath($_) }
    )
    [Array]::Sort($sortedPaths, [System.StringComparer]::OrdinalIgnoreCase)
    return $sortedPaths
}
function Get-TicketboxFileSetSnapshot([string]$Root, [string[]]$Paths) {
    if ($Paths.Count -eq 0) {
        throw "构建 provenance 文件集合为空：$Root"
    }
    $recordsByPath =
        [System.Collections.Generic.SortedDictionary[string, object]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($path in $Paths) {
        $record = Get-TicketboxFileEvidence $Root $path
        $relativePath = [string]$record.path
        if ($relativePath -cmatch "[^\x20-\x7e]") {
            throw (
                "构建 provenance canonical manifest 相对路径只允许可打印 ASCII；" +
                "这可避免不同 .NET Unicode 版本改变 OrdinalIgnoreCase 结果：" +
                $relativePath
            )
        }
        if ($recordsByPath.ContainsKey($relativePath)) {
            throw (
                "构建 provenance 包含 ordinal-ignore-case 等价的重复相对路径：" +
                $relativePath
            )
        }
        $recordsByPath.Add($relativePath, $record)
    }
    $records = [object[]]@($recordsByPath.Values)
    $fingerprintInput = ($records | ForEach-Object {
        "{0}`0{1}`0{2}`n" -f $_.path, $_.size, $_.sha256
    }) -join ""
    return [pscustomobject]@{
        algorithm = "SHA-256"
        fingerprint = Get-TicketboxSha256HexFromText $fingerprintInput
        files = @($records)
    }
}
function Assert-TicketboxFileSetSnapshot([string]$Label, [object]$Recorded, [object]$Actual) {
    if ($null -eq $Recorded) {
        throw "$Label 缺少记录的文件集合。"
    }
    if ($Recorded.algorithm -cne "SHA-256" -or $Actual.algorithm -cne "SHA-256") {
        throw "$Label 的 hash 算法不是 SHA-256。"
    }
    if ($Recorded.fingerprint -cne $Actual.fingerprint) {
        throw "$Label 的汇总指纹与当前文件集合不一致。"
    }

    $recordedFiles = @($Recorded.files)
    $actualFiles = @($Actual.files)
    if ($recordedFiles.Count -ne $actualFiles.Count) {
        throw "$Label 的文件记录数量不一致：recorded=$($recordedFiles.Count)，actual=$($actualFiles.Count)"
    }
    for ($index = 0; $index -lt $actualFiles.Count; $index++) {
        $recordedFile = $recordedFiles[$index]
        $actualFile = $actualFiles[$index]
        if (
            $recordedFile.path -cne $actualFile.path -or
            [int64]$recordedFile.size -ne [int64]$actualFile.size -or
            $recordedFile.sha256 -cne $actualFile.sha256
        ) {
            throw "$Label 的文件记录不一致：index=$index，recorded=$($recordedFile.path)，actual=$($actualFile.path)"
        }
    }
}
function Copy-TicketboxFileSetSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [Parameter(Mandatory = $true)][object]$Snapshot
    )
    $sourceRootPath = [System.IO.Path]::GetFullPath($SourceRoot)
    $destinationRootPath = [System.IO.Path]::GetFullPath($DestinationRoot)
    foreach ($record in @($Snapshot.files)) {
        $relativePath = ([string]$record.path).Replace("/", "\")
        $sourcePath = Join-Path $sourceRootPath $relativePath
        $destinationPath = Join-Path $destinationRootPath $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "构建快照复制缺少源文件：$sourcePath"
        }
        $destinationParent = Split-Path -Parent $destinationPath
        New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
    }
    $copiedPaths = @(
        @($Snapshot.files) | ForEach-Object {
            Join-Path $destinationRootPath (([string]$_.path).Replace("/", "\"))
        }
    )
    $copiedSnapshot = Get-TicketboxFileSetSnapshot $destinationRootPath $copiedPaths
    Assert-TicketboxFileSetSnapshot "构建输入 staging" $Snapshot $copiedSnapshot
    return $copiedSnapshot
}
function Enter-TicketboxFileSetReadLocks {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][object]$Snapshot
    )
    $rootPath = [System.IO.Path]::GetFullPath($Root)
    $streams = New-Object System.Collections.Generic.List[System.IO.FileStream]
    try {
        foreach ($record in @($Snapshot.files)) {
            $path = Join-Path $rootPath (([string]$record.path).Replace("/", "\"))
            $stream = [System.IO.File]::Open(
                $path,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            )
            $streams.Add($stream)
        }
        Assert-TicketboxFileSetSnapshot `
            "已锁定构建输入" `
            $Snapshot `
            (Get-TicketboxFileSetSnapshot $rootPath @(
                @($Snapshot.files) | ForEach-Object {
                    Join-Path $rootPath (([string]$_.path).Replace("/", "\"))
                }
            ))
        return $streams
    }
    catch {
        foreach ($stream in $streams) { $stream.Dispose() }
        throw
    }
}
function Exit-TicketboxFileSetReadLocks([object]$Streams) {
    if ($null -eq $Streams) { return }
    foreach ($stream in @($Streams)) { $stream.Dispose() }
}

function Assert-TicketboxStructuredEvidence(
    [string]$Label,
    [object]$Recorded,
    [object]$Expected
) {
    if ($null -eq $Recorded -or $null -eq $Expected) { throw "$Label 缺少结构化证据。" }
    if (
        ($Recorded | ConvertTo-Json -Depth 20 -Compress) -cne
        ($Expected | ConvertTo-Json -Depth 20 -Compress)
    ) {
        throw "$Label 与本轮已验证输入不一致。"
    }
}
function ConvertTo-TicketboxVendorVersion([string]$Value, [string]$Label) {
    $match = [regex]::Match($Value, '^(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?$')
    if (-not $match.Success) {
        throw "$Label 必须是 2 到 4 段纯数字版本：$Value"
    }
    $parts = @()
    foreach ($index in 1..4) {
        if ($match.Groups[$index].Success) { $parts += [int]$match.Groups[$index].Value }
        else { $parts += 0 }
    }
    return [Version]("{0}.{1}.{2}.{3}" -f $parts[0], $parts[1], $parts[2], $parts[3])
}
function Get-TicketboxVendorVersionPolicy([object]$Config, [string]$Vendor) {
    $propertyName = "${Vendor}_version_policy"
    $property = $Config.PSObject.Properties[$propertyName]
    if ($null -eq $property -or $null -eq $property.Value) {
        throw "Windows release config 缺少 $propertyName。"
    }
    $policy = $property.Value
    $minimum = [string]$policy.minimum
    $maximumExclusive = [string]$policy.maximum_exclusive
    $minimumVersion = ConvertTo-TicketboxVendorVersion $minimum "$propertyName.minimum"
    $maximumVersion = ConvertTo-TicketboxVendorVersion $maximumExclusive "$propertyName.maximum_exclusive"
    if ($minimumVersion.CompareTo($maximumVersion) -ge 0) {
        throw "Windows release config 的 $propertyName 必须满足 minimum < maximum_exclusive。"
    }
    return [pscustomobject]@{
        minimum = $minimum
        maximum_exclusive = $maximumExclusive
        minimum_version = $minimumVersion
        maximum_version = $maximumVersion
    }
}
function Assert-TicketboxVendorVersionAllowed([object]$Config, [string]$Vendor, [string]$Version) {
    $policy = Get-TicketboxVendorVersionPolicy $Config $Vendor
    $candidate = ConvertTo-TicketboxVendorVersion $Version "$Vendor executable version"
    if (
        $candidate.CompareTo($policy.minimum_version) -lt 0 -or
        $candidate.CompareTo($policy.maximum_version) -ge 0
    ) {
        throw "$Vendor 版本不符合 release config 策略：version=$Version，允许 [$($policy.minimum), $($policy.maximum_exclusive))"
    }
    return [pscustomobject]@{
        minimum = $policy.minimum
        maximum_exclusive = $policy.maximum_exclusive
    }
}
function Invoke-TicketboxGitText([string]$Root, [string[]]$Arguments, [switch]$AllowEmpty) {
    $output = @(& git -C $Root @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $rawText = ($output | ForEach-Object { $_.ToString() }) -join "`n"
    $text = if ($AllowEmpty) { $rawText.TrimEnd() } else { $rawText.Trim() }
    if ($exitCode -ne 0) {
        throw "git provenance 探针失败（exit=$exitCode）：$text"
    }
    if (-not $AllowEmpty -and $text.Length -eq 0) {
        throw "git provenance 探针没有输出：git $($Arguments -join ' ')"
    }
    return $text
}
function Get-TicketboxGitProvenance([string]$Root) {
    $commit = Invoke-TicketboxGitText $Root @("rev-parse", "--verify", "HEAD")
    if ($commit -notmatch '^[0-9a-fA-F]{40,64}$') {
        throw "git HEAD 不是支持的 commit id：$commit"
    }
    $tree = Invoke-TicketboxGitText $Root @("show", "-s", "--format=%T", "HEAD")
    if ($tree -notmatch '^[0-9a-fA-F]{40,64}$') {
        throw "git HEAD tree 不是支持的 tree id：$tree"
    }
    $status = Invoke-TicketboxGitText $Root @("status", "--porcelain=v1", "--untracked-files=all") -AllowEmpty
    $statusEntries = @($status -split "`n" | Where-Object { $_.Trim().Length -gt 0 })
    return [pscustomobject]@{
        commit = $commit.ToLowerInvariant()
        tree = $tree.ToLowerInvariant()
        dirty = $statusEntries.Count -gt 0
        status_entry_count = $statusEntries.Count
        status_fingerprint = Get-TicketboxSha256HexFromText $status
    }
}
function Get-TicketboxIsccEngineVersion([string]$Path) {
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\", "/")
    $probeDirectory = Join-Path $tempRoot ("ticketbox-iscc-probe-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
    $probePath = Join-Path $probeDirectory "probe.iss"
    $probeText = @(
        "[Setup]",
        "AppName=TicketboxCompilerProbe",
        "AppVersion=1.0.0",
        "DefaultDirName={tmp}\TicketboxCompilerProbe",
        "Uninstallable=no",
        "OutputBaseFilename=probe"
    ) -join [Environment]::NewLine
    try {
        New-Item -ItemType Directory -Path $probeDirectory | Out-Null
        [System.IO.File]::WriteAllText(
            $probePath,
            $probeText + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
        )
        $output = @(& $Path "/O$probeDirectory" $probePath 2>&1)
        $exitCode = $LASTEXITCODE
        $text = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        if ($exitCode -ne 0) {
            throw "ISCC engine version probe failed (exit=$exitCode): $text"
        }
        $match = [regex]::Match(
            $text,
            '(?m)^Compiler engine version:\s+Inno Setup\s+(\d+\.\d+\.\d+)\s*$'
        )
        if (-not $match.Success) { throw "Cannot parse ISCC engine version output." }
        return $match.Groups[1].Value
    }
    finally {
        $canonicalProbe = [System.IO.Path]::GetFullPath($probeDirectory)
        $tempPrefix = $tempRoot + [System.IO.Path]::DirectorySeparatorChar
        if (
            $canonicalProbe.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
            (Test-Path -LiteralPath $canonicalProbe)
        ) {
            Remove-Item -LiteralPath $canonicalProbe -Recurse -Force
        }
    }
}

function Get-TicketboxIsccProvenance([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 ISCC.exe：$Path"
    }
    $item = Get-Item -LiteralPath $Path
    $versionInfo = $item.VersionInfo
    $identityText = "$($versionInfo.ProductName) $($versionInfo.FileDescription)"
    if ($identityText -notmatch '(?i)Inno Setup') {
        throw "指定编译器的 Windows 版本身份不是 Inno Setup：$identityText"
    }
    if ([string]::IsNullOrWhiteSpace($versionInfo.FileVersion)) {
        throw "ISCC.exe 缺少 Windows FileVersion，拒绝生成不可追溯安装包。"
    }
    return [pscustomobject]@{
        product_name = $versionInfo.ProductName
        product_version = $versionInfo.ProductVersion
        file_version = $versionInfo.FileVersion
        engine_version = Get-TicketboxIsccEngineVersion $item.FullName
        executable = Get-TicketboxFileEvidence (Split-Path -Parent $Path) $Path
    }
}
function Invoke-TicketboxExecutableProbe([string]$Path, [string[]]$Arguments, [string]$Label) {
    $output = @(& $Path @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = (($output | ForEach-Object { $_.ToString() }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        throw "$Label 探针失败（exit=$exitCode）：$text"
    }
    if ($text.Length -eq 0) {
        throw "$Label 探针没有输出，拒绝继续。"
    }
    return $text
}
function Read-TicketboxPgBundleManifest([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 PostgreSQL BUNDLE_MANIFEST.txt：$Path"
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $match = [regex]::Match($line, '^\s*([a-z0-9_]+)\s*=\s*(.*?)\s*$')
        if ($match.Success) {
            $name = $match.Groups[1].Value
            if ($values.ContainsKey($name)) {
                throw "PostgreSQL BUNDLE_MANIFEST.txt 字段重复：$name"
            }
            $values[$name] = $match.Groups[2].Value
        }
    }
    foreach ($required in @(
        "pg_version",
        "source_zip",
        "source_sha256",
        "source_url",
        "payload_file_count",
        "payload_fingerprint",
        "license"
    )) {
        if (-not $values.ContainsKey($required) -or $values[$required].Trim().Length -eq 0) {
            throw "PostgreSQL BUNDLE_MANIFEST.txt 缺少字段：$required"
        }
    }
    if ($values["source_sha256"] -notmatch '^[0-9a-fA-F]{64}$') {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 source_sha256 格式无效。"
    }
    if (
        $values["payload_file_count"] -notmatch '^\d+$' -or
        [int64]$values["payload_file_count"] -le 0
    ) {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 payload_file_count 格式无效。"
    }
    if ($values["payload_fingerprint"] -notmatch '^[0-9a-fA-F]{64}$') {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 payload_fingerprint 格式无效。"
    }
    $sourceUri = $null
    if (
        -not [Uri]::TryCreate($values["source_url"], [UriKind]::Absolute, [ref]$sourceUri) -or
        $sourceUri.Scheme -ne "https"
    ) {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 source_url 必须是 HTTPS 绝对地址。"
    }
    return $values
}

# 配方跨 backend/ 与 distribution/ 两棵子树，快照根是 repo 根（BackendRoot 的父目录）。
function Get-TicketboxInstallerRecipeRoot([string]$BackendRoot) {
    return (Resolve-Path -LiteralPath (Join-Path $BackendRoot "..")).Path
}

function Get-TicketboxInstallerRecipePaths([string]$BackendRoot) {
    $repoRoot = Get-TicketboxInstallerRecipeRoot $BackendRoot
    $paths = @()
    foreach ($relativePath in $script:TicketboxInstallerRecipeRelativePaths) {
        $path = Join-Path $repoRoot $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Windows 安装器配方缺少必需文件：$path"
        }
        $paths += (Resolve-Path -LiteralPath $path).Path
    }
    return @(Get-TicketboxOrdinalSortedPaths $paths)
}

function Get-TicketboxInstallerRecipeSnapshot([string]$BackendRoot) {
    $repoRoot = Get-TicketboxInstallerRecipeRoot $BackendRoot
    return Get-TicketboxFileSetSnapshot $repoRoot (Get-TicketboxInstallerRecipePaths $BackendRoot)
}

function Get-TicketboxNormalizedCompilerDefines([string[]]$Defines) {
    $normalized = [string[]]@()
    $names = @{}
    foreach ($define in $Defines) {
        $match = [regex]::Match([string]$define, '^/D([A-Za-z][A-Za-z0-9_]*)=(.+)$')
        if (-not $match.Success) {
            throw "ISCC define does not use the required /DName=Value form: $define"
        }
        $name = $match.Groups[1].Value
        if ($names.ContainsKey($name)) { throw "Duplicate ISCC define: $name" }
        $names[$name] = $true
        $normalized += [string]$define
    }
    [Array]::Sort($normalized, [System.StringComparer]::Ordinal)
    return $normalized
}

function Assert-TicketboxInstallerBuildProvenance(
    [string]$BackendRoot,
    [string]$Path,
    [object]$ExpectedCompilerProvenance,
    [object]$ExpectedBuildInputs,
    [string[]]$ExpectedCompilerDefines
) {
    try {
        $manifest = Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "安装器 provenance 不是有效 JSON：$Path。$($_.Exception.Message)"
    }
    if ($manifest.schema_version -ne 4 -or $manifest.artifact_type -cne "ticketbox-windows-installer-inputs") {
        throw "安装器 provenance schema/artifact_type 不受支持。"
    }
    Assert-TicketboxStructuredEvidence "安装器 ISCC defines" @($manifest.compiler_defines) @(Get-TicketboxNormalizedCompilerDefines $ExpectedCompilerDefines)
    Assert-TicketboxFileSetSnapshot `
        "Windows 安装器 recipe" `
        $manifest.recipe `
        (Get-TicketboxInstallerRecipeSnapshot $BackendRoot)
    $currentGit = Get-TicketboxGitProvenance $BackendRoot
    if (
        $manifest.git.commit -cne $currentGit.commit -or
        $manifest.git.tree -cne $currentGit.tree -or
        [bool]$manifest.git.dirty -ne [bool]$currentGit.dirty -or
        [int]$manifest.git.status_entry_count -ne [int]$currentGit.status_entry_count -or
        $manifest.git.status_fingerprint -cne $currentGit.status_fingerprint
    ) {
        throw "安装器 provenance 的 Git SHA/dirty state 与当前工作树不一致。"
    }
    $expectsCompiler = $null -ne $ExpectedCompilerProvenance
    if ([bool]$manifest.compiler.included -ne $expectsCompiler) {
        throw "安装器 provenance 的 ISCC identity presence 不一致。"
    }
    if ($expectsCompiler) {
        $recordedExe = $manifest.compiler.executable
        $expectedExe = $ExpectedCompilerProvenance.executable
        if (
            [string]$manifest.compiler.product_name -cne [string]$ExpectedCompilerProvenance.product_name -or
            [string]$manifest.compiler.product_version -cne [string]$ExpectedCompilerProvenance.product_version -or
            [string]$manifest.compiler.file_version -cne [string]$ExpectedCompilerProvenance.file_version -or
            [string]$manifest.compiler.engine_version -cne [string]$ExpectedCompilerProvenance.engine_version -or
            ($manifest.compiler.version_policy | ConvertTo-Json -Compress) -cne
            ($ExpectedCompilerProvenance.version_policy | ConvertTo-Json -Compress) -or
            $recordedExe.path -cne $expectedExe.path -or
            [int64]$recordedExe.size -ne [int64]$expectedExe.size -or
            $recordedExe.sha256 -cne $expectedExe.sha256
        ) {
            throw "安装器 provenance 的 ISCC identity 与选定编译器不一致。"
        }
    }
    Assert-TicketboxStructuredEvidence `
        "安装器 Lifecycle build provenance" `
        $manifest.lifecycle `
        $ExpectedBuildInputs.lifecycle
    Assert-TicketboxStructuredEvidence `
        "安装器 backend provenance" `
        $manifest.backend `
        $ExpectedBuildInputs.backend
    Assert-TicketboxStructuredEvidence `
        "安装器 Desktop Manager provenance" `
        $manifest.manager `
        $ExpectedBuildInputs.manager
    Assert-TicketboxStructuredEvidence `
        "安装器 PostgreSQL provenance" `
        $manifest.postgresql `
        $ExpectedBuildInputs.postgresql
    Assert-TicketboxStructuredEvidence `
        "安装器 Shawl provenance" `
        $manifest.shawl `
        $ExpectedBuildInputs.shawl
    Assert-TicketboxStructuredEvidence `
        "安装器 immutable shipment provenance" `
        $manifest.shipment `
        $ExpectedBuildInputs.shipment
    return $manifest
}

function Write-TicketboxJsonFile([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporaryPath = "$Path.$PID.tmp"
    $json = $Value | ConvertTo-Json -Depth 12
    $encoding = New-Object System.Text.UTF8Encoding($false)
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $json + "`n", $encoding)
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

$backendBuildProvenanceScript = Join-Path $PSScriptRoot "windows_backend_build_provenance.ps1"
if (-not (Test-Path -LiteralPath $backendBuildProvenanceScript -PathType Leaf)) {
    throw "Missing backend build provenance helper: $backendBuildProvenanceScript"
}
. $backendBuildProvenanceScript
