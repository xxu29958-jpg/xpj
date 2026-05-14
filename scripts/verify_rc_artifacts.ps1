param(
    [Parameter(Mandatory = $true)]
    [string]$RunId,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedCommit,

    [string]$ReleaseCandidateName = "v0.9.0a1",
    [string]$ExpectedVersionName = "0.9.0a1",
    [int]$ExpectedVersionCode = 90000,
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ProjectRoot "artifacts\rc-gate\$RunId"
}
$OutputDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)

function Invoke-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = @(& $FilePath @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') 失败：$($output -join "`n")"
    }
    return $output
}

function Get-AaptPath {
    $candidates = @()
    $localSdk = Join-Path $ProjectRoot ".toolchains\android-sdk"
    if (Test-Path -LiteralPath $localSdk) {
        $candidates += Get-ChildItem -LiteralPath (Join-Path $localSdk "build-tools") -Filter "aapt.exe" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -ExpandProperty FullName
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ANDROID_HOME)) {
        $candidates += Get-ChildItem -LiteralPath (Join-Path $env:ANDROID_HOME "build-tools") -Filter "aapt.exe" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -ExpandProperty FullName
    }
    $aapt = @($candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)
    if (-not $aapt) {
        throw "未找到 aapt.exe。请安装 Android SDK build-tools，或设置 ANDROID_HOME。"
    }
    return $aapt[0]
}

function Get-ApkBadging {
    param([Parameter(Mandatory = $true)][string]$ApkPath)

    $packageLine = Invoke-Tool -FilePath $script:AaptPath -Arguments @("dump", "badging", $ApkPath) |
        Where-Object { $_ -match "^package:" } |
        Select-Object -First 1
    if (-not $packageLine) {
        throw "无法读取 APK package 信息：$ApkPath"
    }

    $match = [regex]::Match($packageLine, "name='([^']+)'\s+versionCode='([^']+)'\s+versionName='([^']+)'")
    if (-not $match.Success) {
        throw "无法解析 APK package 信息：$packageLine"
    }

    return [ordered]@{
        package_name = $match.Groups[1].Value
        version_code = [int]$match.Groups[2].Value
        version_name = $match.Groups[3].Value
    }
}

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)][object]$Actual,
        [Parameter(Mandatory = $true)][object]$Expected,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if ($Actual -ne $Expected) {
        throw "$Message。实际：$Actual，预期：$Expected"
    }
}

function Get-ArtifactApk {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactName,
        [Parameter(Mandatory = $true)][string]$ExpectedFileName
    )

    $artifactDir = Join-Path $OutputDir $ArtifactName
    New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
    Invoke-Tool -FilePath "gh" -Arguments @("run", "download", $RunId, "-n", $ArtifactName, "-D", $artifactDir) | Out-Null

    $apk = Get-ChildItem -LiteralPath $artifactDir -Filter $ExpectedFileName -Recurse -File |
        Select-Object -First 1
    if (-not $apk) {
        throw "artifact $ArtifactName 中未找到 $ExpectedFileName"
    }
    return $apk.FullName
}

function New-ArtifactRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Flavor,
        [Parameter(Mandatory = $true)][string]$ArtifactName,
        [Parameter(Mandatory = $true)][string]$ApkPath
    )

    $apk = Get-Item -LiteralPath $ApkPath
    $badging = Get-ApkBadging -ApkPath $apk.FullName
    $sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $apk.FullName).Hash.ToLowerInvariant()

    return [ordered]@{
        flavor = $Flavor
        artifact_name = $ArtifactName
        apk_file_name = $apk.Name
        apk_path = $apk.FullName
        package_name = $badging.package_name
        version_code = $badging.version_code
        version_name = $badging.version_name
        sha256 = $sha256
        size_bytes = $apk.Length
    }
}

$run = (Invoke-Tool -FilePath "gh" -Arguments @(
        "run",
        "view",
        $RunId,
        "--json",
        "databaseId,headSha,status,conclusion,url"
    ) | ConvertFrom-Json)

Assert-Equal -Actual ([string]$run.databaseId) -Expected $RunId -Message "CI run id 不一致"
Assert-Equal -Actual $run.headSha -Expected $ExpectedCommit -Message "CI run commit 不一致"
Assert-Equal -Actual $run.status -Expected "completed" -Message "CI run 尚未完成"
Assert-Equal -Actual $run.conclusion -Expected "success" -Message "CI run 未通过"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$script:AaptPath = Get-AaptPath

$grayApk = Get-ArtifactApk -ArtifactName "ticketbox-gray-debug-apk" -ExpectedFileName "app-gray-debug.apk"
$internalApk = Get-ArtifactApk -ArtifactName "ticketbox-internal-debug-apk" -ExpectedFileName "app-internal-debug.apk"

