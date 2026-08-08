#Requires -Version 5.1
<#
.SYNOPSIS
  Establish the machine-wide Windows prerequisites required by Ticketbox.

.DESCRIPTION
  Runs before Ticketbox program files, services, database state, or installation
  identity are mutated. The bundled Microsoft Visual C++ Redistributable is
  hash-pinned by the exact installer build, installed centrally, and intentionally
  remains installed when Ticketbox is rolled back or uninstalled.
#>
[CmdletBinding()]
param(
    [string]$VcRedistPath = "",
    [string]$RequiredVersion = "",
    [string]$RequiredSha256 = "",
    [string]$DiagnosticLogPath = "",
    [int]$InstallerLockOwnerProcessId = 0,
    [string]$VersionContractProbe = "",
    [string]$OtherVersionContractProbe = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function ConvertTo-TicketboxVisualCppRuntimeVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $match = [regex]::Match(
        $Value.Trim(),
        '^[vV]?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?$'
    )
    if (-not $match.Success) {
        throw "$Label 不是 2-4 段十进制版本：$Value"
    }
    $parts = New-Object int[] 4
    for ($index = 1; $index -le 4; $index++) {
        if ($match.Groups[$index].Success) {
            $parsed = 0
            if (-not [int]::TryParse(
                $match.Groups[$index].Value,
                [Globalization.NumberStyles]::None,
                [Globalization.CultureInfo]::InvariantCulture,
                [ref]$parsed
            )) {
                throw "$Label 版本段超出范围：$Value"
            }
            $parts[$index - 1] = $parsed
        }
    }
    return [Version]::new($parts[0], $parts[1], $parts[2], $parts[3])
}

function Compare-TicketboxVisualCppRuntimeVersions {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $leftVersion = ConvertTo-TicketboxVisualCppRuntimeVersion $Left "左侧 VC runtime"
    $rightVersion = ConvertTo-TicketboxVisualCppRuntimeVersion $Right "右侧 VC runtime"
    return [Math]::Sign($leftVersion.CompareTo($rightVersion))
}

if ($VersionContractProbe.Trim().Length -gt 0 -or
    $OtherVersionContractProbe.Trim().Length -gt 0) {
    if ($VersionContractProbe.Trim().Length -eq 0 -or
        $OtherVersionContractProbe.Trim().Length -eq 0) {
        throw "版本合同探针必须同时提供两个版本。"
    }
    $left = ConvertTo-TicketboxVisualCppRuntimeVersion `
        $VersionContractProbe `
        "版本合同探针左侧"
    $right = ConvertTo-TicketboxVisualCppRuntimeVersion `
        $OtherVersionContractProbe `
        "版本合同探针右侧"
    [ordered]@{
        left = $left.ToString(4)
        right = $right.ToString(4)
        comparison = [Math]::Sign($left.CompareTo($right))
    } | ConvertTo-Json -Compress
    return
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SafetyScript = Join-Path $ScriptDir "windows_installation_safety.ps1"
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
foreach ($dependency in @($SafetyScript, $LockScript)) {
    if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) {
        throw "Windows prerequisite bootstrap dependency is missing: $dependency"
    }
}
. $SafetyScript
. $LockScript

function Assert-TicketboxPrerequisiteAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) {
        throw "Windows prerequisite installation requires an elevated administrator token."
    }
}

function Write-TicketboxPrerequisiteEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Event,
        [Parameter(Mandatory = $true)][string]$CorrelationId,
        [System.Collections.IDictionary]$Fields = @{}
    )

    Write-Host "TBX_PREREQ_SCHEMA=ticketbox-windows-prerequisite-v1"
    Write-Host "TBX_PREREQ_EVENT=$Event"
    Write-Host "CORRELATION_ID=$CorrelationId"
    foreach ($name in @($Fields.Keys | Sort-Object)) {
        $value = [Convert]::ToString(
            $Fields[$name],
            [Globalization.CultureInfo]::InvariantCulture
        )
        if ($value.Contains("`r") -or $value.Contains("`n")) {
            throw "Windows prerequisite log field contains a newline: $name"
        }
        Write-Host ("{0}={1}" -f $name.ToUpperInvariant(), $value)
    }
}

