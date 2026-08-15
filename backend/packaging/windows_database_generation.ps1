#Requires -Version 5.1

# The installed database-generation authority is deliberately small and flat:
# immutable artifacts carry phase state, the reducer is pure, and adapters own
# Windows/PostgreSQL effects.  No journal, heartbeat, or installer stage is an
# authority input.

$contractPath = Join-Path $PSScriptRoot "windows_database_generation_contract.ps1"
$artifactsPath = Join-Path $PSScriptRoot "windows_database_generation_artifacts.ps1"
foreach ($dependency in @(
    $contractPath,
    $artifactsPath
)) {
    if ((Get-TicketboxPathEntryKindNoFollow $dependency) -cne "File") {
        throw "database generation dependency 不是可信普通文件：$dependency"
    }
    Assert-NoTicketboxAncestorReparsePoints $dependency
    . $dependency
}

function Import-TicketboxDatabaseGenerationExecutionDependencies {
    foreach ($name in @(
        "windows_atomic_artifacts.ps1",
        "windows_postgresql_writer_fence.ps1",
        "windows_database_generation_program_adapter.ps1",
        "windows_database_generation_program_execution.ps1",
        "windows_database_generation_recovery_evidence.ps1",
        "windows_database_generation_target_recovery.ps1",
        "windows_database_generation_projection.ps1"
    )) {
        $dependency = Join-Path $PSScriptRoot $name
        if ((Get-TicketboxPathEntryKindNoFollow $dependency) -cne "File") {
            throw "database generation execution dependency 不是可信普通文件：$dependency"
        }
        Assert-NoTicketboxAncestorReparsePoints $dependency
        . $dependency
    }
}

