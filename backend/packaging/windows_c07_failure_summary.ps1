#Requires -Version 5.1

<#
.SYNOPSIS
  Strict, non-authoritative owner-facing failure projection for C07 setup.
.DESCRIPTION
  The protected lifecycle receipt remains the authority.  This module derives a
  bounded allowlisted summary while the installer operation lease is held, then
  publishes it atomically in installer-state.  For lifecycle-lock exit failure,
  a process-local one-shot projection is sealed under that lease; after a failed
  exit it invalidates stale retry guidance before publishing blocked guidance.
  It never serializes exception text, paths, credentials, SQL, business rows,
  or database connection values.

  Dot-source windows_installation_safety.ps1, windows_lifecycle_lock.ps1, and
  windows_c07_lifecycle.ps1 before calling these functions.
#>

$script:TicketboxC07InstallerFailureSummarySchema =
    "ticketbox-c07-installer-failure-summary-v2"
$script:TicketboxC07InstallerFailureSummaryFileName =
    "c07-installer-failure-summary-v2.txt"
$script:TicketboxC07InstallerFailureSummaryMaximumBytes = 4096
$script:TicketboxC07InstallerLifecycleExitFailureProjections = @{}
$script:TicketboxC07InstallerLifecycleExitVetoSchema =
    "ticketbox-c07-installer-lifecycle-exit-veto-v2"
$script:TicketboxC07InstallerLifecycleExitVetoFileName =
    "c07-installer-lifecycle-exit-veto-v2.txt"
$script:TicketboxC07InstallerLifecycleExitVetoMaximumBytes = 1024
$script:TicketboxC07InstallerLifecycleExitVetoProjections = @{}
$script:TicketboxC07InstallerLifecycleExitVetoFields = @(
    "SCHEMA",
    "INSTALLER_OWNER_PID",
    "INSTALLER_OWNER_STARTED_FILETIME_HIGH",
    "INSTALLER_OWNER_STARTED_FILETIME_LOW",
    "OPERATION_ID",
    "FINALIZATION_ATTEMPT_ID",
    "STATE"
)
$script:TicketboxC07InstallerFailureSummaryFields = @(
    "SCHEMA",
    "INSTALLER_OWNER_PID",
    "INSTALLER_OWNER_STARTED_FILETIME_HIGH",
    "INSTALLER_OWNER_STARTED_FILETIME_LOW",
    "OPERATION_ID",
    "FINALIZATION_ATTEMPT_ID",
    "SOURCE_REVISION",
    "TARGET_REVISION",
    "LIFECYCLE_STAGE",
    "LAST_DURABLE_STAGE",
    "FAILURE_CODE",
    "REVISION_STATE",
    "RECOVERY_POINT",
    "RETRY_POLICY",
    "NO_RETURN_CROSSED",
    "DDL_STATE",
    "DATA_STATE",
    "NEXT_ACTION"
)

function Assert-TicketboxC07InstallerFailureSummaryDependencies {
    foreach ($commandName in @(
        "Assert-TicketboxC07OperationLease",
        "Assert-TicketboxExactFileAcl",
        "Assert-TicketboxProtectedDirectoryAcl",
        "Get-TicketboxInstallerStateDirectory",
        "Get-TicketboxPathEntryKindNoFollow",
        "Get-TicketboxProcessIdentity",
        "Initialize-TicketboxExactTreeDeleteNativeMethods",
        "Read-TicketboxC07Authority",
        "Remove-TicketboxProtectedUtf8Artifact",
        "Test-TicketboxProcessIdentityEquals",
        "Write-TicketboxProtectedUtf8FileDurable"
    )) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "C07 failure summary 缺少依赖函数：$commandName"
        }
    }
}

function Test-TicketboxC07FailureSummaryUInt32([string]$Value) {
    $parsed = [uint32]0
    return [uint32]::TryParse(
        $Value,
        [Globalization.NumberStyles]::None,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$parsed
    )
}

function Get-TicketboxC07FailureSummaryStageState([string]$Stage) {
    switch ($Stage) {
        { $_ -in @("captured", "writers_frozen") } {
            return [pscustomobject][ordered]@{
                RevisionState = "source"
                RecoveryPoint = "none"
                NoReturnCrossed = "false"
                DdlState = "not_started"
                DataState = "source_unchanged_writer_stopped"
            }
        }
        "recovery_generation_ready" {
            return [pscustomobject][ordered]@{
                RevisionState = "source"
                RecoveryPoint = "source_generation_unverified"
                NoReturnCrossed = "false"
                DdlState = "not_started"
                DataState = "source_unchanged_writer_stopped"
            }
        }
        "isolated_restore_verified" {
            return [pscustomobject][ordered]@{
                RevisionState = "source"
                RecoveryPoint = "source_restore_verified"
                NoReturnCrossed = "false"
                DdlState = "not_started"
                DataState = "source_unchanged_writer_stopped"
            }
        }
        "ddl_started" {
            return [pscustomobject][ordered]@{
                RevisionState = "unknown_source_or_target"
                RecoveryPoint = "source_restore_verified"
                NoReturnCrossed = "true"
                DdlState = "execution_started_commit_unknown"
                DataState = "revision_unknown_writer_stopped"
            }
        }
        "target_committed" {
            return [pscustomobject][ordered]@{
                RevisionState = "target"
                RecoveryPoint = "source_restore_verified"
                NoReturnCrossed = "true"
                DdlState = "target_committed"
                DataState = "target_committed_writer_stopped"
            }
        }
        "target_recovery_generation_ready" {
            return [pscustomobject][ordered]@{
                RevisionState = "target"
                RecoveryPoint = "target_generation_unverified"
                NoReturnCrossed = "true"
                DdlState = "target_committed"
                DataState = "target_committed_writer_stopped"
            }
        }
        { $_ -in @(
            "target_isolated_restore_verified",
            "runtime_acl_verified",
            "ready"
        ) } {
            return [pscustomobject][ordered]@{
                RevisionState = "target"
                RecoveryPoint = "target_restore_verified"
                NoReturnCrossed = "true"
                DdlState = "target_committed"
                DataState = "target_committed_writer_stopped"
            }
        }
        default { throw "C07 failure summary 拒绝未知 durable stage：$Stage" }
    }
}

