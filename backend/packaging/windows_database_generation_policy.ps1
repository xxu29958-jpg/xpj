#Requires -Version 5.1

# Durable intent policy and the IO-free next-action reducer.  This module is
# safe to load during Inno's preinstall bootstrap; execution adapters are not.
function Assert-TicketboxDatabaseGenerationPreinstallEligibility {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$PgServiceName,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][bool]$HasPersistedInstalledReleaseConfig,
        [Parameter(Mandatory = $true)][object]$LifecycleEvidence,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$ExistingPathFacts
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Assert-TicketboxDatabaseGenerationExactProperties `
        $LifecycleEvidence `
        @("current_sha256", "install_completed", "operation_id", "receipt_present", "schema") `
        "database generation lifecycle evidence"
    if (
        [string]$LifecycleEvidence.schema -cne
            "ticketbox-database-generation-lifecycle-evidence-v1" -or
        $LifecycleEvidence.receipt_present -isnot [bool] -or
        $LifecycleEvidence.install_completed -isnot [bool] -or
        (
            -not [bool]$LifecycleEvidence.receipt_present -and
            (
                [bool]$LifecycleEvidence.install_completed -or
                -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.operation_id) -or
                -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.current_sha256)
            )
        ) -or
        (
            [bool]$LifecycleEvidence.receipt_present -and
            (
                ([guid][string]$LifecycleEvidence.operation_id).ToString("D") -cne
                    [string]$LifecycleEvidence.operation_id -or
                (
                    -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.current_sha256) -and
                    [string]$LifecycleEvidence.current_sha256 -cnotmatch '^[0-9a-f]{64}$'
                )
            )
        )
    ) {
        throw "database generation lifecycle evidence 不是闭合合同。"
    }
    if ([bool]$LifecycleEvidence.install_completed) {
        throw "尚未实现 repair/reinstall；completed install 不得进入 fresh-only generation。"
    }
    $activeIntent = Read-TicketboxDatabaseGenerationActiveIntent `
        $StateRoot -AllowAbsent
    $current = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
    if ($null -eq $activeIntent) {
        $existingFacts = @()
        if ($null -ne $current) { $existingFacts += "database generation CURRENT" }
        if (Test-TicketboxServiceExists $PgServiceName) {
            $existingFacts += "PostgreSQL service"
        }
        if (Test-TicketboxServiceExists $BackendServiceName) {
            $existingFacts += "backend service"
        }
        if ($HasPersistedInstalledReleaseConfig) {
            $existingFacts += "installed release config"
        }
        foreach ($fact in $ExistingPathFacts) {
            Assert-TicketboxDatabaseGenerationExactProperties `
                $fact @("Label", "Path") "preinstall path fact"
            if ((Get-TicketboxPathEntryKindNoFollow ([string]$fact.Path)) -cne "Missing") {
                $existingFacts += [string]$fact.Label
            }
        }
        if ($existingFacts.Count -gt 0) {
            throw (
                "尚未实现既有安装 successor；首笔 generation intent 前已发现：" +
                ($existingFacts -join ", ")
            )
        }
        return
    }
    if (
        [bool]$LifecycleEvidence.receipt_present -and
        [string]$LifecycleEvidence.operation_id -cne
            [string]$activeIntent.Payload.operation_id
    ) {
        throw "lifecycle receipt 不属于现有 active intent。"
    }
    if ($null -ne $current) {
        if (
            [string]$current.Payload.operation_id -cne
                [string]$activeIntent.Payload.operation_id -or
            [string]$current.Payload.intent_sha256 -cne
                [string]$activeIntent.PayloadSha256
        ) {
            throw "database generation CURRENT 不属于现有 active intent。"
        }
        if (-not [bool]$LifecycleEvidence.receipt_present) {
            throw "CURRENT 缺少未完成 lifecycle receipt，拒绝猜测恢复。"
        }
        if (
            -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.current_sha256) -and
            [string]$LifecycleEvidence.current_sha256 -cne
                [string]$current.PayloadSha256
        ) {
            throw "lifecycle receipt 绑定了其他 database generation CURRENT。"
        }
    }
    elseif (-not [string]::IsNullOrEmpty([string]$LifecycleEvidence.current_sha256)) {
        throw "lifecycle receipt 声明了缺失的 database generation CURRENT。"
    }
}

function New-TicketboxDatabaseGenerationIntent {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ExpectedPredecessorSha256,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$SourceRequestSha256,
        [Parameter(Mandatory = $true)][string]$TargetBackendVersion,
        [Parameter(Mandatory = $true)][int64]$MaintenanceHelperSize,
        [Parameter(Mandatory = $true)][string]$MaintenanceHelperSha256,
        [Parameter(Mandatory = $true)][object]$ProgramContract,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$ProjectionContract
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    ConvertTo-TicketboxNumericVersion $TargetBackendVersion | Out-Null
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        $MaintenanceHelperSha256 `
        "database generation migration helper"
    Assert-TicketboxDatabaseGenerationExactProperties `
        $ProgramContract `
        @("RelativePath", "Sha256", "Size", "TargetRevision") `
        "database generation program contract"
    if (
        $MaintenanceHelperSize -lt 1 -or
        [string]$ProgramContract.RelativePath -cne
            $script:TicketboxDatabaseGenerationProgramRelativePath -or
        [int64]$ProgramContract.Size -lt 1
    ) {
        throw "database generation release evidence 无效。"
    }
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$ProgramContract.Sha256) `
        "database generation program"
    $stateRoot = Initialize-TicketboxDatabaseGenerationStateRoot $InstallerState $LifecycleLock
    $path = Join-Path $stateRoot $script:TicketboxDatabaseGenerationActiveIntentName
    $existing = Read-TicketboxDatabaseGenerationActiveIntent $stateRoot -AllowAbsent
    $current = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
    $successor = -not [string]::IsNullOrEmpty($ExpectedPredecessorSha256)
    $hasSourceRequest = -not [string]::IsNullOrEmpty($SourceRequestSha256)
    if ($successor -ne $hasSourceRequest) {
        throw "database generation predecessor 与 source request 必须同时存在。"
    }
    if ($hasSourceRequest) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $SourceRequestSha256 "database generation source request"
    }
    if ($successor) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $ExpectedPredecessorSha256 "database generation predecessor"
        if (
            $null -eq $current -or
            [string]$current.PayloadSha256 -cne $ExpectedPredecessorSha256
        ) {
            throw "database generation successor predecessor CURRENT 漂移。"
        }
    }
    elseif ($null -ne $current) {
        throw "fresh database generation 拒绝既有 CURRENT。"
    }

    if (
        $successor -and
        $null -ne $existing -and
        [string]$existing.Payload.expected_predecessor_sha256 -ceq
            $ExpectedPredecessorSha256
    ) {
        $operationId = ([guid][string]$existing.Payload.operation_id).ToString("D")
        $installationId = ([guid][string]$existing.Payload.installation_id).ToString("D")
    }
    elseif ($successor) {
        if (
            $null -eq $existing -or
            [string]$existing.PayloadSha256 -cne [string]$current.Payload.intent_sha256 -or
            [string]$existing.Payload.operation_id -cne
                [string]$current.Payload.operation_id
        ) {
            throw "database generation successor active intent 不等于 predecessor authority。"
        }
        $operationId = [guid]::NewGuid().ToString("D")
        $installationId = ([guid][string]$current.Payload.installation_id).ToString("D")
    }
    elseif ($null -ne $existing) {
        if (-not [string]::IsNullOrEmpty(
            [string]$existing.Payload.expected_predecessor_sha256
        )) {
            throw "fresh database generation active intent 已属于 successor。"
        }
        $operationId = ([guid][string]$existing.Payload.operation_id).ToString("D")
        $installationId = ([guid][string]$existing.Payload.installation_id).ToString("D")
    }
    else {
        $operationId = [guid]::NewGuid().ToString("D")
        $installationId = [guid]::NewGuid().ToString("D")
    }

    $expected = [ordered]@{
        schema = "ticketbox-database-generation-intent-v2"
        operation_id = $operationId
        installation_id = $installationId
        expected_predecessor_sha256 = $ExpectedPredecessorSha256
        source_request_sha256 = $SourceRequestSha256
        target_backend_version = $TargetBackendVersion
        database_maintenance_helper_relative_path =
            $script:TicketboxDatabaseMaintenanceHelperRelativePath
        database_maintenance_helper_size = $MaintenanceHelperSize
        database_maintenance_helper_sha256 = $MaintenanceHelperSha256
        generation_program_relative_path = [string]$ProgramContract.RelativePath
        generation_program_size = [int64]$ProgramContract.Size
        generation_program_sha256 = [string]$ProgramContract.Sha256
        host_contract_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $HostContract
        )
        projection_contract_sha256 =
            Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 `
                $ProjectionContract
        target_revision = [string]$ProgramContract.TargetRevision
    }
    if ($null -ne $existing) {
        $same = (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload
        ) -ceq (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $expected
        )
        if ($same) {
            return [pscustomobject]@{ StateRoot = $stateRoot; Artifact = $existing }
        }
        if (
            -not $successor -or
            [string]$existing.PayloadSha256 -cne [string]$current.Payload.intent_sha256
        ) {
            throw "existing database generation intent 与当前 immutable request 漂移。"
        }
        $intent = Replace-TicketboxDatabaseGenerationActiveIntent `
            $stateRoot ([string]$existing.PayloadSha256) $expected $LifecycleLock
        return [pscustomobject]@{ StateRoot = $stateRoot; Artifact = $intent }
    }
    $intent = New-TicketboxDatabaseGenerationActiveIntent `
        $stateRoot $expected $LifecycleLock
    return [pscustomobject]@{ StateRoot = $stateRoot; Artifact = $intent }
}

function Start-TicketboxDatabaseGenerationIntent {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$PreinstallFacts,
        [Parameter(Mandatory = $true)][string]$TargetBackendVersion,
        [Parameter(Mandatory = $true)][int64]$MaintenanceHelperSize,
        [Parameter(Mandatory = $true)][string]$MaintenanceHelperSha256,
        [Parameter(Mandatory = $true)][object]$ProgramContract,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$ProjectionContract
    )
    Assert-TicketboxDatabaseGenerationExactProperties `
        $PreinstallFacts `
        @(
            "BackendServiceName",
            "ExistingPathFacts",
            "HasPersistedInstalledReleaseConfig",
            "LifecycleEvidence",
            "PgServiceName",
            "StateRoot"
        ) `
        "database generation preinstall facts"
    Assert-TicketboxDatabaseGenerationPreinstallEligibility `
        -StateRoot ([string]$PreinstallFacts.StateRoot) `
        -LifecycleLock $LifecycleLock `
        -PgServiceName ([string]$PreinstallFacts.PgServiceName) `
        -BackendServiceName ([string]$PreinstallFacts.BackendServiceName) `
        -HasPersistedInstalledReleaseConfig `
            ([bool]$PreinstallFacts.HasPersistedInstalledReleaseConfig) `
        -LifecycleEvidence $PreinstallFacts.LifecycleEvidence `
        -ExistingPathFacts @($PreinstallFacts.ExistingPathFacts)
    return New-TicketboxDatabaseGenerationIntent `
        -InstallerState $InstallerState `
        -LifecycleLock $LifecycleLock `
        -ExpectedPredecessorSha256 "" `
        -SourceRequestSha256 "" `
        -TargetBackendVersion $TargetBackendVersion `
        -MaintenanceHelperSize $MaintenanceHelperSize `
        -MaintenanceHelperSha256 $MaintenanceHelperSha256 `
        -ProgramContract $ProgramContract `
        -HostContract $HostContract `
        -ProjectionContract $ProjectionContract
}

