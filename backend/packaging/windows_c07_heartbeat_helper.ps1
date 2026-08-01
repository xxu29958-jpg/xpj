#Requires -Version 5.1

<#
.SYNOPSIS
  Minimal, credential-free subprocess carrier for the C07 durable heartbeat.
.DESCRIPTION
  This file is executable only with -TicketboxC07HeartbeatHelper. It accepts a
  single bounded JSON descriptor over stdin, loads only the protected host/path,
  process-identity, and C07 durable-lifecycle authorities, advances the existing
  durable heartbeat, and emits one JSON result line. It never accepts or loads
  database credentials, PostgreSQL connection state, recovery-generation code,
  service control, or bundled-database helpers.
#>

param(
    [switch]$TicketboxC07HeartbeatHelper
)

$script:TicketboxC07HeartbeatHelperRequestSchema =
    "ticketbox-c07-heartbeat-helper-request-v1"
$script:TicketboxC07HeartbeatHelperResultSchema =
    "ticketbox-c07-heartbeat-helper-result-v1"

class TicketboxC07HeartbeatChildException : System.Exception {
    TicketboxC07HeartbeatChildException(
        [string]$failureCode,
        [string]$message
    ) : base($message) {
        $this.Data["TicketboxC07FailureCode"] = $failureCode
    }

    TicketboxC07HeartbeatChildException(
        [string]$failureCode,
        [string]$message,
        [Exception]$innerException
    ) : base($message, $innerException) {
        $this.Data["TicketboxC07FailureCode"] = $failureCode
    }
}

function Assert-TicketboxC07HeartbeatHelperBootstrapFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    $current = $fullPath
    while (-not [string]::IsNullOrEmpty($current)) {
        if (-not (Test-Path -LiteralPath $current)) {
            throw "C07 heartbeat helper bootstrap path 缺失：$current"
        }
        $attributes = [IO.File]::GetAttributes($current)
        if (
            ($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "C07 heartbeat helper bootstrap path 含 reparse point：$current"
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrEmpty($parent) -or $parent -ceq $current) {
            break
        }
        $current = $parent
    }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "C07 heartbeat helper bootstrap 不是普通文件：$fullPath"
    }
    return $fullPath
}

function Get-TicketboxC07HeartbeatHelperDependencyPaths {
    foreach ($leaf in @(
        "windows_installation_safety.ps1",
        "windows_lifecycle_lock.ps1",
        "windows_c07_lifecycle.ps1"
    )) {
        $path = Assert-TicketboxC07HeartbeatHelperBootstrapFile (
            Join-Path $PSScriptRoot $leaf
        )
        $path
    }
}

function Read-TicketboxC07HeartbeatHelperRequest {
    $inputText = [Console]::In.ReadToEnd()
    if (
        [string]::IsNullOrEmpty($inputText) -or
        $inputText.Length -gt 65536
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "C07 heartbeat helper request 缺失或过大。"
        )
    }
    $payloadText = $inputText -replace "(?:`r`n|`n|`r)$", ""
    if (
        [string]::IsNullOrWhiteSpace($payloadText) -or
        $payloadText.IndexOfAny([char[]]@("`r", "`n")) -ge 0
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "C07 heartbeat helper 只接受一条 JSON descriptor。"
        )
    }
    try {
        return ConvertFrom-TicketboxC07JsonText `
            -Text $payloadText `
            -Label "heartbeat helper request"
    }
    finally {
        $payloadText = $null
        $inputText = $null
    }
}

function Assert-TicketboxC07HeartbeatHelperAccounts {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -is [string]) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "$Label 必须是非空账户数组。"
        )
    }
    $accounts = @([string[]]$Value)
    if (
        $accounts.Count -eq 0 -or
        @($accounts | Where-Object {
            [string]::IsNullOrWhiteSpace([string]$_)
        }).Count -ne 0 -or
        @($accounts | Sort-Object -Unique).Count -ne $accounts.Count
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "$Label 账户集合不规范。"
        )
    }
    return [string[]]$accounts
}