function Get-TicketboxC07FailureSummaryCode {
    param(
        [Parameter(Mandatory = $true)][Exception]$Failure,
        [Parameter(Mandatory = $true)][object]$Authority
    )

    $stage = [string]$Authority.Receipt.stage
    $candidate = if ($stage -in @("refused_pre_ddl", "repair_required")) {
        [string]$Authority.Receipt.failure_code
    }
    elseif ($Failure.Data.Contains("TicketboxC07FailureCode")) {
        [string]$Failure.Data["TicketboxC07FailureCode"]
    }
    else {
        "unclassified_installer_failure"
    }
    if ($candidate -cnotmatch "^[a-z0-9_]{1,64}$") {
        return "unclassified_installer_failure"
    }
    return $candidate
}

function ConvertTo-TicketboxC07InstallerFailureSummaryText([object]$Summary) {
    $lines = foreach ($fieldName in $script:TicketboxC07InstallerFailureSummaryFields) {
        $propertyName = $fieldName.ToLowerInvariant()
        $property = $Summary.PSObject.Properties[$propertyName]
        if ($null -eq $property) {
            throw "C07 failure summary 缺少字段：$fieldName"
        }
        $value = [string]$property.Value
        if (
            [string]::IsNullOrEmpty($value) -or
            $value.Contains("`r") -or
            $value.Contains("`n") -or
            $value.Contains("=")
        ) {
            throw "C07 failure summary 字段值无效：$fieldName"
        }
        "$fieldName=$value"
    }
    return (($lines -join "`r`n") + "`r`n")
}

