#Requires -Version 5.1

$contractPath = Join-Path $PSScriptRoot "windows_database_generation_contract.ps1"
$releasePath = Join-Path $PSScriptRoot "windows_database_generation_release.ps1"
$operationFailurePath = Join-Path $PSScriptRoot "windows_operation_failure.ps1"
$artifactsPath = Join-Path $PSScriptRoot "windows_database_generation_artifacts.ps1"
$commitVerifierPath = Join-Path $PSScriptRoot "windows_database_generation_commit_verifier.ps1"
$policyPath = Join-Path $PSScriptRoot "windows_database_generation_policy.ps1"
foreach ($dependency in @(
    $contractPath,
    $releasePath,
    $operationFailurePath,
    $artifactsPath,
    $commitVerifierPath,
    $policyPath
)) {
    if ((Get-TicketboxPathEntryKindNoFollow $dependency) -cne "File") {
        throw "database generation dependency 不是可信普通文件：$dependency"
    }
    Assert-NoTicketboxAncestorReparsePoints $dependency
    . $dependency
}

function Get-TicketboxDatabaseGenerationExecutionDependencyPaths {
    param(
        [Parameter(Mandatory = $true)][string]$Root
    )
    $paths = @()
    foreach ($name in @(
        "windows_atomic_artifacts.ps1",
        "windows_pg_recovery_tools.ps1",
        "windows_postgresql_credentials.ps1",
        "windows_postgresql_database_command.ps1",
        "windows_postgresql_database_catalog.ps1",
        "windows_postgresql_writer_fence.ps1",
        "windows_ticketbox_database_contract.ps1",
        "windows_ticketbox_database_acl.ps1",
        "windows_ticketbox_database_acl_observation.ps1",
        "windows_ticketbox_database_roles.ps1",
        "windows_service_contract.ps1",
        "windows_service_identity.ps1",
        "windows_service_lifecycle.ps1",
        "windows_postgresql_single_user.ps1",
        "windows_database_generation_credentials.ps1",
        "windows_database_generation_role_fence.ps1",
        "windows_database_generation_host_authority.ps1",
        "windows_database_generation_role_bootstrap.ps1",
        "windows_database_generation_source.ps1",
        "windows_database_generation_source_binding.ps1",
        "windows_database_generation_program_adapter.ps1",
        "windows_database_generation_program_execution.ps1",
        "windows_database_generation_recovery_evidence.ps1",
        "windows_database_generation_target_recovery.ps1",
        "windows_database_generation_target_authorization.ps1",
        "windows_database_generation_database_binding.ps1",
        "windows_database_generation_current.ps1",
        "windows_database_generation_retirement.ps1",
        "windows_database_generation_projection.ps1"
    )) {
        $dependency = Join-Path $Root $name
        if ((Get-TicketboxPathEntryKindNoFollow $dependency) -cne "File") {
            throw "database generation execution dependency 不是可信普通文件：$dependency"
        }
        Assert-NoTicketboxAncestorReparsePoints $dependency
        $paths += $dependency
    }
    return $paths
}

