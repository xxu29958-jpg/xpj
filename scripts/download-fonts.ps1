# scripts/download-fonts.ps1
#
# 下载 /web 桌面账本所需的本地 webfont 子集到 backend/app/static/web/fonts/。
# 一次性运行；产物入 git。后端无需运行时下载、不依赖互联网。
#
# 字体清单：
#   - Noto Sans SC      400 / 500 / 700 / 900   (zh-CN 主字)
#   - Newsreader        400 / 500 / 400i        (期刊大标题衬线，仅拉丁字符)
#   - Inter             400 / 500 / 600         (tabular 数字 + 拉丁)
#
# 实现：调 Google Fonts CSS API（伪装现代浏览器 UA 拿 woff2），解析返回的
# @font-face 里的 .woff2 URL，下载到 fonts/ 目录，文件名规范化为
# "Family-Weight[Italic].woff2"。
#
# 用法（在仓库根目录）：
#   pwsh scripts/download-fonts.ps1
#   # 或 cmd / PowerShell 5.1:
#   powershell -File scripts\download-fonts.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $repoRoot "backend/app/static/web/fonts"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# 现代 Chrome UA，触发 Google Fonts 返回 woff2 而非 ttf
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# 字体族 → 在 Google Fonts CSS API 里的 family 字符串与本地命名映射
$families = @(
    @{
        cssQuery = "Noto+Sans+SC:wght@400;500;700;900"
        weights  = @{ "400" = "Regular"; "500" = "Medium"; "700" = "Bold"; "900" = "Black" }
        prefix   = "NotoSansSC"
    },
    @{
        cssQuery = "Newsreader:ital,wght@0,400;0,500;1,400"
        # ital,wght 元组：0,400=Regular  0,500=Medium  1,400=Italic
        weights  = @{ "400" = "Regular"; "500" = "Medium"; "400i" = "Italic" }
        prefix   = "Newsreader"
    },
    @{
        cssQuery = "Inter:wght@400;500;600"
        weights  = @{ "400" = "Regular"; "500" = "Medium"; "600" = "SemiBold" }
        prefix   = "Inter"
    }
)

foreach ($f in $families) {
    $url = "https://fonts.googleapis.com/css2?family=$($f.cssQuery)&display=swap"
    Write-Host "Fetching CSS for $($f.prefix) ..."
    $css = (Invoke-WebRequest -Uri $url -UserAgent $ua -UseBasicParsing).Content

    # 每个 @font-face 块里抓 (font-weight, font-style, src.url)。
    # Noto Sans SC 会按 unicode-range 切成大量子集；desktop.css 只引用每个
    # 字重的中文主子集文件，所以这里只保留包含 U+4E00（汉字"一"）的块。

    $blocks = [regex]::Matches($css, "@font-face\s*\{([^\}]+)\}")
    Write-Host "  found $($blocks.Count) @font-face blocks"

    foreach ($block in $blocks) {
        $body = $block.Groups[1].Value
        $weight = ([regex]::Match($body, "font-weight:\s*(\d+)")).Groups[1].Value
        $style = ([regex]::Match($body, "font-style:\s*(\w+)")).Groups[1].Value
        $woff2Url = ([regex]::Match($body, "url\(([^)]+\.woff2)\)")).Groups[1].Value
        $range = ([regex]::Match($body, "unicode-range:\s*([^;]+)")).Groups[1].Value

        if (-not $woff2Url) { continue }

        # 命名 key：500 → "500"，italic 加 "i"
        $key = if ($style -eq "italic") { "${weight}i" } else { $weight }
        if (-not $f.weights.ContainsKey($key)) { continue }
        $weightName = $f.weights[$key]

        # 判断是不是中文主子集：unicode-range 包含 U+4E00（汉字"一"）
        $isChinese = $range -match "4E00"
        if ($f.prefix -eq "NotoSansSC" -and -not $isChinese) { continue }
        $suffix = ""

        # Google Fonts 对 CJK 会返回大量 unicode-range 子集。desktop.css 只引用
        # 每个字重的中文主子集标准文件名，不应被误编号成 NotoSansSC-Regular-2.woff2。
        $base = "$($f.prefix)-$weightName$suffix"
        if ($isChinese) {
            $primaryPath = Join-Path $outDir "$base.woff2"
            if (Test-Path -LiteralPath $primaryPath) {
                continue
            }
        }

        $outPath = Join-Path $outDir "$base.woff2"
        Write-Host "  -> $base.woff2 (zh=$isChinese, range head=$($range.Substring(0, [Math]::Min($range.Length, 40))))"
        Invoke-WebRequest -Uri $woff2Url -UserAgent $ua -OutFile $outPath -UseBasicParsing
    }
}

Write-Host ""
Write-Host "Done. Files in: $outDir"
Get-ChildItem $outDir -Filter "*.woff2" | Sort-Object Name | Select-Object Name, @{n="KB";e={[int]($_.Length/1KB)}} | Format-Table