function ConvertFrom-TicketboxC07InstallerFailureSummaryText([string]$Text) {
    if (
        [string]::IsNullOrEmpty($Text) -or
        $Text.Length -gt $script:TicketboxC07InstallerFailureSummaryMaximumBytes -or
        -not $Text.EndsWith("`r`n", [StringComparison]::Ordinal) -or
        [Text.Encoding]::UTF8.GetByteCount($Text) -gt
            $script:TicketboxC07InstallerFailureSummaryMaximumBytes
    ) {
        throw "C07 failure summary 文本大小或终止符无效。"
    }
    $body = $Text.Substring(0, $Text.Length - 2)
    if ($body -match "(?<!`r)`n|`r(?!`n)") {
        throw "C07 failure summary 只能使用 canonical CRLF。"
    }
    $lines = $body.Split(
        [string[]]@("`r`n"),
        [StringSplitOptions]::None
    )
    if ($lines.Count -ne $script:TicketboxC07InstallerFailureSummaryFields.Count) {
        throw "C07 failure summary 字段数量无效。"
    }
    $values = [ordered]@{}
    for ($index = 0; $index -lt $lines.Count; $index++) {
        $expectedName = $script:TicketboxC07InstallerFailureSummaryFields[$index]
        $prefix = "$expectedName="
        if (-not $lines[$index].StartsWith($prefix, [StringComparison]::Ordinal)) {
            throw "C07 failure summary 字段顺序或名称无效。"
        }
        $value = $lines[$index].Substring($prefix.Length)
        if ([string]::IsNullOrEmpty($value) -or $value.Contains("=")) {
            throw "C07 failure summary 字段值无效：$expectedName"
        }
        $values[$expectedName.ToLowerInvariant()] = $value
    }
    $summary = [pscustomobject]$values
    if (
        [string]$summary.schema -cne
            $script:TicketboxC07InstallerFailureSummarySchema -or
        -not (Test-TicketboxC07FailureSummaryUInt32 (
            [string]$summary.installer_owner_started_filetime_high
        )) -or
        -not (Test-TicketboxC07FailureSummaryUInt32 (
            [string]$summary.installer_owner_started_filetime_low
        )) -or
        [int64]$summary.installer_owner_pid -lt 1 -or
        [int64]$summary.installer_owner_pid -gt 2147483647
    ) {
        throw "C07 failure summary schema 或 installer owner identity 无效。"
    }
    $operationId = [guid]::Empty
    $finalizationAttemptId = [guid]::Empty
    if (
        -not [guid]::TryParseExact(
            [string]$summary.operation_id,
            "D",
            [ref]$operationId
        ) -or
        $operationId -eq [guid]::Empty -or
        $operationId.ToString("D") -cne [string]$summary.operation_id -or
        -not [guid]::TryParseExact(
            [string]$summary.finalization_attempt_id,
            "D",
            [ref]$finalizationAttemptId
        ) -or
        $finalizationAttemptId -eq [guid]::Empty -or
        $finalizationAttemptId.ToString("D") -cne
            [string]$summary.finalization_attempt_id -or
        [string]$summary.source_revision -cne "20260722_0001" -or
        [string]$summary.target_revision -cne "20260729_0001" -or
        [string]$summary.failure_code -cnotmatch "^[a-z0-9_]{1,64}$"
    ) {
        throw "C07 failure summary operation/revision/failure_code 无效。"
    }
    $allStages = @($script:TicketboxC07OrderedStages) +
        @($script:TicketboxC07FailureStages)
    if (
        [string]$summary.lifecycle_stage -cnotin $allStages -or
        [string]$summary.last_durable_stage -cnotin
            @($script:TicketboxC07OrderedStages)
    ) {
        throw "C07 failure summary stage 无效。"
    }
    if (
        [string]$summary.lifecycle_stage -in $script:TicketboxC07FailureStages
    ) {
        if ([string]$summary.last_durable_stage -ceq "ready") {
            throw "C07 failure terminal 不能从 READY 派生。"
        }
    }
    elseif (
        [string]$summary.lifecycle_stage -cne
            [string]$summary.last_durable_stage
    ) {
        throw "C07 transient/READY summary 的 durable stage 不一致。"
    }
    $expected = Get-TicketboxC07FailureSummaryStageState (
        [string]$summary.last_durable_stage
    )
    if (
        [string]$summary.revision_state -cne $expected.RevisionState -or
        [string]$summary.recovery_point -cne $expected.RecoveryPoint -or
        [string]$summary.no_return_crossed -cne $expected.NoReturnCrossed -or
        [string]$summary.ddl_state -cne $expected.DdlState
    ) {
        throw "C07 failure summary 与 durable stage 的状态映射不一致。"
    }
    $blocked = [string]$summary.retry_policy -ceq "blocked"
    if ($blocked) {
        if (
            [string]$summary.next_action -cne
                "keep_services_stopped_contact_support" -or
            [string]$summary.data_state -cne
                "authority_or_writer_state_unverified"
        ) {
            throw "C07 blocked failure summary 的唯一动作无效。"
        }
    }
    else {
        if ([string]$summary.data_state -cne $expected.DataState) {
            throw "C07 failure summary data_state 与 revision 不一致。"
        }
        switch ([string]$summary.lifecycle_stage) {
            "refused_pre_ddl" {
                if (
                    [string]$summary.retry_policy -cne "successor_pre_ddl" -or
                    [string]$summary.next_action -cne "rerun_setup_successor"
                ) { throw "C07 pre-DDL failure summary 的 successor 动作无效。" }
            }
            "repair_required" {
                if (
                    [string]$summary.retry_policy -cne
                        "successor_forward_repair" -or
                    [string]$summary.next_action -cne
                        "install_compatible_repair_build"
                ) { throw "C07 repair failure summary 的前滚动作无效。" }
            }
            default {
                if (
                    [string]$summary.retry_policy -cne
                        "resume_same_operation" -or
                    [string]$summary.next_action -cne "rerun_setup_resume"
                ) { throw "C07 transient failure summary 的续跑动作无效。" }
            }
        }
    }
    return $summary
}

