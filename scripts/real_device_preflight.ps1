param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$SessionToken = "",
    [string]$UploadLink = "",
    [switch]$SkipBackend,
    [switch]$SkipUpload,
    [switch]$SkipDevice,
    [switch]$BuildApk,
    [switch]$Install,
    [switch]$Launch,
    [string]$Serial = "",
    [string]$Adb = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$InstallScript = Join-Path $ProjectRoot "android\scripts\install_debug_apk.ps1"

function Resolve-SecretValue {
    param(
        [string]$ExplicitValue,
        [string]$Name
    )

    if ($ExplicitValue.Trim().Length -gt 0) {
        return $ExplicitValue.Trim()
    }
    $processValue = [Environment]::GetEnvironmentVariable($Name)
    if ($processValue -and $processValue.Trim().Length -gt 0) {
        return $processValue.Trim()
    }

    throw "缺少 $Name。请通过参数或环境变量传入。"
}

function Resolve-UploadUrl {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("http://", [System.StringComparison]::OrdinalIgnoreCase) -or
        $trimmed.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $trimmed
    }
    if ($trimmed.StartsWith("/")) {
        return "$BaseUrl$trimmed"
    }
    return "$BaseUrl/$trimmed"
}

function Invoke-Json {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{}
    )

    try {
        return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers
    }
    catch {
        throw "请求失败：$Uri。$($_.Exception.Message)"
    }
}

function Invoke-TestUpload {
    param(
        [Parameter(Mandatory = $true)][string]$UploadUrl
    )

    $pngBytes = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")
    $boundary = "----ticketbox-preflight-$([Guid]::NewGuid().ToString("N"))"
    $prefix = (
        "--$boundary`r`n" +
        "Content-Disposition: form-data; name=`"file`"; filename=`"preflight.png`"`r`n" +
        "Content-Type: image/png`r`n`r`n"
    )
    $suffix = "`r`n--$boundary--`r`n"
    $prefixBytes = [System.Text.Encoding]::UTF8.GetBytes($prefix)
    $suffixBytes = [System.Text.Encoding]::UTF8.GetBytes($suffix)
    $body = New-Object byte[] ($prefixBytes.Length + $pngBytes.Length + $suffixBytes.Length)
    [System.Buffer]::BlockCopy($prefixBytes, 0, $body, 0, $prefixBytes.Length)
    [System.Buffer]::BlockCopy($pngBytes, 0, $body, $prefixBytes.Length, $pngBytes.Length)
    [System.Buffer]::BlockCopy($suffixBytes, 0, $body, $prefixBytes.Length + $pngBytes.Length, $suffixBytes.Length)

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-WebRequest `
            -Method Post `
            -Uri $UploadUrl `
            -ContentType "multipart/form-data; boundary=$boundary" `
            -Body $body `
            -UseBasicParsing
        $stopwatch.Stop()
        $payload = $response.Content | ConvertFrom-Json
        $payload | Add-Member -NotePropertyName client_duration_ms -NotePropertyValue $stopwatch.ElapsedMilliseconds -Force
        return $payload
    }
    catch {
        $stopwatch.Stop()
        $response = $_.Exception.Response
        if ($response) {
            $stream = $response.GetResponseStream()
            if ($stream) {
                $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
                $bodyText = $reader.ReadToEnd()
                if ($bodyText.Trim().Length -gt 0) {
                    throw "测试上传失败。$bodyText"
                }
            }
        }
        throw "测试上传失败。$($_.Exception.Message)"
    }
}

function Invoke-RejectExpense {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][hashtable]$Headers,
        [Parameter(Mandatory = $true)]$Id
    )

    try {
        Invoke-RestMethod `
            -Method Post `
            -Uri "$BaseUrl/api/expenses/$Id/reject" `
            -Headers $Headers | Out-Null
        Write-Host "测试 pending 已清理：$Id"
    }
    catch {
        Write-Warning "测试 pending 清理失败：$Id。$($_.Exception.Message)"
    }
}

function Get-FirstScalar {
    param(
        $Value
    )

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [System.Array]) {
        if ($Value.Count -eq 0) {
            return $null
        }
        return Get-FirstScalar -Value $Value[0]
    }
    return $Value
}

function Add-FlatItems {
    param(
        [AllowEmptyCollection()][System.Collections.Generic.List[object]]$Target,
        $Items
    )

    foreach ($item in @($Items)) {
        if ($item -is [System.Array]) {
            Add-FlatItems -Target $Target -Items $item
        }
        elseif ($null -ne $item) {
            $Target.Add($item) | Out-Null
        }
    }
}

function Get-FlatItems {
    param($Items)

    $flat = New-Object System.Collections.Generic.List[object]
    Add-FlatItems -Target $flat -Items $Items
    return $flat.ToArray()
}