function Assert-TicketboxC07HeartbeatHelperRequest {
    param([Parameter(Mandatory = $true)][object]$Request)

    $expectedNames = @(
        "schema",
        "request_nonce",
        "operation_schema",
        "data_root",
        "operation_id",
        "descriptor_sha256",
        "coordinator_binding_sha256",
        "coordinator_binding_sequence",
        "maintenance_attempt_id",
        "maintenance_attempt_sha256",
        "maintenance_attempt_sequence",
        "coordinator_pid",
        "coordinator_started_filetime_high",
        "coordinator_started_filetime_low",
        "deadline_utc",
        "remaining_ceiling_ms",
        "host_full_control_accounts",
        "host_owner_account",
        "installation_identity_acl_accounts",
        "installation_identity_owner_account",
        "primary_lifecycle_lock_path",
        "operation_lifecycle_lock_path"
    )
    Assert-TicketboxC07ExactProperties `
        -Value $Request `
        -ExpectedNames $expectedNames `
        -ArtifactName "heartbeat helper request"
    if (
        [string]$Request.schema -cne
            $script:TicketboxC07HeartbeatHelperRequestSchema -or
        [string]$Request.operation_schema -cne
            "ticketbox-c07-durable-heartbeat-operation-v2" -or
        [string]$Request.request_nonce -cnotmatch "^[0-9a-f]{64}$"
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "C07 heartbeat helper request schema/nonce 无效。"
        )
    }
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Request.operation_id
    )
    Assert-TicketboxC07Sha256 `
        ([string]$Request.descriptor_sha256) `
        "heartbeat helper descriptor hash"
    Assert-TicketboxC07Sha256 `
        ([string]$Request.coordinator_binding_sha256) `
        "heartbeat helper coordinator binding hash"
    ConvertTo-TicketboxC07CanonicalOperationId `
        ([string]$Request.maintenance_attempt_id) | Out-Null
    Assert-TicketboxC07Sha256 `
        ([string]$Request.maintenance_attempt_sha256) `
        "heartbeat helper maintenance attempt hash"
    foreach ($field in @(
        "coordinator_binding_sequence",
        "maintenance_attempt_sequence",
        "coordinator_pid",
        "coordinator_started_filetime_high",
        "coordinator_started_filetime_low",
        "remaining_ceiling_ms"
    )) {
        if (
            $Request.$field -isnot [int] -and
            $Request.$field -isnot [long]
        ) {
            throw [TicketboxC07HeartbeatChildException]::new(
                "heartbeat_helper_request_invalid",
                "C07 heartbeat helper $field 必须是 JSON integer。"
            )
        }
    }
    if (
        [int64]$Request.coordinator_binding_sequence -lt 0 -or
        [int64]$Request.maintenance_attempt_sequence -lt 1 -or
        [int64]$Request.maintenance_attempt_sequence -gt 64 -or
        [int64]$Request.coordinator_pid -lt 1 -or
        [int64]$Request.coordinator_pid -gt [int]::MaxValue -or
        [int64]$Request.coordinator_started_filetime_high -lt 0 -or
        [int64]$Request.coordinator_started_filetime_high -gt
            [uint32]::MaxValue -or
        [int64]$Request.coordinator_started_filetime_low -lt 0 -or
        [int64]$Request.coordinator_started_filetime_low -gt
            [uint32]::MaxValue -or
        [int64]$Request.remaining_ceiling_ms -lt 1000 -or
        [int64]$Request.remaining_ceiling_ms -gt 1200000
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "C07 heartbeat helper identity/budget 数值越界。"
        )
    }
    $deadlineText = ConvertTo-TicketboxC07CanonicalUtcTimestamp `
        -Value ([string]$Request.deadline_utc) `
        -Label "C07 heartbeat helper maintenance deadline"
    $deadlineUtc = [DateTime]::ParseExact(
        $deadlineText,
        "o",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind
    ).ToUniversalTime()
    $wallRemaining = [int64][Math]::Floor(
        ($deadlineUtc - [DateTime]::UtcNow).TotalMilliseconds
    )
    $effectiveRemaining = [Math]::Min(
        [int64]$Request.remaining_ceiling_ms,
        $wallRemaining
    )
    if ($effectiveRemaining -lt 1000) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_deadline_exceeded",
            "C07 heartbeat helper maintenance deadline 已耗尽。"
        )
    }

    $dataRoot = ConvertTo-TicketboxCanonicalPath (
        [string]$Request.data_root
    )
    if (
        -not (Test-TicketboxPathEquals `
            $dataRoot `
            ([string]$Request.data_root)) -or
        (Get-TicketboxPathEntryKindNoFollow $dataRoot) -cne "Directory"
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "C07 heartbeat helper DataRoot 不是现有 canonical directory。"
        )
    }
    Assert-NoTicketboxAncestorReparsePoints $dataRoot

    $primaryLockPath = [IO.Path]::GetFullPath(
        [string]$Request.primary_lifecycle_lock_path
    )
    $operationLockPath = [IO.Path]::GetFullPath(
        [string]$Request.operation_lifecycle_lock_path
    )
    $expectedOperationLockPath = [IO.Path]::GetFullPath(
        (Join-Path `
            (Split-Path -Parent $primaryLockPath) `
            $script:TicketboxLifecycleOperationLockFileName)
    )
    if (
        -not (Test-TicketboxPathEquals `
            $primaryLockPath `
            ([string]$Request.primary_lifecycle_lock_path)) -or
        -not (Test-TicketboxPathEquals `
            $operationLockPath `
            ([string]$Request.operation_lifecycle_lock_path)) -or
        -not (Test-TicketboxPathEquals `
            $operationLockPath `
            $expectedOperationLockPath) -or
        (Split-Path -Leaf $primaryLockPath) -cne
            $script:TicketboxLifecycleLockFileName -or
        (Get-TicketboxPathEntryKindNoFollow $primaryLockPath) -cne "File" -or
        (Get-TicketboxPathEntryKindNoFollow $operationLockPath) -cne "File"
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "C07 heartbeat helper lifecycle lock paths 无效。"
        )
    }
    Assert-NoTicketboxAncestorReparsePoints $primaryLockPath
    Assert-NoTicketboxAncestorReparsePoints $operationLockPath

    $hostAccounts = Assert-TicketboxC07HeartbeatHelperAccounts `
        -Value $Request.host_full_control_accounts `
        -Label "C07 heartbeat helper host ACL"
    $identityAccounts = Assert-TicketboxC07HeartbeatHelperAccounts `
        -Value $Request.installation_identity_acl_accounts `
        -Label "C07 heartbeat helper installation identity ACL"
    if (
        [string]::IsNullOrWhiteSpace(
            [string]$Request.host_owner_account
        ) -or
        [string]::IsNullOrWhiteSpace(
            [string]$Request.installation_identity_owner_account
        )
    ) {
        throw [TicketboxC07HeartbeatChildException]::new(
            "heartbeat_helper_request_invalid",
            "C07 heartbeat helper owner accounts 缺失。"
        )
    }
    return [pscustomobject]@{
        OperationId = $operationId
        DataRoot = $dataRoot
        DescriptorSha256 = [string]$Request.descriptor_sha256
        CoordinatorBindingSha256 =
            [string]$Request.coordinator_binding_sha256
        CoordinatorBindingSequence =
            [int64]$Request.coordinator_binding_sequence
        MaintenanceAttemptId =
            [string]$Request.maintenance_attempt_id
        MaintenanceAttemptSha256 =
            [string]$Request.maintenance_attempt_sha256
        MaintenanceAttemptSequence =
            [int64]$Request.maintenance_attempt_sequence
        CoordinatorIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
            -ProcessId ([int]$Request.coordinator_pid) `
            -StartedFileTimeHigh (
                [uint32]$Request.coordinator_started_filetime_high
            ) `
            -StartedFileTimeLow (
                [uint32]$Request.coordinator_started_filetime_low
            )
        DeadlineUtc = $deadlineUtc
        EffectiveRemainingMilliseconds = $effectiveRemaining
        HostFullControlAccounts = $hostAccounts
        HostOwnerAccount = [string]$Request.host_owner_account
        InstallationIdentityAclAccounts = $identityAccounts
        InstallationIdentityOwnerAccount =
            [string]$Request.installation_identity_owner_account
        PrimaryLifecycleLockPath = $primaryLockPath
        OperationLifecycleLockPath = $operationLockPath
    }
}