$gray = New-ArtifactRecord -Flavor "gray" -ArtifactName "ticketbox-gray-debug-apk" -ApkPath $grayApk
$internal = New-ArtifactRecord -Flavor "internal" -ArtifactName "ticketbox-internal-debug-apk" -ApkPath $internalApk

Assert-Equal -Actual $gray.package_name -Expected "com.ticketbox" -Message "gray 包名错误"
Assert-Equal -Actual $internal.package_name -Expected "com.ticketbox.internal" -Message "internal 包名错误"
Assert-Equal -Actual $gray.version_name -Expected $ExpectedVersionName -Message "gray 版本名错误"
Assert-Equal -Actual $internal.version_name -Expected "$ExpectedVersionName-internal" -Message "internal 版本名错误"
Assert-Equal -Actual $gray.version_code -Expected $ExpectedVersionCode -Message "gray versionCode 错误"
Assert-Equal -Actual $internal.version_code -Expected $ExpectedVersionCode -Message "internal versionCode 错误"

if ($gray.package_name -eq $internal.package_name) {
    throw "gray/internal 包名相同，禁止发包。"
}
if ($gray.version_name -eq $internal.version_name) {
    throw "gray/internal 版本名相同，禁止发包。"
}
if ($gray.sha256 -eq $internal.sha256) {
    throw "gray/internal APK sha256 相同，疑似 artifact 取错。"
}
if (-not $ReleaseCandidateName.StartsWith("v$ExpectedVersionName")) {
    throw "ReleaseCandidateName 必须以 v$ExpectedVersionName 开头。"
}

$manifest = [ordered]@{
    release_candidate = $ReleaseCandidateName
    gate_passed = $true
    checked_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    ci = [ordered]@{
        run_id = [string]$run.databaseId
        run_url = $run.url
        commit = $run.headSha
        status = $run.status
        conclusion = $run.conclusion
    }
    artifacts = @($gray, $internal)
    token_handoff = [ordered]@{
        gray_android_user_receives = "server URL and one-time Pairing Code only"
        ios_shortcut_user_receives = "full UploadLink URL only for the target shortcut setup"
        internal_owner_receives = "internal APK plus owner-maintained admin/session credentials only"
        must_not_send = @(
            "backend .env",
            "admin token",
            "session token",
            "UploadLink for other ledgers",
            "CI logs or screenshots containing credentials",
            "keystore files or signing passwords"
        )
    }
}

$manifestPath = Join-Path $OutputDir "$ReleaseCandidateName-artifact-manifest.json"
$checklistPath = Join-Path $OutputDir "$ReleaseCandidateName-handoff-checklist.md"

[System.IO.File]::WriteAllText($manifestPath, (($manifest | ConvertTo-Json -Depth 8) + "`n"), $Utf8NoBom)

$checklist = @(
    "# $ReleaseCandidateName 发包门禁清单",
    "",
    "- CI run: $($run.databaseId)",
    "- Commit: $($run.headSha)",
    "- Gray APK: $($gray.artifact_name) / $($gray.apk_file_name)",
    "- Gray package/version: $($gray.package_name) / $($gray.version_name) ($($gray.version_code))",
    "- Gray SHA256: $($gray.sha256)",
    "- Internal APK: $($internal.artifact_name) / $($internal.apk_file_name)",
    "- Internal package/version: $($internal.package_name) / $($internal.version_name) ($($internal.version_code))",
    "- Internal SHA256: $($internal.sha256)",
    "",
    "## 访问口令发放对象",
    "",
    "- Android gray 用户：只发服务地址和一次性 Pairing Code。",
    "- iPhone 快捷指令用户：只在配置对应快捷指令时提供完整 UploadLink URL。",
    "- 服务拥有者：internal APK、admin token 和维护凭据只在服务拥有者手里。",
    "",
    "## 不能发的内容",
    "",
    "- backend .env",
    "- admin token",
    "- session token",
    "- 其他账本或设备的 UploadLink",
    "- 含凭证的日志、截图、CI 输出",
    "- keystore 文件或签名密码",
    "",
    "## 门禁结论",
    "",
    "通过。只有这份清单和 manifest 同时存在，且脚本退出码为 0，才允许称为 $ReleaseCandidateName。"
) -join "`n"
[System.IO.File]::WriteAllText($checklistPath, ($checklist + "`n"), $Utf8NoBom)

Write-Host "OK   $ReleaseCandidateName artifact 门禁通过。"
Write-Host "清单：$checklistPath"
Write-Host "manifest：$manifestPath"