function Find-ExpenseById {
    param(
        $Items,
        [Parameter(Mandatory = $true)]$Id
    )

    $targetId = [int64](Get-FirstScalar -Value $Id)
    foreach ($item in @($Items)) {
        if ($item -is [System.Array]) {
            $found = Find-ExpenseById -Items $item -Id $targetId
            if ($found) {
                return $found
            }
            continue
        }

        $itemId = Get-FirstScalar -Value $item.id
        if ($null -ne $itemId -and [int64]$itemId -eq $targetId) {
            return $item
        }
    }
    return $null
}

function Assert-PublicId {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $publicId = [string](Get-FirstScalar -Value $Value)
    if ($publicId.Trim().Length -eq 0) {
        throw "$Context 缺少 public_id。请确认后端已重启并运行最新代码。"
    }

    try {
        [Guid]::Parse($publicId) | Out-Null
    }
    catch {
        throw "$Context 的 public_id 不是有效 UUID：$publicId"
    }
}

$baseUrl = $ServerUrl.TrimEnd("/")

if (-not $SkipBackend) {
    $resolvedSessionToken = Resolve-SecretValue -ExplicitValue $SessionToken -Name "TICKETBOX_SESSION_TOKEN"
    $appHeaders = @{ Authorization = "Bearer $resolvedSessionToken" }

    $health = Invoke-Json -Uri "$baseUrl/api/health"
    if ($health.status -ne "ok") {
        throw "健康检查未返回 ok。"
    }
    Write-Host "后端健康检查通过：$baseUrl"

    $auth = Invoke-Json -Uri "$baseUrl/api/auth/check" -Headers $appHeaders
    if ($auth.status -ne "ok") {
        throw "Session Token 检查未返回 ok。"
    }
    Write-Host "Session Token 检查通过。"

    $confirmedProbe = Invoke-Json -Uri "$baseUrl/api/expenses/confirmed?page=1&page_size=1" -Headers $appHeaders
    if ($confirmedProbe.items -and $confirmedProbe.items.Count -gt 0) {
        Assert-PublicId -Value $confirmedProbe.items[0].public_id -Context "已确认账单接口"
    }
    Write-Host "账单 API 契约检查通过。"

    if (-not $SkipUpload) {
        $resolvedUploadLink = Resolve-SecretValue -ExplicitValue $UploadLink -Name "TICKETBOX_UPLOAD_LINK"
        $resolvedUploadUrl = Resolve-UploadUrl -BaseUrl $baseUrl -Value $resolvedUploadLink
        $uploadedId = $null
        try {
            $upload = Invoke-TestUpload -UploadUrl $resolvedUploadUrl
            $uploadedId = Get-FirstScalar -Value $upload.id
            Assert-PublicId -Value $upload.public_id -Context "上传接口"
            $serverDuration = Get-FirstScalar -Value $upload.duration_ms
            $uploadBytes = Get-FirstScalar -Value $upload.upload_size_bytes
            Write-Host "测试截图上传成功，pending id：$uploadedId"
            if ($null -ne $uploadBytes -or $null -ne $serverDuration) {
                Write-Host "上传耗时：客户端 $($upload.client_duration_ms) ms；服务端保存 $serverDuration ms；文件 $uploadBytes bytes"
            }
            else {
                Write-Host "上传耗时：客户端 $($upload.client_duration_ms) ms；当前后端未返回服务端耗时字段。"
            }

            $pending = Get-FlatItems -Items (Invoke-Json -Uri "$baseUrl/api/expenses/pending" -Headers $appHeaders)
            $uploadedPending = Find-ExpenseById -Items $pending -Id $uploadedId
            if (-not $uploadedPending) {
                throw "pending 列表中没有刚上传的账单 id：$uploadedId"
            }
            Assert-PublicId -Value $uploadedPending.public_id -Context "pending 接口"
            Write-Host "当前 pending 数量：$($pending.Count)"
        }
        finally {
            if ($null -ne $uploadedId) {
                Invoke-RejectExpense -BaseUrl $baseUrl -Headers $appHeaders -Id $uploadedId
            }
        }
    }
    else {
        Write-Host "已跳过测试上传。"
    }
}
else {
    Write-Host "已跳过后端 API 检查。"
}

if (-not $SkipDevice) {
    if (-not (Test-Path -LiteralPath $InstallScript)) {
        throw "未找到 Android 安装脚本：$InstallScript"
    }

    $installArgs = @()
    if ($BuildApk) { $installArgs += "-Build" }
    if ($Launch) { $installArgs += "-Launch" }
    if ($Serial.Trim().Length -gt 0) { $installArgs += @("-Serial", $Serial) }
    if ($Adb.Trim().Length -gt 0) { $installArgs += @("-Adb", $Adb) }

    if ($Install) {
        Write-Host "开始安装 Android debug APK。"
        & powershell -ExecutionPolicy Bypass -File $InstallScript @installArgs
    }
    else {
        Write-Host "列出 Android 设备。需要安装时加 -Install；需要构建时加 -BuildApk。"
        & powershell -ExecutionPolicy Bypass -File $InstallScript -ListDevices @installArgs
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Android 设备检查失败。"
    }
}
else {
    Write-Host "已跳过 Android 设备检查。"
}

Write-Host "实机联调预检完成。"