function New-TicketboxDatabaseGenerationIntent {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$TargetBackendVersion,
        [Parameter(Mandatory = $true)][int64]$MigrationHelperSize,
        [Parameter(Mandatory = $true)][string]$MigrationHelperSha256,
        [Parameter(Mandatory = $true)][object]$ProgramContract,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$ProjectionContract
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    ConvertTo-TicketboxNumericVersion $TargetBackendVersion | Out-Null
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        $MigrationHelperSha256 `
        "database generation migration helper"
    Assert-TicketboxDatabaseGenerationExactProperties `
        $ProgramContract `
        @("RelativePath", "Sha256", "Size", "TargetRevision") `
        "database generation program contract"
    if (
        $MigrationHelperSize -lt 1 -or
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
    $operationId = if ($null -eq $existing) {
        [guid]::NewGuid().ToString("D")
    }
    else {
        ([guid][string]$existing.Payload.operation_id).ToString("D")
    }
    $installationId = if ($null -eq $existing) {
        [guid]::NewGuid().ToString("D")
    }
    else {
        ([guid][string]$existing.Payload.installation_id).ToString("D")
    }
    $expected = [ordered]@{
        schema = "ticketbox-database-generation-intent-v1"
        operation_id = $operationId
        installation_id = $installationId
        expected_predecessor_sha256 = ""
        target_backend_version = $TargetBackendVersion
        migration_helper_relative_path =
            $script:TicketboxDatabaseGenerationMigrationHelperRelativePath
        migration_helper_size = $MigrationHelperSize
        migration_helper_sha256 = $MigrationHelperSha256
        generation_program_relative_path = [string]$ProgramContract.RelativePath
        generation_program_size = [int64]$ProgramContract.Size
        generation_program_sha256 = [string]$ProgramContract.Sha256
        host_contract_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $HostContract
        )
        projection_contract_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $ProjectionContract
        )
        target_revision = [string]$ProgramContract.TargetRevision
    }
    if ($null -ne $existing) {
        Assert-TicketboxDatabaseGenerationExactProperties `
            $existing.Payload `
            @($expected.Keys) `
            "database generation intent"
        if (
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload) -cne
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $expected)
        ) {
            throw "existing database generation intent 与当前 immutable request 漂移。"
        }
        return [pscustomobject]@{ StateRoot = $stateRoot; Artifact = $existing }
    }
    $current = Read-TicketboxDatabaseGenerationCurrent $stateRoot -AllowAbsent
    if ($null -ne $current) {
        throw "尚未实现跨 generation successor；既有 current 必须进入显式升级裁决。"
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
        [Parameter(Mandatory = $true)][int64]$MigrationHelperSize,
        [Parameter(Mandatory = $true)][string]$MigrationHelperSha256,
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
        -ExistingPathFacts @($PreinstallFacts.ExistingPathFacts)
    return New-TicketboxDatabaseGenerationIntent `
        -InstallerState $InstallerState `
        -LifecycleLock $LifecycleLock `
        -TargetBackendVersion $TargetBackendVersion `
        -MigrationHelperSize $MigrationHelperSize `
        -MigrationHelperSha256 $MigrationHelperSha256 `
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
            (Get-TicketboxDatabaseGenerationTextSha256 (
                ConvertTo-TicketboxDatabaseGenerationCanonicalJson $ProjectionContract
            ))
    ) {
        throw "database generation intent 与 installed host/projection 漂移。"
    }
    return [pscustomobject]@{ StateRoot = $stateRoot; Artifact = $intent }
}

function Assert-TicketboxDatabaseGenerationReleaseBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity
    )
    $program = Get-TicketboxInstalledDatabaseGenerationProgram `
        -ReleaseIdentity $ReleaseIdentity
    if (
        [string]$Intent.Payload.operation_id -cne
            ([guid][string]$ReleaseIdentity.InstallationOperationId).ToString("D") -or
        [string]$Intent.Payload.installation_id -cne
            ([guid][string]$ReleaseIdentity.InstallationId).ToString("D") -or
        [string]$Intent.Payload.target_backend_version -cne
            [string]$ReleaseIdentity.BackendVersionFloor -or
        [string]$Intent.Payload.migration_helper_relative_path -cne
            [string]$ReleaseIdentity.MigrationHelperRelativePath -or
        [int64]$Intent.Payload.migration_helper_size -ne
            [int64]$ReleaseIdentity.MigrationHelperSize -or
        [string]$Intent.Payload.migration_helper_sha256 -cne
            ([string]$ReleaseIdentity.MigrationHelperSha256).ToLowerInvariant() -or
        [string]$Intent.Payload.generation_program_relative_path -cne
            [string]$ReleaseIdentity.DatabaseGenerationProgramRelativePath -or
        [int64]$Intent.Payload.generation_program_size -ne
            [int64]$ReleaseIdentity.DatabaseGenerationProgramSize -or
        [string]$Intent.Payload.generation_program_sha256 -cne
            ([string]$ReleaseIdentity.DatabaseGenerationProgramSha256).ToLowerInvariant() -or
        [string]$Intent.Payload.target_revision -cne
            [string]$program.target_revision
    ) {
        throw "database generation intent 与 installed release evidence 漂移。"
    }
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
        $null -eq $Current
    ) {
        throw "database generation CURRENT 前 credential 不得缺失。"
    }
    if ($null -ne $Current) {
        if ($null -eq $Candidate -or $null -eq $TargetAuthorization -or $null -eq $SourceBinding) {
            throw "database generation CURRENT 缺少 immutable authority chain。"
        }
        return "reconcile_projection"
    }
    if ($null -eq $Credentials) { return "ensure_credentials" }
    if ($null -eq $SourceBinding) { return "bind_source" }
    if ($null -eq $TargetAuthorization) { return "authorize_target" }
    if ($null -eq $Candidate) { return "seal_candidate" }
    return "publish_current"
}

