#Requires -Version 5.1

$script:TicketboxLifecycleReceiptSchema = "ticketbox-windows-lifecycle-receipt-v8"
$script:TicketboxLegacyLifecycleReceiptSchema = "ticketbox-windows-lifecycle-receipt-v7"
$script:TicketboxLifecycleReceiptModes = @(
    "fresh_install",
    "preserved_data_reinstall",
    "repair_install",
    "upgrade"
)
$script:TicketboxLifecycleReceiptStates = @("absent", "stopped", "running")
$script:TicketboxLifecycleReceiptStartPolicies = @(
    "absent",
    "disabled",
    "manual",
    "auto",
    "delayed_auto"
)
$script:TicketboxLifecycleReceiptPreparationStages = @(
    "captured",
    "backup_deferred_until_program_files_installed",
    "program_files_installed_backup_pending",
    "prepared",
    "files_may_have_been_replaced",
    "install_completed"
)
$script:TicketboxLifecycleReceiptAclAccounts = @("SYSTEM", "BUILTIN\Administrators")
$script:TicketboxLifecycleReceiptOwnerAccount = "SYSTEM"
$script:TicketboxLifecycleReceiptFileName = "installer-lifecycle-receipt.json"
$script:TicketboxDeleteDataIntentSchema = "ticketbox-delete-data-intent-v1"
$script:TicketboxInstallerRuntimeRecoveryGuardSchema = "ticketbox-installer-runtime-recovery-guard-v1"
$script:TicketboxInstallerRuntimeRecoveryGuardFileName = "installer-runtime-recovery-pending"
$script:TicketboxInstallerRuntimeStateDirectoryName = "TicketboxRuntimeState"

function ConvertTo-TicketboxLifecycleVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [string]$FieldName = "版本"
    )

    $value = $Version.Trim()
    $parts = @($value -split '\.')
    if ($parts.Count -lt 3 -or $parts.Count -gt 4) {
        throw "$FieldName 必须是三段或四段数字版本。"
    }
    $components = @(0, 0, 0, 0)
    for ($index = 0; $index -lt $parts.Count; $index++) {
        $component = 0
        if (
            $parts[$index] -cnotmatch '^(0|[1-9][0-9]{0,4})$' -or
            -not [int]::TryParse($parts[$index], [ref]$component) -or
            $component -gt 65535
        ) {
            throw "$FieldName 包含无效版本分量。"
        }
        $components[$index] = $component
    }
    $canonical = "$($components[0]).$($components[1]).$($components[2])"
    if ($parts.Count -eq 4) { $canonical += ".$($components[3])" }
    return [pscustomobject]@{
        Canonical = $canonical
        Components = $components
    }
}

function Compare-TicketboxLifecycleVersions {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $leftVersion = ConvertTo-TicketboxLifecycleVersion $Left "当前安装器目标版本"
    $rightVersion = ConvertTo-TicketboxLifecycleVersion $Right "生命周期回执目标版本下限"
    for ($index = 0; $index -lt 4; $index++) {
        if ($leftVersion.Components[$index] -lt $rightVersion.Components[$index]) { return -1 }
        if ($leftVersion.Components[$index] -gt $rightVersion.Components[$index]) { return 1 }
    }
    return 0
}

function Get-TicketboxLifecycleReceiptPath {
    if ($null -eq (Get-Command Get-TicketboxLifecycleLockPath -ErrorAction SilentlyContinue)) {
        throw "生命周期回执校验缺少机器级锁路径提供者。"
    }
    return Join-Path `
        (Split-Path -Parent (Get-TicketboxLifecycleLockPath)) `
        $script:TicketboxLifecycleReceiptFileName
}

function Assert-TicketboxLifecycleReceiptPath([string]$Path) {
    $expected = Get-TicketboxLifecycleReceiptPath
    $actual = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-TicketboxPathEquals $actual $expected)) {
        throw "生命周期回执必须位于受保护的机器级安装锁目录。"
    }
    return $actual
}

function Get-TicketboxDeferredBackupRoot {
    $lockDirectory = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    return Join-Path $lockDirectory "preserved-data-backups"
}

function Get-TicketboxPreparedInstallMode {
    param(
        [bool]$HasPgService,
        [bool]$HasBackendService,
        [bool]$HasPgData,
        [bool]$HasEnv,
        [bool]$HasPgBootstrapRecovery
    )
    if (-not ($HasPgService -or $HasBackendService -or $HasPgData -or $HasEnv -or $HasPgBootstrapRecovery)) {
        return "fresh_install"
    }
    if ((-not $HasPgData -and -not $HasPgBootstrapRecovery) -or
        (-not $HasEnv -and -not $HasPgBootstrapRecovery)) {
        throw "既有安装状态不完整且没有可验证恢复材料；拒绝覆盖。"
    }
    if ($HasPgService -and $HasBackendService -and $HasEnv) {
        return "upgrade"
    }
    if (-not $HasPgService -and -not $HasBackendService -and $HasEnv) {
        return "preserved_data_reinstall"
    }
    return "repair_install"
}

function Assert-TicketboxProtectedLifecycleReceipt([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少受保护的安装生命周期回执：$Path"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "安装生命周期回执不能是重解析点：$Path"
    }

    $ownerSid = ConvertTo-TicketboxAccountSid $script:TicketboxLifecycleReceiptOwnerAccount
    $allowedSids = @($script:TicketboxLifecycleReceiptAclAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    $acl = Get-TicketboxPathAcl $Path
    if (
        -not $acl.AreAccessRulesProtected -or
        (ConvertTo-TicketboxAccountSid $acl.Owner) -ne $ownerSid
    ) {
        throw "安装生命周期回执的 owner 或继承状态不可信：$Path"
    }
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        $hasFullControl =
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
            [System.Security.AccessControl.FileSystemRights]::FullControl
        if (
            $ruleSid -notin $allowedSids -or
            -not $hasFullControl -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.IsInherited
        ) {
            throw "安装生命周期回执 ACL 含有未授权规则：$Path ($ruleSid)"
        }
    }
    foreach ($sid in $allowedSids) {
        if (-not @($acl.Access | Where-Object {
            $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value -eq $sid
        })) {
            throw "安装生命周期回执 ACL 缺少目标账户：$Path ($sid)"
        }
    }
}

function Get-TicketboxLifecycleBackupEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$Mode,
        [switch]$KeepOpen
    )

    if ([string]::IsNullOrWhiteSpace($BackupPath)) {
        throw "安装生命周期回执声明备份完成时必须记录备份路径。"
    }
    $canonicalPath = [System.IO.Path]::GetFullPath($BackupPath)
    $backupRoot = Join-Path (ConvertTo-TicketboxCanonicalPath $DataRoot) "installer-backups"
    $deferredBackupRoot = Get-TicketboxDeferredBackupRoot
    $withinAllowedBackupRoot =
        (Test-TicketboxPathWithin $canonicalPath $backupRoot) -or
        (
            $Mode -eq "preserved_data_reinstall" -and
            (Test-TicketboxPathWithin $canonicalPath $deferredBackupRoot)
        )
    if (
        -not $withinAllowedBackupRoot -or
        -not (Test-Path -LiteralPath $canonicalPath -PathType Leaf)
    ) {
        throw "安装生命周期回执指向不存在或越界的备份文件。"
    }
    Assert-NoTicketboxAncestorReparsePoints $canonicalPath

    $stream = New-Object System.IO.FileStream(
        $canonicalPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read,
        4096,
        [System.IO.FileOptions]::SequentialScan
    )
    $retainStream = $false
    try {
        Assert-NoTicketboxAncestorReparsePoints $canonicalPath
        $item = Get-Item -LiteralPath $canonicalPath -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "安装生命周期备份不能是重解析点：$canonicalPath"
        }
        Assert-TicketboxExactFileAcl `
            -Path $canonicalPath `
            -Accounts $script:TicketboxLifecycleReceiptAclAccounts `
            -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
        $byteLength = [long]$stream.Length
        if ($byteLength -le 0) {
            throw "安装生命周期备份不能为空文件。"
        }
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $digest = $sha256.ComputeHash($stream)
        }
        finally { $sha256.Dispose() }
        $retainStream = [bool]$KeepOpen
    }
    finally {
        if (-not $retainStream) { $stream.Dispose() }
    }

    return [pscustomobject]@{
        Path = $canonicalPath
        Sha256 = ([System.BitConverter]::ToString($digest) -replace "-", "").ToUpperInvariant()
        ByteLength = $byteLength
        GuardStream = if ($retainStream) { $stream } else { $null }
    }
}

function Assert-TicketboxLifecycleBackupEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$Mode,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][long]$ExpectedByteLength,
        [switch]$KeepOpen
    )

    if ($ExpectedSha256 -cnotmatch '^[0-9A-F]{64}$' -or $ExpectedByteLength -le 0) {
        throw "安装生命周期回执缺少有效的备份摘要或字节长度。"
    }
    $evidence = Get-TicketboxLifecycleBackupEvidence `
        -BackupPath $BackupPath `
        -DataRoot $DataRoot `
        -Mode $Mode `
        -KeepOpen:$KeepOpen
    if (
        $evidence.Sha256 -cne $ExpectedSha256 -or
        $evidence.ByteLength -ne $ExpectedByteLength
    ) {
        if ($null -ne $evidence.GuardStream) { $evidence.GuardStream.Dispose() }
        throw "安装生命周期备份已被替换或损坏；拒绝继续恢复、安装或清理回执。"
    }
    return $evidence
}

function Write-TicketboxLifecycleReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet(
            "fresh_install",
            "preserved_data_reinstall",
            "repair_install",
            "upgrade"
        )][string]$Mode,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][object]$InstalledReleaseConfig,
        [Parameter(Mandatory = $true)][string]$TargetBackendVersionFloor,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][ValidateSet("absent", "stopped", "running")][string]$PreviousPgState,
        [Parameter(Mandatory = $true)][ValidateSet("absent", "stopped", "running")][string]$PreviousBackendState,
        [Parameter(Mandatory = $true)][ValidateSet(
            "absent",
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        )][string]$PreviousPgStartPolicy,
        [Parameter(Mandatory = $true)][ValidateSet(
            "absent",
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        )][string]$PreviousBackendStartPolicy,
        [Parameter(Mandatory = $true)][bool]$BackupRequired,
        [Parameter(Mandatory = $true)][bool]$BackupCompleted,
        [Parameter(Mandatory = $true)][ValidateSet(
            "captured",
            "backup_deferred_until_program_files_installed",
            "program_files_installed_backup_pending",
            "prepared",
            "files_may_have_been_replaced",
            "install_completed"
        )][string]$PreparationStage,
        [string]$BackupPath = "",
        [string]$BackupSha256 = "",
        [long]$BackupByteLength = 0,
        [bool]$FilesMayHaveBeenReplaced = $false,
        [bool]$InstallCompleted = $false,
        [bool]$TemporaryPgServiceCleanupPending = $false,
        [switch]$ReplaceProtectedReceipt,
        [switch]$ReplaceVerifiedLegacyReceipt
    )

    if ($InstallerOwnerProcessId -le 0) {
        throw "Inno 生命周期回执必须绑定有效的安装器进程。"
    }
    if ($ReplaceVerifiedLegacyReceipt -and -not $ReplaceProtectedReceipt) {
        throw "legacy 生命周期回执只能通过受保护原子替换迁移。"
    }
    $targetVersionFloor = ConvertTo-TicketboxLifecycleVersion `
        $TargetBackendVersionFloor `
        "生命周期回执目标版本下限"
    $dataRootMarker = Read-TicketboxProtectedDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    if ($PgPort -eq $BackendPort) {
        throw "安装生命周期回执中的 PostgreSQL 与后端端口不能相同。"
    }
    if ($BackupCompleted -and -not $BackupRequired) {
        throw "不需要备份的安装生命周期不能声明备份已完成。"
    }
    $backupEvidence = $null
    if ($BackupCompleted) {
        $backupEvidence = Assert-TicketboxLifecycleBackupEvidence `
            -BackupPath $BackupPath `
            -DataRoot $DataRoot `
            -Mode $Mode `
            -ExpectedSha256 $BackupSha256 `
            -ExpectedByteLength $BackupByteLength
    }
    elseif (
        -not [string]::IsNullOrWhiteSpace($BackupPath) -or
        -not [string]::IsNullOrWhiteSpace($BackupSha256) -or
        $BackupByteLength -ne 0
    ) {
        throw "未完成的安装生命周期备份不能携带路径、摘要或字节长度。"
    }
    if (
        ($PreviousPgState -eq "absent") -ne ($PreviousPgStartPolicy -eq "absent") -or
        ($PreviousBackendState -eq "absent") -ne ($PreviousBackendStartPolicy -eq "absent")
    ) {
        throw "安装生命周期回执中的服务状态与启动策略不一致。"
    }
    $expectedFilesReplaced = $PreparationStage -in @(
        "program_files_installed_backup_pending",
        "files_may_have_been_replaced",
        "install_completed"
    )
    $expectedInstallCompleted = $PreparationStage -eq "install_completed"
    if (
        $FilesMayHaveBeenReplaced -ne $expectedFilesReplaced -or
        $InstallCompleted -ne $expectedInstallCompleted
    ) {
        throw "安装生命周期回执阶段与文件替换/完成标记不一致。"
    }
    if ($PreparationStage -eq "captured" -and $BackupCompleted) {
        throw "captured 生命周期回执不能提前声明备份完成。"
    }
    if ($PreparationStage -in @(
        "backup_deferred_until_program_files_installed",
        "program_files_installed_backup_pending"
    )) {
        if (
            $Mode -ne "preserved_data_reinstall" -or
            -not $BackupRequired -or
            $BackupCompleted
        ) {
            throw "延期备份阶段只允许用于尚未改动 DataRoot 的 preserved-data reinstall。"
        }
    }
    if (
        $TemporaryPgServiceCleanupPending -and
        (
            $Mode -ne "preserved_data_reinstall" -or
            $PreparationStage -ne "program_files_installed_backup_pending"
        )
    ) {
        throw "临时 PostgreSQL 服务清理义务只允许存在于 preserved-data backup-pending 阶段。"
    }

    $canonicalPath = Assert-TicketboxLifecycleReceiptPath $Path
    $parent = Split-Path -Parent $canonicalPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "安装生命周期回执目录不存在：$parent"
    }
    Assert-NoTicketboxAncestorReparsePoints $parent
    if (Test-Path -LiteralPath $canonicalPath) {
        if (-not $ReplaceProtectedReceipt) {
            throw "已存在安装生命周期回执；拒绝静默覆盖旧的运行态或备份证据。"
        }
        Assert-TicketboxProtectedLifecycleReceipt $canonicalPath
        try {
            $existingReceipt = Get-Content `
                -LiteralPath $canonicalPath `
                -Encoding UTF8 `
                -Raw | ConvertFrom-Json
        }
        catch {
            throw "既有安装生命周期回执不是有效 JSON；拒绝替换。"
        }
        $existingFloorProperty =
            $existingReceipt.PSObject.Properties["target_backend_version_floor"]
        if ($ReplaceVerifiedLegacyReceipt) {
            if (
                $existingReceipt.schema -cne $script:TicketboxLegacyLifecycleReceiptSchema -or
                $null -ne $existingFloorProperty
            ) {
                throw "只有已验证且尚无版本下限的 v7 生命周期回执可以迁移。"
            }
        }
        else {
            if (
                $existingReceipt.schema -cne $script:TicketboxLifecycleReceiptSchema -or
                $null -eq $existingFloorProperty -or
                $existingFloorProperty.Value -isnot [string]
            ) {
                throw "既有安装生命周期回执缺少受支持的目标版本下限；拒绝替换。"
            }
            $existingFloor = ConvertTo-TicketboxLifecycleVersion `
                ([string]$existingFloorProperty.Value) `
                "既有生命周期回执目标版本下限"
            if (
                [string]$existingFloorProperty.Value -cne $existingFloor.Canonical -or
                (Compare-TicketboxLifecycleVersions `
                    -Left $targetVersionFloor.Canonical `
                    -Right $existingFloor.Canonical) -lt 0
            ) {
                throw "安装生命周期回执目标版本下限不能回退。"
            }
        }
    }
    elseif ($ReplaceVerifiedLegacyReceipt) {
        throw "legacy 生命周期回执迁移缺少既有受保护回执。"
    }
    $payload = [ordered]@{
        schema = $script:TicketboxLifecycleReceiptSchema
        mode = $Mode
        install_dir = ConvertTo-TicketboxCanonicalPath $InstallDir
        data_root = ConvertTo-TicketboxCanonicalPath $DataRoot
        data_volume_identity = $dataRootMarker.DataVolumeIdentity
        pg_port = $PgPort
        backend_port = $BackendPort
        target_backend_version_floor = $targetVersionFloor.Canonical
        installer_owner_process_id = $InstallerOwnerProcessId
        previous_pg_state = $PreviousPgState
        previous_backend_state = $PreviousBackendState
        previous_pg_start_policy = $PreviousPgStartPolicy
        previous_backend_start_policy = $PreviousBackendStartPolicy
        preparation_stage = $PreparationStage
        backup_required = $BackupRequired
        backup_completed = $BackupCompleted
        files_may_have_been_replaced = $FilesMayHaveBeenReplaced
        install_completed = $InstallCompleted
        temporary_pg_service_cleanup_pending = $TemporaryPgServiceCleanupPending
        temporary_pg_service_name = [string]$InstalledReleaseConfig.pg_service_name
        temporary_pg_service_account = "NT SERVICE\$([string]$InstalledReleaseConfig.pg_service_name)"
        temporary_pg_service_data_root = Join-Path (ConvertTo-TicketboxCanonicalPath $DataRoot) "pgdata"
        backup_path = if ($null -ne $backupEvidence) { $backupEvidence.Path } else { "" }
        backup_sha256 = if ($null -ne $backupEvidence) { $backupEvidence.Sha256 } else { "" }
        backup_byte_length = if ($null -ne $backupEvidence) { $backupEvidence.ByteLength } else { 0 }
        installed_release_config = $InstalledReleaseConfig
        prepared_at_utc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 8
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $canonicalPath `
        -Text $payload `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount `
        -ReplaceExisting:$ReplaceProtectedReceipt
    Assert-TicketboxProtectedLifecycleReceipt $canonicalPath
}

function Read-TicketboxLifecycleReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][object]$TargetReleaseConfig,
        [string]$CurrentTargetBackendVersion = "",
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [switch]$AllowPreviousInstallerOwnerProcessId,
        [switch]$AllowLegacyV7WithoutTargetVersionFloor
    )

    $canonicalPath = Assert-TicketboxLifecycleReceiptPath $Path
    Assert-TicketboxProtectedLifecycleReceipt $canonicalPath
    try {
        $receipt = Get-Content -LiteralPath $canonicalPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "安装生命周期回执不是有效 JSON。"
    }
    $targetVersionProperty = $receipt.PSObject.Properties["target_backend_version_floor"]
    $isLegacyV7 =
        [string]$receipt.schema -ceq $script:TicketboxLegacyLifecycleReceiptSchema
    if ($isLegacyV7) {
        if (-not $AllowLegacyV7WithoutTargetVersionFloor -or $null -ne $targetVersionProperty) {
            throw "legacy v7 生命周期回执只能由显式迁移或只读卸载合同接管。"
        }
    }
    else {
        if ([string]$receipt.schema -cne $script:TicketboxLifecycleReceiptSchema) {
            throw "安装生命周期回执 schema 不受支持。"
        }
        if ($null -eq $targetVersionProperty -or $targetVersionProperty.Value -isnot [string]) {
            throw "安装生命周期回执缺少目标版本下限。"
        }
        if ([string]::IsNullOrWhiteSpace($CurrentTargetBackendVersion)) {
            throw "读取当前生命周期回执必须提供安装器目标版本。"
        }
        $targetVersionFloor = ConvertTo-TicketboxLifecycleVersion `
            ([string]$targetVersionProperty.Value) `
            "生命周期回执目标版本下限"
        if ([string]$targetVersionProperty.Value -cne $targetVersionFloor.Canonical) {
            throw "安装生命周期回执目标版本下限不是规范版本。"
        }
        if (
            (Compare-TicketboxLifecycleVersions `
                -Left $CurrentTargetBackendVersion `
                -Right $targetVersionFloor.Canonical) -lt 0
        ) {
            throw "当前安装器目标版本低于已开始安装事务的版本下限；拒绝降级覆盖。"
        }
    }
    foreach ($name in @(
        "backup_required",
        "backup_completed",
        "files_may_have_been_replaced",
        "install_completed",
        "temporary_pg_service_cleanup_pending"
    )) {
        if ($receipt.PSObject.Properties[$name].Value -isnot [bool]) {
            throw "安装生命周期回执的 $name 必须是布尔值。"
        }
    }
    if ([string]$receipt.mode -notin $script:TicketboxLifecycleReceiptModes) {
        throw "安装生命周期回执 mode 不受支持。"
    }
    if ([string]$receipt.preparation_stage -notin $script:TicketboxLifecycleReceiptPreparationStages) {
        throw "安装生命周期回执 preparation_stage 不受支持。"
    }
    if (
        [string]$receipt.previous_pg_state -notin $script:TicketboxLifecycleReceiptStates -or
        [string]$receipt.previous_backend_state -notin $script:TicketboxLifecycleReceiptStates
    ) {
        throw "安装生命周期回执包含无效服务状态。"
    }
    if (
        [string]$receipt.previous_pg_start_policy -notin $script:TicketboxLifecycleReceiptStartPolicies -or
        [string]$receipt.previous_backend_start_policy -notin $script:TicketboxLifecycleReceiptStartPolicies -or
        (
            ([string]$receipt.previous_pg_state -eq "absent") -ne
            ([string]$receipt.previous_pg_start_policy -eq "absent")
        ) -or
        (
            ([string]$receipt.previous_backend_state -eq "absent") -ne
            ([string]$receipt.previous_backend_start_policy -eq "absent")
        )
    ) {
        throw "安装生命周期回执包含无效或不一致的服务启动策略。"
    }
    if (
        -not (Test-TicketboxPathEquals ([string]$receipt.install_dir) $InstallDir) -or
        -not (Test-TicketboxPathEquals ([string]$receipt.data_root) $DataRoot) -or
        [int]$receipt.pg_port -ne $PgPort -or
        [int]$receipt.backend_port -ne $BackendPort -or
        [int]$receipt.installer_owner_process_id -le 0 -or
        (
            -not $AllowPreviousInstallerOwnerProcessId -and
            [int]$receipt.installer_owner_process_id -ne $InstallerOwnerProcessId
        )
    ) {
        throw "安装生命周期回执与当前安装输入不匹配。"
    }
    try {
        $receiptVolumeIdentity = ConvertTo-TicketboxCanonicalVolumeIdentity `
            ([string]$receipt.data_volume_identity)
    }
    catch {
        throw "安装生命周期回执的 Windows volume identity 无效。"
    }
    $dataRootMarker = Read-TicketboxProtectedDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    if ($receiptVolumeIdentity -cne $dataRootMarker.DataVolumeIdentity) {
        throw "安装生命周期回执与当前 DataRoot volume authority 不匹配。"
    }
    if ($PgPort -eq $BackendPort) {
        throw "PostgreSQL 与后端端口不能相同。"
    }
    Assert-TicketboxReleaseIdentityCompatible `
        -InstalledConfig $receipt.installed_release_config `
        -TargetConfig $TargetReleaseConfig
    $expectedTemporaryServiceName = [string]$receipt.installed_release_config.pg_service_name
    if (
        [string]$receipt.temporary_pg_service_name -cne $expectedTemporaryServiceName -or
        [string]$receipt.temporary_pg_service_account -cne "NT SERVICE\$expectedTemporaryServiceName" -or
        -not (Test-TicketboxPathEquals `
            ([string]$receipt.temporary_pg_service_data_root) `
            (Join-Path (ConvertTo-TicketboxCanonicalPath $DataRoot) "pgdata"))
    ) {
        throw "安装生命周期回执中的临时 PostgreSQL SCM 身份与发布配置不一致。"
    }
    if ([bool]$receipt.backup_completed -and -not [bool]$receipt.backup_required) {
        throw "安装生命周期回执的备份状态矛盾。"
    }
    $expectedFilesReplaced = [string]$receipt.preparation_stage -in @(
        "program_files_installed_backup_pending",
        "files_may_have_been_replaced",
        "install_completed"
    )
    $expectedInstallCompleted = [string]$receipt.preparation_stage -eq "install_completed"
    if (
        [bool]$receipt.files_may_have_been_replaced -ne $expectedFilesReplaced -or
        [bool]$receipt.install_completed -ne $expectedInstallCompleted
    ) {
        throw "安装生命周期回执的阶段状态矛盾。"
    }
    if ([string]$receipt.preparation_stage -in @(
        "backup_deferred_until_program_files_installed",
        "program_files_installed_backup_pending"
    )) {
        if (
            [string]$receipt.mode -ne "preserved_data_reinstall" -or
            -not [bool]$receipt.backup_required -or
            [bool]$receipt.backup_completed -or
            -not [string]::IsNullOrWhiteSpace([string]$receipt.backup_path)
        ) {
            throw "安装生命周期回执的延期备份状态不可信。"
        }
    }
    if (
        [bool]$receipt.temporary_pg_service_cleanup_pending -and
        (
            [string]$receipt.mode -ne "preserved_data_reinstall" -or
            [string]$receipt.preparation_stage -ne "program_files_installed_backup_pending"
        )
    ) {
        throw "安装生命周期回执中的临时 PostgreSQL 服务清理义务不可信。"
    }
    if (
        [string]$receipt.preparation_stage -notin @(
            "captured",
            "backup_deferred_until_program_files_installed",
            "program_files_installed_backup_pending"
        ) -and
        [bool]$receipt.backup_required -and
        -not [bool]$receipt.backup_completed
    ) {
        throw "需要保留数据的安装回执必须证明复制前备份已完成。"
    }
    $backupByteLength = 0L
    if (-not [long]::TryParse([string]$receipt.backup_byte_length, [ref]$backupByteLength)) {
        throw "安装生命周期回执的备份字节长度无效。"
    }
    if ([bool]$receipt.backup_completed) {
        $verifiedBackup = Assert-TicketboxLifecycleBackupEvidence `
            -BackupPath ([string]$receipt.backup_path) `
            -DataRoot $DataRoot `
            -Mode ([string]$receipt.mode) `
            -ExpectedSha256 ([string]$receipt.backup_sha256) `
            -ExpectedByteLength $backupByteLength `
            -KeepOpen:(-not [bool]$receipt.install_completed)
        if ($null -ne $verifiedBackup.GuardStream) {
            $receipt | Add-Member `
                -NotePropertyName "backup_guard_stream" `
                -NotePropertyValue $verifiedBackup.GuardStream
        }
    }
    elseif (
        -not [string]::IsNullOrWhiteSpace([string]$receipt.backup_path) -or
        -not [string]::IsNullOrWhiteSpace([string]$receipt.backup_sha256) -or
        $backupByteLength -ne 0
    ) {
        throw "未完成的安装生命周期回执携带了备份证据。"
    }
    return $receipt
}

function Read-TicketboxCompatibleLifecycleReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][object]$TargetReleaseConfig,
        [Parameter(Mandatory = $true)][string]$CurrentTargetBackendVersion,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [switch]$AllowPreviousInstallerOwnerProcessId
    )

    $canonicalPath = Assert-TicketboxLifecycleReceiptPath $Path
    Assert-TicketboxProtectedLifecycleReceipt $canonicalPath
    try {
        $envelope = Get-Content -LiteralPath $canonicalPath -Encoding UTF8 -Raw |
            ConvertFrom-Json
    }
    catch {
        throw "安装生命周期回执不是有效 JSON。"
    }
    $readArguments = @{
        Path = $canonicalPath
        InstallDir = $InstallDir
        DataRoot = $DataRoot
        PgPort = $PgPort
        BackendPort = $BackendPort
        TargetReleaseConfig = $TargetReleaseConfig
        InstallerOwnerProcessId = $InstallerOwnerProcessId
        AllowPreviousInstallerOwnerProcessId = $AllowPreviousInstallerOwnerProcessId
    }
    if ([string]$envelope.schema -ceq $script:TicketboxLegacyLifecycleReceiptSchema) {
        $readArguments.AllowLegacyV7WithoutTargetVersionFloor = $true
    }
    elseif ([string]$envelope.schema -ceq $script:TicketboxLifecycleReceiptSchema) {
        $readArguments.CurrentTargetBackendVersion = $CurrentTargetBackendVersion
    }
    else {
        throw "安装生命周期回执 schema 不受支持。"
    }
    return Read-TicketboxLifecycleReceipt @readArguments
}

function ConvertTo-TicketboxCurrentLifecycleReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][object]$TargetReleaseConfig,
        [Parameter(Mandatory = $true)][string]$CurrentTargetBackendVersion,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [switch]$AllowPreviousInstallerOwnerProcessId
    )

    $compatibleReceipt = Read-TicketboxCompatibleLifecycleReceipt `
        -Path $Path `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -TargetReleaseConfig $TargetReleaseConfig `
        -CurrentTargetBackendVersion $CurrentTargetBackendVersion `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -AllowPreviousInstallerOwnerProcessId:$AllowPreviousInstallerOwnerProcessId
    if ([string]$compatibleReceipt.schema -ceq $script:TicketboxLifecycleReceiptSchema) {
        return $compatibleReceipt
    }
    $canonicalPath = Assert-TicketboxLifecycleReceiptPath $Path
    try {
        Write-TicketboxLifecycleReceipt `
            -Path $canonicalPath `
            -Mode ([string]$compatibleReceipt.mode) `
            -InstallDir ([string]$compatibleReceipt.install_dir) `
            -DataRoot ([string]$compatibleReceipt.data_root) `
            -PgPort ([int]$compatibleReceipt.pg_port) `
            -BackendPort ([int]$compatibleReceipt.backend_port) `
            -InstalledReleaseConfig $compatibleReceipt.installed_release_config `
            -TargetBackendVersionFloor $CurrentTargetBackendVersion `
            -InstallerOwnerProcessId $InstallerOwnerProcessId `
            -PreviousPgState ([string]$compatibleReceipt.previous_pg_state) `
            -PreviousBackendState ([string]$compatibleReceipt.previous_backend_state) `
            -PreviousPgStartPolicy ([string]$compatibleReceipt.previous_pg_start_policy) `
            -PreviousBackendStartPolicy ([string]$compatibleReceipt.previous_backend_start_policy) `
            -BackupRequired ([bool]$compatibleReceipt.backup_required) `
            -BackupCompleted ([bool]$compatibleReceipt.backup_completed) `
            -PreparationStage ([string]$compatibleReceipt.preparation_stage) `
            -BackupPath ([string]$compatibleReceipt.backup_path) `
            -BackupSha256 ([string]$compatibleReceipt.backup_sha256) `
            -BackupByteLength ([long]$compatibleReceipt.backup_byte_length) `
            -FilesMayHaveBeenReplaced ([bool]$compatibleReceipt.files_may_have_been_replaced) `
            -InstallCompleted ([bool]$compatibleReceipt.install_completed) `
            -TemporaryPgServiceCleanupPending `
                ([bool]$compatibleReceipt.temporary_pg_service_cleanup_pending) `
            -ReplaceProtectedReceipt `
            -ReplaceVerifiedLegacyReceipt
    }
    finally {
        Close-TicketboxLifecycleBackupGuard $compatibleReceipt
    }
    return Read-TicketboxLifecycleReceipt `
        -Path $canonicalPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -TargetReleaseConfig $TargetReleaseConfig `
        -CurrentTargetBackendVersion $CurrentTargetBackendVersion `
        -InstallerOwnerProcessId $InstallerOwnerProcessId
}

function Assert-TicketboxLifecycleReceiptStage([object]$Receipt, [string]$ExpectedStage) {
    if ([string]$Receipt.preparation_stage -ne $ExpectedStage) {
        throw "安装生命周期回执不能从 $($Receipt.preparation_stage) 跃迁；预期阶段为 $ExpectedStage。"
    }
}

function Set-TicketboxLifecycleReceiptTargetVersionFloor {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][string]$TargetBackendVersionFloor
    )

    $comparison = Compare-TicketboxLifecycleVersions `
        -Left $TargetBackendVersionFloor `
        -Right ([string]$Receipt.target_backend_version_floor)
    if ($comparison -lt 0) {
        throw "安装生命周期回执目标版本下限不能回退。"
    }
    if ($comparison -eq 0) {
        Close-TicketboxLifecycleBackupGuard $Receipt
        return
    }
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor $TargetBackendVersionFloor `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired ([bool]$Receipt.backup_required) `
        -BackupCompleted ([bool]$Receipt.backup_completed) `
        -PreparationStage ([string]$Receipt.preparation_stage) `
        -BackupPath ([string]$Receipt.backup_path) `
        -BackupSha256 ([string]$Receipt.backup_sha256) `
        -BackupByteLength ([long]$Receipt.backup_byte_length) `
        -FilesMayHaveBeenReplaced ([bool]$Receipt.files_may_have_been_replaced) `
        -InstallCompleted ([bool]$Receipt.install_completed) `
        -TemporaryPgServiceCleanupPending ([bool]$Receipt.temporary_pg_service_cleanup_pending) `
        -ReplaceProtectedReceipt
    Close-TicketboxLifecycleBackupGuard $Receipt
}

function Set-TicketboxLifecycleReceiptDeferredBackup {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId
    )

    Assert-TicketboxLifecycleReceiptStage $Receipt "captured"
    if ([string]$Receipt.mode -ne "preserved_data_reinstall") {
        throw "只有 preserved-data reinstall 可以延期到目标 PostgreSQL 工具完成备份。"
    }
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired $true `
        -BackupCompleted $false `
        -PreparationStage "backup_deferred_until_program_files_installed" `
        -FilesMayHaveBeenReplaced $false `
        -InstallCompleted $false `
        -ReplaceProtectedReceipt
}