function Invoke-TicketboxInstalledDatabaseGeneration {
    param(
        [Parameter(Mandatory = $true)][object]$IntentContext,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][string]$BootstrapRecoveryPath
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `
        -Root $PSScriptRoot)) {
        . $dependency
    }
    $stateRoot = [string]$IntentContext.StateRoot
    $intent = $IntentContext.Artifact
    $operationId = [string]$intent.Payload.operation_id
    $bootstrapDataRoot = [string]$HostContract.data_root
    $bootstrapAppData = Join-Path $bootstrapDataRoot "app"
    $bootstrapSecretByteCount =
        [int]$HostContract.release_config.secret_byte_count
    $expectedBootstrapRecoveryPath =
        Get-PostgresBootstrapRecoveryPath -AppData $bootstrapAppData
    if (
        $bootstrapSecretByteCount -lt 32 -or
        -not (Test-TicketboxPathEquals `
            $BootstrapRecoveryPath `
            $expectedBootstrapRecoveryPath)
    ) {
        throw "database generation bootstrap binding 与 HostContract 漂移。"
    }
    $hostContractSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $HostContract
    )
    $projectionContractSha256 =
        Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 `
            $ProjectionContract
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
    $hostAuthority = $null
    $httpBootstrapSecret = ""
    $maintenanceAuthority = $null
    $primary = $null
    $cleanup = @()
    $completed = $null
    $credentials = $null
    $runtimeCredentials = $null
    try {
        while ($true) {
            Assert-TicketboxLifecycleOperationLease $LifecycleLock
            if ($null -ne $credentials) {
                Close-TicketboxDatabaseGenerationCredentials $credentials
                $credentials = $null
            }
            if ($null -ne $runtimeCredentials) {
                Close-TicketboxDatabaseGenerationRuntimeCredentials $runtimeCredentials
                $runtimeCredentials = $null
            }
            $credentials = Read-TicketboxDatabaseGenerationCredentials `
                -StateRoot $stateRoot -Intent $intent -AllowAbsent
            $source = Read-TicketboxDatabaseGenerationOperationArtifact `
                $stateRoot $operationId "source-binding" -AllowAbsent
            if ($null -ne $source) {
                $source = Assert-TicketboxDatabaseGenerationSourceBindingChain `
                    -StateRoot $stateRoot -Binding $source -Intent $intent
            }
            $target = Read-TicketboxDatabaseGenerationOperationArtifact `
                $stateRoot $operationId "target-authorization" -AllowAbsent
            $candidate = Read-TicketboxDatabaseGenerationOperationArtifact `
                $stateRoot $operationId "candidate" -AllowAbsent
            $terminal = Read-TicketboxDatabaseGenerationOperationArtifact `
                $stateRoot $operationId "terminal-state" -AllowAbsent
            $serviceTransition = Read-TicketboxDatabaseGenerationServiceTransition `
                $stateRoot -AllowAbsent
            $current = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
            $currentForOperation = $null
            if ($null -ne $current) {
                if ([string]$current.Payload.operation_id -ceq $operationId) {
                    $currentForOperation = $current
                }
                elseif (
                    [string]::IsNullOrEmpty(
                        [string]$intent.Payload.expected_predecessor_sha256
                    ) -or
                    [string]$current.PayloadSha256 -cne
                        [string]$intent.Payload.expected_predecessor_sha256
                ) {
                    throw "database generation predecessor CURRENT changed during execution。"
                }
            }
            $hostAuthority = $null
            $bootstrapRetired = $null
            $runtimeProjection = $null
            if ($null -eq $serviceTransition) {
                $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                    $HostContract
                if ($null -ne $candidate) {
                    $runtimeCredentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -Candidate $candidate `
                        -AllowAbsent
                }
                $runtimeRetirementProbeFailure = $null
                if ($null -ne $runtimeCredentials) {
                    try {
                        $bootstrapRetired =
                            Test-TicketboxDatabaseGenerationBootstrapRetirement `
                                $intent $candidate $hostAuthority `
                                $runtimeCredentials.RuntimePassword
                    }
                    catch { $runtimeRetirementProbeFailure = $_ }
                }
                $needsBootstrapAuthority =
                    $null -ne $runtimeRetirementProbeFailure -or
                    (
                        $null -ne $credentials -and
                        ($null -eq $source -or $null -eq $target)
                    ) -or
                    ($null -ne $candidate -and $null -eq $runtimeCredentials)
                if (
                    $needsBootstrapAuthority -and
                    $null -eq $maintenanceAuthority
                ) {
                    $bootstrapRecoveryState = $null
                    try {
                        $bootstrapRecoveryState = Read-PostgresBootstrapRecoveryState `
                            -Path $BootstrapRecoveryPath `
                            -AppData $bootstrapAppData `
                            -SecretByteCount $bootstrapSecretByteCount
                        $httpBootstrapSecret =
                            [string]$bootstrapRecoveryState.HttpBootstrapSecret
                        if ($httpBootstrapSecret -cnotmatch '^[A-Za-z0-9_-]{32,128}$') {
                            throw "HTTP bootstrap secret 不是受控 secret。"
                        }
                        $maintenanceAuthority =
                            New-TicketboxDatabaseGenerationMaintenanceAuthority `
                                -Intent $intent `
                                -SuperuserPassword (
                                    [string]$bootstrapRecoveryState.SuperuserPassword
                                ) `
                                -HostAuthority $hostAuthority `
                                -LifecycleLock $LifecycleLock
                    }
                    finally {
                        if ($null -ne $bootstrapRecoveryState) {
                            $bootstrapRecoveryState.SuperuserPassword = ""
                            $bootstrapRecoveryState.HttpBootstrapSecret = ""
                        }
                    }
                }
                if ($null -ne $runtimeRetirementProbeFailure) {
                    if (
                        (Get-TicketboxPathEntryKindNoFollow `
                            $BootstrapRecoveryPath) -cne "File"
                    ) {
                        throw $runtimeRetirementProbeFailure
                    }
                    $bootstrapRetired =
                        Test-TicketboxDatabaseGenerationBootstrapRetirementWithMaintenanceAuthority `
                            $intent $candidate $hostAuthority `
                            $maintenanceAuthority $LifecycleLock
                    if ($bootstrapRetired) {
                        throw $runtimeRetirementProbeFailure
                    }
                }
                if ($bootstrapRetired) {
                    $runtimeProjection = Read-TicketboxDatabaseGenerationRuntimeProjection `
                        $intent $candidate $hostAuthority $ProjectionContract `
                        $LifecycleLock -AllowAbsent
                }
            }
            $credentialsPath = Get-TicketboxDatabaseGenerationArtifactPath `
                $stateRoot "credentials" $operationId
            $transientAuthorityPresent =
                (Get-TicketboxPathEntryKindNoFollow $BootstrapRecoveryPath) -cne "Missing" -or
                (Get-TicketboxPathEntryKindNoFollow $credentialsPath) -cne "Missing" -or
                $null -ne $serviceTransition
            $observation = [pscustomobject][ordered]@{
                bootstrap_retired = $bootstrapRetired
                candidate = $candidate
                credentials = $credentials
                current = $currentForOperation
                runtime_credentials = $runtimeCredentials
                runtime_projection = $runtimeProjection
                service_transition_present = $null -ne $serviceTransition
                source_binding = $source
                target_authorization = $target
                terminal_state = $terminal
                transient_authority_present = $transientAuthorityPresent
            }
            $next = Resolve-TicketboxDatabaseGenerationNextAction $observation
            switch ($next) {
                "reconcile_service_transition" {
                    Repair-TicketboxDatabaseGenerationServiceTransition `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -HostContract $HostContract `
                        -LifecycleLock $LifecycleLock
                }
                "ensure_credentials" {
                    $createdCredentials = New-TicketboxDatabaseGenerationCredentials `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -LifecycleLock $LifecycleLock
                    Close-TicketboxDatabaseGenerationCredentials $createdCredentials
                }
                "bind_source" {
                    $evidence = Invoke-TicketboxDatabaseGenerationSourceBinding `
                        $stateRoot $intent $credentials $HostContract `
                        $maintenanceAuthority $LifecycleLock
                    [void](New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "source-binding" $evidence `
                        $LifecycleLock)
                }
                "authorize_target" {
                    $evidence = Invoke-TicketboxDatabaseGenerationTargetAuthorization `
                        $stateRoot $intent $source $credentials $ReleaseIdentity `
                        $LifecycleLock $HostContract $maintenanceAuthority
                    [void](New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "target-authorization" $evidence `
                        $LifecycleLock)
                }
                "seal_candidate" {
                    [void](New-TicketboxDatabaseGenerationCandidate `
                        $stateRoot $intent $source $target $LifecycleLock)
                }
                "seal_runtime_credentials" {
                    $runtimeCredentials = New-TicketboxDatabaseGenerationRuntimeCredentials `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -Candidate $candidate `
                        -Credentials $credentials `
                        -HttpBootstrapSecret $httpBootstrapSecret `
                        -LifecycleLock $LifecycleLock
                }
                "transition_bootstrap_authority" {
                    [void](Prepare-TicketboxDatabaseGenerationRuntimeProjection `
                        -Intent $intent `
                        -Candidate $candidate `
                        -RuntimeCredentials $runtimeCredentials `
                        -HostAuthority $hostAuthority `
                        -MaintenanceAuthority $maintenanceAuthority `
                        -ProjectionContract $ProjectionContract `
                        -LifecycleLock $LifecycleLock)
                    Close-TicketboxDatabaseGenerationMaintenanceAuthority `
                        $maintenanceAuthority $intent $hostAuthority $LifecycleLock
                    $maintenanceAuthority = $null
                    [void](Retire-TicketboxDatabaseGenerationBootstrapAuthority `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -Candidate $candidate `
                        -HostContract $HostContract `
                        -HostAuthority $hostAuthority `
                        -RuntimePassword $runtimeCredentials.RuntimePassword `
                        -LifecycleLock $LifecycleLock)
                }
                "publish_runtime_projection" {
                    [void](Publish-TicketboxDatabaseGenerationRuntimeProjection `
                        $intent $candidate $runtimeCredentials $hostAuthority `
                        $ProjectionContract $LifecycleLock)
                }
                "retire_transient_authority" {
                    Remove-TicketboxDatabaseGenerationTransientAuthority `
                        $stateRoot $intent $BootstrapRecoveryPath `
                        $bootstrapAppData $LifecycleLock
                }
                "seal_terminal" {
                    [void](New-TicketboxDatabaseGenerationTerminalState `
                        $stateRoot $intent $candidate $runtimeCredentials `
                        $runtimeProjection $LifecycleLock)
                }
                "publish_current" {
                    $currentTransition = `
                        New-TicketboxDatabaseGenerationAdvanceCurrentTransition `
                            $intent $candidate $terminal
                    [void](Publish-TicketboxDatabaseGenerationCurrent `
                        $currentTransition $LifecycleLock)
                }
                "read_current" {
                    Assert-TicketboxDatabaseGenerationCommitReadyArtifact `
                        -ExpectedOperationId $operationId `
                        -ExpectedCurrentSha256 (
                            [string]$currentForOperation.PayloadSha256
                        ) | Out-Null
                    $completed = New-TicketboxInstalledDatabaseGenerationResult `
                        $currentForOperation $runtimeProjection
                }
                default { throw "unknown database generation action: $next" }
            }
            if ($null -ne $completed) { break }
        }
    }
    catch { $primary = $_ }
    finally {
        try {
            if ($null -ne $maintenanceAuthority) {
                Close-TicketboxDatabaseGenerationMaintenanceAuthority `
                    -Authority $maintenanceAuthority `
                    -Intent $intent `
                    -HostAuthority $hostAuthority `
                    -LifecycleLock $LifecycleLock
            }
        }
        catch { $cleanup += $_ }
        if ($null -ne $credentials) {
            try { Close-TicketboxDatabaseGenerationCredentials $credentials }
            catch { $cleanup += $_ }
            $credentials = $null
        }
        if ($null -ne $runtimeCredentials) {
            try {
                Close-TicketboxDatabaseGenerationRuntimeCredentials `
                    $runtimeCredentials
            }
            catch { $cleanup += $_ }
            $runtimeCredentials = $null
        }
        $httpBootstrapSecret = ""
    }
    Throw-TicketboxOperationFailure $primary $cleanup
    return $completed
}

function Restore-TicketboxInstalledDatabaseGenerationPredecessor {
    param(
        [Parameter(Mandatory = $true)][object]$PredecessorCurrentPayload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $PredecessorCurrentPayload `
        -ExpectedNames (Get-TicketboxDatabaseGenerationPayloadProperties "current") `
        -Label "database generation predecessor CURRENT"
    $targetSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $PredecessorCurrentPayload
    )
    $current = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
    if ($null -eq $current) {
        throw "database generation predecessor restoration lacks CURRENT."
    }
    if ([string]$current.PayloadSha256 -ceq $targetSha256) { return $current }
    if (
        [string]$current.Payload.expected_predecessor_sha256 -cne $targetSha256 -or
        [string]$current.Payload.installation_id -cne
            [string]$PredecessorCurrentPayload.installation_id -or
        [string]$current.Payload.operation_id -ceq
            [string]$PredecessorCurrentPayload.operation_id
    ) {
        throw "database generation predecessor restoration is not the exact immediate predecessor."
    }
    $transition = [pscustomobject][ordered]@{
        schema = "ticketbox-database-generation-current-transition-v1"
        mode = "restore_predecessor"
        expected_current_sha256 = [string]$current.PayloadSha256
        target_payload_sha256 = $targetSha256
        target_payload = $PredecessorCurrentPayload
    }
    return Publish-TicketboxDatabaseGenerationCurrent $transition $LifecycleLock
}
