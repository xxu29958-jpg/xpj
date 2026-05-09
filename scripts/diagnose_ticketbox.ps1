param(
    [string]$ServerUrl = "https://api.zen70.cn",
    [int]$Port = 8000,
    [int]$Tail = 20,
    [switch]$Advanced,
    [switch]$Strict,
    [string]$SessionToken = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$EnvPath = Join-Path $BackendRoot ".env"
$DbPath = Join-Path $BackendRoot "data\ticketbox.db"
$BackupDir = Join-Path $BackendRoot "backups"
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

function Resolve-SessionToken {
    if ($SessionToken.Trim().Length -gt 0) {
        return $SessionToken.Trim()
    }
    $processValue = [Environment]::GetEnvironmentVariable("TICKETBOX_SESSION_TOKEN")
    if ($processValue -and $processValue.Trim().Length -gt 0) {
        return $processValue.Trim()
    }
    return ""
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

$tasks = Get-ScheduledTask -TaskName TicketboxBackend,TicketboxCloudflareTunnel,TicketboxBackup -ErrorAction SilentlyContinue
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

$backupFiles = @(Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*.db" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending)
if ($backupFiles.Count -gt 0) {
    $latestBackup = $backupFiles[0]
    $backupBytes = ($backupFiles | Measure-Object -Property Length -Sum).Sum
    Add-Row -Target $Summary -Name "最近备份" -Status "OK" -Detail "$($latestBackup.LastWriteTime.ToString('yyyy-MM-dd HH:mm')) · $(Format-Bytes $latestBackup.Length)"
    Add-Row -Target $Summary -Name "备份占用" -Status "OK" -Detail "$(Format-Bytes $backupBytes)"
    Add-Row -Target $Details -Name "备份数量" -Status "OK" -Detail "$($backupFiles.Count) 个"
}
else {
    Add-Row -Target $Summary -Name "最近备份" -Status "WARN" -Detail "暂无 SQLite 备份"
}

Invoke-JsonCheck -Name "本机健康检查" -Uri "http://127.0.0.1:$Port/api/health" -Target $Details | Out-Null
$publicHealth = Invoke-JsonCheck -Name "公网健康检查" -Uri "$BaseUrl/api/health" -Target $Details
if ($publicHealth) {
    Add-Row -Target $Summary -Name "外网访问" -Status "OK" -Detail "正常"
}
else {
    Add-Row -Target $Summary -Name "外网访问" -Status "FAIL" -Detail "不可访问"
}

$resolvedSessionToken = Resolve-SessionToken

if ($resolvedSessionToken.Length -gt 0) {
    $sessionHeaders = @{ Authorization = "Bearer $resolvedSessionToken" }
    $auth = Invoke-JsonCheck -Name "Session 身份检查" -Uri "$BaseUrl/api/auth/check" -Headers $sessionHeaders -Target $Details
    if ($auth) {
        Add-Row -Target $Summary -Name "当前账号" -Status "OK" -Detail $auth.account_name
        Add-Row -Target $Summary -Name "当前账本" -Status "OK" -Detail $auth.ledger_name
        Add-Row -Target $Summary -Name "当前设备" -Status "OK" -Detail $auth.device_name
    }
    $settings = Invoke-JsonCheck -Name "服务概况" -Uri "$BaseUrl/api/settings/server" -Headers $sessionHeaders -Target $Details
    if ($settings) {
        $latestUpload = if ($settings.latest_upload_at) { $settings.latest_upload_at } else { "暂无" }
        Add-Row -Target $Summary -Name "最近上传" -Status "OK" -Detail $latestUpload
        Add-Row -Target $Summary -Name "待确认" -Status "OK" -Detail "$($settings.pending_count) 笔"
        Add-Row -Target $Summary -Name "已入账" -Status "OK" -Detail "$($settings.confirmed_count) 笔"
        Add-Row -Target $Summary -Name "图片占用" -Status "OK" -Detail (Format-Bytes $settings.upload_storage_bytes)
    }
}
else {
    Add-Row -Target $Summary -Name "服务概况" -Status "WARN" -Detail "没有 TICKETBOX_SESSION_TOKEN"
}

Add-Row -Target $Details -Name "UploadLink 检查" -Status "INFO" -Detail "UploadLink 只能 POST 创建 pending，诊断脚本不读取或打印 upload key。"

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
