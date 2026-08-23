#Requires -Version 5.1

$script:TicketboxInstallationOwnerContract =
    "ticketbox-installation-owner-pairing-v1"
$script:TicketboxOwnerHandoffMaximumBytes = 16384
$script:TicketboxOwnerHandoffAclAccounts = @(
    "SYSTEM",
    "BUILTIN\Administrators"
)

function Get-TicketboxOwnerHandoffLifecycleIdentity {
    param(
        [ValidateRange(1, 2147483647)]
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId
    )

    if (-not (Get-Command Get-TicketboxValidatedExternalLifecycleOwnerIdentity -ErrorAction SilentlyContinue)) {
        throw "owner handoff 缺少已验证的安装器生命周期身份 provider。"
    }
    $identity = Get-TicketboxValidatedExternalLifecycleOwnerIdentity `
        $InstallerOwnerProcessId
    return [pscustomobject]@{
        ProcessId = [int]$identity.ProcessId
        StartedUtc = [string]$identity.StartedUtc
    }
}

function Read-TicketboxOwnerHandoffArtifact {
    param([Parameter(Mandatory = $true)][string]$Path)

    Assert-TicketboxProtectedDirectoryAcl (Split-Path -Parent $Path)
    return Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $script:TicketboxOwnerHandoffAclAccounts `
        -OwnerAccount "SYSTEM" `
        -MaximumBytes $script:TicketboxOwnerHandoffMaximumBytes
}

function Write-TicketboxOwnerHandoffRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 2147483647)]
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 2147483647)]
        [int]$ClaimGeneration,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 63)]
        [int]$PairingDerivationIndex,
        [Parameter(Mandatory = $true)][string]$PairingCode,
        [Parameter(Mandatory = $true)][string]$PairingExpiresAt,
        [Parameter(Mandatory = $true)][bool]$ReplaceExisting
    )

    [DateTimeOffset]$parsedPairingExpiresAt = [DateTimeOffset]::MinValue
    if (
        $OperationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        $InstallationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        $PairingCode -cnotmatch '^[0-9]{8}$' -or
        -not [DateTimeOffset]::TryParse(
            $PairingExpiresAt,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$parsedPairingExpiresAt
        )
    ) {
        throw "installation owner handoff 身份参数无效。"
    }
    Assert-TicketboxProtectedDirectoryAcl (Split-Path -Parent $Path)
    $ownerIdentity = Get-TicketboxOwnerHandoffLifecycleIdentity `
        -InstallerOwnerProcessId $InstallerOwnerProcessId
    $text = [string]::Join([Environment]::NewLine, @(
        "SCHEMA=ticketbox-installation-owner-handoff-v2",
        "STATE=pending",
        "CONTRACT=$script:TicketboxInstallationOwnerContract",
        "OPERATION_ID=$OperationId",
        "INSTALLATION_ID=$InstallationId",
        "CLAIM_GENERATION=$ClaimGeneration",
        "PAIRING_DERIVATION_INDEX=$PairingDerivationIndex",
        "PAIRING_CODE=$PairingCode",
        "PAIRING_EXPIRES_AT=$PairingExpiresAt",
        "INSTALLER_OWNER_PID=$($ownerIdentity.ProcessId)",
        "INSTALLER_OWNER_STARTED_UTC=$($ownerIdentity.StartedUtc)"
    )) + [Environment]::NewLine
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text $text `
        -FullControlAccounts $script:TicketboxOwnerHandoffAclAccounts `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting:$ReplaceExisting
    $persisted = Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -MaximumBytes $script:TicketboxOwnerHandoffMaximumBytes
    if ($persisted.Text -cne $text) {
        throw "owner 短期配对交付记录持久化校验失败。"
    }
}

function Inspect-TicketboxRetiredOwnerHandoffArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$LegacyOwnerBootstrapPath,
        [Parameter(Mandatory = $true)][string]$LegacyOwnerHandoffPendingPath,
        [Parameter(Mandatory = $true)][string]$RetiredOwnerBootstrapPath,
        [Parameter(Mandatory = $true)][string]$RetiredOwnerHandoffPendingPath
    )

    $observed = @()
    foreach ($path in @(
        $LegacyOwnerBootstrapPath,
        $LegacyOwnerHandoffPendingPath,
        $RetiredOwnerBootstrapPath,
        $RetiredOwnerHandoffPendingPath
    )) {
        $kind = "Unclassifiable"
        try { $kind = Get-TicketboxPathEntryKindNoFollow $path }
        catch {
            # Retired protocols are audit evidence only. Never open, migrate,
            # delete, repair, or use them as current authority.
        }
        if ($kind -cne "Missing") { $observed += "${path} [$kind]" }
    }
    if ($observed.Count -gt 0) {
        Write-Warning (
            "发现旧 owner handoff 协议文件；它们仅作为受保护审计对象保留，" +
            "不会读取内容、迁移、删除、展示、阻断安装或成为当前 pairing handoff 权威：" +
            ($observed -join ";")
        )
    }
}

