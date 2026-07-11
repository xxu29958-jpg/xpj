#Requires -Version 5.1

$script:TicketboxPgRecoveryDirectoryName = "postgresql-preserved-data-recovery"
$script:TicketboxPgRecoveryCompletionName = "BUILD_COMPLETE.json"
$script:TicketboxPgRecoveryManifestName = "BUILD_PROVENANCE.json"
$script:TicketboxPgRecoveryFullControlAccounts = @("SYSTEM", "BUILTIN\Administrators")
$script:TicketboxPgRecoveryOwnerAccount = "SYSTEM"

function Get-TicketboxPgRecoveryRoot {
    $lifecycleDirectory = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    return Join-Path $lifecycleDirectory $script:TicketboxPgRecoveryDirectoryName
}

function Get-TicketboxPgRecoveryHome {
    return Join-Path (Get-TicketboxPgRecoveryRoot) "pg"
}

function Read-TicketboxPgRecoveryBuildManifest([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 PostgreSQL 恢复工具 provenance：$Path"
    }
    try {
        $manifest = Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "PostgreSQL 恢复工具 provenance 不是有效 JSON：$Path"
    }
    if (
        [int]$manifest.schema_version -ne 3 -or
        [string]$manifest.artifact_type -cne "ticketbox-windows-installer-inputs" -or
        [string]$manifest.postgresql.payload_algorithm -cne "SHA-256" -or
        [string]$manifest.postgresql.payload_fingerprint -notmatch '^[0-9a-f]{64}$' -or
        [int]$manifest.postgresql.payload_file_count -le 0 -or
        [int]$manifest.postgresql.major -le 0
    ) {
        throw "PostgreSQL 恢复工具 provenance schema 或 payload 证据无效。"
    }
    return $manifest
}

function Get-TicketboxPgRecoveryPayloadSnapshot([string]$PgHome) {
    if (-not (Test-Path -LiteralPath $PgHome -PathType Container)) {
        throw "缺少 PostgreSQL 恢复工具目录：$PgHome"
    }
    Assert-NoTicketboxAncestorReparsePoints $PgHome
    $paths = @(
        Get-ChildItem -LiteralPath $PgHome -Recurse -File |
            ForEach-Object { $_.FullName }
    )
    return Get-TicketboxFileSetSnapshot $PgHome $paths
}

function Assert-TicketboxPgRecoveryPayload {
    param(
        [Parameter(Mandatory = $true)][string]$PgHome,
        [Parameter(Mandatory = $true)][string]$BuildManifestPath,
        [Parameter(Mandatory = $true)][int]$ExpectedMajor
    )

    $manifest = Read-TicketboxPgRecoveryBuildManifest $BuildManifestPath
    if ([int]$manifest.postgresql.major -ne $ExpectedMajor) {
        throw "PostgreSQL 恢复工具 major 与数据簇不一致：tools=$($manifest.postgresql.major)，data=$ExpectedMajor"
    }
    $snapshot = Get-TicketboxPgRecoveryPayloadSnapshot $PgHome
    if (
        $snapshot.fingerprint -cne [string]$manifest.postgresql.payload_fingerprint -or
        @($snapshot.files).Count -ne [int]$manifest.postgresql.payload_file_count
    ) {
        throw "PostgreSQL 恢复工具 payload 与安装 provenance 不一致。"
    }
    foreach ($name in @(
        "postgres.exe",
        "pg_ctl.exe",
        "pg_isready.exe",
        "psql.exe",
        "pg_dump.exe",
        "pg_restore.exe"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $PgHome "bin\$name") -PathType Leaf)) {
            throw "PostgreSQL 恢复工具缺少关键文件：$name"
        }
    }
    return [pscustomobject]@{
        Home = [System.IO.Path]::GetFullPath($PgHome)
        Manifest = $manifest
        Snapshot = $snapshot
    }
}

function Set-TicketboxPgRecoveryAcl([string[]]$ReadExecuteAccounts = @()) {
    $root = Get-TicketboxPgRecoveryRoot
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return }
    Set-TicketboxExactDirectoryAcl `
        -Path $root `
        -Accounts $script:TicketboxPgRecoveryFullControlAccounts `
        -InheritableReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $script:TicketboxPgRecoveryOwnerAccount `
        -Recurse
}