function Set-TicketboxLifecycleReceiptProgramFilesInstalledBackupPending {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId
    )

    Assert-TicketboxLifecycleReceiptStage `
        $Receipt `
        "backup_deferred_until_program_files_installed"
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired $true `
        -BackupCompleted $false `
        -PreparationStage "program_files_installed_backup_pending" `
        -FilesMayHaveBeenReplaced $true `
        -InstallCompleted $false `
        -ReplaceProtectedReceipt
}

function Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][bool]$CleanupPending
    )

    Assert-TicketboxLifecycleReceiptStage $Receipt "program_files_installed_backup_pending"
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired $true `
        -BackupCompleted $false `
        -PreparationStage "program_files_installed_backup_pending" `
        -FilesMayHaveBeenReplaced $true `
        -InstallCompleted $false `
        -TemporaryPgServiceCleanupPending $CleanupPending `
        -ReplaceProtectedReceipt
}

function Set-TicketboxLifecycleReceiptDeferredBackupCompleted {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][string]$BackupPath
    )

    Assert-TicketboxLifecycleReceiptStage $Receipt "program_files_installed_backup_pending"
    if ([bool]$Receipt.temporary_pg_service_cleanup_pending) {
        throw "临时 PostgreSQL 服务尚未完成精确清理，不能提交 preserved-data 备份。"
    }
    $backupEvidence = Get-TicketboxLifecycleBackupEvidence `
        -BackupPath $BackupPath `
        -DataRoot ([string]$Receipt.data_root) `
        -Mode ([string]$Receipt.mode)
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired $true `
        -BackupCompleted $true `
        -PreparationStage "files_may_have_been_replaced" `
        -BackupPath $backupEvidence.Path `
        -BackupSha256 $backupEvidence.Sha256 `
        -BackupByteLength $backupEvidence.ByteLength `
        -FilesMayHaveBeenReplaced $true `
        -InstallCompleted $false `
        -ReplaceProtectedReceipt
}

function Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId
    )

    Assert-TicketboxLifecycleReceiptStage $Receipt "prepared"
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired ([bool]$Receipt.backup_required) `
        -BackupCompleted ([bool]$Receipt.backup_completed) `
        -PreparationStage "files_may_have_been_replaced" `
        -BackupPath ([string]$Receipt.backup_path) `
        -BackupSha256 ([string]$Receipt.backup_sha256) `
        -BackupByteLength ([long]$Receipt.backup_byte_length) `
        -FilesMayHaveBeenReplaced $true `
        -InstallCompleted ([bool]$Receipt.install_completed) `
        -ReplaceProtectedReceipt
    Close-TicketboxLifecycleBackupGuard $Receipt
}

function Set-TicketboxLifecycleReceiptInstallCompleted {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId
    )

    Assert-TicketboxLifecycleReceiptStage $Receipt "files_may_have_been_replaced"
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired ([bool]$Receipt.backup_required) `
        -BackupCompleted ([bool]$Receipt.backup_completed) `
        -PreparationStage "install_completed" `
        -BackupPath ([string]$Receipt.backup_path) `
        -BackupSha256 ([string]$Receipt.backup_sha256) `
        -BackupByteLength ([long]$Receipt.backup_byte_length) `
        -FilesMayHaveBeenReplaced ([bool]$Receipt.files_may_have_been_replaced) `
        -InstallCompleted $true `
        -ReplaceProtectedReceipt
    Close-TicketboxLifecycleBackupGuard $Receipt
}