function Read-TicketboxOwnerHandoffRecord {
    param([Parameter(Mandatory = $true)][string]$Path)

    $artifact = Read-TicketboxOwnerHandoffArtifact -Path $Path
    $newLine = [Environment]::NewLine
    if (-not $artifact.Text.EndsWith($newLine, [System.StringComparison]::Ordinal)) {
        throw "owner 绑定交付标记必须以平台换行结尾。"
    }
    $body = $artifact.Text.Substring(0, $artifact.Text.Length - $newLine.Length)
    $lines = @($body.Split(
        [string[]]@($newLine),
        [System.StringSplitOptions]::None
    ))
    if (
        $lines.Count -ne 11 -or
        $lines[0] -cne "SCHEMA=ticketbox-installation-owner-handoff-v2" -or
        $lines[1] -cne "STATE=pending" -or
        $lines[2] -cne "CONTRACT=$script:TicketboxInstallationOwnerContract" -or
        -not $lines[3].StartsWith("OPERATION_ID=", [System.StringComparison]::Ordinal) -or
        -not $lines[4].StartsWith("INSTALLATION_ID=", [System.StringComparison]::Ordinal) -or
        -not $lines[5].StartsWith("CLAIM_GENERATION=", [System.StringComparison]::Ordinal) -or
        -not $lines[6].StartsWith("PAIRING_DERIVATION_INDEX=", [System.StringComparison]::Ordinal) -or
        -not $lines[7].StartsWith("PAIRING_CODE=", [System.StringComparison]::Ordinal) -or
        -not $lines[8].StartsWith("PAIRING_EXPIRES_AT=", [System.StringComparison]::Ordinal) -or
        -not $lines[9].StartsWith("INSTALLER_OWNER_PID=", [System.StringComparison]::Ordinal) -or
        -not $lines[10].StartsWith("INSTALLER_OWNER_STARTED_UTC=", [System.StringComparison]::Ordinal)
    ) {
        throw "owner 绑定交付标记格式无效。"
    }
    $operationId = $lines[3].Substring("OPERATION_ID=".Length)
    $installationId = $lines[4].Substring("INSTALLATION_ID=".Length)
    $claimGeneration = 0
    $pairingDerivationIndex = -1
    [DateTimeOffset]$pairingExpiresAt = [DateTimeOffset]::MinValue
    if (
        $operationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        $installationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        -not [int]::TryParse(
            $lines[5].Substring("CLAIM_GENERATION=".Length),
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$claimGeneration
        ) -or
        $claimGeneration -lt 1 -or
        -not [int]::TryParse(
            $lines[6].Substring("PAIRING_DERIVATION_INDEX=".Length),
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$pairingDerivationIndex
        ) -or
        $pairingDerivationIndex -lt 0 -or
        $pairingDerivationIndex -gt 63 -or
        $lines[7].Substring("PAIRING_CODE=".Length) -cnotmatch '^[0-9]{8}$' -or
        -not [DateTimeOffset]::TryParse(
            $lines[8].Substring("PAIRING_EXPIRES_AT=".Length),
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$pairingExpiresAt
        )
    ) {
        throw "owner 绑定交付标记事务身份无效。"
    }
    $ownerProcessId = 0
    $ownerProcessText = $lines[9].Substring("INSTALLER_OWNER_PID=".Length)
    if (
        $ownerProcessText -cnotmatch '^[1-9][0-9]*$' -or
        -not [int]::TryParse(
            $ownerProcessText,
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$ownerProcessId
        ) -or
        $ownerProcessId -le 0
    ) {
        throw "owner 绑定交付标记 owner PID 无效。"
    }
    $timestampFormat = "yyyy-MM-ddTHH:mm:ss.fffffffZ"
    $timestampStyles =
        [System.Globalization.DateTimeStyles]::AssumeUniversal -bor
        [System.Globalization.DateTimeStyles]::AdjustToUniversal
    [DateTimeOffset]$ownerStartedAt = [DateTimeOffset]::MinValue
    $ownerStartedText = $lines[10].Substring("INSTALLER_OWNER_STARTED_UTC=".Length)
    if (
        -not [DateTimeOffset]::TryParseExact(
            $ownerStartedText,
            $timestampFormat,
            [System.Globalization.CultureInfo]::InvariantCulture,
            $timestampStyles,
            [ref]$ownerStartedAt
        ) -or
        $ownerStartedAt.ToUniversalTime().ToString(
            $timestampFormat,
            [System.Globalization.CultureInfo]::InvariantCulture
        ) -cne $ownerStartedText
    ) {
        throw "owner 绑定交付标记 owner 启动时间无效。"
    }
    return [pscustomobject]@{
        State = "pending"
        OperationId = $operationId
        InstallationId = $installationId
        ClaimGeneration = $claimGeneration
        PairingDerivationIndex = $pairingDerivationIndex
        PairingCode = $lines[7].Substring("PAIRING_CODE=".Length)
        PairingExpiresAt = $lines[8].Substring("PAIRING_EXPIRES_AT=".Length)
        OwnerProcessId = $ownerProcessId
        OwnerStartedUtc = $ownerStartedText
    }
}

function Assert-TicketboxOwnerHandoffIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Record,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )

    if (
        [string]$Record.OperationId -cne $ExpectedOperationId -or
        [string]$Record.InstallationId -cne $ExpectedInstallationId
    ) {
        throw "owner 绑定交付标记不属于当前 installation operation。"
    }
}

function Test-TicketboxOwnerHandoffObservedProcessIsAlive {
    param(
        [Parameter(Mandatory = $true)][object]$Record,
        [Parameter(Mandatory = $true)][bool]$ProcessFound,
        [Parameter(Mandatory = $true)][bool]$ExitedBeforeIdentityRead,
        [Parameter(Mandatory = $true)][string]$ObservedStartedUtc,
        [Parameter(Mandatory = $true)][bool]$ExitedAfterIdentityRead
    )

    return (
        $ProcessFound -and
        -not $ExitedBeforeIdentityRead -and
        $ObservedStartedUtc -ceq [string]$Record.OwnerStartedUtc -and
        -not $ExitedAfterIdentityRead
    )
}

function Test-TicketboxOwnerHandoffProcessIsAlive {
    param([Parameter(Mandatory = $true)][object]$Record)

    try { $process = Get-Process -Id $Record.OwnerProcessId -ErrorAction SilentlyContinue }
    catch { return $false }
    if ($null -eq $process) { return $false }
    try {
        $process.Refresh()
        $exitedBefore = [bool]$process.HasExited
        $startedUtc = $process.StartTime.ToUniversalTime().ToString(
            "yyyy-MM-ddTHH:mm:ss.fffffffZ",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        $process.Refresh()
        return Test-TicketboxOwnerHandoffObservedProcessIsAlive `
            -Record $Record `
            -ProcessFound $true `
            -ExitedBeforeIdentityRead $exitedBefore `
            -ObservedStartedUtc $startedUtc `
            -ExitedAfterIdentityRead ([bool]$process.HasExited)
    }
    catch {
        # The current installer holds the exclusive lifecycle lock. An
        # unverifiable reused PID cannot retain authority from an older record.
        return $false
    }
}

function Read-TicketboxOwnerHandoffState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 2147483647)]
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )

    $record = Read-TicketboxOwnerHandoffRecord -Path $Path
    Assert-TicketboxOwnerHandoffIdentity `
        -Record $record `
        -ExpectedOperationId $ExpectedOperationId `
        -ExpectedInstallationId $ExpectedInstallationId
    $currentOwner = Get-TicketboxOwnerHandoffLifecycleIdentity `
        -InstallerOwnerProcessId $InstallerOwnerProcessId
    if (
        $record.OwnerProcessId -ne $currentOwner.ProcessId -or
        $record.OwnerStartedUtc -cne $currentOwner.StartedUtc
    ) {
        throw "owner 绑定交付标记不属于当前安装器生命周期。"
    }
    return $record.State
}

function Adopt-TicketboxOwnerBootstrapHandoff {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 2147483647)]
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )

    $handoffKind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($handoffKind -ceq "Missing") { return "absent" }
    if ($handoffKind -cne "File") {
        throw "owner 绑定交付标记不是可信普通文件。"
    }
    $record = Read-TicketboxOwnerHandoffRecord -Path $Path
    Assert-TicketboxOwnerHandoffIdentity `
        -Record $record `
        -ExpectedOperationId $ExpectedOperationId `
        -ExpectedInstallationId $ExpectedInstallationId
    $currentOwner = Get-TicketboxOwnerHandoffLifecycleIdentity `
        -InstallerOwnerProcessId $InstallerOwnerProcessId
    if (
        $record.OwnerProcessId -eq $currentOwner.ProcessId -and
        $record.OwnerStartedUtc -ceq $currentOwner.StartedUtc
    ) {
        return "pending"
    }
    if (Test-TicketboxOwnerHandoffProcessIsAlive -Record $record) {
        throw "上一个安装器仍持有 owner 绑定交付，拒绝接管。"
    }
    Write-TicketboxOwnerHandoffRecord `
        -Path $Path `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -OperationId $record.OperationId `
        -InstallationId $record.InstallationId `
        -ClaimGeneration $record.ClaimGeneration `
        -PairingDerivationIndex $record.PairingDerivationIndex `
        -PairingCode $record.PairingCode `
        -PairingExpiresAt $record.PairingExpiresAt `
        -ReplaceExisting $true
    return "pending"
}

function Complete-TicketboxOwnerBootstrapHandoff {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 2147483647)]
        [Parameter(Mandatory = $true)][int]$InstallerOwnerProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )

    $handoffKind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($handoffKind -ceq "Missing") { return "already_absent" }
    if ($handoffKind -cne "File") {
        throw "owner 绑定交付标记不是可信普通文件。"
    }
    if ((Read-TicketboxOwnerHandoffState `
        -Path $Path `
        -InstallerOwnerProcessId $InstallerOwnerProcessId `
        -ExpectedOperationId $ExpectedOperationId `
        -ExpectedInstallationId $ExpectedInstallationId) -cne "pending") {
        throw "owner 短期配对交付记录不允许清理。"
    }
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $script:TicketboxOwnerHandoffAclAccounts `
        -OwnerAccount "SYSTEM"
    return "removed"
}
