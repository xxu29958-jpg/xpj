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
# 合法包含 marker 字面量的文件：本脚本定义 marker 列表，runbook 文档化 marker 示例。
# 这些文件仍受非法 UTF-8 / U+FFFD 检查约束，只豁免「marker 字符」这条兜底启发式。
# 用「相对仓库根的正斜杠路径」精确匹配，避免同名文件落到别处时被误豁免。
$MojibakeMarkerAllowlist = @(
    "scripts/check_text_encoding.ps1",
    "docs/runbook/windows-powershell-gotchas.md"
)
$TextExtensions = @(
    ".bat", ".cmd", ".css", ".env.example", ".gradle", ".html", ".json",
    ".kt", ".kts", ".md", ".properties", ".ps1", ".py", ".toml", ".txt",
    ".xml", ".yaml", ".yml"
)
$IgnoredDirectories = @(
    ".claude", ".git", ".gradle", ".gradle-user", ".idea", ".pytest_cache", ".ruff_cache", ".toolchains",
    ".venv", ".venv-build", ".ci-venv", "build", "__pycache__"
)
# 按「相对仓库根的路径前缀」忽略（区别于上面的目录名段匹配）：捆绑 PG/Shawl 原生二进制目录
# 含 PG tsearch 词典等**非 UTF-8** 文本，本地存在时不应误触发编码门（gitignore 忽略、永不进
# CI 检出）。用前缀而非裸 "vendor" 段——后者会误伤 backend/app/static/*/vendor 的受跟踪资产。
# 见 ADR-0047 Slice 2-C。
$IgnoredPathPrefixes = @(
    "backend/packaging/vendor"
)

function Get-RelativePath {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    $rootPath = $ProjectRoot.Path.TrimEnd("\", "/")
    $relative = $File.FullName
    if ($relative.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relative = $relative.Substring($rootPath.Length).TrimStart("\", "/")
    }
    return ($relative -replace "\\", "/")
}

function Test-IgnoredPath {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    $relative = Get-RelativePath -File $File
    foreach ($prefix in $IgnoredPathPrefixes) {
        if ($relative.StartsWith($prefix + "/", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    $parts = $relative -split "/"
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

    if ($MojibakeMarkerAllowlist -notcontains (Get-RelativePath -File $File)) {
        foreach ($marker in $MojibakeMarkers) {
            if ($text.Contains($marker)) {
                throw "发现疑似乱码片段 '$marker'：$($File.FullName)。请确认不是把 UTF-8 当 ANSI 读取后写回。"
            }
        }
    }
}

Get-ChildItem -LiteralPath $ProjectRoot -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    Test-TextFile -File $_
}

Write-Host "文本编码检查通过：UTF-8 正常，PowerShell 脚本为 UTF-8 with BOM。"