function Get-TicketboxVisualCppRuntimeRegistryVersion {
    $baseKey = $null
    $runtimeKey = $null
    try {
        $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
            [Microsoft.Win32.RegistryHive]::LocalMachine,
            [Microsoft.Win32.RegistryView]::Registry64
        )
        $runtimeKey = $baseKey.OpenSubKey(
            'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
            $false
        )
        if ($null -eq $runtimeKey) {
            return $null
        }
        $installed = $runtimeKey.GetValue('Installed', $null)
        if ($null -eq $installed -or [int64]$installed -ne 1) {
            return $null
        }
        $versionText = [string]$runtimeKey.GetValue('Version', '')
        if (-not [string]::IsNullOrWhiteSpace($versionText)) {
            return ConvertTo-TicketboxVisualCppRuntimeVersion `
                $versionText `
                "已安装 VC runtime 注册表 Version"
        }
        $parts = @('Major', 'Minor', 'Bld', 'Rbld') | ForEach-Object {
            $value = $runtimeKey.GetValue($_, $null)
            if ($null -eq $value -or [int64]$value -lt 0 -or
                [int64]$value -gt [int]::MaxValue) {
                throw "已安装 VC runtime 注册表缺少有效的 $_。"
            }
            [int]$value
        }
        return [Version]::new($parts[0], $parts[1], $parts[2], $parts[3])
    }
    finally {
        if ($null -ne $runtimeKey) { $runtimeKey.Dispose() }
        if ($null -ne $baseKey) { $baseKey.Dispose() }
    }
}

function Get-TicketboxVisualCppRuntimeState {
    param([Parameter(Mandatory = $true)][Version]$Required)

    if (-not [Environment]::Is64BitOperatingSystem -or
        -not [Environment]::Is64BitProcess) {
        throw "Ticketbox x64 prerequisite probe requires a 64-bit Windows process."
    }
    $registryVersion = Get-TicketboxVisualCppRuntimeRegistryVersion
    $runtimePath = Join-Path $env:windir 'System32\VCRUNTIME140.dll'
    $runtimeVersion = $null
    if (Test-Path -LiteralPath $runtimePath -PathType Leaf) {
        $runtimeItem = Get-Item -LiteralPath $runtimePath -Force -ErrorAction Stop
        if (($runtimeItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "System32 VCRUNTIME140.dll cannot be a reparse point."
        }
        $runtimeVersion = ConvertTo-TicketboxVisualCppRuntimeVersion `
            ([Diagnostics.FileVersionInfo]::GetVersionInfo($runtimePath).FileVersion) `
            "System32 VCRUNTIME140.dll FileVersion"
    }
    return [pscustomobject]@{
        RegistryVersion = $registryVersion
        RuntimeFile = $runtimePath
        RuntimeFileVersion = $runtimeVersion
        Satisfied = (
            $null -ne $registryVersion -and
            $registryVersion.CompareTo($Required) -ge 0 -and
            $null -ne $runtimeVersion -and
            $runtimeVersion.CompareTo($Required) -ge 0
        )
    }
}

function Assert-TicketboxVisualCppRedistributable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )

    if ($ExpectedSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "Bundled VC redistributable SHA-256 pin is invalid."
    }
    $fullPath = [IO.Path]::GetFullPath($Path)
    Assert-NoTicketboxAncestorReparsePoints (Split-Path -Parent $fullPath)
    if ((Get-TicketboxPathEntryKindNoFollow $fullPath) -cne 'File') {
        throw "Bundled VC redistributable is missing or is not a regular file."
    }
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Bundled VC redistributable cannot be a reparse point."
    }
    $actualHash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
    if ($actualHash -ine $ExpectedSha256) {
        throw "Bundled VC redistributable SHA-256 does not match this installer build."
    }
    return $fullPath
}

function Assert-TicketboxPrerequisiteDiagnosticLogPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    if ($fullPath.Contains('"') -or $fullPath.Contains("`r") -or
        $fullPath.Contains("`n")) {
        throw "Windows prerequisite diagnostic log path contains unsafe characters."
    }
    $parent = Split-Path -Parent $fullPath
    Assert-NoTicketboxAncestorReparsePoints $parent
    Assert-TicketboxProtectedDirectoryAcl -Path $parent
    if ((Get-TicketboxPathEntryKindNoFollow $fullPath) -cne 'Missing') {
        throw "Windows prerequisite diagnostic log path must be new."
    }
    return $fullPath
}

function Format-TicketboxOptionalVersion([AllowNull()][Version]$Version) {
    if ($null -eq $Version) { return 'missing' }
    return $Version.ToString(4)
}

if ($VcRedistPath.Trim().Length -eq 0 -or
    $RequiredVersion.Trim().Length -eq 0 -or
    $RequiredSha256.Trim().Length -eq 0 -or
    $DiagnosticLogPath.Trim().Length -eq 0 -or
    $InstallerLockOwnerProcessId -le 0) {
    throw "Normal prerequisite execution requires the pinned payload, version, hash, protected log, and installer lock owner."
}

$required = ConvertTo-TicketboxVisualCppRuntimeVersion `
    $RequiredVersion `
    "Ticketbox required VC runtime"