function Invoke-TicketboxC07HeartbeatHelperRequest {
    param([Parameter(Mandatory = $true)][object]$Request)

    $validated = Assert-TicketboxC07HeartbeatHelperRequest $Request
    $script:TicketboxC07HostFullControlAccounts =
        [string[]]$validated.HostFullControlAccounts
    $script:TicketboxC07HostOwnerAccount =
        [string]$validated.HostOwnerAccount
    $script:TicketboxPersistentInstallationIdentityAclAccounts =
        [string[]]$validated.InstallationIdentityAclAccounts
    $script:TicketboxPersistentInstallationIdentityOwnerAccount =
        [string]$validated.InstallationIdentityOwnerAccount
    $script:TicketboxC07HeartbeatHelperLease = $validated
    function Get-TicketboxLifecycleLockPath {
        return [string](
            $script:TicketboxC07HeartbeatHelperLease.PrimaryLifecycleLockPath
        )
    }
    function Get-TicketboxLifecycleOperationLockPath {
        return [string](
            $script:TicketboxC07HeartbeatHelperLease.OperationLifecycleLockPath
        )
    }

    $envelope = Write-TicketboxC07DurableHeartbeat `
        -DataRoot ([string]$validated.DataRoot) `
        -CoordinatorIdentity $validated.CoordinatorIdentity `
        -ExpectedOperationId ([string]$validated.OperationId) `
        -ExpectedDescriptorSha256 (
            [string]$validated.DescriptorSha256
        ) `
        -ExpectedCoordinatorBindingSha256 (
            [string]$validated.CoordinatorBindingSha256
        ) `
        -ExpectedCoordinatorBindingSequence (
            [int64]$validated.CoordinatorBindingSequence
        ) `
        -ExpectedMaintenanceAttemptId (
            [string]$validated.MaintenanceAttemptId
        ) `
        -ExpectedMaintenanceAttemptSha256 (
            [string]$validated.MaintenanceAttemptSha256
        ) `
        -ExpectedMaintenanceAttemptSequence (
            [int64]$validated.MaintenanceAttemptSequence
        ) `
        -ExpectedDeadlineUtc ([DateTime]$validated.DeadlineUtc) `
        -MaintenanceRemainingCeilingMilliseconds (
            [int64]$validated.EffectiveRemainingMilliseconds
        )
    return [pscustomobject]@{
        OperationId = [string]$validated.OperationId
        Sequence = [int64]$envelope.Payload.sequence
    }
}

function Invoke-TicketboxC07HeartbeatHelperMain {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"
    $VerbosePreference = "SilentlyContinue"
    $DebugPreference = "SilentlyContinue"
    $InformationPreference = "SilentlyContinue"
    $WarningPreference = "SilentlyContinue"
    [Console]::InputEncoding = [Text.UTF8Encoding]::new($false, $true)
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false, $true)
    $requestNonce = ""
    $operationId = ""
    $result = $null
    $exitCode = 41
    try {
        $request = Read-TicketboxC07HeartbeatHelperRequest
        $requestNonce = [string]$request.request_nonce
        $operationId = [string]$request.operation_id
        $heartbeat = Invoke-TicketboxC07HeartbeatHelperRequest $request
        $operationId = [string]$heartbeat.OperationId
        $result = [ordered]@{
            schema = $script:TicketboxC07HeartbeatHelperResultSchema
            request_nonce = $requestNonce
            status = "ok"
            failure_code = ""
            operation_id = $operationId
            heartbeat_sequence = [int64]$heartbeat.Sequence
        }
        $exitCode = 0
    }
    catch {
        $failureCode = [string](
            $_.Exception.Data["TicketboxC07FailureCode"]
        )
        if ($failureCode -cnotmatch "^heartbeat_helper_[a-z0-9_]+$") {
            $failureCode = "heartbeat_helper_authority_rejected"
        }
        $result = [ordered]@{
            schema = $script:TicketboxC07HeartbeatHelperResultSchema
            request_nonce = $requestNonce
            status = "failed"
            failure_code = $failureCode
            operation_id = $operationId
            heartbeat_sequence = [int64]-1
        }
    }
    $json = [string]($result | ConvertTo-Json -Depth 4 -Compress)
    [Console]::Out.WriteLine($json)
    [Console]::Out.Flush()
    exit $exitCode
}

if (-not $TicketboxC07HeartbeatHelper) {
    throw (
        "C07 durable heartbeat helper 必须通过 " +
        "-TicketboxC07HeartbeatHelper 显式执行。"
    )
}

if ($TicketboxC07HeartbeatHelper) {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"
    $VerbosePreference = "SilentlyContinue"
    $DebugPreference = "SilentlyContinue"
    $InformationPreference = "SilentlyContinue"
    $WarningPreference = "SilentlyContinue"
    [Console]::InputEncoding = [Text.UTF8Encoding]::new($false, $true)
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false, $true)
    try {
        foreach (
            $heartbeatDependencyPath in
                (Get-TicketboxC07HeartbeatHelperDependencyPaths)
        ) {
            if (
                (Split-Path -Leaf $heartbeatDependencyPath) -ceq
                    "windows_c07_lifecycle.ps1"
            ) {
                . $heartbeatDependencyPath `
                    -TicketboxC07DependencyProfile "durable_heartbeat" |
                    Out-Null
            }
            else {
                . $heartbeatDependencyPath | Out-Null
            }
            Assert-NoTicketboxAncestorReparsePoints $heartbeatDependencyPath
            if (
                (Get-TicketboxPathEntryKindNoFollow `
                    $heartbeatDependencyPath) -cne "File"
            ) {
                throw (
                    "C07 heartbeat helper 依赖不是可信普通文件：" +
                    $heartbeatDependencyPath
                )
            }
        }
    }
    catch {
        $bootstrapResult = [ordered]@{
            schema = $script:TicketboxC07HeartbeatHelperResultSchema
            request_nonce = ""
            status = "failed"
            failure_code = "heartbeat_helper_bootstrap_invalid"
            operation_id = ""
            heartbeat_sequence = [int64]-1
        }
        [Console]::Out.WriteLine(
            [string]($bootstrapResult | ConvertTo-Json -Depth 4 -Compress)
        )
        [Console]::Out.Flush()
        exit 41
    }
    Invoke-TicketboxC07HeartbeatHelperMain
}
