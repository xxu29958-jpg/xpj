#Requires -Version 5.1

# Durable intent policy and the IO-free next-action reducer.  This module is
# safe to load during Inno's preinstall bootstrap; execution adapters are not.
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
    }
    $intent = Write-TicketboxDatabaseGenerationEnvelope `
        $path "intent" $expected $LifecycleLock
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
        [AllowNull()][object]$Credentials,
        [AllowNull()][object]$SourceBinding,
        [AllowNull()][object]$TargetAuthorization,
        [AllowNull()][object]$Candidate,
        [AllowNull()][object]$Current
    )
    if (
        $null -ne $Candidate -and
        ($null -eq $TargetAuthorization -or $null -eq $SourceBinding)
    ) {
        throw "database generation candidate 缺少前置 authority。"
    }
    if ($null -ne $TargetAuthorization -and $null -eq $SourceBinding) {
        throw "database generation target authorization 缺少 SourceBinding。"
    }
    if (
        $null -ne $SourceBinding -and
        $null -eq $Credentials -and
        $null -eq $Candidate -and
        $null -eq $Current
    ) {
        throw "database generation CURRENT 前 credential 不得缺失。"
    }
    if ($null -ne $Current) {
        if ($null -eq $Candidate -or $null -eq $TargetAuthorization -or $null -eq $SourceBinding) {
            throw "database generation CURRENT 缺少 immutable authority chain。"
        }
        return "read_current"
    }
    if ($null -eq $Credentials) { return "ensure_credentials" }
    if ($null -eq $SourceBinding) { return "bind_source" }
    if ($null -eq $TargetAuthorization) { return "authorize_target" }
    if ($null -eq $Candidate) { return "seal_candidate" }
    return "finalize_current"
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
