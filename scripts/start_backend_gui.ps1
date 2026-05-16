param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$LogDir = Join-Path $BackendRoot "logs"
$StartScript = Join-Path $ProjectRoot "scripts\start_backend.ps1"
$StopScript = Join-Path $ProjectRoot "scripts\stop_backend.ps1"
$RestartScript = Join-Path $ProjectRoot "scripts\restart_backend.ps1"

function New-UiFont {
    param(
        [float]$Size,
        [System.Drawing.FontStyle]$Style = [System.Drawing.FontStyle]::Regular
    )
    return [System.Drawing.Font]::new("Microsoft YaHei UI", $Size, $Style)
}

function Get-LocalUrl {
    param([string]$Path = "/api/health")
    return "http://127.0.0.1:$($portBox.Value)$Path"
}

function Add-LogLine {
    param([string]$Text)
    $timestamp = Get-Date -Format "HH:mm:ss"
    $logBox.AppendText("[$timestamp] $Text`r`n")
    $logBox.SelectionStart = $logBox.TextLength
    $logBox.ScrollToCaret()
}

function Set-Status {
    param(
        [string]$Text,
        [System.Drawing.Color]$Color
    )
    $statusValue.Text = $Text
    $statusValue.ForeColor = $Color
}

function Invoke-ProjectScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$Arguments = @()
    )

    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        throw "脚本不存在：$ScriptPath"
    }

    function ConvertTo-CommandLineArgument {
        param([string]$Value)
        if ($Value -notmatch '[\s"]') {
            return $Value
        }
        return '"' + ($Value -replace '"', '\"') + '"'
    }

    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $ScriptPath
    ) + $Arguments

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = "powershell.exe"
    $psi.Arguments = ($argList | ForEach-Object { ConvertTo-CommandLineArgument $_ }) -join " "
    $psi.WorkingDirectory = $ProjectRoot.Path
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($psi)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    if ($stdout.Trim().Length -gt 0) {
        Add-LogLine $stdout.Trim()
    }
    if ($stderr.Trim().Length -gt 0) {
        Add-LogLine $stderr.Trim()
    }
    if ($process.ExitCode -ne 0) {
        throw "脚本执行失败，exit=$($process.ExitCode)"
    }
}

function Test-BackendHealth {
    try {
        $response = Invoke-RestMethod -Uri (Get-LocalUrl "/api/health") -TimeoutSec 4
        if ($response.status -eq "ok") {
            $version = [string]$response.backend_version
            if ($version.Trim().Length -eq 0) {
                $version = "未知版本"
            }
            Set-Status "运行中 · $version" ([System.Drawing.Color]::FromArgb(34, 122, 75))
            $openWebButton.Enabled = $true
            $openOwnerButton.Enabled = $true
            return $true
        }
    }
    catch {
        $listener = Get-NetTCPConnection -LocalPort ([int]$portBox.Value) -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener) {
            Set-Status "端口监听中，但健康检查失败" ([System.Drawing.Color]::FromArgb(170, 95, 0))
            $openWebButton.Enabled = $true
            $openOwnerButton.Enabled = $true
            return $false
        }
    }

    Set-Status "未运行" ([System.Drawing.Color]::FromArgb(150, 55, 55))
    $openWebButton.Enabled = $false
    $openOwnerButton.Enabled = $false
    return $false
}

function Refresh-LogTail {
    $logBox.Clear()
    Add-LogLine "项目目录：$($ProjectRoot.Path)"
    Add-LogLine "后端目录：$BackendRoot"
    Add-LogLine "本机地址：http://127.0.0.1:$($portBox.Value)"

    if (-not (Test-Path -LiteralPath $LogDir)) {
        Add-LogLine "暂无日志目录。"
        return
    }

    $latestLogs = Get-ChildItem -LiteralPath $LogDir -Filter "ticketbox-backend-*.err.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latestLogs) {
        $latestLogs = Get-ChildItem -LiteralPath $LogDir -Filter "ticketbox-backend-*.out.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    }
    if (-not $latestLogs) {
        Add-LogLine "未找到后端日志。"
        return
    }

    Add-LogLine "最近日志：$($latestLogs.FullName)"
    $tail = Get-Content -Encoding UTF8 -LiteralPath $latestLogs.FullName -Tail 80 -ErrorAction SilentlyContinue
    foreach ($line in $tail) {
        $logBox.AppendText("$line`r`n")
    }
}

function Run-UiAction {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    try {
        $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
        $buttons = @($startButton, $stopButton, $restartButton, $healthButton, $refreshLogButton)
        foreach ($button in $buttons) {
            $button.Enabled = $false
        }
        Add-LogLine "开始：$Name"
        & $Action
        Add-LogLine "完成：$Name"
    }
    catch {
        Add-LogLine "失败：$Name。$($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            "小票夹后端 GUI",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    finally {
        foreach ($button in @($startButton, $stopButton, $restartButton, $healthButton, $refreshLogButton)) {
            $button.Enabled = $true
        }
        $form.Cursor = [System.Windows.Forms.Cursors]::Default
        [void](Test-BackendHealth)
    }
}

$form = [System.Windows.Forms.Form]::new()
$form.Text = "小票夹后端"
$form.StartPosition = "CenterScreen"
$form.Size = [System.Drawing.Size]::new(760, 560)
$form.MinimumSize = [System.Drawing.Size]::new(680, 480)
$form.Font = New-UiFont 10

