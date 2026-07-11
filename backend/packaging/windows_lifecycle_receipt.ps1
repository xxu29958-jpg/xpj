#Requires -Version 5.1

$script:TicketboxLifecycleReceiptSchema = "ticketbox-windows-lifecycle-receipt-v6"
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
        [switch]$ReplaceProtectedReceipt
    )

    if ($InstallerOwnerProcessId -le 0) {
        throw "Inno 生命周期回执必须绑定有效的安装器进程。"
    }
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
    }
    $payload = [ordered]@{
        schema = $script:TicketboxLifecycleReceiptSchema
        mode = $Mode
        install_dir = ConvertTo-TicketboxCanonicalPath $InstallDir
        data_root = ConvertTo-TicketboxCanonicalPath $DataRoot
        pg_port = $PgPort
        backend_port = $BackendPort
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
    $receiptAclAccounts = $script:TicketboxLifecycleReceiptAclAccounts
    $receiptOwnerAccount = $script:TicketboxLifecycleReceiptOwnerAccount
    $protectTemporary = {
        param($TemporaryPath)
        Set-TicketboxExactFileAcl `
            -Path $TemporaryPath `
            -Accounts $receiptAclAccounts `
            -OwnerAccount $receiptOwnerAccount
    }.GetNewClosure()
    Write-TicketboxUtf8FileDurable `
        -Path $canonicalPath `
        -Text $payload `
        -ProtectTemporaryFile $protectTemporary `
        -ReplaceExisting:$ReplaceProtectedReceipt
    Set-TicketboxExactFileAcl `
        -Path $canonicalPath `
        -Accounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
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
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [switch]$AllowPreviousInstallerOwnerProcessId
    )

    $canonicalPath = Assert-TicketboxLifecycleReceiptPath $Path
    Assert-TicketboxProtectedLifecycleReceipt $canonicalPath
    try {
        $receipt = Get-Content -LiteralPath $canonicalPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "安装生命周期回执不是有效 JSON。"
    }
    if ($receipt.schema -ne $script:TicketboxLifecycleReceiptSchema) {
        throw "安装生命周期回执 schema 不受支持。"
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

function Assert-TicketboxLifecycleReceiptStage([object]$Receipt, [string]$ExpectedStage) {
    if ([string]$Receipt.preparation_stage -ne $ExpectedStage) {
        throw "安装生命周期回执不能从 $($Receipt.preparation_stage) 跃迁；预期阶段为 $ExpectedStage。"
    }
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
        "files_may_have_been_replaced"
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
    if (
        -not [int]::TryParse([string]$envelope.pg_port, [ref]$pgPort) -or
        -not [int]::TryParse([string]$envelope.backend_port, [ref]$backendPort) -or
        $pgPort -lt 1 -or $pgPort -gt 65535 -or
        $backendPort -lt 1 -or $backendPort -gt 65535
    ) {
        throw "安装生命周期回执端口无效。"
    }
    $receipt = Read-TicketboxLifecycleReceipt `
        -Path $canonicalPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -PgPort $pgPort `
        -BackendPort $backendPort `
        -TargetReleaseConfig $TargetReleaseConfig `
        -InstallerOwnerProcessId $PID `
        -AllowPreviousInstallerOwnerProcessId
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

function Write-TicketboxInstallerRecoveryMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$Reason
    )
    $canonicalPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $canonicalPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
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
    $markerAclAccounts = $script:TicketboxLifecycleReceiptAclAccounts
    $markerOwnerAccount = $script:TicketboxLifecycleReceiptOwnerAccount
    $protectTemporary = {
        param($TemporaryPath)
        Set-TicketboxExactFileAcl `
            -Path $TemporaryPath `
            -Accounts $markerAclAccounts `
            -OwnerAccount $markerOwnerAccount
    }.GetNewClosure()
    Write-TicketboxUtf8FileDurable `
        -Path $canonicalPath `
        -Text $payload `
        -ProtectTemporaryFile $protectTemporary `
        -ReplaceExisting:(Test-Path -LiteralPath $canonicalPath)
    Set-TicketboxExactFileAcl `
        -Path $canonicalPath `
        -Accounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    Assert-TicketboxExactFileAcl `
        -Path $canonicalPath `
        -Accounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    try {
        $published = Get-Content -LiteralPath $canonicalPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "安装恢复标记发布后无法复读为有效 JSON。"
    }
    if (
        [string]$published.schema -cne "ticketbox-installer-recovery-required-v1" -or
        [string]$published.reason -cne $Reason -or
        $published.files_may_have_been_replaced -isnot [bool] -or
        -not [bool]$published.files_may_have_been_replaced -or
        [string]$published.recovery_action -cne "rerun_installer_repair" -or
        -not (Test-TicketboxPathEquals ([string]$published.install_dir) $InstallDir) -or
        -not (Test-TicketboxPathEquals ([string]$published.data_root) $DataRoot)
    ) {
        throw "安装恢复标记发布后内容校验失败。"
    }
}

function Close-TicketboxLifecycleBackupGuard([object]$Receipt) {
    $guardProperty = $Receipt.PSObject.Properties["backup_guard_stream"]
    if ($null -ne $guardProperty -and $null -ne $guardProperty.Value) {
        $guardProperty.Value.Dispose()
        $Receipt.backup_guard_stream = $null
    }
}