function Resolve-TicketboxC07InstallerFailureSummaryStateDirectory {
    param([Parameter(Mandatory = $true)][string]$InstallerState)

    $canonicalState = [IO.Path]::GetFullPath($InstallerState)
    $expectedState = [IO.Path]::GetFullPath(
        (Get-TicketboxInstallerStateDirectory)
    )
    if ($canonicalState -ine $expectedState) {
        throw "C07 failure summary installer-state 不在权威机器域。"
    }
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $canonicalState `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    return $canonicalState
}

function Get-TicketboxC07InstallerFailureSummaryDirectoryIdentity {
    param([Parameter(Mandatory = $true)][string]$InstallerState)

    Initialize-TicketboxExactTreeDeleteNativeMethods
    $identity = @(
        [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity(
            $InstallerState
        )
    )
    if (
        $identity.Count -ne 2 -or
        [string]$identity[0] -cnotmatch '^[0-9A-F]{16}$' -or
        [string]$identity[1] -cnotmatch '^[0-9A-F]{32}$'
    ) {
        throw "C07 failure summary installer-state identity 无效。"
    }
    return [string[]]@([string]$identity[0], [string]$identity[1])
}

function Test-TicketboxC07InstallerFailureSummaryDirectoryIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Left,
        [Parameter(Mandatory = $true)][object]$Right
    )

    $leftValues = @($Left)
    $rightValues = @($Right)
    return (
        $leftValues.Count -eq 2 -and
        $rightValues.Count -eq 2 -and
        [string]$leftValues[0] -ceq [string]$rightValues[0] -and
        [string]$leftValues[1] -ceq [string]$rightValues[1]
    )
}

function New-TicketboxC07InstallerFailureSummaryValue {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$OwnerIdentity,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId,
        [Parameter(Mandatory = $true)][Exception]$Failure
    )

    if ($null -eq $OwnerIdentity -or [int]$OwnerIdentity.ProcessId -lt 1) {
        throw "C07 failure summary 缺少已冻结的 Inno owner identity。"
    }
    $stage = [string]$Authority.Receipt.stage
    $lastDurableStage = if ($stage -in $script:TicketboxC07FailureStages) {
        [string]$Authority.Receipt.previous_stage
    }
    else { $stage }
    $stageState = Get-TicketboxC07FailureSummaryStageState $lastDurableStage
    $blocked =
        $Failure.Data.Contains("TicketboxInstallCompensationFailed") -or
        $Failure.Data.Contains("TicketboxInstallFinalizationFailed")
    $retryPolicy = "resume_same_operation"
    $nextAction = "rerun_setup_resume"
    if ($stage -ceq "refused_pre_ddl") {
        $retryPolicy = "successor_pre_ddl"
        $nextAction = "rerun_setup_successor"
    }
    elseif ($stage -ceq "repair_required") {
        $retryPolicy = "successor_forward_repair"
        $nextAction = "install_compatible_repair_build"
    }
    if ($blocked) {
        $retryPolicy = "blocked"
        $nextAction = "keep_services_stopped_contact_support"
    }
    return [pscustomobject][ordered]@{
        schema = $script:TicketboxC07InstallerFailureSummarySchema
        installer_owner_pid = [string][int]$OwnerIdentity.ProcessId
        installer_owner_started_filetime_high =
            [string][uint32]$OwnerIdentity.StartedFileTimeHigh
        installer_owner_started_filetime_low =
            [string][uint32]$OwnerIdentity.StartedFileTimeLow
        operation_id = [string]$Authority.Receipt.operation_id
        finalization_attempt_id =
            ([guid]$FinalizationAttemptId).ToString("D").ToLowerInvariant()
        source_revision =
            [string]$Authority.Descriptor.Payload.source_alembic_revision
        target_revision =
            [string]$Authority.Descriptor.Payload.target_alembic_revision
        lifecycle_stage = $stage
        last_durable_stage = $lastDurableStage
        failure_code = Get-TicketboxC07FailureSummaryCode `
            -Failure $Failure `
            -Authority $Authority
        revision_state = $stageState.RevisionState
        recovery_point = $stageState.RecoveryPoint
        retry_policy = $retryPolicy
        no_return_crossed = $stageState.NoReturnCrossed
        ddl_state = $stageState.DdlState
        data_state = if ($blocked) {
            "authority_or_writer_state_unverified"
        }
        else { $stageState.DataState }
        next_action = $nextAction
    }
}

function Publish-TicketboxC07InstallerFailureSummaryText {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][object]$ExpectedOwnerIdentity,
        [AllowNull()][object]$ExpectedDirectoryIdentity = $null,
        [switch]$InvalidateExistingFirst
    )

    $canonicalState =
        Resolve-TicketboxC07InstallerFailureSummaryStateDirectory `
            $InstallerState
    $parsed = ConvertFrom-TicketboxC07InstallerFailureSummaryText $Text
    if (
        [string]$parsed.installer_owner_pid -cne
            [string][int]$ExpectedOwnerIdentity.ProcessId -or
        [string]$parsed.installer_owner_started_filetime_high -cne
            [string][uint32]$ExpectedOwnerIdentity.StartedFileTimeHigh -or
        [string]$parsed.installer_owner_started_filetime_low -cne
            [string][uint32]$ExpectedOwnerIdentity.StartedFileTimeLow
    ) {
        throw "C07 failure summary 未绑定预授权的不可变 Inno owner identity。"
    }
    $directoryIdentityBefore =
        Get-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
            $canonicalState
    if (
        $null -ne $ExpectedDirectoryIdentity -and
        -not (Test-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
            -Left $directoryIdentityBefore `
            -Right $ExpectedDirectoryIdentity)
    ) {
        throw "C07 failure summary installer-state identity 已漂移。"
    }
    $path = Join-Path `
        $canonicalState `
        $script:TicketboxC07InstallerFailureSummaryFileName
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -cne "Missing" -and $kind -cne "File") {
        throw "C07 failure summary 路径不是 missing/plain-file。"
    }
    if ($kind -ceq "File") {
        Assert-TicketboxExactFileAcl `
            -Path $path `
            -Accounts @("SYSTEM", "BUILTIN\Administrators") `
            -OwnerAccount "SYSTEM"
        $existingText =
            [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
                $path,
                $script:TicketboxC07InstallerFailureSummaryMaximumBytes
            )
        [void](ConvertFrom-TicketboxC07InstallerFailureSummaryText $existingText)
        if ($InvalidateExistingFirst) {
            Remove-TicketboxProtectedUtf8Artifact `
                -Path $path `
                -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
                -OwnerAccount "SYSTEM"
            if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "Missing") {
                throw "C07 failure summary stale retry guidance 无法失效。"
            }
            $kind = "Missing"
        }
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text $Text `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting:($kind -ceq "File")
    $persistedText =
        [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
            $path,
            $script:TicketboxC07InstallerFailureSummaryMaximumBytes
        )
    if ($persistedText -cne $Text) {
        throw "C07 failure summary 原子发布后复读不一致。"
    }
    $persisted = ConvertFrom-TicketboxC07InstallerFailureSummaryText `
        $persistedText
    Assert-TicketboxExactFileAcl `
        -Path $path `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    $directoryIdentityAfter =
        Get-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
            $canonicalState
    if (-not (Test-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
        -Left $directoryIdentityBefore `
        -Right $directoryIdentityAfter)) {
        throw "C07 failure summary 发布期间 installer-state identity 漂移。"
    }
    return [pscustomobject][ordered]@{
        Path = $path
        Summary = $persisted
    }
}

function Write-TicketboxC07InstallerFailureSummary {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId,
        [Parameter(Mandatory = $true)][Exception]$Failure
    )

    Assert-TicketboxC07InstallerFailureSummaryDependencies
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $ownerIdentity = $LifecycleLock.ExternalOwnerIdentity
    $summary = New-TicketboxC07InstallerFailureSummaryValue `
        -Authority $authority `
        -OwnerIdentity $ownerIdentity `
        -FinalizationAttemptId $FinalizationAttemptId `
        -Failure $Failure
    $text = ConvertTo-TicketboxC07InstallerFailureSummaryText $summary
    [void](ConvertFrom-TicketboxC07InstallerFailureSummaryText $text)
    return Publish-TicketboxC07InstallerFailureSummaryText `
        -InstallerState $InstallerState `
        -Text $text `
        -ExpectedOwnerIdentity $ownerIdentity
}

function ConvertTo-TicketboxC07InstallerLifecycleExitVetoText {
    param([Parameter(Mandatory = $true)][object]$Marker)

    $lines = foreach (
        $fieldName in $script:TicketboxC07InstallerLifecycleExitVetoFields
    ) {
        $propertyName = $fieldName.ToLowerInvariant()
        $property = $Marker.PSObject.Properties[$propertyName]
        if ($null -eq $property) {
            throw "C07 lifecycle-exit veto 缺少字段：$fieldName"
        }
        $value = [string]$property.Value
        if (
            [string]::IsNullOrEmpty($value) -or
            $value.Contains("`r") -or
            $value.Contains("`n") -or
            $value.Contains("=")
        ) {
            throw "C07 lifecycle-exit veto 字段值无效：$fieldName"
        }
        "$fieldName=$value"
    }
    return (($lines -join "`r`n") + "`r`n")
}

function ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText {
    param([Parameter(Mandatory = $true)][string]$Text)

    if (
        [string]::IsNullOrEmpty($Text) -or
        $Text.Length -gt
            $script:TicketboxC07InstallerLifecycleExitVetoMaximumBytes -or
        -not $Text.EndsWith("`r`n", [StringComparison]::Ordinal) -or
        [Text.Encoding]::UTF8.GetByteCount($Text) -gt
            $script:TicketboxC07InstallerLifecycleExitVetoMaximumBytes
    ) {
        throw "C07 lifecycle-exit veto 文本大小或终止符无效。"
    }
    $body = $Text.Substring(0, $Text.Length - 2)
    if ($body -match "(?<!`r)`n|`r(?!`n)") {
        throw "C07 lifecycle-exit veto 只能使用 canonical CRLF。"
    }
    $lines = $body.Split(
        [string[]]@("`r`n"),
        [StringSplitOptions]::None
    )
    if (
        $lines.Count -ne
            $script:TicketboxC07InstallerLifecycleExitVetoFields.Count
    ) {
        throw "C07 lifecycle-exit veto 字段数量无效。"
    }
    $values = [ordered]@{}
    for ($index = 0; $index -lt $lines.Count; $index++) {
        $fieldName =
            $script:TicketboxC07InstallerLifecycleExitVetoFields[$index]
        $prefix = "$fieldName="
        if (
            -not $lines[$index].StartsWith(
                $prefix,
                [StringComparison]::Ordinal
            )
        ) {
            throw "C07 lifecycle-exit veto 字段顺序无效：$fieldName"
        }
        $value = $lines[$index].Substring($prefix.Length)
        if (
            [string]::IsNullOrEmpty($value) -or
            $value.Contains("=")
        ) {
            throw "C07 lifecycle-exit veto 字段值无效：$fieldName"
        }
        $values[$fieldName.ToLowerInvariant()] = $value
    }
    if (
        [string]$values.schema -cne
            $script:TicketboxC07InstallerLifecycleExitVetoSchema -or
        -not (Test-TicketboxC07FailureSummaryUInt32 (
            [string]$values.installer_owner_pid
        )) -or
        [uint32]$values.installer_owner_pid -lt 1 -or
        -not (Test-TicketboxC07FailureSummaryUInt32 (
            [string]$values.installer_owner_started_filetime_high
        )) -or
        -not (Test-TicketboxC07FailureSummaryUInt32 (
            [string]$values.installer_owner_started_filetime_low
        )) -or
        [string]$values.operation_id -cnotmatch
            '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
        [string]$values.finalization_attempt_id -cnotmatch
            '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
        [string]$values.finalization_attempt_id -ceq
            '00000000-0000-0000-0000-000000000000' -or
        [string]$values.state -cnotin @(
            "lock_release_pending",
            "lock_release_completed"
        )
    ) {
        throw "C07 lifecycle-exit veto identity/state 无效。"
    }
    return [pscustomobject]$values
}

function New-TicketboxC07InstallerLifecycleExitVetoValue {
    param(
        [Parameter(Mandatory = $true)][object]$OwnerIdentity,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("lock_release_pending", "lock_release_completed")]
        [string]$State
    )

    return [pscustomobject][ordered]@{
        schema = $script:TicketboxC07InstallerLifecycleExitVetoSchema
        installer_owner_pid = [string][uint32]$OwnerIdentity.ProcessId
        installer_owner_started_filetime_high =
            [string][uint32]$OwnerIdentity.StartedFileTimeHigh
        installer_owner_started_filetime_low =
            [string][uint32]$OwnerIdentity.StartedFileTimeLow
        operation_id = $OperationId
        finalization_attempt_id =
            ([guid]$FinalizationAttemptId).ToString("D").ToLowerInvariant()
        state = $State
    }
}

function Publish-TicketboxC07InstallerLifecycleExitVetoText {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][object]$ExpectedOwnerIdentity,
        [Parameter(Mandatory = $true)][object]$ExpectedDirectoryIdentity,
        [AllowEmptyString()][string]$ExpectedExistingText = ""
    )

    $canonicalState =
        Resolve-TicketboxC07InstallerFailureSummaryStateDirectory `
            $InstallerState
    $parsed = ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText $Text
    if (
        [string]$parsed.installer_owner_pid -cne
            [string][uint32]$ExpectedOwnerIdentity.ProcessId -or
        [string]$parsed.installer_owner_started_filetime_high -cne
            [string][uint32]$ExpectedOwnerIdentity.StartedFileTimeHigh -or
        [string]$parsed.installer_owner_started_filetime_low -cne
            [string][uint32]$ExpectedOwnerIdentity.StartedFileTimeLow
    ) {
        throw "C07 lifecycle-exit veto 未绑定 exact Inno owner identity。"
    }
    $directoryIdentityBefore =
        Get-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
            $canonicalState
    if (-not (Test-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
        -Left $directoryIdentityBefore `
        -Right $ExpectedDirectoryIdentity)) {
        throw "C07 lifecycle-exit veto installer-state identity 已漂移。"
    }
    $path = Join-Path `
        $canonicalState `
        $script:TicketboxC07InstallerLifecycleExitVetoFileName
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -cne "Missing" -and $kind -cne "File") {
        throw "C07 lifecycle-exit veto 路径不是 missing/plain-file。"
    }
    if ($kind -ceq "File") {
        Assert-TicketboxExactFileAcl `
            -Path $path `
            -Accounts @("SYSTEM", "BUILTIN\Administrators") `
            -OwnerAccount "SYSTEM"
        $existingText =
            [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
                $path,
                $script:TicketboxC07InstallerLifecycleExitVetoMaximumBytes
            )
        $existing =
            ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText `
                $existingText
        if (-not [string]::IsNullOrEmpty($ExpectedExistingText)) {
            if ($existingText -cne $ExpectedExistingText) {
                throw "C07 lifecycle-exit veto pending authority 已漂移。"
            }
        }
        elseif (
            [string]$existing.state -ceq "lock_release_pending" -and
            $existingText -cne $Text
        ) {
            throw "C07 lifecycle-exit veto 存在 foreign pending authority。"
        }
    }
    elseif (-not [string]::IsNullOrEmpty($ExpectedExistingText)) {
        throw "C07 lifecycle-exit veto pending authority 缺失。"
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text $Text `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting:($kind -ceq "File")
    $persistedText =
        [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
            $path,
            $script:TicketboxC07InstallerLifecycleExitVetoMaximumBytes
        )
    if ($persistedText -cne $Text) {
        throw "C07 lifecycle-exit veto durable publication 复读不一致。"
    }
    $persisted =
        ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText $persistedText
    Assert-TicketboxExactFileAcl `
        -Path $path `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    $directoryIdentityAfter =
        Get-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
            $canonicalState
    if (-not (Test-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
        -Left $directoryIdentityBefore `
        -Right $directoryIdentityAfter)) {
        throw "C07 lifecycle-exit veto 发布期间 installer-state identity 漂移。"
    }
    return [pscustomobject][ordered]@{
        Path = $path
        Marker = $persisted
        Text = $persistedText
    }
}

