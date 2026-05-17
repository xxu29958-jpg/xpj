param(
    [string]$Root = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = if ($Root.Trim().Length -gt 0) {
    Resolve-Path -LiteralPath $Root
}
else {
    Resolve-Path (Join-Path $PSScriptRoot "..")
}

$StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$MojibakeMarkers = @(
    "灏", "銆", "锛", "绋", "缁", "璁", "鐨", "丄", "丷", "鈥"
)
$TextExtensions = @(
    ".bat", ".cmd", ".css", ".env.example", ".gradle", ".html", ".json",
    ".kt", ".kts", ".md", ".properties", ".ps1", ".py", ".toml", ".txt",
    ".xml", ".yaml", ".yml"
)
$IgnoredDirectories = @(
    ".git", ".gradle", ".gradle-user", ".idea", ".pytest_cache", ".ruff_cache", ".toolchains",
    "artifacts",
    ".venv", "build", "__pycache__"
)

function Test-IgnoredPath {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    $rootPath = $ProjectRoot.Path.TrimEnd("\", "/")
    $relative = $File.FullName
    if ($relative.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relative = $relative.Substring($rootPath.Length).TrimStart("\", "/")
    }
    $parts = $relative -split "[\\/]"
    foreach ($part in $parts) {
        if ($IgnoredDirectories -contains $part) {
            return $true
        }
    }
    return $false
}

function Test-TextFile {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    if (Test-IgnoredPath -File $File) {
        return
    }

    $name = $File.Name
    $extension = $File.Extension
    $isEnvExample = $name.EndsWith(".env.example", [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $isEnvExample -and -not ($TextExtensions -contains $extension)) {
        return
    }

    $bytes = [System.IO.File]::ReadAllBytes($File.FullName)
    try {
        $text = $StrictUtf8.GetString($bytes)
    }
    catch {
        throw "不是合法 UTF-8：$($File.FullName)"
    }

    if ($extension -eq ".ps1") {
        $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        if (-not $hasBom) {
            throw "PowerShell 脚本必须使用 UTF-8 with BOM：$($File.FullName)"
        }
    }

    if ($text.Contains([char]0xFFFD)) {
        throw "发现 UTF-8 替换字符，疑似编码损坏：$($File.FullName)"
    }

    if ($File.Name -ne "check_text_encoding.ps1") {
        foreach ($marker in $MojibakeMarkers) {
            if ($text.Contains($marker)) {
                throw "发现疑似乱码片段 '$marker'：$($File.FullName)。请确认不是把 UTF-8 当 ANSI 读取后写回。"
            }
        }
    }
}

function Invoke-TextFileCheck {
    param([Parameter(Mandatory = $true)][System.IO.DirectoryInfo]$Directory)

    foreach ($entry in Get-ChildItem -LiteralPath $Directory.FullName -Force -ErrorAction Stop) {
        if ($entry.PSIsContainer) {
            if ($IgnoredDirectories -contains $entry.Name) {
                continue
            }
            Invoke-TextFileCheck -Directory $entry
            continue
        }

        Test-TextFile -File $entry
    }
}

Invoke-TextFileCheck -Directory (Get-Item -LiteralPath $ProjectRoot.Path)

Write-Host "文本编码检查通过：UTF-8 正常，PowerShell 脚本为 UTF-8 with BOM。"