function Get-TicketboxInstallerRuntimeStateDirectory([string]$CommonApplicationData = "") {
    if ([string]::IsNullOrWhiteSpace($CommonApplicationData)) {
        $CommonApplicationData = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::CommonApplicationData
        )
    }
    if ([string]::IsNullOrWhiteSpace($CommonApplicationData)) {
        throw "Windows 未提供 Common Application Data，无法建立安装运行时阻断投影。"
    }
    return Join-Path `
        ([System.IO.Path]::GetFullPath($CommonApplicationData)) `
        $script:TicketboxInstallerRuntimeStateDirectoryName
}

function Get-TicketboxInstallerRuntimeRecoveryGuardPath {
    return Join-Path `
        (Get-TicketboxInstallerRuntimeStateDirectory) `
        $script:TicketboxInstallerRuntimeRecoveryGuardFileName
}

function Enable-TicketboxInstalledServicesAutoStart {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$TargetReleaseConfig
    )

    $pgServiceName = [string]$TargetReleaseConfig.pg_service_name
    $backendServiceName = [string]$TargetReleaseConfig.backend_service_name
    $pgCtl = Join-Path $InstallDir "pg\bin\pg_ctl.exe"
    $shawl = Join-Path $InstallDir "shawl\shawl.exe"
    $binding = Read-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts @(
            (Get-TicketboxServiceSid $pgServiceName),
            (Get-TicketboxServiceSid $backendServiceName)
        )
    Assert-TicketboxServiceAccount `
        -Name $pgServiceName `
        -ExpectedAccount "NT SERVICE\$pgServiceName"
    Assert-TicketboxPgServiceCommand `
        -Name $pgServiceName `
        -ExpectedExecutable $pgCtl `
        -ExpectedServiceName $pgServiceName `
        -ExpectedDataRoot $binding.RuntimePgData
    Assert-TicketboxServiceAccount `
        -Name $backendServiceName `
        -ExpectedAccount "NT SERVICE\$backendServiceName"
    Assert-TicketboxShawlServiceCommand `
        -Name $backendServiceName `
        -ExpectedExecutable $shawl `
        -ExpectedServiceName $backendServiceName `
        -ExpectedCwd $binding.RuntimeAppData `
        -ExpectedPayload (Join-Path $InstallDir "program\ticketbox-backend\ticketbox-backend.exe") `
        -ExpectedDependency $pgServiceName `
        -ExpectedLogDir (Join-Path $binding.RuntimeAppData "logs") `
        -ExpectedPgDumpPath (Join-Path $InstallDir "pg\bin\pg_dump.exe") `
        -ExpectedPgRestorePath (Join-Path $InstallDir "pg\bin\pg_restore.exe") `
        -ExpectedBootstrapRecoveryGuardPath (Get-TicketboxRuntimeBootstrapRecoveryGuardPath $binding.RuntimeDataRoot) `
        -ExpectedInstallerRecoveryGuardPath (Get-TicketboxInstallerRuntimeRecoveryGuardPath) `
        -ExpectedDataRootMarkerPath (Join-Path $binding.RuntimeDataRoot $script:TicketboxDataRootMarkerName) `
        -ExpectedDataVolumeIdentity $binding.DataVolumeIdentity `
        -ExpectedOwnerRecoveryChannel ([string]$TargetReleaseConfig.owner_recovery_channel) `
        -ExpectedStopTimeoutMs ([int]$TargetReleaseConfig.stop_timeout_ms) `
        -ExpectedRestartDelayMs ([int]$TargetReleaseConfig.restart_delay_ms)
    $services = @(
        @{
            Name = $pgServiceName
            Executable = $pgCtl
        },
        @{
            Name = $backendServiceName
            Executable = $shawl
        }
    )
    foreach ($service in $services) {
        if (-not (Test-TicketboxServiceExists $service.Name)) {
            throw "安装提交缺少 Windows 服务：$($service.Name)"
        }
        Assert-TicketboxServiceOwnership `
            -Name $service.Name `
            -ExpectedExecutable $service.Executable | Out-Null
        Set-TicketboxOwnedServiceDelayedAutoStartIfExists `
            -Name $service.Name `
            -ExpectedExecutable $service.Executable
        Assert-TicketboxServiceDelayedAutoStart $service.Name
    }
}