function Throw-TicketboxDatabaseGenerationOperationFailure {
    param(
        [AllowNull()][object]$Primary,
        [AllowNull()][object]$Cleanup
    )
    if ($null -ne $Primary -and $null -ne $Cleanup) {
        $aggregate = [AggregateException]::new(
            "database generation primary operation and capability cleanup failed",
            @($Primary.Exception, $Cleanup.Exception)
        )
        foreach ($key in @("TicketboxC07FailureCode", "TicketboxC07FailureCodes")) {
            if ($Primary.Exception.Data.Contains($key)) {
                $aggregate.Data[$key] = $Primary.Exception.Data[$key]
            }
        }
        throw $aggregate
    }
    if ($null -ne $Primary) { throw $Primary }
    if ($null -ne $Cleanup) { throw $Cleanup }
}

function Invoke-TicketboxInstalledDatabaseGeneration {
    param(
        [Parameter(Mandatory = $true)][object]$IntentContext,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][string]$RecoveryArtifactPath
    )
    $adapterPath = Join-Path $PSScriptRoot "windows_database_generation_adapter.ps1"
    if ((Get-TicketboxPathEntryKindNoFollow $adapterPath) -cne "File") {
        throw "database generation adapter 不是可信普通文件：$adapterPath"
    }
    Assert-NoTicketboxAncestorReparsePoints $adapterPath
    . $adapterPath
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Import-TicketboxDatabaseGenerationExecutionDependencies
    $stateRoot = [string]$IntentContext.StateRoot
    $intent = $IntentContext.Artifact
    $operationId = [string]$intent.Payload.operation_id
    $hostContractSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $HostContract
    )
    $projectionContractSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $ProjectionContract
    )
    if (
        [string]$intent.Payload.host_contract_sha256 -cne $hostContractSha256 -or
        [string]$intent.Payload.projection_contract_sha256 -cne
            $projectionContractSha256
    ) {
        throw "database generation host/projection contract 与 durable intent 漂移。"
    }
    Assert-TicketboxDatabaseGenerationReleaseBinding `
        -Intent $intent `
        -ReleaseIdentity $ReleaseIdentity
    $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority $HostContract
    $publishedCurrent = Read-TicketboxDatabaseGenerationCurrent $stateRoot -AllowAbsent
    $publishedCredentials = Read-TicketboxDatabaseGenerationCredentials `
        -StateRoot $stateRoot -Intent $intent -AllowAbsent
    if ($null -ne $publishedCurrent -and $null -eq $publishedCredentials) {
        Assert-TicketboxDatabaseGenerationCommitReadyArtifact `
            -ExpectedOperationId $operationId `
            -ExpectedCurrentSha256 ([string]$publishedCurrent.PayloadSha256) | Out-Null
        return Read-TicketboxDatabaseGenerationRuntimeProjection `
            -Intent $intent `
            -Current $publishedCurrent `
            -HostAuthority $hostAuthority `
            -ProjectionContract $ProjectionContract `
            -LifecycleLock $LifecycleLock
    }
    while ($true) {
        Assert-TicketboxLifecycleOperationLease $LifecycleLock
        $credentials = Read-TicketboxDatabaseGenerationCredentials `
            -StateRoot $stateRoot -Intent $intent -AllowAbsent
        $source = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "source-binding" -AllowAbsent
        $target = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "target-authorization" -AllowAbsent
        $candidate = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "candidate" -AllowAbsent
        $current = Read-TicketboxDatabaseGenerationCurrent $stateRoot -AllowAbsent
        $next = Resolve-TicketboxDatabaseGenerationNextAction `
            $credentials $source $target $candidate $current
        switch ($next) {
            "ensure_credentials" {
                [void](New-TicketboxDatabaseGenerationCredentials `
                    -StateRoot $stateRoot `
                    -Intent $intent `
                    -LifecycleLock $LifecycleLock)
            }
            "bind_source" {
                $capability = Acquire-TicketboxC07SuperuserCapability `
                    -HostAuthority $hostAuthority `
                    -RecoveryArtifactPath $RecoveryArtifactPath `
                    -ExpectedOperationId $operationId `
                    -LifecycleLock $LifecycleLock
                $primary = $null
                $cleanup = $null
                try {
                    [void](Renew-TicketboxC07SuperuserCapability `
                        $capability $operationId $LifecycleLock)
                    $evidence = Invoke-TicketboxDatabaseGenerationEmptySource `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -Credentials $credentials `
                        -HostAuthority $hostAuthority `
                        -SuperuserCapability $capability `
                        -LifecycleLock $LifecycleLock
                    [void](New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "source-binding" $evidence `
                        $LifecycleLock)
                }
                catch { $primary = $_ }
                finally {
                    try {
                        Revoke-TicketboxC07SuperuserCapability `
                            $capability $operationId $LifecycleLock
                    }
                    catch { $cleanup = $_ }
                }
                Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
            }
            "authorize_target" {
                $capability = Acquire-TicketboxC07SuperuserCapability `
                    -HostAuthority $hostAuthority `
                    -RecoveryArtifactPath $RecoveryArtifactPath `
                    -ExpectedOperationId $operationId `
                    -LifecycleLock $LifecycleLock
                $primary = $null
                $cleanup = $null
                try {
                    [void](Renew-TicketboxC07SuperuserCapability `
                        $capability $operationId $LifecycleLock)
                    $evidence = Invoke-TicketboxDatabaseGenerationTargetAdapter `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -SourceBinding $source `
                        -Credentials $credentials `
                        -ReleaseIdentity $ReleaseIdentity `
                        -LifecycleLock $LifecycleLock `
                        -HostContract $HostContract `
                        -HostAuthority $hostAuthority `
                        -SuperuserCapability $capability
                    [void](New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "target-authorization" $evidence `
                        $LifecycleLock)
                }
                catch { $primary = $_ }
                finally {
                    try {
                        Revoke-TicketboxC07SuperuserCapability `
                            $capability $operationId $LifecycleLock
                    }
                    catch { $cleanup = $_ }
                }
                Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
            }
            "seal_candidate" {
                $payload = [ordered]@{
                    schema = "ticketbox-database-generation-candidate-v1"
                    operation_id = $operationId
                    intent_sha256 = [string]$intent.PayloadSha256
                    source_binding_sha256 = [string]$source.PayloadSha256
                    target_authorization_sha256 = [string]$target.PayloadSha256
                    database_binding_sha256 = [string]$target.Payload.database_binding_sha256
                    target_revision = [string]$intent.Payload.target_revision
                    generation_program_sha256 =
                        [string]$intent.Payload.generation_program_sha256
                }
                [void](New-TicketboxDatabaseGenerationChainedArtifact `
                    $stateRoot $operationId "candidate" $payload $LifecycleLock)
            }
            "publish_current" {
                [void](Publish-TicketboxDatabaseGenerationCurrent `
                    $stateRoot $intent $candidate $LifecycleLock)
            }
            "reconcile_projection" {
                $capability = Acquire-TicketboxC07SuperuserCapability `
                    -HostAuthority $hostAuthority `
                    -RecoveryArtifactPath $RecoveryArtifactPath `
                    -ExpectedOperationId $operationId `
                    -LifecycleLock $LifecycleLock
                $primary = $null
                $cleanup = $null
                $result = $null
                try {
                    [void](Renew-TicketboxC07SuperuserCapability `
                        $capability $operationId $LifecycleLock)
                    $result = Complete-TicketboxDatabaseGenerationRuntimeProjection `
                        -Intent $intent `
                        -Current $current `
                        -Credentials $credentials `
                        -HostAuthority $hostAuthority `
                        -SuperuserCapability $capability `
                        -ProjectionContract $ProjectionContract `
                        -LifecycleLock $LifecycleLock
                }
                catch { $primary = $_ }
                finally {
                    try {
                        Revoke-TicketboxC07SuperuserCapability `
                            $capability $operationId $LifecycleLock
                    }
                    catch { $cleanup = $_ }
                }
                Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
                Remove-TicketboxDatabaseGenerationCredentials `
                    -StateRoot $stateRoot `
                    -Intent $intent `
                    -LifecycleLock $LifecycleLock
                return $result
            }
            default { throw "unknown database generation action: $next" }
        }
    }
}
