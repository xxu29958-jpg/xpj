#Requires -Version 5.1

$script:TicketboxPgRecoveryDirectoryName = "postgresql-preserved-data-recovery"
$script:TicketboxPgRecoveryCompletionName = "BUILD_COMPLETE.json"
$script:TicketboxPgRecoveryManifestName = "BUILD_PROVENANCE.json"
$script:TicketboxPgRecoveryDeletionIntentName = "DELETE_IN_PROGRESS.json"
$script:TicketboxPgRecoveryStagingPrefix = ".postgresql-recovery-staging-"
$script:TicketboxPgRecoveryFullControlAccounts = @("SYSTEM", "BUILTIN\Administrators")
$script:TicketboxPgRecoveryOwnerAccount = "SYSTEM"

function Invoke-TicketboxPostgresqlHostNative {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [AllowEmptyString()][string]$StandardInputText,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000,
        [AllowEmptyString()][string]$PgPassFile = ""
    )

    # PostgreSQL client environment is process-global. Snapshot every PG*
    # variable, run the bounded host operation with an explicit environment,
    # and restore the caller exactly without ever copying a credential to argv.
    $saved = @{}
    foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
        if ($item.Name -match '^(?i)PG') {
            $saved[$item.Name] = [string]$item.Value
        }
    }
    try {
        foreach ($name in @($saved.Keys)) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        if (-not [string]::IsNullOrWhiteSpace($PgPassFile)) {
            $env:PGPASSFILE = [System.IO.Path]::GetFullPath($PgPassFile)
        }
        $parameters = @{
            FilePath = $FilePath
            Arguments = $Arguments
            TimeoutMilliseconds = $TimeoutMilliseconds
            Label = $Label
        }
        if ($PSBoundParameters.ContainsKey("StandardInputText")) {
            $parameters.StandardInputText = $StandardInputText
        }
        return Invoke-TicketboxBoundedNativeProcess @parameters
    }
    finally {
        foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
            if ($item.Name -match '^(?i)PG') {
                Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
            }
        }
        foreach ($entry in $saved.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable(
                [string]$entry.Key,
                [string]$entry.Value,
                "Process"
            )
        }
    }
}

function Invoke-TicketboxPostgresqlHostPsql {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label,
        [AllowEmptyString()][string]$PgPassFile = "",
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000
    )

    if (
        [string]::IsNullOrWhiteSpace($PsqlPath) -or
        [string]::IsNullOrWhiteSpace($DatabaseUrl) -or
        $DatabaseUrl.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0
    ) {
        throw "$Label 缺少有效的 PostgreSQL host invocation。"
    }
    $databaseUri = $null
    if (
        -not [Uri]::TryCreate(
            $DatabaseUrl,
            [UriKind]::Absolute,
            [ref]$databaseUri
        ) -or
        $databaseUri.Scheme -cnotin @("postgres", "postgresql") -or
        [Uri]::UnescapeDataString([string]$databaseUri.UserInfo).Contains(":") -or
        [string]$databaseUri.Query -match
            '(?i)(?:^|[?&])(?:password|sslpassword)='
    ) {
        throw "$Label 的 PostgreSQL URL 含无效 scheme 或 argv credential。"
    }
    $parameters = @{
        FilePath = $PsqlPath
        Arguments = @(
            "--no-psqlrc",
            "--no-password",
            # PostgreSQL 15+ prints every result in a multi-command input.
            # tuples-only removes table decoration but not command status;
            # quiet is therefore part of the machine-readable row contract.
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--field-separator", "`t",
            "--set", "ON_ERROR_STOP=1",
            "--dbname", $DatabaseUrl
        )
        StandardInputText = $Sql + "`n"
        TimeoutMilliseconds = $TimeoutMilliseconds
        Label = $Label
    }
    if (-not [string]::IsNullOrWhiteSpace($PgPassFile)) {
        $parameters.PgPassFile = $PgPassFile
    }
    return Invoke-TicketboxPostgresqlHostNative @parameters
}