function Get-TicketboxInstallerRuntimeStateShape {
    param([Parameter(Mandatory = $true)][string]$DataRoot)

    $runtimeStateDirectory = Get-TicketboxInstallerRuntimeStateDirectory
    $guardPath = Get-TicketboxInstallerRuntimeRecoveryGuardPath
    if (
        (Test-TicketboxPathWithin $runtimeStateDirectory $DataRoot) -or
        (Test-TicketboxPathWithin $DataRoot $runtimeStateDirectory)
    ) {
        throw "安装运行时恢复 guard 不能位于可恢复 DataRoot 内或包含 DataRoot。"
    }
    Assert-NoTicketboxAncestorReparsePoints $runtimeStateDirectory
    $directoryKind = Get-TicketboxPathEntryKindNoFollow $runtimeStateDirectory
    if ($directoryKind -ceq "Missing") {
        return [pscustomobject]@{
            DirectoryExists = $false
            GuardExists = $false
            DirectoryPath = $runtimeStateDirectory
            GuardPath = $guardPath
        }
    }
    if ($directoryKind -cne "Directory") {
        throw "machine runtime-state 路径不是可信普通目录：$runtimeStateDirectory"
    }
    $guardKind = Get-TicketboxPathEntryKindNoFollow $guardPath
    if ($guardKind -notin @("Missing", "File")) {
        throw "安装运行时恢复 guard 不是可信普通文件：$guardPath"
    }
    $guardExists = $guardKind -ceq "File"
    return [pscustomobject]@{
        DirectoryExists = $true
        GuardExists = [bool]$guardExists
        DirectoryPath = $runtimeStateDirectory
        GuardPath = $guardPath
    }
}

function Assert-TicketboxInstallerRuntimeRecoveryGuardPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )

    $canonicalPath = [System.IO.Path]::GetFullPath($Path)
    $expectedPath = Get-TicketboxInstallerRuntimeRecoveryGuardPath
    if (-not (Test-TicketboxPathEquals $canonicalPath $expectedPath)) {
        throw "安装运行时恢复 guard 必须位于 OS 动态解析的独立 machine runtime-state 域。"
    }
    $shape = Get-TicketboxInstallerRuntimeStateShape -DataRoot $DataRoot
    if ($shape.DirectoryExists) {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $shape.DirectoryPath `
            -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
            -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
            -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    }
    return $canonicalPath
}

function Initialize-TicketboxInstallerRuntimeStateDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )

    $runtimeStateDirectory = Get-TicketboxInstallerRuntimeStateDirectory
    if (
        (Test-TicketboxPathWithin $runtimeStateDirectory $DataRoot) -or
        (Test-TicketboxPathWithin $DataRoot $runtimeStateDirectory)
    ) {
        throw "machine runtime-state 目录不能位于可恢复 DataRoot 内或包含 DataRoot。"
    }
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $runtimeStateDirectory `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount | Out-Null
    return $runtimeStateDirectory
}

function Read-TicketboxInstallerRuntimeRecoveryGuard {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )

    Assert-TicketboxDataRootMarker -DataRoot $DataRoot -InstallDir $InstallDir
    $canonicalPath = Assert-TicketboxInstallerRuntimeRecoveryGuardPath `
        -Path $Path `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName
    $backendReadAccount = "NT SERVICE\$BackendServiceName"
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $canonicalPath `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -ReadExecuteAccounts @($backendReadAccount) `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount `
        -MaximumBytes 16384
    try { $guard = ConvertFrom-Json -InputObject $artifact.Text }
    catch { throw "安装运行时恢复 guard 无法读取为有效 JSON。" }
    $createdAt = [DateTimeOffset]::MinValue
    if (
        @($guard.PSObject.Properties).Count -ne 5 -or
        [string]$guard.schema -cne $script:TicketboxInstallerRuntimeRecoveryGuardSchema -or
        [string]$guard.state -cne "installer_transaction_pending" -or
        -not (Test-TicketboxPathEquals ([string]$guard.install_dir) $InstallDir) -or
        -not (Test-TicketboxPathEquals ([string]$guard.data_root) $DataRoot) -or
        -not [DateTimeOffset]::TryParse(
            [string]$guard.created_at_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$createdAt
        )
    ) {
        throw "安装运行时恢复 guard 内容或安装绑定校验失败。"
    }
    return $guard
}

function Write-TicketboxInstallerRuntimeRecoveryGuard {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )

    Assert-TicketboxDataRootMarker -DataRoot $DataRoot -InstallDir $InstallDir
    Initialize-TicketboxInstallerRuntimeStateDirectory `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName | Out-Null
    $canonicalPath = Assert-TicketboxInstallerRuntimeRecoveryGuardPath `
        -Path $Path `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName
    if (Test-Path -LiteralPath $canonicalPath) {
        Read-TicketboxInstallerRuntimeRecoveryGuard `
            -Path $canonicalPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -BackendServiceName $BackendServiceName | Out-Null
        return
    }
    $payload = [ordered]@{
        schema = $script:TicketboxInstallerRuntimeRecoveryGuardSchema
        state = "installer_transaction_pending"
        install_dir = ConvertTo-TicketboxCanonicalPath $InstallDir
        data_root = ConvertTo-TicketboxCanonicalPath $DataRoot
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $canonicalPath `
        -Text $payload `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    Read-TicketboxInstallerRuntimeRecoveryGuard `
        -Path $canonicalPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName | Out-Null
}

function Remove-TicketboxInstallerRuntimeRecoveryGuard {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )

    $canonicalPath = Assert-TicketboxInstallerRuntimeRecoveryGuardPath `
        -Path $Path `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName
    if (-not (Test-Path -LiteralPath $canonicalPath)) { return }
    Read-TicketboxInstallerRuntimeRecoveryGuard `
        -Path $canonicalPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName | Out-Null
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $canonicalPath `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
}

function Remove-TicketboxInstallerRuntimeStateDirectoryIfEmpty {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )

    $runtimeStateDirectory = Get-TicketboxInstallerRuntimeStateDirectory
    if (-not (Test-Path -LiteralPath $runtimeStateDirectory)) { return }
    Assert-TicketboxInstallerRuntimeRecoveryGuardPath `
        -Path (Get-TicketboxInstallerRuntimeRecoveryGuardPath) `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName | Out-Null
    $remaining = @(Get-ChildItem -LiteralPath $runtimeStateDirectory -Force -ErrorAction Stop)
    if ($remaining.Count -gt 0) {
        throw "安装运行时状态目录仍含未退役 artifact：$($remaining.Name -join ', ')"
    }
    Remove-Item -LiteralPath $runtimeStateDirectory -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $runtimeStateDirectory) {
        throw "无法删除已退役的安装运行时状态目录。"
    }
}