function Assert-TicketboxPgRecoveryAcl([string[]]$ReadExecuteAccounts = @()) {
    $root = Get-TicketboxPgRecoveryRoot
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "缺少 PostgreSQL 恢复工具根目录：$root"
    }
    Assert-NoTicketboxReparsePoints $root
    $fullControlSids = @($script:TicketboxPgRecoveryFullControlAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    $readExecuteSids = @($ReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    if (@($fullControlSids | Where-Object { $_ -in $readExecuteSids }).Count -gt 0) {
        throw "PostgreSQL 恢复工具 FullControl 与 ReadExecute 账户不能重叠。"
    }
    $allowedSids = @($fullControlSids + $readExecuteSids | Sort-Object -Unique)
    $ownerSid = ConvertTo-TicketboxAccountSid $script:TicketboxPgRecoveryOwnerAccount
    $paths = @($root) + @(Get-ChildItem -LiteralPath $root -Force -Recurse | ForEach-Object {
        $_.FullName
    })
    foreach ($path in $paths) {
        $acl = Get-TicketboxPathAcl $path
        $isRoot = Test-TicketboxPathEquals $path $root
        if ((ConvertTo-TicketboxAccountSid $acl.Owner) -ne $ownerSid) {
            throw "PostgreSQL 恢复工具 ACL owner 不一致：$path"
        }
        if ($isRoot -and -not $acl.AreAccessRulesProtected) {
            throw "PostgreSQL 恢复工具根目录仍继承外部 ACL。"
        }
        foreach ($rule in $acl.Access) {
            $ruleSid = $rule.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
            if (
                $ruleSid -notin $allowedSids -or
                $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow
            ) {
                throw "PostgreSQL 恢复工具含有未授权 ACL：$path ($ruleSid)"
            }
            if ($ruleSid -in $readExecuteSids) {
                $required = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
                $forbidden =
                    [System.Security.AccessControl.FileSystemRights]::Write -bor
                    [System.Security.AccessControl.FileSystemRights]::Delete -bor
                    [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
                    [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                    [System.Security.AccessControl.FileSystemRights]::TakeOwnership
                if (
                    ($rule.FileSystemRights -band $required) -ne $required -or
                    ($rule.FileSystemRights -band $forbidden) -ne 0
                ) {
                    throw "PostgreSQL 恢复服务账户拥有越权 ACL：$path ($ruleSid)"
                }
            }
        }
        foreach ($sid in $fullControlSids) {
            $matchingRules = @($acl.Access | Where-Object {
                $ruleSid = $_.IdentityReference.Translate(
                    [System.Security.Principal.SecurityIdentifier]
                ).Value
                $hasFullControl =
                    ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
                    [System.Security.AccessControl.FileSystemRights]::FullControl
                $requiredInheritance =
                    [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                    [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
                $hasRootInheritance =
                    -not $isRoot -or
                    (
                        -not $_.IsInherited -and
                        ($_.InheritanceFlags -band $requiredInheritance) -eq $requiredInheritance
                    )
                $ruleSid -eq $sid -and $hasFullControl -and $hasRootInheritance
            })
            if ($matchingRules.Count -eq 0) {
                throw "PostgreSQL 恢复工具缺少必需 FullControl ACL：$path ($sid)"
            }
        }
        foreach ($sid in $readExecuteSids) {
            $matchingRules = @($acl.Access | Where-Object {
                $ruleSid = $_.IdentityReference.Translate(
                    [System.Security.Principal.SecurityIdentifier]
                ).Value
                $required = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
                $forbidden =
                    [System.Security.AccessControl.FileSystemRights]::Write -bor
                    [System.Security.AccessControl.FileSystemRights]::Delete -bor
                    [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
                    [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                    [System.Security.AccessControl.FileSystemRights]::TakeOwnership
                $requiredInheritance =
                    [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                    [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
                $hasRootInheritance =
                    -not $isRoot -or
                    (
                        -not $_.IsInherited -and
                        ($_.InheritanceFlags -band $requiredInheritance) -eq $requiredInheritance
                    )
                $ruleSid -eq $sid -and
                    ($_.FileSystemRights -band $required) -eq $required -and
                    ($_.FileSystemRights -band $forbidden) -eq 0 -and
                    $hasRootInheritance
            })
            if ($matchingRules.Count -eq 0) {
                throw "PostgreSQL 恢复工具缺少必需 ReadExecute ACL：$path ($sid)"
            }
        }
    }
}

function Assert-TicketboxPgRecoveryToolset {
    param(
        [Parameter(Mandatory = $true)][int]$ExpectedMajor,
        [string[]]$ReadExecuteAccounts = @()
    )

    $root = Get-TicketboxPgRecoveryRoot
    $pgHomePath = Join-Path $root "pg"
    $manifestPath = Join-Path $root $script:TicketboxPgRecoveryManifestName
    $completionPath = Join-Path $root $script:TicketboxPgRecoveryCompletionName
    Assert-TicketboxPgRecoveryAcl -ReadExecuteAccounts $ReadExecuteAccounts
    try {
        $completion = Get-Content -LiteralPath $completionPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "PostgreSQL 恢复工具完成标记无效。"
    }
    $payload = Assert-TicketboxPgRecoveryPayload `
        -PgHome $pgHomePath `
        -BuildManifestPath $manifestPath `
        -ExpectedMajor $ExpectedMajor
    if (
        [string]$completion.schema -cne "ticketbox-pg-recovery-v1" -or
        [int]$completion.pg_major -ne $ExpectedMajor -or
        [string]$completion.payload_fingerprint -cne $payload.Snapshot.fingerprint -or
        [string]$completion.manifest_sha256 -cne (Get-TicketboxFileSha256 $manifestPath)
    ) {
        throw "PostgreSQL 恢复工具完成标记与 payload 不一致。"
    }
    return $payload
}

function Remove-TicketboxKnownPgRecoveryDirectory([string]$Path) {
    $lifecycleDirectory = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    $candidate = [System.IO.Path]::GetFullPath($Path)
    $expectedPrefix = [System.IO.Path]::GetFullPath($lifecycleDirectory).TrimEnd("\", "/") + "\"
    if (-not $candidate.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理机器级生命周期目录之外的 PostgreSQL 恢复路径。"
    }
    if (Test-Path -LiteralPath $candidate) {
        Assert-NoTicketboxAncestorReparsePoints $candidate
        $item = Get-Item -LiteralPath $candidate -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "PostgreSQL 恢复路径是重解析点，拒绝清理：$candidate"
        }
        Remove-Item -LiteralPath $candidate -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $candidate) {
        throw "无法清理 PostgreSQL 恢复路径：$candidate"
    }
}

function Save-TicketboxPgRecoveryToolset {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePgHome,
        [Parameter(Mandatory = $true)][string]$BuildManifestPath,
        [Parameter(Mandatory = $true)][int]$ExpectedMajor
    )

    $source = Assert-TicketboxPgRecoveryPayload `
        -PgHome $SourcePgHome `
        -BuildManifestPath $BuildManifestPath `
        -ExpectedMajor $ExpectedMajor
    $targetRoot = Get-TicketboxPgRecoveryRoot
    if (Test-Path -LiteralPath $targetRoot) {
        $existing = Assert-TicketboxPgRecoveryToolset -ExpectedMajor $ExpectedMajor
        if ($existing.Snapshot.fingerprint -cne $source.Snapshot.fingerprint) {
            throw "已存在不同 payload 的 PostgreSQL 恢复工具，拒绝静默替换。"
        }
        return $existing
    }

    $lifecycleDirectory = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    $stagingRoot = Join-Path $lifecycleDirectory (
        ".postgresql-recovery-staging-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N")
    )
    try {
        New-Item -ItemType Directory -Path $stagingRoot | Out-Null
        $stagingPgHome = Join-Path $stagingRoot "pg"
        New-Item -ItemType Directory -Path $stagingPgHome | Out-Null
        Copy-Item -Path (Join-Path $SourcePgHome "*") -Destination $stagingPgHome -Recurse -Force
        Copy-Item `
            -LiteralPath $BuildManifestPath `
            -Destination (Join-Path $stagingRoot $script:TicketboxPgRecoveryManifestName)
        Set-TicketboxExactDirectoryAcl `
            -Path $stagingRoot `
            -Accounts $script:TicketboxPgRecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxPgRecoveryOwnerAccount `
            -Recurse
        $staged = Assert-TicketboxPgRecoveryPayload `
            -PgHome $stagingPgHome `
            -BuildManifestPath (Join-Path $stagingRoot $script:TicketboxPgRecoveryManifestName) `
            -ExpectedMajor $ExpectedMajor
        $completion = [ordered]@{
            schema = "ticketbox-pg-recovery-v1"
            pg_major = $ExpectedMajor
            payload_fingerprint = $staged.Snapshot.fingerprint
            manifest_sha256 = Get-TicketboxFileSha256 (
                Join-Path $stagingRoot $script:TicketboxPgRecoveryManifestName
            )
        }
        Write-TicketboxProtectedUtf8FileDurable `
            -Path (Join-Path $stagingRoot $script:TicketboxPgRecoveryCompletionName) `
            -Text (($completion | ConvertTo-Json -Depth 4) + [Environment]::NewLine) `
            -FullControlAccounts $script:TicketboxPgRecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxPgRecoveryOwnerAccount
        [System.IO.Directory]::Move($stagingRoot, $targetRoot)
        Set-TicketboxPgRecoveryAcl
        return Assert-TicketboxPgRecoveryToolset -ExpectedMajor $ExpectedMajor
    }
    finally {
        if (Test-Path -LiteralPath $stagingRoot) {
            Remove-TicketboxKnownPgRecoveryDirectory $stagingRoot
        }
    }
}

function Remove-TicketboxPgRecoveryToolset([int]$ExpectedMajor) {
    $root = Get-TicketboxPgRecoveryRoot
    if (-not (Test-Path -LiteralPath $root)) { return }
    if ($ExpectedMajor -le 0) {
        $manifest = Read-TicketboxPgRecoveryBuildManifest (
            Join-Path $root $script:TicketboxPgRecoveryManifestName
        )
        $ExpectedMajor = [int]$manifest.postgresql.major
    }
    Assert-TicketboxPgRecoveryToolset -ExpectedMajor $ExpectedMajor | Out-Null
    Remove-TicketboxKnownPgRecoveryDirectory $root
}
