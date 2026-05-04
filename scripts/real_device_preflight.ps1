param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$AppToken = "",
    [string]$UploadToken = "",
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

function Read-BackendEnv {
    $envPath = Join-Path $BackendRoot ".env"
    $values = @{}
    if (-not (Test-Path -LiteralPath $envPath)) {
        return $values
    }

    foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $envPath) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed -split "=", 2
        if ($parts.Count -eq 2) {
            $values[$parts[0].Trim()] = $parts[1].Trim()
        }
    }

    return $values
}

function Resolve-SecretValue {
    param(
        [string]$ExplicitValue,
        [string]$Name,
        [hashtable]$EnvValues
    )

    if ($ExplicitValue.Trim().Length -gt 0) {
        return $ExplicitValue.Trim()
    }
    if ($EnvValues.ContainsKey($Name) -and $EnvValues[$Name].Trim().Length -gt 0) {
        return $EnvValues[$Name].Trim()
    }
    $processValue = [Environment]::GetEnvironmentVariable($Name)
    if ($processValue -and $processValue.Trim().Length -gt 0) {
        return $processValue.Trim()
    }

    throw "缺少 $Name。请传入参数，或在 backend\.env 中配置。"
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
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$Token
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

    try {
        $response = Invoke-WebRequest `
            -Method Post `
            -Uri "$BaseUrl/api/upload-screenshot" `
            -Headers @{ "Upload-Token" = $Token } `
            -ContentType "multipart/form-data; boundary=$boundary" `
            -Body $body `
            -UseBasicParsing
        return ($response.Content | ConvertFrom-Json)
    }
    catch {
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

$baseUrl = $ServerUrl.TrimEnd("/")
$envValues = Read-BackendEnv

if (-not $SkipBackend) {
    $resolvedAppToken = Resolve-SecretValue -ExplicitValue $AppToken -Name "APP_TOKEN" -EnvValues $envValues
    $appHeaders = @{ Authorization = "Bearer $resolvedAppToken" }

    $health = Invoke-Json -Uri "$baseUrl/api/health"
    if ($health.status -ne "ok") {
        throw "健康检查未返回 ok。"
    }
    Write-Host "后端健康检查通过：$baseUrl"

    $auth = Invoke-Json -Uri "$baseUrl/api/auth/check" -Headers $appHeaders
    if ($auth.status -ne "ok") {
        throw "App Token 检查未返回 ok。"
    }
    Write-Host "App Token 检查通过。"

    if (-not $SkipUpload) {
        $resolvedUploadToken = Resolve-SecretValue -ExplicitValue $UploadToken -Name "UPLOAD_TOKEN" -EnvValues $envValues
        $upload = Invoke-TestUpload -BaseUrl $baseUrl -Token $resolvedUploadToken
        Write-Host "测试截图上传成功，pending id：$($upload.id)"

        $pending = @(Invoke-Json -Uri "$baseUrl/api/expenses/pending" -Headers $appHeaders)
        Write-Host "当前 pending 数量：$($pending.Count)"
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