function ConvertFrom-TicketboxPostgresqlHostEvidenceRow {
    param(
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Output,
        [ValidateRange(1, 16)][int]$FieldCount,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $lines = @(
        $Output -split "`r?`n" |
            ForEach-Object { [string]$_ } |
            Where-Object { $_.Trim().Length -gt 0 }
    )
    if ($lines.Count -ne 1) {
        throw "$Label 未返回唯一结果行。"
    }
    $fields = @($lines[0].Split([char]9))
    if ($fields.Count -ne $FieldCount) {
        throw "$Label 返回字段数无效。"
    }
    return $fields
}

function Invoke-TicketboxPostgresqlHostCredentialRotation {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Verifier,
        [Parameter(Mandatory = $true)][string]$ClusterSystemIdentifier,
        [Parameter(Mandatory = $true)][string[]]$ExpectedDataDirectories,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000
    )

    if (
        $Verifier -cnotmatch
            '^SCRAM-SHA-256\$4096:[A-Za-z0-9+/]+={0,2}\$' +
            '[A-Za-z0-9+/]+={0,2}:[A-Za-z0-9+/]+={0,2}$'
    ) {
        throw "$Label 的 locally-derived verifier shape 无效。"
    }
    $expectedDirectories = @(
        $ExpectedDataDirectories |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
            Select-Object -Unique
    )
    if ($expectedDirectories.Count -eq 0) {
        throw "$Label 缺少 exact PostgreSQL data directory。"
    }
    $validUntil = [DateTime]::UtcNow.AddHours(1).ToString(
        "yyyy-MM-dd HH:mm:ss.fffffff'+00'"
    )
    $sql = @"
ALTER ROLE postgres WITH LOGIN PASSWORD '$Verifier' VALID UNTIL '$validUntil';
SELECT
    session_user,
    current_user,
    control.system_identifier::text,
    current_setting('data_directory'),
    current_setting('port'),
    role.rolcanlogin::text,
    (role.rolpassword = '$Verifier')::text
FROM pg_catalog.pg_control_system() AS control
CROSS JOIN pg_catalog.pg_authid AS role
WHERE role.rolname = 'postgres';
"@
    $result = Invoke-TicketboxPostgresqlHostPsql `
        -PsqlPath $PsqlPath `
        -DatabaseUrl $DatabaseUrl `
        -Sql $sql `
        -Label $Label `
        -TimeoutMilliseconds $TimeoutMilliseconds
    if ($result.ExitCode -ne 0) {
        throw "$Label 失败（原生输出已抑制）。"
    }
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $result.StandardOutput `
        -FieldCount 7 `
        -Label $Label
    $dataDirectoryMatches = $false
    foreach ($expectedDirectory in $expectedDirectories) {
        if (Test-TicketboxPathEquals $fields[3].Trim() $expectedDirectory) {
            $dataDirectoryMatches = $true
            break
        }
    }
    if (
        $fields[0].Trim() -cne "postgres" -or
        $fields[1].Trim() -cne "postgres" -or
        $fields[2].Trim() -cne $ClusterSystemIdentifier -or
        -not $dataDirectoryMatches -or
        $fields[4].Trim() -cne [string]$Port
    ) {
        throw "$Label 未绑定 exact postgres/cluster/data-dir/port。"
    }
    if ($fields[5].Trim() -cne "true" -or $fields[6].Trim() -cne "true") {
        throw "$Label 未 exact commit PostgreSQL host LOGIN/verifier。"
    }
}

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

function Read-TicketboxPgRecoveryCompletion {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$ExpectedMajor,
        [string[]]$ReadExecuteAccounts = @()
    )

    Assert-TicketboxPgRecoveryAcl -ReadExecuteAccounts $ReadExecuteAccounts
    $text = Read-TicketboxPgRecoveryStrictUtf8Text -Path $Path -MaximumBytes 4096
    try { $completion = $text | ConvertFrom-Json }
    catch { throw "PostgreSQL 恢复工具完成标记不是有效 JSON。" }
    $expectedProperties = @(
        "manifest_sha256",
        "payload_fingerprint",
        "pg_major",
        "schema"
    )
    $actualProperties = @($completion.PSObject.Properties.Name | Sort-Object)
    if (@(Compare-Object $expectedProperties $actualProperties -CaseSensitive).Count -gt 0) {
        throw "PostgreSQL 恢复工具完成标记字段不符合严格 schema。"
    }
    $pgMajor = 0
    if (
        [string]$completion.schema -cne "ticketbox-pg-recovery-v1" -or
        -not [int]::TryParse([string]$completion.pg_major, [ref]$pgMajor) -or
        $pgMajor -le 0 -or
        ($ExpectedMajor -gt 0 -and $pgMajor -ne $ExpectedMajor) -or
        [string]$completion.payload_fingerprint -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$completion.manifest_sha256 -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw "PostgreSQL 恢复工具完成标记 schema 或校验字段无效。"
    }
    return $completion
}

function Read-TicketboxPgRecoveryDeletionIntent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$ExpectedMajor
    )

    Assert-TicketboxPgRecoveryAcl
    $text = Read-TicketboxPgRecoveryStrictUtf8Text -Path $Path -MaximumBytes 4096
    try { $intent = $text | ConvertFrom-Json }
    catch { throw "PostgreSQL 恢复工具删除意图不是有效 JSON。" }
    $expectedProperties = @(
        "completion_sha256",
        "manifest_sha256",
        "payload_fingerprint",
        "pg_major",
        "schema"
    )
    $actualProperties = @($intent.PSObject.Properties.Name | Sort-Object)
    if (@(Compare-Object $expectedProperties $actualProperties -CaseSensitive).Count -gt 0) {
        throw "PostgreSQL 恢复工具删除意图字段不符合严格 schema。"
    }
    $pgMajor = 0
    if (
        [string]$intent.schema -cne "ticketbox-pg-recovery-delete-v1" -or
        -not [int]::TryParse([string]$intent.pg_major, [ref]$pgMajor) -or
        $pgMajor -le 0 -or
        ($ExpectedMajor -gt 0 -and $pgMajor -ne $ExpectedMajor) -or
        [string]$intent.payload_fingerprint -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$intent.manifest_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$intent.completion_sha256 -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw "PostgreSQL 恢复工具删除意图 schema 或校验字段无效。"
    }
    return $intent
}

function Read-TicketboxPgRecoveryStrictUtf8Text {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65536)][int]$MaximumBytes
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    Assert-NoTicketboxAncestorReparsePoints $fullPath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "PostgreSQL 恢复工具状态文件不存在或不是普通文件：$fullPath"
    }
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $item.Length -le 0 -or
        $item.Length -gt $MaximumBytes
    ) {
        throw "PostgreSQL 恢复工具状态文件大小或类型无效：$fullPath"
    }
    $bytes = [System.IO.File]::ReadAllBytes($fullPath)
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    try { $text = $encoding.GetString($bytes) }
    catch { throw "PostgreSQL 恢复工具状态文件不是严格 UTF-8：$fullPath" }
    if (-not (Test-TicketboxByteArrayEquals -Left $bytes -Right $encoding.GetBytes($text))) {
        throw "PostgreSQL 恢复工具状态文件不能无损 UTF-8 往返：$fullPath"
    }
    return $text
}

function Set-TicketboxPgRecoveryAcl([string[]]$ReadExecuteAccounts = @()) {
    $root = Get-TicketboxPgRecoveryRoot
    $rootKind = Get-TicketboxPathEntryKindNoFollow $root
    if ($rootKind -ceq "Missing") { return }
    if ($rootKind -cne "Directory") {
        throw "PostgreSQL 恢复工具根存在但不是普通目录：$root ($rootKind)"
    }
    Set-TicketboxExactDirectoryAcl `
        -Path $root `
        -Accounts $script:TicketboxPgRecoveryFullControlAccounts `
        -InheritableReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $script:TicketboxPgRecoveryOwnerAccount `
        -Recurse
}

function Assert-TicketboxPgRecoveryAcl([string[]]$ReadExecuteAccounts = @()) {
    $root = Get-TicketboxPgRecoveryRoot
    $rootKind = Get-TicketboxPathEntryKindNoFollow $root
    if ($rootKind -cne "Directory") {
        throw "PostgreSQL 恢复工具根不存在或不是普通目录：$root ($rootKind)"
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
    $completion = Read-TicketboxPgRecoveryCompletion `
        -Path $completionPath `
        -ExpectedMajor $ExpectedMajor `
        -ReadExecuteAccounts $ReadExecuteAccounts
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

function Remove-TicketboxKnownPgRecoveryDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowEmptyString()][string]$DeferredRootLeafName = ""
    )

    $lifecycleDirectory = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    $candidate = [System.IO.Path]::GetFullPath($Path)
    $expectedPrefix = [System.IO.Path]::GetFullPath($lifecycleDirectory).TrimEnd("\", "/") + "\"
    if (-not $candidate.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理机器级生命周期目录之外的 PostgreSQL 恢复路径。"
    }
    $candidateKind = Get-TicketboxPathEntryKindNoFollow $candidate
    if ($candidateKind -ceq "Missing") { return }
    if ($candidateKind -cne "Directory") {
        throw "PostgreSQL 恢复路径存在但不是普通目录，拒绝清理：$candidate ($candidateKind)"
    }
    Assert-NoTicketboxAncestorReparsePoints $candidate
    Remove-TicketboxTreeExact `
        -Path $candidate `
        -DeferredRootLeafName $DeferredRootLeafName
    if ((Get-TicketboxPathEntryKindNoFollow $candidate) -cne "Missing") {
        throw "无法清理 PostgreSQL 恢复路径：$candidate"
    }
}