function Complete-TicketboxInstalledLifecycleTransaction {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][int]$PgPort,
        [Parameter(Mandatory = $true)][int]$BackendPort,
        [Parameter(Mandatory = $true)][object]$TargetReleaseConfig,
        [Parameter(Mandatory = $true)][string]$TargetBackendVersion,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][string]$BuildManifestPath,
        [Parameter(Mandatory = $true)][string]$RecoveryRequiredPath,
        [Parameter(Mandatory = $true)][string]$RuntimeRecoveryGuardPath
    )

    $receipt = Read-TicketboxLifecycleReceipt `
        -Path $Path `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -TargetReleaseConfig $TargetReleaseConfig `
        -CurrentTargetBackendVersion $TargetBackendVersion `
        -InstallerOwnerProcessId $InstallerOwnerProcessId
    if ([string]$receipt.preparation_stage -notin @(
        "files_may_have_been_replaced",
        "install_completed"
    )) {
        throw "安装提交阶段不允许从当前回执继续：$($receipt.preparation_stage)。"
    }
    Write-TicketboxPersistentInstallationIdentity `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -PgServiceName ([string]$TargetReleaseConfig.pg_service_name) `
        -BackendServiceName ([string]$TargetReleaseConfig.backend_service_name) `
        -BuildManifestPath $BuildManifestPath | Out-Null
    if ([string]$receipt.preparation_stage -eq "files_may_have_been_replaced") {
        Set-TicketboxLifecycleReceiptInstallCompleted `
            -Path $Path `
            -Receipt $receipt `
            -InstallerOwnerProcessId $InstallerOwnerProcessId
        $receipt = Read-TicketboxLifecycleReceipt `
            -Path $Path `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $TargetReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerOwnerProcessId
    }
    Assert-TicketboxCompletedLifecycleReceipt $receipt
    Remove-TicketboxPgRecoveryToolset `
        -ExpectedMajor 0 `
        -InstallCommitValidated
    Enable-TicketboxInstalledServicesAutoStart `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -TargetReleaseConfig $TargetReleaseConfig
    Remove-TicketboxInstallerRecoveryMarker `
        -Path $RecoveryRequiredPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot
    Remove-TicketboxInstallerRuntimeRecoveryGuard `
        -Path $RuntimeRecoveryGuardPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -BackendServiceName ([string]$TargetReleaseConfig.backend_service_name)
}

function Set-TicketboxLifecycleReceiptInstallerOwner {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId
    )

    if ([string]$Receipt.preparation_stage -notin @(
        "backup_deferred_until_program_files_installed",
        "program_files_installed_backup_pending",
        "prepared",
        "files_may_have_been_replaced",
        "install_completed"
    )) {
        throw "只能为可恢复安装阶段重绑当前安装器进程。"
    }
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired ([bool]$Receipt.backup_required) `
        -BackupCompleted ([bool]$Receipt.backup_completed) `
        -PreparationStage ([string]$Receipt.preparation_stage) `
        -BackupPath ([string]$Receipt.backup_path) `
        -BackupSha256 ([string]$Receipt.backup_sha256) `
        -BackupByteLength ([long]$Receipt.backup_byte_length) `
        -FilesMayHaveBeenReplaced ([bool]$Receipt.files_may_have_been_replaced) `
        -InstallCompleted ([bool]$Receipt.install_completed) `
        -TemporaryPgServiceCleanupPending ([bool]$Receipt.temporary_pg_service_cleanup_pending) `
        -ReplaceProtectedReceipt
    Close-TicketboxLifecycleBackupGuard $Receipt
}

function Set-TicketboxLifecycleReceiptPrepared {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][bool]$BackupCompleted,
        [string]$BackupPath = ""
    )

    Assert-TicketboxLifecycleReceiptStage $Receipt "captured"
    $backupEvidence = $null
    if ($BackupCompleted) {
        $backupEvidence = Get-TicketboxLifecycleBackupEvidence `
            -BackupPath $BackupPath `
            -DataRoot ([string]$Receipt.data_root) `
            -Mode ([string]$Receipt.mode)
    }
    Write-TicketboxLifecycleReceipt `
        -Path $Path `
        -Mode ([string]$Receipt.mode) `
        -InstallDir ([string]$Receipt.install_dir) `
        -DataRoot ([string]$Receipt.data_root) `
        -PgPort ([int]$Receipt.pg_port) `
        -BackendPort ([int]$Receipt.backend_port) `
        -InstalledReleaseConfig $Receipt.installed_release_config `
        -TargetBackendVersionFloor ([string]$Receipt.target_backend_version_floor) `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -PreviousPgState ([string]$Receipt.previous_pg_state) `
        -PreviousBackendState ([string]$Receipt.previous_backend_state) `
        -PreviousPgStartPolicy ([string]$Receipt.previous_pg_start_policy) `
        -PreviousBackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
        -BackupRequired ([bool]$Receipt.backup_required) `
        -BackupCompleted $BackupCompleted `
        -PreparationStage "prepared" `
        -BackupPath $BackupPath `
        -BackupSha256 $(if ($null -ne $backupEvidence) { $backupEvidence.Sha256 } else { "" }) `
        -BackupByteLength $(if ($null -ne $backupEvidence) { $backupEvidence.ByteLength } else { 0 }) `
        -FilesMayHaveBeenReplaced $false `
        -InstallCompleted $false `
        -ReplaceProtectedReceipt
}

function Assert-TicketboxCompletedLifecycleReceipt([object]$Receipt) {
    if (
        $null -eq $Receipt -or
        [string]$Receipt.preparation_stage -cne "install_completed" -or
        $Receipt.install_completed -isnot [bool] -or
        -not [bool]$Receipt.install_completed -or
        $Receipt.files_may_have_been_replaced -isnot [bool] -or
        -not [bool]$Receipt.files_may_have_been_replaced -or
        $Receipt.temporary_pg_service_cleanup_pending -isnot [bool] -or
        [bool]$Receipt.temporary_pg_service_cleanup_pending
    ) {
        throw "只能清理已完成且无临时服务清理义务的安装生命周期回执。"
    }
}

function Read-TicketboxCompletedLifecycleReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$TargetReleaseConfig,
        [ValidateRange(0, 65535)][int]$ExpectedPgPort = 0,
        [ValidateRange(0, 65535)][int]$ExpectedBackendPort = 0,
        [string]$ExpectedPgServiceName = "",
        [string]$ExpectedBackendServiceName = ""
    )

    $canonicalPath = Assert-TicketboxLifecycleReceiptPath $Path
    Assert-TicketboxProtectedLifecycleReceipt $canonicalPath
    try {
        $envelope = Get-Content -LiteralPath $canonicalPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "安装生命周期回执不是有效 JSON。"
    }
    $pgPort = 0
    $backendPort = 0
    $targetVersionProperty = $envelope.PSObject.Properties["target_backend_version_floor"]
    $isLegacyV7 =
        [string]$envelope.schema -ceq $script:TicketboxLegacyLifecycleReceiptSchema
    if ($isLegacyV7) {
        if ($null -ne $targetVersionProperty) {
            throw "legacy v7 生命周期回执不能携带目标版本下限。"
        }
    }
    else {
        if ([string]$envelope.schema -cne $script:TicketboxLifecycleReceiptSchema) {
            throw "安装生命周期回执 schema 不受支持。"
        }
        if ($null -eq $targetVersionProperty -or $targetVersionProperty.Value -isnot [string]) {
            throw "安装生命周期回执缺少目标版本下限。"
        }
        $targetVersionFloor = ConvertTo-TicketboxLifecycleVersion `
            ([string]$targetVersionProperty.Value) `
            "生命周期回执目标版本下限"
        if ([string]$targetVersionProperty.Value -cne $targetVersionFloor.Canonical) {
            throw "安装生命周期回执目标版本下限不是规范版本。"
        }
    }
    if (
        -not [int]::TryParse([string]$envelope.pg_port, [ref]$pgPort) -or
        -not [int]::TryParse([string]$envelope.backend_port, [ref]$backendPort) -or
        $pgPort -lt 1 -or $pgPort -gt 65535 -or
        $backendPort -lt 1 -or $backendPort -gt 65535
    ) {
        throw "安装生命周期回执端口无效。"
    }
    $readArguments = @{
        Path = $canonicalPath
        InstallDir = $InstallDir
        DataRoot = $DataRoot
        PgPort = $pgPort
        BackendPort = $backendPort
        TargetReleaseConfig = $TargetReleaseConfig
        InstallerOwnerProcessId = $PID
        AllowPreviousInstallerOwnerProcessId = $true
    }
    if ($isLegacyV7) {
        $readArguments.AllowLegacyV7WithoutTargetVersionFloor = $true
    }
    else {
        $readArguments.CurrentTargetBackendVersion = $targetVersionFloor.Canonical
    }
    $receipt = Read-TicketboxLifecycleReceipt @readArguments
    Assert-TicketboxCompletedLifecycleReceipt $receipt
    if (
        ($ExpectedPgPort -gt 0 -and $pgPort -ne $ExpectedPgPort) -or
        ($ExpectedBackendPort -gt 0 -and $backendPort -ne $ExpectedBackendPort) -or
        (
            $ExpectedPgServiceName.Trim().Length -gt 0 -and
            -not [string]::Equals(
                [string]$receipt.installed_release_config.pg_service_name,
                $ExpectedPgServiceName,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) -or
        (
            $ExpectedBackendServiceName.Trim().Length -gt 0 -and
            -not [string]::Equals(
                [string]$receipt.installed_release_config.backend_service_name,
                $ExpectedBackendServiceName,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        )
    ) {
        throw "已完成安装生命周期回执与旧注册安装身份不匹配。"
    }
    return $receipt
}

function Remove-TicketboxCompletedLifecycleReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Receipt
    )
    Assert-TicketboxCompletedLifecycleReceipt $Receipt
    Remove-TicketboxLifecycleReceipt $Path
}

function Remove-TicketboxLifecycleReceipt([string]$Path) {
    $canonicalPath = Assert-TicketboxLifecycleReceiptPath $Path
    Assert-TicketboxProtectedLifecycleReceipt $canonicalPath
    Remove-Item -LiteralPath $canonicalPath -Force
    if (Test-Path -LiteralPath $canonicalPath) {
        throw "无法清理安装生命周期回执：$canonicalPath"
    }
}

function Read-TicketboxInstallerRecoveryMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [string]$ExpectedReason = ""
    )
    $canonicalPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $canonicalPath
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $parent `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $canonicalPath `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount `
        -MaximumBytes 16384
    try {
        $marker = ConvertFrom-Json -InputObject $artifact.Text
    }
    catch {
        throw "安装恢复标记无法读取为有效 JSON。"
    }
    $createdAt = [DateTimeOffset]::MinValue
    if (
        [string]$marker.schema -cne "ticketbox-installer-recovery-required-v1" -or
        [string]::IsNullOrWhiteSpace([string]$marker.reason) -or
        ($ExpectedReason.Length -gt 0 -and [string]$marker.reason -cne $ExpectedReason) -or
        $marker.files_may_have_been_replaced -isnot [bool] -or
        -not [bool]$marker.files_may_have_been_replaced -or
        [string]$marker.recovery_action -cne "rerun_installer_repair" -or
        -not (Test-TicketboxPathEquals ([string]$marker.install_dir) $InstallDir) -or
        -not (Test-TicketboxPathEquals ([string]$marker.data_root) $DataRoot) -or
        -not [DateTimeOffset]::TryParse(
            [string]$marker.created_at_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$createdAt
        )
    ) {
        throw "安装恢复标记内容或安装绑定校验失败。"
    }
    return $marker
}

function Remove-TicketboxInstallerRecoveryMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot
    )
    $entryKind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($entryKind -ceq "Missing") { return }
    if ($entryKind -cne "File") {
        throw "安装恢复标记不是普通文件：$Path"
    }
    Read-TicketboxInstallerRecoveryMarker -Path $Path -InstallDir $InstallDir -DataRoot $DataRoot | Out-Null
    Remove-Item -LiteralPath $Path -Force
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "Missing") {
        throw "无法清理安装恢复标记：$Path"
    }
}

function Write-TicketboxInstallerRecoveryMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$Reason
    )
    $canonicalPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $canonicalPath
    Assert-TicketboxDataRootMarker -DataRoot $DataRoot -InstallDir $InstallDir
    Initialize-TicketboxInstallerStateDirectory `
        -Path $parent `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount | Out-Null
    $entryKind = Get-TicketboxPathEntryKindNoFollow $canonicalPath
    if ($entryKind -ceq "File") {
        Read-TicketboxInstallerRecoveryMarker -Path $canonicalPath -InstallDir $InstallDir -DataRoot $DataRoot | Out-Null
        return
    }
    if ($entryKind -cne "Missing") {
        throw "安装恢复标记不是普通文件：$canonicalPath"
    }
    $payload = [ordered]@{
        schema = "ticketbox-installer-recovery-required-v1"
        reason = $Reason
        files_may_have_been_replaced = $true
        recovery_action = "rerun_installer_repair"
        install_dir = ConvertTo-TicketboxCanonicalPath $InstallDir
        data_root = ConvertTo-TicketboxCanonicalPath $DataRoot
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json
    Assert-NoTicketboxAncestorReparsePoints $parent
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $canonicalPath `
        -Text $payload `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    Read-TicketboxInstallerRecoveryMarker -Path $canonicalPath -InstallDir $InstallDir -DataRoot $DataRoot -ExpectedReason $Reason | Out-Null
}

function Ensure-TicketboxInstallerRecoveryMarkerAfterFailure {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerStatePath,
        [Parameter(Mandatory = $true)][string]$LegacyPath,
        [Parameter(Mandatory = $true)][string]$CurrentPath,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    Initialize-TicketboxInstallerStateDirectory $InstallerStatePath | Out-Null
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $LegacyPath `
        -CurrentPath $CurrentPath
    if (Test-Path -LiteralPath $CurrentPath) {
        Read-TicketboxInstallerRecoveryMarker `
            -Path $CurrentPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot | Out-Null
        return
    }
    Write-TicketboxInstallerRecoveryMarker `
        -Path $CurrentPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -Reason $Reason
}

function Read-TicketboxDeleteDataIntent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string]$DataRoot = ""
    )

    $canonicalPath = [System.IO.Path]::GetFullPath($Path)
    Assert-TicketboxProtectedDirectoryAcl `
        -Path (Split-Path -Parent $canonicalPath) `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $canonicalPath `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount `
        -MaximumBytes 16384
    try { $intent = ConvertFrom-Json -InputObject $artifact.Text }
    catch { throw "删除数据意图无法读取为有效 JSON。" }
    $createdAt = [DateTimeOffset]::MinValue
    $intentDataRoot = [string]$intent.data_root
    if (
        @($intent.PSObject.Properties).Count -ne 5 -or
        [string]$intent.schema -cne $script:TicketboxDeleteDataIntentSchema -or
        -not (Test-TicketboxPathEquals ([string]$intent.install_dir) $InstallDir) -or
        [string]::IsNullOrWhiteSpace($intentDataRoot) -or
        -not [System.IO.Path]::IsPathRooted($intentDataRoot) -or
        (
            -not [string]::IsNullOrWhiteSpace($DataRoot) -and
            -not (Test-TicketboxPathEquals $intentDataRoot $DataRoot)
        ) -or
        [string]$intent.completed_receipt_sha256 -cnotmatch '^[0-9A-F]{64}$' -or
        -not [DateTimeOffset]::TryParse(
            [string]$intent.created_at_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$createdAt
        )
    ) {
        throw "删除数据意图内容或安装绑定校验失败。"
    }
    return $intent
}

function Write-TicketboxDeleteDataIntent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$CompletedReceiptPath,
        [Parameter(Mandatory = $true)][object]$CompletedReceipt,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot
    )

    Assert-TicketboxCompletedLifecycleReceipt $CompletedReceipt
    Assert-TicketboxProtectedLifecycleReceipt $CompletedReceiptPath
    $receiptSha256 = Get-TicketboxPortableFileSha256 $CompletedReceiptPath
    $parent = Split-Path -Parent ([System.IO.Path]::GetFullPath($Path))
    Initialize-TicketboxInstallerStateDirectory `
        -Path $parent `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount | Out-Null
    if (Test-Path -LiteralPath $Path) {
        $existing = Read-TicketboxDeleteDataIntent `
            -Path $Path `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot
        if ([string]$existing.completed_receipt_sha256 -cne $receiptSha256) {
            throw "既有删除数据意图绑定了另一份 lifecycle receipt。"
        }
        return $existing
    }
    $payload = [ordered]@{
        schema = $script:TicketboxDeleteDataIntentSchema
        install_dir = ConvertTo-TicketboxCanonicalPath $InstallDir
        data_root = ConvertTo-TicketboxCanonicalPath $DataRoot
        completed_receipt_sha256 = $receiptSha256
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text $payload `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    return Read-TicketboxDeleteDataIntent `
        -Path $Path `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot
}

function Close-TicketboxLifecycleBackupGuard([object]$Receipt) {
    $guardProperty = $Receipt.PSObject.Properties["backup_guard_stream"]
    if ($null -ne $guardProperty -and $null -ne $guardProperty.Value) {
        $guardProperty.Value.Dispose()
        $Receipt.backup_guard_stream = $null
    }
}