function New-TicketboxC07InstallerLifecycleExitVeto {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId
    )

    Assert-TicketboxC07InstallerFailureSummaryDependencies
    $canonicalState =
        Resolve-TicketboxC07InstallerFailureSummaryStateDirectory `
            $InstallerState
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $ownerIdentity = $LifecycleLock.ExternalOwnerIdentity
    if ($null -eq $ownerIdentity -or [int]$ownerIdentity.ProcessId -lt 1) {
        throw "C07 lifecycle-exit veto 缺少 Inno owner identity。"
    }
    $liveOwner = Get-TicketboxProcessIdentity `
        -ProcessId ([int]$ownerIdentity.ProcessId)
    if (-not (Test-TicketboxProcessIdentityEquals $liveOwner $ownerIdentity)) {
        throw "C07 lifecycle-exit veto Inno owner identity 已漂移。"
    }
    $coordinatorIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
    $directoryIdentity =
        Get-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
            $canonicalState
    $operationId = [string]$authority.Receipt.operation_id
    $pendingText =
        ConvertTo-TicketboxC07InstallerLifecycleExitVetoText (
            New-TicketboxC07InstallerLifecycleExitVetoValue `
                -OwnerIdentity $ownerIdentity `
                -OperationId $operationId `
                -FinalizationAttemptId $FinalizationAttemptId `
                -State "lock_release_pending"
        )
    $completedText =
        ConvertTo-TicketboxC07InstallerLifecycleExitVetoText (
            New-TicketboxC07InstallerLifecycleExitVetoValue `
                -OwnerIdentity $ownerIdentity `
                -OperationId $operationId `
                -FinalizationAttemptId $FinalizationAttemptId `
                -State "lock_release_completed"
        )
    [void](Publish-TicketboxC07InstallerLifecycleExitVetoText `
        -InstallerState $canonicalState `
        -Text $pendingText `
        -ExpectedOwnerIdentity $ownerIdentity `
        -ExpectedDirectoryIdentity $directoryIdentity)
    $randomBytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
    $nonce =
        ([BitConverter]::ToString($randomBytes) -replace "-", "").ToLowerInvariant()
    if ($script:TicketboxC07InstallerLifecycleExitVetoProjections.ContainsKey($nonce)) {
        throw "C07 lifecycle-exit veto nonce 碰撞。"
    }
    $script:TicketboxC07InstallerLifecycleExitVetoProjections[$nonce] =
        [pscustomobject][ordered]@{
            InstallerState = $canonicalState
            DirectoryIdentity = [string[]]@($directoryIdentity)
            PendingText = $pendingText
            CompletedText = $completedText
            OwnerIdentity = [pscustomobject][ordered]@{
                ProcessId = [int]$ownerIdentity.ProcessId
                StartedFileTimeHigh = [uint32]$ownerIdentity.StartedFileTimeHigh
                StartedFileTimeLow = [uint32]$ownerIdentity.StartedFileTimeLow
            }
            CoordinatorIdentity = [pscustomobject][ordered]@{
                ProcessId = [int]$coordinatorIdentity.ProcessId
                StartedFileTimeHigh =
                    [uint32]$coordinatorIdentity.StartedFileTimeHigh
                StartedFileTimeLow =
                    [uint32]$coordinatorIdentity.StartedFileTimeLow
            }
        }
    return [pscustomobject][ordered]@{ Nonce = $nonce }
}