function Remove-TicketboxAbandonedPgRecoveryStagingDirectories {
    $lifecycleDirectory = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    if (-not (Test-Path -LiteralPath $lifecycleDirectory -PathType Container)) { return }
    $stagingPattern = '^\.postgresql-recovery-staging-[1-9][0-9]*-[0-9a-f]{32}$'
    $candidates = @(Get-ChildItem -LiteralPath $lifecycleDirectory -Force -ErrorAction Stop | Where-Object {
        $_.Name.StartsWith(
            $script:TicketboxPgRecoveryStagingPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    })
    foreach ($candidate in $candidates) {
        if (
            $candidate -isnot [System.IO.DirectoryInfo] -or
            $candidate.Name -cnotmatch $stagingPattern -or
            ($candidate.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "PostgreSQL 恢复 staging 命名空间含有不可验证 artifact：$($candidate.FullName)"
        }
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $candidate.FullName `
            -FullControlAccounts $script:TicketboxPgRecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxPgRecoveryOwnerAccount
        Remove-TicketboxKnownPgRecoveryDirectory $candidate.FullName
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
    Remove-TicketboxAbandonedPgRecoveryStagingDirectories
    $targetRoot = Get-TicketboxPgRecoveryRoot
    $targetRootKind = Get-TicketboxPathEntryKindNoFollow $targetRoot
    if ($targetRootKind -cne "Missing") {
        if ($targetRootKind -cne "Directory") {
            throw "PostgreSQL 恢复工具目标存在但不是普通目录：$targetRoot ($targetRootKind)"
        }
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
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $stagingRoot `
            -FullControlAccounts $script:TicketboxPgRecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxPgRecoveryOwnerAccount | Out-Null
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
        if ((Get-TicketboxPathEntryKindNoFollow $stagingRoot) -cne "Missing") {
            Remove-TicketboxKnownPgRecoveryDirectory $stagingRoot
        }
    }
}

function Remove-TicketboxPgRecoveryToolset {
    param(
        [Parameter(Mandatory = $true)][int]$ExpectedMajor,
        [switch]$DeleteDataIntentValidated,
        [switch]$InstallCommitValidated
    )

    if ([bool]$DeleteDataIntentValidated -eq [bool]$InstallCommitValidated) {
        throw "删除 PostgreSQL 恢复工具必须且只能由 completed install commit 或机器级 delete-data 意图授权。"
    }
    Remove-TicketboxAbandonedPgRecoveryStagingDirectories
    $root = Get-TicketboxPgRecoveryRoot
    $rootKind = Get-TicketboxPathEntryKindNoFollow $root
    if ($rootKind -ceq "Missing") { return }
    if ($rootKind -cne "Directory") {
        throw "PostgreSQL 恢复工具根存在但不是普通目录，拒绝退役：$root ($rootKind)"
    }
    $deletionIntentPath = Join-Path $root $script:TicketboxPgRecoveryDeletionIntentName
    Assert-TicketboxPgRecoveryAcl
    $deletionIntentKind = Get-TicketboxPathEntryKindNoFollow $deletionIntentPath
    if ($deletionIntentKind -ceq "File") {
        $deletionIntent = Read-TicketboxPgRecoveryDeletionIntent `
            -Path $deletionIntentPath `
            -ExpectedMajor $ExpectedMajor
        if ($ExpectedMajor -le 0) {
            $ExpectedMajor = [int]$deletionIntent.pg_major
        }
    }
    elseif ($deletionIntentKind -ceq "Missing") {
        $remainingEntries = @(Get-ChildItem -LiteralPath $root -Force -ErrorAction Stop)
        if ($remainingEntries.Count -eq 0) {
            Remove-TicketboxKnownPgRecoveryDirectory $root
            return
        }
        if ($ExpectedMajor -le 0) {
            $manifest = Read-TicketboxPgRecoveryBuildManifest (
                Join-Path $root $script:TicketboxPgRecoveryManifestName
            )
            $ExpectedMajor = [int]$manifest.postgresql.major
        }
        $payload = Assert-TicketboxPgRecoveryToolset -ExpectedMajor $ExpectedMajor
        $completionPath = Join-Path $root $script:TicketboxPgRecoveryCompletionName
        $completion = Read-TicketboxPgRecoveryCompletion `
            -Path $completionPath `
            -ExpectedMajor $ExpectedMajor
        $deletionIntent = [ordered]@{
            schema = "ticketbox-pg-recovery-delete-v1"
            pg_major = $ExpectedMajor
            payload_fingerprint = [string]$payload.Snapshot.fingerprint
            manifest_sha256 = [string]$completion.manifest_sha256
            completion_sha256 = Get-TicketboxFileSha256 $completionPath
        }
        Write-TicketboxProtectedUtf8FileDurable `
            -Path $deletionIntentPath `
            -Text (($deletionIntent | ConvertTo-Json -Depth 4) + [Environment]::NewLine) `
            -FullControlAccounts $script:TicketboxPgRecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxPgRecoveryOwnerAccount
        Read-TicketboxPgRecoveryDeletionIntent `
            -Path $deletionIntentPath `
            -ExpectedMajor $ExpectedMajor | Out-Null
    }
    else {
        throw "PostgreSQL 恢复工具删除意图存在但不是普通文件：$deletionIntentPath ($deletionIntentKind)"
    }
    Remove-TicketboxKnownPgRecoveryDirectory `
        -Path $root `
        -DeferredRootLeafName $script:TicketboxPgRecoveryDeletionIntentName
}
