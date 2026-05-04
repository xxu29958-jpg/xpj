param(
    [string]$Root = "",
    [switch]$FailOnOutdated,
    [switch]$IncludePreRelease,
    [int]$TimeoutSeconds = 20
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

$UserAgent = "ticketbox-dependency-audit/1.0"
$MavenRepositories = @(
    "https://dl.google.com/dl/android/maven2",
    "https://repo.maven.apache.org/maven2"
)
$PluginModuleOverrides = @{
    "com.android.application" = "com.android.tools.build:gradle"
}

function Test-StableVersion {
    param([Parameter(Mandatory = $true)][string]$Version)

    if ($IncludePreRelease) {
        return $true
    }

    $normalized = $Version.ToLowerInvariant()
    if ($normalized -match "(alpha|beta|snapshot|eap|preview)") {
        return $false
    }
    if ($normalized -match "(^|[0-9._-])(a|b)[0-9]+") {
        return $false
    }
    if ($normalized -match "(^|[0-9._-])(rc|pre|dev)[0-9]*($|[._-])") {
        return $false
    }

    return $normalized -notmatch "(?i)m\d+"
}

function Get-VersionParts {
    param([Parameter(Mandatory = $true)][string]$Version)

    $matches = [regex]::Matches($Version, "\d+")
    if ($matches.Count -eq 0) {
        return @(0)
    }

    return @($matches | ForEach-Object { [int]$_.Value })
}

function Compare-VersionString {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $leftParts = Get-VersionParts -Version $Left
    $rightParts = Get-VersionParts -Version $Right
    $length = [Math]::Max($leftParts.Count, $rightParts.Count)

    for ($i = 0; $i -lt $length; $i++) {
        $leftValue = if ($i -lt $leftParts.Count) { $leftParts[$i] } else { 0 }
        $rightValue = if ($i -lt $rightParts.Count) { $rightParts[$i] } else { 0 }
        if ($leftValue -lt $rightValue) {
            return -1
        }
        if ($leftValue -gt $rightValue) {
            return 1
        }
    }

    return [string]::Compare($Left, $Right, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-LatestVersion {
    param([Parameter(Mandatory = $true)][string[]]$Versions)

    $stableVersions = @($Versions | Where-Object { Test-StableVersion -Version $_ })
    if ($stableVersions.Count -eq 0) {
        return $null
    }

    $latest = $stableVersions[0]
    foreach ($version in $stableVersions) {
        if ((Compare-VersionString -Left $version -Right $latest) -gt 0) {
            $latest = $version
        }
    }

    return $latest
}

function Invoke-JsonGet {
    param([Parameter(Mandatory = $true)][string]$Uri)

    return Invoke-RestMethod `
        -Uri $Uri `
        -Headers @{ "User-Agent" = $UserAgent } `
        -TimeoutSec $TimeoutSeconds
}

function Invoke-TextGet {
    param([Parameter(Mandatory = $true)][string]$Uri)

    return (Invoke-WebRequest `
            -Uri $Uri `
            -Headers @{ "User-Agent" = $UserAgent } `
            -TimeoutSec $TimeoutSeconds `
            -UseBasicParsing).Content
}

function Read-VersionCatalog {
    param([Parameter(Mandatory = $true)][string]$Path)

    $versions = @{}
    $libraries = @()
    $plugins = @()
    $section = ""

    foreach ($rawLine in Get-Content -Encoding UTF8 -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith("#")) {
            continue
        }

        if ($line -match "^\[(.+)\]$") {
            $section = $Matches[1]
            continue
        }

        if ($section -eq "versions" -and $line -match "^([A-Za-z0-9_.-]+)\s*=\s*`"([^`"]+)`"") {
            $versions[$Matches[1]] = $Matches[2]
            continue
        }

        if ($section -eq "libraries" -and $line -match "^([A-Za-z0-9_.-]+)\s*=\s*\{(.+)\}$") {
            $alias = $Matches[1]
            $body = $Matches[2]
            if ($body -notmatch "module\s*=\s*`"([^`"]+)`"") {
                continue
            }

            $module = $Matches[1]
            $version = $null
            if ($body -match "version\.ref\s*=\s*`"([^`"]+)`"") {
                $versionRef = $Matches[1]
                if ($versions.ContainsKey($versionRef)) {
                    $version = $versions[$versionRef]
                }
            }
            elseif ($body -match "version\s*=\s*`"([^`"]+)`"") {
                $version = $Matches[1]
            }

            if ($null -ne $version) {
                $libraries += [pscustomobject]@{
                    Alias   = $alias
                    Module  = $module
                    Version = $version
                }
            }
        }

        if ($section -eq "plugins" -and $line -match "^([A-Za-z0-9_.-]+)\s*=\s*\{(.+)\}$") {
            $alias = $Matches[1]
            $body = $Matches[2]
            if ($body -notmatch "id\s*=\s*`"([^`"]+)`"") {
                continue
            }

            $pluginId = $Matches[1]
            $version = $null
            if ($body -match "version\.ref\s*=\s*`"([^`"]+)`"") {
                $versionRef = $Matches[1]
                if ($versions.ContainsKey($versionRef)) {
                    $version = $versions[$versionRef]
                }
            }
            elseif ($body -match "version\s*=\s*`"([^`"]+)`"") {
                $version = $Matches[1]
            }

            if ($null -ne $version) {
                $module = if ($PluginModuleOverrides.ContainsKey($pluginId)) {
                    $PluginModuleOverrides[$pluginId]
                }
                else {
                    "${pluginId}:${pluginId}.gradle.plugin"
                }
                $plugins += [pscustomobject]@{
                    Alias   = $alias
                    Id      = $pluginId
                    Module  = $module
                    Version = $version
                }
            }
        }
    }

    return [pscustomobject]@{
        Libraries = $libraries
        Plugins   = $plugins
    }
}

function Read-RequirementsFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$SeenFiles
    )

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($SeenFiles.ContainsKey($resolved)) {
        return @()
    }
    $SeenFiles[$resolved] = $true

    $items = @()
    $directory = Split-Path -Parent $resolved
    foreach ($rawLine in Get-Content -Encoding UTF8 -LiteralPath $resolved) {
        $line = ($rawLine -split "#", 2)[0].Trim()
        if ($line.Length -eq 0) {
            continue
        }

        if ($line -match "^-r\s+(.+)$") {
            $include = Join-Path $directory $Matches[1].Trim()
            $items += Read-RequirementsFile -Path $include -SeenFiles $SeenFiles
            continue
        }

        if ($line -match "^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)") {
            $items += [pscustomobject]@{
                Name    = $Matches[1]
                Version = $Matches[2]
                File    = $resolved
            }
        }
    }

    return $items
}

function Get-MavenLatestVersion {
    param([Parameter(Mandatory = $true)][string]$Module)

    $parts = $Module.Split(":")
    if ($parts.Count -ne 2) {
        throw "Maven module 格式不正确：$Module"
    }

    $groupPath = $parts[0].Replace(".", "/")
    $artifact = $parts[1]
    $bestLatest = $null
    $bestSource = $null
    foreach ($repository in $MavenRepositories) {
        $metadataUri = "$repository/$groupPath/$artifact/maven-metadata.xml"
        try {
            [xml]$metadata = Invoke-TextGet -Uri $metadataUri
            $versions = @($metadata.metadata.versioning.versions.version | ForEach-Object { [string]$_ })
            $latest = Get-LatestVersion -Versions $versions
            if ($null -ne $latest -and ($null -eq $bestLatest -or (Compare-VersionString -Left $latest -Right $bestLatest) -gt 0)) {
                $bestLatest = $latest
                $bestSource = $metadataUri
            }
        }
        catch {
            continue
        }
    }

    if ($null -eq $bestLatest) {
        return $null
    }

    return [pscustomobject]@{
        Latest = $bestLatest
        Source = $bestSource
    }
}

function Get-PypiLatestVersion {
    param([Parameter(Mandatory = $true)][string]$Package)

    $uri = "https://pypi.org/pypi/$Package/json"
    $json = Invoke-JsonGet -Uri $uri
    $versions = @($json.releases.PSObject.Properties.Name | ForEach-Object { [string]$_ })
    $latest = Get-LatestVersion -Versions $versions
    if ($null -eq $latest) {
        $latest = [string]$json.info.version
    }

    return [pscustomobject]@{
        Latest = $latest
        Source = $uri
    }
}

function Write-CheckResult {
    param(
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Current,
        [string]$Latest,
        [string]$Source,
        [string]$Warning
    )

    if ($Warning) {
        Write-Host "[WARN] $Kind $Name $Current：$Warning"
        return [pscustomobject]@{ Checked = 0; Outdated = 0; Warnings = 1 }
    }

    $comparison = Compare-VersionString -Left $Current -Right $Latest
    if ($comparison -lt 0) {
        Write-Host "[OUTDATED] $Kind $Name $Current -> $Latest"
        Write-Host "           $Source"
        return [pscustomobject]@{ Checked = 1; Outdated = 1; Warnings = 0 }
    }

    Write-Host "[OK] $Kind $Name $Current"
    return [pscustomobject]@{ Checked = 1; Outdated = 0; Warnings = 0 }
}

$checked = 0
$outdated = 0
$warnings = 0

Write-Host "小票夹依赖版本审计"
Write-Host "项目根目录：$($ProjectRoot.Path)"
Write-Host "策略：默认只比较稳定版本，排除 alpha/beta/rc/snapshot/dev/eap/preview。"

$catalogPath = Join-Path $ProjectRoot "android/gradle/libs.versions.toml"
if (Test-Path -LiteralPath $catalogPath) {
    $catalog = Read-VersionCatalog -Path $catalogPath

    Write-Host ""
    Write-Host "Android Maven 依赖："
    $uniqueLibraries = $catalog.Libraries | Sort-Object Module, Version -Unique
    foreach ($library in $uniqueLibraries) {
        try {
            $latest = Get-MavenLatestVersion -Module $library.Module
            if ($null -eq $latest) {
                $result = Write-CheckResult -Kind "maven" -Name $library.Module -Current $library.Version -Warning "没有在 Google Maven 或 Maven Central 找到 metadata"
            }
            else {
                $result = Write-CheckResult -Kind "maven" -Name $library.Module -Current $library.Version -Latest $latest.Latest -Source $latest.Source
            }
        }
        catch {
            $result = Write-CheckResult -Kind "maven" -Name $library.Module -Current $library.Version -Warning $_.Exception.Message
        }
        $checked += $result.Checked
        $outdated += $result.Outdated
        $warnings += $result.Warnings
    }

    Write-Host ""
    Write-Host "Android Gradle 插件："
    $uniquePlugins = $catalog.Plugins | Sort-Object Module, Version -Unique
    foreach ($plugin in $uniquePlugins) {
        try {
            $latest = Get-MavenLatestVersion -Module $plugin.Module
            if ($null -eq $latest) {
                $result = Write-CheckResult -Kind "plugin" -Name $plugin.Id -Current $plugin.Version -Warning "没有在 Google Maven 或 Maven Central 找到 metadata"
            }
            else {
                $result = Write-CheckResult -Kind "plugin" -Name $plugin.Id -Current $plugin.Version -Latest $latest.Latest -Source $latest.Source
            }
        }
        catch {
            $result = Write-CheckResult -Kind "plugin" -Name $plugin.Id -Current $plugin.Version -Warning $_.Exception.Message
        }
        $checked += $result.Checked
        $outdated += $result.Outdated
        $warnings += $result.Warnings
    }
}

$requirementsPaths = @(
    (Join-Path $ProjectRoot "backend/requirements.txt"),
    (Join-Path $ProjectRoot "backend/requirements-dev.txt")
) | Where-Object { Test-Path -LiteralPath $_ }

if ($requirementsPaths.Count -gt 0) {
    Write-Host ""
    Write-Host "Python PyPI 依赖："
    $seenFiles = @{}
    $packages = @()
    foreach ($requirementsPath in $requirementsPaths) {
        $packages += Read-RequirementsFile -Path $requirementsPath -SeenFiles $seenFiles
    }
    $uniquePackages = $packages | Sort-Object Name, Version -Unique
    foreach ($package in $uniquePackages) {
        try {
            $latest = Get-PypiLatestVersion -Package $package.Name
            $result = Write-CheckResult -Kind "pypi" -Name $package.Name -Current $package.Version -Latest $latest.Latest -Source $latest.Source
        }
        catch {
            $result = Write-CheckResult -Kind "pypi" -Name $package.Name -Current $package.Version -Warning $_.Exception.Message
        }
        $checked += $result.Checked
        $outdated += $result.Outdated
        $warnings += $result.Warnings
    }
}

Write-Host ""
Write-Host "审计结果：checked=$checked outdated=$outdated warnings=$warnings"
if ($FailOnOutdated -and $outdated -gt 0) {
    throw "发现 $outdated 个稳定版本落后依赖。请评估升级，或临时不使用 -FailOnOutdated。"
}