function Complete-TicketboxC07InstallerLifecycleExitVeto {
    param([Parameter(Mandatory = $true)][object]$Projection)

    Assert-TicketboxC07InstallerFailureSummaryDependencies
    $nonce = [string]$Projection.Nonce
    if (
        $nonce -cnotmatch '^[0-9a-f]{64}$' -or
        -not $script:TicketboxC07InstallerLifecycleExitVetoProjections.ContainsKey(
            $nonce
        )
    ) {
        throw "C07 lifecycle-exit veto projection 缺失、无效或已消费。"
    }
    $record = $script:TicketboxC07InstallerLifecycleExitVetoProjections[$nonce]
    [void]$script:TicketboxC07InstallerLifecycleExitVetoProjections.Remove($nonce)
    $coordinatorIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
    if (-not (Test-TicketboxProcessIdentityEquals `
        $coordinatorIdentity `
        $record.CoordinatorIdentity)) {
        throw "C07 lifecycle-exit veto coordinator identity 已漂移。"
    }
    $liveOwner = Get-TicketboxProcessIdentity `
        -ProcessId ([int]$record.OwnerIdentity.ProcessId)
    if (-not (Test-TicketboxProcessIdentityEquals `
        $liveOwner `
        $record.OwnerIdentity)) {
        throw "C07 lifecycle-exit veto Inno owner identity 已漂移。"
    }
    return Publish-TicketboxC07InstallerLifecycleExitVetoText `
        -InstallerState ([string]$record.InstallerState) `
        -Text ([string]$record.CompletedText) `
        -ExpectedOwnerIdentity $record.OwnerIdentity `
        -ExpectedDirectoryIdentity $record.DirectoryIdentity `
        -ExpectedExistingText ([string]$record.PendingText)
}