$operationLock = $null
$correlationId = "{0}:{1}" -f `
    $InstallerLockOwnerProcessId,
    [IO.Path]::GetFileName($DiagnosticLogPath)
try {
    $operationLock = Enter-TicketboxLifecycleLock `
        -ExternalOwnerProcessId $InstallerLockOwnerProcessId
    Assert-TicketboxPrerequisiteAdministrator
    $redist = Assert-TicketboxVisualCppRedistributable `
        -Path $VcRedistPath `
        -ExpectedSha256 $RequiredSha256
    $diagnosticLog = Assert-TicketboxPrerequisiteDiagnosticLogPath `
        $DiagnosticLogPath
    $before = Get-TicketboxVisualCppRuntimeState $required
    Write-TicketboxPrerequisiteEvent `
        -Event 'probe_before' `
        -CorrelationId $correlationId `
        -Fields ([ordered]@{
            component = 'visual_cpp_runtime_x64'
            installer_owner_pid = $InstallerLockOwnerProcessId
            required_version = $required.ToString(4)
            registry_version = Format-TicketboxOptionalVersion $before.RegistryVersion
            runtime_file_version = Format-TicketboxOptionalVersion $before.RuntimeFileVersion
            satisfied = $before.Satisfied.ToString().ToLowerInvariant()
        })
    if ($before.Satisfied) {
        Write-TicketboxPrerequisiteEvent `
            -Event 'complete' `
            -CorrelationId $correlationId `
            -Fields ([ordered]@{
                action = 'already_satisfied'
                retry_class = 'none'
                support_code = 'none'
            })
        return
    }

    $action = '/install'
    if ($null -ne $before.RegistryVersion -and
        $before.RegistryVersion.CompareTo($required) -ge 0) {
        if ($before.RegistryVersion.CompareTo($required) -gt 0) {
            throw (
                "A newer machine-wide VC runtime is registered but its System32 runtime file " +
                "is missing or older. Ticketbox will not downgrade or overwrite it. " +
                "SUPPORT_CODE=TBX-INSTALL-PREREQ-INCONSISTENT"
            )
        }
        $action = '/repair'
    }

    Write-TicketboxPrerequisiteEvent `
        -Event 'native_start' `
        -CorrelationId $correlationId `
        -Fields ([ordered]@{
            action = $action.TrimStart('/')
            diagnostic_log_path = $diagnosticLog
            payload_sha256 = $RequiredSha256.ToLowerInvariant()
        })
    $nativeArguments = @(
        $action,
        '/quiet',
        '/norestart',
        '/log',
        ('"{0}"' -f $diagnosticLog)
    )
    $process = Start-Process `
        -FilePath $redist `
        -ArgumentList $nativeArguments `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    $nativeExitCode = [int]$process.ExitCode
    if ((Get-TicketboxPathEntryKindNoFollow $diagnosticLog) -cne 'File') {
        throw "Microsoft VC redistributable did not publish the requested diagnostic log."
    }
    $logItem = Get-Item -LiteralPath $diagnosticLog -Force -ErrorAction Stop
    if (($logItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Microsoft VC redistributable diagnostic log became a reparse point."
    }
    $after = Get-TicketboxVisualCppRuntimeState $required
    Write-TicketboxPrerequisiteEvent `
        -Event 'native_complete' `
        -CorrelationId $correlationId `
        -Fields ([ordered]@{
            native_exit_code = $nativeExitCode
            registry_version = Format-TicketboxOptionalVersion $after.RegistryVersion
            runtime_file_version = Format-TicketboxOptionalVersion $after.RuntimeFileVersion
            satisfied = $after.Satisfied.ToString().ToLowerInvariant()
        })

    if ($nativeExitCode -in @(1641, 3010)) {
        Write-TicketboxPrerequisiteEvent `
            -Event 'restart_required' `
            -CorrelationId $correlationId `
            -Fields ([ordered]@{
                native_exit_code = $nativeExitCode
                retry_class = 'reboot_then_rerun_same_installer'
                support_code = 'TBX-INSTALL-PREREQ-RESTART'
            })
        $global:LASTEXITCODE = $nativeExitCode
        return
    }
    if ($nativeExitCode -eq 0 -and $after.Satisfied) {
        Write-TicketboxPrerequisiteEvent `
            -Event 'complete' `
            -CorrelationId $correlationId `
            -Fields ([ordered]@{
                action = $action.TrimStart('/')
                retry_class = 'none'
                support_code = 'none'
            })
        return
    }
    if ($nativeExitCode -eq 1638 -and $after.Satisfied) {
        Write-TicketboxPrerequisiteEvent `
            -Event 'complete' `
            -CorrelationId $correlationId `
            -Fields ([ordered]@{
                action = 'reconciled_newer_runtime_race'
                native_exit_code = $nativeExitCode
                retry_class = 'none'
                support_code = 'none'
            })
        return
    }
    throw (
        "Microsoft VC redistributable prerequisite did not reach the required state " +
        "(native_exit=$nativeExitCode, registry=" +
        "$(Format-TicketboxOptionalVersion $after.RegistryVersion), runtime_file=" +
        "$(Format-TicketboxOptionalVersion $after.RuntimeFileVersion)). " +
        "SUPPORT_CODE=TBX-INSTALL-PREREQ"
    )
}
finally {
    Exit-TicketboxLifecycleLock $operationLock
}
