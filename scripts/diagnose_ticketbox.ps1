param(
    [string]$ServerUrl = "https://api.zen70.cn",
    [int]$Port = 8000,
    [int]$Tail = 20,
    [switch]$Advanced,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$EnvPath = Join-Path $BackendRoot ".env"
$DbPath = Join-Path $BackendRoot "data\ticketbox.db"
$LogDir = Join-Path $BackendRoot "logs"
$BaseUrl = $ServerUrl.TrimEnd("/")
$Summary = New-Object System.Collections.Generic.List[object]
$Details = New-Object System.Collections.Generic.List[object]

function Add-Row {
    param(
        [System.Collections.Generic.List[object]]$Target,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Detail
    )

    $Target.Add([PSCustomObject]@{
        Name = $Name
        Status = $Status
        Detail = $Detail
    })
}

function Read-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Test-Path -LiteralPath $EnvPath)) {
        return ""
    }
    $line = Get-Content -Encoding UTF8 -LiteralPath $EnvPath |
        Where-Object { $_ -match "^$Name=" } |
        Select-Object -First 1
    if (-not $line) {
        return ""
    }
    return ($line -replace "^$Name=", "").Trim()
}

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Invoke-JsonCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{},
        [System.Collections.Generic.List[object]]$Target = $Details
    )

    try {
        $response = Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 12
        Add-Row -Target $Target -Name $Name -Status "OK" -Detail "可访问"
        return $response
    }
    catch {
        Add-Row -Target $Target -Name $Name -Status "FAIL" -Detail $_.Exception.Message
        return $null
    }
}

function Get-TenantCount {
    $tenantsJson = Read-EnvValue -Name "TENANTS_JSON"
    if ([string]::IsNullOrWhiteSpace($tenantsJson)) {
        return 1
    }
    try {
        $tenants = $tenantsJson | ConvertFrom-Json
        if ($tenants -is [array]) {
            return $tenants.Count
        }
        return 1
    }
    catch {
        return 1
    }
}

Write-Host "小票夹服务诊断"
Write-Host ""

if (Test-Path -LiteralPath $EnvPath) {
    Add-Row -Target $Details -Name "后端配置" -Status "OK" -Detail "已找到 backend\.env"
}
else {
    Add-Row -Target $Details -Name "后端配置" -Status "FAIL" -Detail "未找到 backend\.env"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    Add-Row -Target $Summary -Name "本地服务" -Status "OK" -Detail "正常"
    Add-Row -Target $Details -Name "本地服务详情" -Status "OK" -Detail "127.0.0.1:$Port，进程 $($process.ProcessName)($($listener.OwningProcess))"
}
else {
    Add-Row -Target $Summary -Name "本地服务" -Status "FAIL" -Detail "未运行"
    Add-Row -Target $Details -Name "本地服务详情" -Status "FAIL" -Detail "127.0.0.1:$Port 未监听"
}

$cloudflaredProcess = Get-Process -Name "cloudflared*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cloudflaredProcess) {
    Add-Row -Target $Summary -Name "Cloudflare Tunnel" -Status "OK" -Detail "在线"
    Add-Row -Target $Details -Name "cloudflared 进程" -Status "OK" -Detail "PID $($cloudflaredProcess.Id)"
}
else {
    Add-Row -Target $Summary -Name "Cloudflare Tunnel" -Status "WARN" -Detail "未发现进程"
}

$tasks = Get-ScheduledTask -TaskName TicketboxBackend,TicketboxCloudflareTunnel -ErrorAction SilentlyContinue
if ($tasks) {
    $taskSummary = ($tasks | ForEach-Object { "$($_.TaskName):$($_.State)" }) -join "，"
    Add-Row -Target $Details -Name "开机自启" -Status "OK" -Detail $taskSummary
}
else {
    Add-Row -Target $Details -Name "开机自启" -Status "WARN" -Detail "未找到小票夹计划任务"
}

if (Test-Path -LiteralPath $DbPath) {
    $dbFile = Get-Item -LiteralPath $DbPath
    Add-Row -Target $Summary -Name "数据库大小" -Status "OK" -Detail (Format-Bytes $dbFile.Length)
}
else {
    Add-Row -Target $Summary -Name "数据库大小" -Status "WARN" -Detail "还没有创建 ticketbox.db"
}

Invoke-JsonCheck -Name "本机健康检查" -Uri "http://127.0.0.1:$Port/api/health" -Target $Details | Out-Null
$publicHealth = Invoke-JsonCheck -Name "公网健康检查" -Uri "$BaseUrl/api/health" -Target $Details
if ($publicHealth) {
    Add-Row -Target $Summary -Name "外网访问" -Status "OK" -Detail "正常"
}
else {
    Add-Row -Target $Summary -Name "外网访问" -Status "FAIL" -Detail "不可访问"
}

$appToken = Read-EnvValue -Name "APP_TOKEN"
$uploadToken = Read-EnvValue -Name "UPLOAD_TOKEN"

if ($appToken.Length -gt 0) {
    Invoke-JsonCheck -Name "App 访问口令" -Uri "$BaseUrl/api/auth/check" -Headers @{ Authorization = "Bearer $appToken" } -Target $Details | Out-Null
    $settings = Invoke-JsonCheck -Name "服务概况" -Uri "$BaseUrl/api/settings/server" -Headers @{ Authorization = "Bearer $appToken" } -Target $Details
    if ($settings) {
        $latestUpload = if ($settings.latest_upload_at) { $settings.latest_upload_at } else { "暂无" }
        Add-Row -Target $Summary -Name "最近上传" -Status "OK" -Detail $latestUpload
        Add-Row -Target $Summary -Name "待确认" -Status "OK" -Detail "$($settings.pending_count) 笔"
        Add-Row -Target $Summary -Name "已入账" -Status "OK" -Detail "$($settings.confirmed_count) 笔"
        Add-Row -Target $Summary -Name "图片占用" -Status "OK" -Detail (Format-Bytes $settings.upload_storage_bytes)
    }
}
else {
    Add-Row -Target $Summary -Name "服务概况" -Status "WARN" -Detail "backend\.env 中没有 APP_TOKEN"
}

if ($uploadToken.Length -gt 0) {
    Invoke-JsonCheck -Name "上传口令检查" -Uri "$BaseUrl/api/upload/check" -Headers @{
        "Upload-Token" = $uploadToken
        "User-Agent" = "TicketBox/1.0 Windows-Diagnostics"
    } -Target $Details | Out-Null
}
else {
    Add-Row -Target $Details -Name "上传口令检查" -Status "WARN" -Detail "backend\.env 中没有 UPLOAD_TOKEN"
}

Add-Row -Target $Summary -Name "租户数量" -Status "OK" -Detail "$(Get-TenantCount) 个"

$Summary | Format-Table -AutoSize

if ($Advanced) {
    Write-Host ""
    Write-Host "高级详情"
    Write-Host "本机后端：http://127.0.0.1:$Port"
    Write-Host "公网入口：$BaseUrl"
    $Details | Format-Table -AutoSize

    $latestLog = Get-ChildItem -LiteralPath $LogDir -Filter "ticketbox-backend-*.out.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestLog) {
        Write-Host ""
        Write-Host "最近后端日志：$($latestLog.FullName)"
        Get-Content -Encoding UTF8 -LiteralPath $latestLog.FullName -Tail $Tail
    }
}

$failed = @($Summary + $Details | Where-Object { $_.Status -eq "FAIL" })
if ($Strict -and $failed) {
    throw "小票夹诊断失败：$($failed.Name -join '，')"
}