function New-TicketboxC07InstallerLifecycleExitFailureProjection {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId
    )

    Assert-TicketboxC07InstallerFailureSummaryDependencies
    $canonicalState =
        Resolve-TicketboxC07InstallerFailureSummaryStateDirectory `
            $InstallerState
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $ownerIdentity = $LifecycleLock.ExternalOwnerIdentity
    if ($null -eq $ownerIdentity -or [int]$ownerIdentity.ProcessId -lt 1) {
        throw "C07 lifecycle-exit projection 缺少 Inno owner identity。"
    }
    $liveOwner = Get-TicketboxProcessIdentity `
        -ProcessId ([int]$ownerIdentity.ProcessId)
    if (-not (Test-TicketboxProcessIdentityEquals $liveOwner $ownerIdentity)) {
        throw "C07 lifecycle-exit projection 的 Inno owner identity 已漂移。"
    }
    $coordinatorIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
    $failure = [InvalidOperationException]::new(
        "C07 lifecycle lock exit 未完成；owner summary 必须 fail closed。"
    )
    $failure.Data["TicketboxInstallFinalizationFailed"] = $true
    $failure.Data["TicketboxInstallFinalizationStep"] =
        "lifecycle_lock_exit"
    $failure.Data["TicketboxC07FailureCode"] =
        "lifecycle_lock_exit_failed"
    $summary = New-TicketboxC07InstallerFailureSummaryValue `
        -Authority $authority `
        -OwnerIdentity $ownerIdentity `
        -FinalizationAttemptId $FinalizationAttemptId `
        -Failure $failure
    $text = ConvertTo-TicketboxC07InstallerFailureSummaryText $summary
    $validated = ConvertFrom-TicketboxC07InstallerFailureSummaryText $text
    if (
        [string]$validated.retry_policy -cne "blocked" -or
        [string]$validated.next_action -cne
            "keep_services_stopped_contact_support"
    ) {
        throw "C07 lifecycle-exit projection 未生成 blocked summary。"
    }
    $directoryIdentity =
        Get-TicketboxC07InstallerFailureSummaryDirectoryIdentity `
            $canonicalState
    $randomBytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($randomBytes)
    }
    finally {
        $rng.Dispose()
    }
    $nonce = ([BitConverter]::ToString($randomBytes) -replace "-", "").ToLowerInvariant()
    if ($script:TicketboxC07InstallerLifecycleExitFailureProjections.ContainsKey($nonce)) {
        throw "C07 lifecycle-exit projection nonce 碰撞。"
    }
    $record = [pscustomobject][ordered]@{
        Nonce = $nonce
        InstallerState = $canonicalState
        DirectoryIdentity = [string[]]@($directoryIdentity)
        Text = $text
        OwnerIdentity = [pscustomobject][ordered]@{
            ProcessId = [int]$ownerIdentity.ProcessId
            StartedFileTimeHigh = [uint32]$ownerIdentity.StartedFileTimeHigh
            StartedFileTimeLow = [uint32]$ownerIdentity.StartedFileTimeLow
        }
        CoordinatorIdentity = [pscustomobject][ordered]@{
            ProcessId = [int]$coordinatorIdentity.ProcessId
            StartedFileTimeHigh =
                [uint32]$coordinatorIdentity.StartedFileTimeHigh
            StartedFileTimeLow =
                [uint32]$coordinatorIdentity.StartedFileTimeLow
        }
    }
    $script:TicketboxC07InstallerLifecycleExitFailureProjections[$nonce] =
        $record
    return [pscustomobject][ordered]@{ Nonce = $nonce }
}

function Remove-TicketboxC07InstallerLifecycleExitFailureProjection {
    param([AllowNull()][object]$Projection)

    if ($null -eq $Projection) {
        return
    }
    $nonce = [string]$Projection.Nonce
    if ($nonce -cnotmatch '^[0-9a-f]{64}$') {
        throw "C07 lifecycle-exit projection token 无效。"
    }
    [void]$script:TicketboxC07InstallerLifecycleExitFailureProjections.Remove(
        $nonce
    )
}

function Publish-TicketboxC07InstallerLifecycleExitFailureProjection {
    param([Parameter(Mandatory = $true)][object]$Projection)

    Assert-TicketboxC07InstallerFailureSummaryDependencies
    $nonce = [string]$Projection.Nonce
    if (
        $nonce -cnotmatch '^[0-9a-f]{64}$' -or
        -not $script:TicketboxC07InstallerLifecycleExitFailureProjections.ContainsKey(
            $nonce
        )
    ) {
        throw "C07 lifecycle-exit projection token 缺失、无效或已消费。"
    }
    $record =
        $script:TicketboxC07InstallerLifecycleExitFailureProjections[$nonce]
    [void]$script:TicketboxC07InstallerLifecycleExitFailureProjections.Remove(
        $nonce
    )
    $coordinatorIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
    if (-not (Test-TicketboxProcessIdentityEquals `
        $coordinatorIdentity `
        $record.CoordinatorIdentity)) {
        throw "C07 lifecycle-exit projection coordinator identity 已漂移。"
    }
    $liveOwner = Get-TicketboxProcessIdentity `
        -ProcessId ([int]$record.OwnerIdentity.ProcessId)
    if (-not (Test-TicketboxProcessIdentityEquals `
        $liveOwner `
        $record.OwnerIdentity)) {
        throw "C07 lifecycle-exit projection Inno owner identity 已漂移。"
    }
    return Publish-TicketboxC07InstallerFailureSummaryText `
        -InstallerState ([string]$record.InstallerState) `
        -Text ([string]$record.Text) `
        -ExpectedOwnerIdentity $record.OwnerIdentity `
        -ExpectedDirectoryIdentity $record.DirectoryIdentity `
        -InvalidateExistingFirst
}