function Read-TicketboxDatabaseGenerationIntentContext {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$ProjectionContract
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $stateRoot = Get-TicketboxDatabaseGenerationStateRoot $InstallerState
    $intent = Read-TicketboxDatabaseGenerationActiveIntent $stateRoot
    if (
        [string]$intent.Payload.host_contract_sha256 -cne
            (Get-TicketboxDatabaseGenerationTextSha256 (
                ConvertTo-TicketboxDatabaseGenerationCanonicalJson $HostContract
            )) -or
        [string]$intent.Payload.projection_contract_sha256 -cne
            (Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 `
                $ProjectionContract)
    ) {
        throw "database generation intent 与 installed host/projection 漂移。"
    }
    return [pscustomobject]@{ StateRoot = $stateRoot; Artifact = $intent }
}

function Resolve-TicketboxDatabaseGenerationNextAction {
    param(
        [Parameter(Mandatory = $true)][object]$Observation
    )
    $expectedNames = @(
        "bootstrap_retired", "candidate", "credentials", "current",
        "runtime_credentials", "runtime_projection",
        "service_transition_present", "source_binding",
        "target_authorization", "terminal_state",
        "transient_authority_present"
    )
    $actualNames = @($Observation.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $sortedExpected = @($expectedNames | Sort-Object -CaseSensitive)
    if (($actualNames -join "`n") -cne ($sortedExpected -join "`n")) {
        throw "database generation observation 不是 closed contract。"
    }
    if (
        $Observation.service_transition_present -isnot [bool] -or
        $Observation.transient_authority_present -isnot [bool] -or
        (
            $null -ne $Observation.bootstrap_retired -and
            $Observation.bootstrap_retired -isnot [bool]
        )
    ) {
        throw "database generation observation boolean state 无效。"
    }
    $credentials = $Observation.credentials
    $sourceBinding = $Observation.source_binding
    $targetAuthorization = $Observation.target_authorization
    $candidate = $Observation.candidate
    $runtimeCredentials = $Observation.runtime_credentials
    $runtimeProjection = $Observation.runtime_projection
    $terminalState = $Observation.terminal_state
    $current = $Observation.current
    if (
        $null -ne $candidate -and
        ($null -eq $targetAuthorization -or $null -eq $sourceBinding)
    ) {
        throw "database generation candidate 缺少前置 authority。"
    }
    if ($null -ne $targetAuthorization -and $null -eq $sourceBinding) {
        throw "database generation target authorization 缺少 SourceBinding。"
    }
    if (
        $null -ne $sourceBinding -and
        $null -eq $credentials -and
        $null -eq $candidate -and
        $null -eq $current
    ) {
        throw "database generation CURRENT 前 credential 不得缺失。"
    }
    if (
        $null -ne $runtimeCredentials -and $null -eq $candidate -or
        $null -ne $runtimeProjection -and (
            $null -eq $runtimeCredentials -or
            $Observation.bootstrap_retired -ne $true
        ) -or
        $null -ne $terminalState -and (
            $null -eq $runtimeProjection -or
            $Observation.transient_authority_present
        )
    ) {
        throw "database generation terminal authority chain 不完整。"
    }
    if ($null -ne $Current) {
        if (
            $null -eq $candidate -or
            $null -eq $targetAuthorization -or
            $null -eq $sourceBinding -or
            $null -eq $runtimeCredentials -or
            $Observation.bootstrap_retired -ne $true -or
            $null -eq $runtimeProjection -or
            $null -eq $terminalState -or
            $Observation.transient_authority_present -or
            $Observation.service_transition_present
        ) {
            throw "database generation CURRENT 缺少 immutable authority chain。"
        }
        return "read_current"
    }
    if ($Observation.service_transition_present) {
        return "reconcile_service_transition"
    }
    if ($null -eq $credentials -and $null -eq $candidate) {
        return "ensure_credentials"
    }
    if ($null -eq $sourceBinding) { return "bind_source" }
    if ($null -eq $targetAuthorization) { return "authorize_target" }
    if ($null -eq $candidate) { return "seal_candidate" }
    if ($null -eq $runtimeCredentials) {
        if ($null -eq $credentials) {
            throw "candidate 已封存但 durable runtime credentials 缺失。"
        }
        return "seal_runtime_credentials"
    }
    if ($Observation.bootstrap_retired -isnot [bool]) {
        throw "candidate bootstrap retirement observation 缺失。"
    }
    if (-not $Observation.bootstrap_retired) {
        return "transition_bootstrap_authority"
    }
    if ($null -eq $runtimeProjection) { return "publish_runtime_projection" }
    if ($Observation.transient_authority_present) {
        return "retire_transient_authority"
    }
    if ($null -eq $terminalState) { return "seal_terminal" }
    return "publish_current"
}

function New-TicketboxInstalledDatabaseGenerationResult {
    param(
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$Projection
    )
    if (
        [string]$Projection.Payload.operation_id -cne [string]$Current.Payload.operation_id -or
        [string]$Projection.Payload.candidate_sha256 -cne [string]$Current.Payload.candidate_sha256 -or
        [string]$Projection.Payload.committed_revision -cne [string]$Current.Payload.committed_revision
    ) {
        throw "database generation completion result 与 CURRENT 漂移。"
    }
    return [pscustomobject]@{
        OperationId = [string]$Current.Payload.operation_id
        CurrentSha256 = [string]$Current.PayloadSha256
        CommittedRevision = [string]$Current.Payload.committed_revision
        DatabaseUrl = [string]$Projection.DatabaseUrl
    }
}