$titleLabel = [System.Windows.Forms.Label]::new()
$titleLabel.Text = "小票夹后端"
$titleLabel.Font = New-UiFont 18 ([System.Drawing.FontStyle]::Bold)
$titleLabel.AutoSize = $true
$titleLabel.Location = [System.Drawing.Point]::new(24, 22)
$form.Controls.Add($titleLabel)

$subtitleLabel = [System.Windows.Forms.Label]::new()
$subtitleLabel.Text = "本机 FastAPI 服务运维壳，业务操作仍在 /web 和 /owner。"
$subtitleLabel.AutoSize = $true
$subtitleLabel.ForeColor = [System.Drawing.Color]::FromArgb(96, 111, 120)
$subtitleLabel.Location = [System.Drawing.Point]::new(27, 62)
$form.Controls.Add($subtitleLabel)

$statusLabel = [System.Windows.Forms.Label]::new()
$statusLabel.Text = "状态"
$statusLabel.AutoSize = $true
$statusLabel.Location = [System.Drawing.Point]::new(27, 104)
$form.Controls.Add($statusLabel)

$statusValue = [System.Windows.Forms.Label]::new()
$statusValue.Text = "检查中..."
$statusValue.Font = New-UiFont 11 ([System.Drawing.FontStyle]::Bold)
$statusValue.AutoSize = $true
$statusValue.Location = [System.Drawing.Point]::new(82, 101)
$form.Controls.Add($statusValue)

$portLabel = [System.Windows.Forms.Label]::new()
$portLabel.Text = "端口"
$portLabel.AutoSize = $true
$portLabel.Location = [System.Drawing.Point]::new(27, 142)
$form.Controls.Add($portLabel)

$portBox = [System.Windows.Forms.NumericUpDown]::new()
$portBox.Minimum = 1024
$portBox.Maximum = 65535
$portBox.Value = $Port
$portBox.Width = 96
$portBox.Location = [System.Drawing.Point]::new(82, 138)
$form.Controls.Add($portBox)

$urlLabel = [System.Windows.Forms.Label]::new()
$urlLabel.Text = "本机地址：http://127.0.0.1:$Port"
$urlLabel.AutoSize = $true
$urlLabel.ForeColor = [System.Drawing.Color]::FromArgb(96, 111, 120)
$urlLabel.Location = [System.Drawing.Point]::new(198, 142)
$form.Controls.Add($urlLabel)

$portBox.Add_ValueChanged({
    $urlLabel.Text = "本机地址：http://127.0.0.1:$($portBox.Value)"
    [void](Test-BackendHealth)
})

$buttonPanel = [System.Windows.Forms.FlowLayoutPanel]::new()
$buttonPanel.Location = [System.Drawing.Point]::new(24, 182)
$buttonPanel.Size = [System.Drawing.Size]::new(700, 48)
$buttonPanel.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$buttonPanel.WrapContents = $false
$form.Controls.Add($buttonPanel)

function New-Button {
    param(
        [string]$Text,
        [int]$Width = 96
    )
    $button = [System.Windows.Forms.Button]::new()
    $button.Text = $Text
    $button.Width = $Width
    $button.Height = 34
    $button.Margin = [System.Windows.Forms.Padding]::new(0, 0, 10, 0)
    return $button
}

$startButton = New-Button "启动"
$stopButton = New-Button "停止"
$restartButton = New-Button "重启"
$healthButton = New-Button "检查"
$openWebButton = New-Button "打开 /web" 110
$openOwnerButton = New-Button "打开 /owner" 120
$refreshLogButton = New-Button "刷新日志" 110

$buttonPanel.Controls.AddRange(@(
    $startButton,
    $stopButton,
    $restartButton,
    $healthButton,
    $openWebButton,
    $openOwnerButton,
    $refreshLogButton
))

$logBox = [System.Windows.Forms.TextBox]::new()
$logBox.Multiline = $true
$logBox.ReadOnly = $true
$logBox.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$logBox.WordWrap = $false
$logBox.Font = [System.Drawing.Font]::new("Consolas", 9)
$logBox.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
$logBox.Location = [System.Drawing.Point]::new(24, 250)
$logBox.Size = [System.Drawing.Size]::new(700, 250)
$form.Controls.Add($logBox)

$startButton.Add_Click({
    Run-UiAction "启动后端" {
        Invoke-ProjectScript -ScriptPath $StartScript -Arguments @("-Port", "$([int]$portBox.Value)")
    }
})

$stopButton.Add_Click({
    Run-UiAction "停止后端" {
        Invoke-ProjectScript -ScriptPath $StopScript -Arguments @("-Port", "$([int]$portBox.Value)")
    }
})

$restartButton.Add_Click({
    Run-UiAction "重启后端" {
        Invoke-ProjectScript -ScriptPath $RestartScript -Arguments @("-Port", "$([int]$portBox.Value)")
    }
})

$healthButton.Add_Click({
    Run-UiAction "检查状态" {
        if (-not (Test-BackendHealth)) {
            Add-LogLine "健康检查未通过：$(Get-LocalUrl "/api/health")"
        }
    }
})

$openWebButton.Add_Click({
    Start-Process (Get-LocalUrl "/web")
})

$openOwnerButton.Add_Click({
    Start-Process (Get-LocalUrl "/owner")
})

$refreshLogButton.Add_Click({
    Run-UiAction "刷新日志" {
        Refresh-LogTail
    }
})

$form.Add_Shown({
    Refresh-LogTail
    [void](Test-BackendHealth)
})

[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::Run($form)
