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

function Read-TicketboxDatabaseGenerationBootstrapRetirementState {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$HostAuthority
    )
    $runtimeCredentials = $null
    $primary = $null
    $cleanup = @()
    $state = $null
    try {
        $runtimeCredentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
            -StateRoot $StateRoot -Intent $Intent -Candidate $Candidate
        try {
            $retired = Test-TicketboxDatabaseGenerationBootstrapRetirement `
                $Intent $Candidate $HostAuthority `
                $runtimeCredentials.RuntimePassword
            $state = if ($retired) { "retired" } else { "active" }
        }
        catch { $state = "unknown" }
    }
    catch { $primary = $_ }
    finally {
        if ($null -ne $runtimeCredentials) {
            try {
                Close-TicketboxDatabaseGenerationRuntimeCredentials `
                    $runtimeCredentials
            }
            catch { $cleanup += $_ }
        }
    }
    Throw-TicketboxOperationFailure $primary $cleanup
    return $state
}

function Get-TicketboxInstalledDatabaseGenerationBudget {
    param([Parameter(Mandatory = $true)][object]$Release)
    $service = [int64]$Release.service_state_timeout_ms
    $database = [int64]$Release.database_tool_timeout_ms
    $postgres = [int64]$Release.postgres_ready_timeout_ms
    $command = [int64]$script:TicketboxPostgresqlDatabaseCommandTimeoutMs
    $catalog = [int64]$script:TicketboxPostgresqlDatabaseCatalogTimeoutMs
    $fence = [int64]$script:TicketboxDatabaseGenerationWriterFenceTimeoutMs
    $program = [int64]$script:TicketboxDatabaseGenerationProgramTimeoutMs
    $recovery = [int64]$script:TicketboxDatabaseGenerationRecoveryTimeoutMs
    foreach ($value in @(
        $service, $database, $postgres, $command, $catalog, $fence,
        $program, $recovery
    )) {
        if ($value -lt 1) {
            throw "database generation budget dependency is unavailable."
        }
    }

    # Restored SourceBinding: catalog identity, live Dataset Authority, fence.
    $sourceBinding = $catalog + $command + $fence

    # Target authorization before its isolated recovery proof.
    $targetPrelude =
        $catalog +                         # live SourceBinding catalog
        $command + $command +             # migrator window + credential
        $program +                         # frozen Alembic program
        $command + $command +             # ACL apply + verification
        $fence +                           # post-migration writer fence
        $command + $command                # role + ACL evidence

    # Recovery performs dump and archive inspection, binds an isolated DB,
    # restores it, verifies both copies, then deletes and re-observes the copy.
    $recoveryArchive = $recovery + $recovery
    $recoveryBinding =
        $catalog + $command + $command + $catalog + $command + $catalog
    $recoveryRestore =
        $command + $command +              # revision table + revision value
        $command + $command +              # public owner read + optional repair
        $recovery
    $recoveryVerification = $recovery + $recovery
    $recoveryCleanup = $catalog + $command + $command + $catalog
    $targetRecovery =
        $recoveryArchive + $recoveryBinding + $recoveryRestore +
        $recoveryVerification + $recoveryCleanup
    $databaseBinding = $command + $command # live identity + publication
    $targetAuthorization = $targetPrelude + $targetRecovery + $databaseBinding

    # Prepare-runtime has two mutually exclusive longest branches. Both spell
    # out their real DB calls; max selects the legal branch, not a multiplier.
    $projectionActive =
        $command +                         # migrator state
        $command +                         # runtime admission
        $command + $command +              # runtime + backup credential probes
        $command +                         # active role policy
        $command +                         # runtime ACL
        $command +                         # migrator retirement
        $command +                         # retirement verification
        $command                           # retired role policy
    $projectionPending =
        $command +                         # migrator state
        $command + $command +              # pending retirement + verification
        $command +                         # runtime admission
        $command + $command +              # runtime + backup credential probes
        $command +                         # runtime ACL
        $command +                         # final retirement verification
        $command                           # retired role policy
    $projectionPrepare = [Math]::Max($projectionActive, $projectionPending)
    $bootstrapTransition =
        $command + $command +              # runtime + maintenance probes
        $projectionPrepare +
        $service +                         # stop formal service
        $database +                        # single-user retirement
        $service + $postgres +             # retire helper + restart PG
        $command                           # runtime semantic reread

    # Publication validates marker and PGDATA directly, then through the
    # persisted runtime descriptor.
    $runtimeProjectionPublication =
        $command + $database + $database + $command

    # After runtime credentials exist, two pre-publication observations and
    # four later durable actions re-observe marker + PGDATA + projection.
    $ownerObservation =
        $command + $command +
        ($command + $database + $command) +
        ($command + $database + $command) +
        ($command + $database + $command) +
        ($command + $database + $command)

    # A process resumed inside single-user transition restores the formal
    # service and proves retirement before normal reducer execution.
    $serviceTransitionRecovery = $service + $postgres + $command

    $components = [ordered]@{
        service_transition_recovery_ms = $serviceTransitionRecovery
        restored_source_binding_ms = $sourceBinding
        target_authorization_ms = $targetAuthorization
        bootstrap_transition_ms = $bootstrapTransition
        runtime_projection_publication_ms = $runtimeProjectionPublication
        reducer_observation_ms = $ownerObservation
    }
    $total = [int64]0
    foreach ($value in $components.Values) { $total += [int64]$value }
    return [pscustomobject][ordered]@{
        Schema = "ticketbox-installed-database-generation-budget-v1"
        Components = $components
        TotalMilliseconds = $total
    }
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
    $primary = $null
    $cleanup = @()
    $completed = $null
    try {
        while ($true) {
            $credentials = $null
            $runtimeCredentials = $null
            $maintenanceAuthority = $null
            $httpBootstrapSecret = ""
            $iterationPrimary = $null
            $iterationCleanup = @()
            try {
                Assert-TicketboxLifecycleOperationLease $LifecycleLock
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
                $credentialsPath = Get-TicketboxDatabaseGenerationArtifactPath `
                    $stateRoot "credentials" $operationId
                $runtimeCredentialsPath = Get-TicketboxDatabaseGenerationArtifactPath `
                    $stateRoot "runtime-credentials" $operationId
                $credentialsKind =
                    Get-TicketboxPathEntryKindNoFollow $credentialsPath
                $runtimeCredentialsKind =
                    Get-TicketboxPathEntryKindNoFollow $runtimeCredentialsPath
                if (
                    $credentialsKind -cnotin @("File", "Missing") -or
                    $runtimeCredentialsKind -cnotin @("File", "Missing")
                ) {
                    throw "database generation credential artifact 不是可信普通文件。"
                }
                $credentialsPresent = $credentialsKind -ceq "File"
                $runtimeCredentialsPresent =
                    $runtimeCredentialsKind -ceq "File"
                $hostAuthority = $null
                $bootstrapRetirementState = "not_applicable"
                $runtimeProjection = $null
                if (
                    $null -eq $serviceTransition -and
                    $null -ne $candidate -and
                    $runtimeCredentialsPresent
                ) {
                    $hostAuthority =
                        Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                            $HostContract
                    $bootstrapRetirementState =
                        Read-TicketboxDatabaseGenerationBootstrapRetirementState `
                            $stateRoot $intent $candidate $hostAuthority
                    if ($bootstrapRetirementState -ceq "retired") {
                        $runtimeProjection =
                            Read-TicketboxDatabaseGenerationRuntimeProjection `
                                $intent $candidate $hostAuthority `
                                $ProjectionContract $LifecycleLock -AllowAbsent
                    }
                }
                $transientAuthorityPresent =
                    (Get-TicketboxPathEntryKindNoFollow `
                        $BootstrapRecoveryPath) -cne "Missing" -or
                    $credentialsPresent -or $null -ne $serviceTransition
                $observation = [pscustomobject][ordered]@{
                    bootstrap_retirement_state = $bootstrapRetirementState
                    candidate_present = $null -ne $candidate
                    credentials_present = $credentialsPresent
                    current_present = $null -ne $currentForOperation
                    runtime_credentials_present = $runtimeCredentialsPresent
                    runtime_projection_present = $null -ne $runtimeProjection
                    service_transition_present = $null -ne $serviceTransition
                    source_binding_present = $null -ne $source
                    target_authorization_present = $null -ne $target
                    terminal_state_present = $null -ne $terminal
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
                    $credentials = Read-TicketboxDatabaseGenerationCredentials `
                        -StateRoot $stateRoot -Intent $intent
                    $hostAuthority =
                        Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                            $HostContract
                    $maintenanceAuthority =
                        Open-TicketboxDatabaseGenerationMaintenanceAuthority `
                            $intent $hostAuthority $BootstrapRecoveryPath `
                            $bootstrapAppData $bootstrapSecretByteCount `
                            $LifecycleLock
                    $evidence = Invoke-TicketboxDatabaseGenerationSourceBinding `
                        $stateRoot $intent $credentials $HostContract `
                        $maintenanceAuthority $LifecycleLock
                    [void](New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "source-binding" $evidence `
                        $LifecycleLock)
                }
                "authorize_target" {
                    $credentials = Read-TicketboxDatabaseGenerationCredentials `
                        -StateRoot $stateRoot -Intent $intent
                    $hostAuthority =
                        Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                            $HostContract
                    $maintenanceAuthority =
                        Open-TicketboxDatabaseGenerationMaintenanceAuthority `
                            $intent $hostAuthority $BootstrapRecoveryPath `
                            $bootstrapAppData $bootstrapSecretByteCount `
                            $LifecycleLock
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
                    $credentials = Read-TicketboxDatabaseGenerationCredentials `
                        -StateRoot $stateRoot -Intent $intent
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
                    }
                    finally {
                        if ($null -ne $bootstrapRecoveryState) {
                            $bootstrapRecoveryState.SuperuserPassword = ""
                            $bootstrapRecoveryState.HttpBootstrapSecret = ""
                        }
                    }
                    $runtimeCredentials = New-TicketboxDatabaseGenerationRuntimeCredentials `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -Candidate $candidate `
                        -Credentials $credentials `
                        -HttpBootstrapSecret $httpBootstrapSecret `
                        -LifecycleLock $LifecycleLock
                }
                "transition_bootstrap_authority" {
                    $runtimeCredentials =
                        Read-TicketboxDatabaseGenerationRuntimeCredentials `
                            $stateRoot $intent $candidate
                    $hostAuthority =
                        Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                            $HostContract
                    $runtimeProbeFailure = $null
                    try {
                        $bootstrapRetired =
                            Test-TicketboxDatabaseGenerationBootstrapRetirement `
                                $intent $candidate $hostAuthority `
                                $runtimeCredentials.RuntimePassword
                    }
                    catch { $runtimeProbeFailure = $_ }
                    if ($null -ne $runtimeProbeFailure) {
                        if (
                            (Get-TicketboxPathEntryKindNoFollow `
                                $BootstrapRecoveryPath) -cne "File"
                        ) {
                            throw $runtimeProbeFailure
                        }
                        $maintenanceAuthority =
                            Open-TicketboxDatabaseGenerationMaintenanceAuthority `
                                $intent $hostAuthority $BootstrapRecoveryPath `
                                $bootstrapAppData $bootstrapSecretByteCount `
                                $LifecycleLock
                        $bootstrapRetired =
                            Test-TicketboxDatabaseGenerationBootstrapRetirementWithMaintenanceAuthority `
                                $intent $candidate $hostAuthority `
                                $maintenanceAuthority $LifecycleLock
                        if ($bootstrapRetired) { throw $runtimeProbeFailure }
                    }
                    if (-not $bootstrapRetired) {
                        if ($null -eq $maintenanceAuthority) {
                            $maintenanceAuthority =
                                Open-TicketboxDatabaseGenerationMaintenanceAuthority `
                                    $intent $hostAuthority $BootstrapRecoveryPath `
                                    $bootstrapAppData $bootstrapSecretByteCount `
                                    $LifecycleLock
                        }
                        [void](Prepare-TicketboxDatabaseGenerationRuntimeProjection `
                            -Intent $intent `
                            -Candidate $candidate `
                            -RuntimeCredentials $runtimeCredentials `
                            -HostAuthority $hostAuthority `
                            -MaintenanceAuthority $maintenanceAuthority `
                            -ProjectionContract $ProjectionContract `
                            -LifecycleLock $LifecycleLock)
                        Close-TicketboxDatabaseGenerationMaintenanceAuthority `
                            $maintenanceAuthority $intent $hostAuthority `
                            $LifecycleLock
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
                }
                "publish_runtime_projection" {
                    $runtimeCredentials =
                        Read-TicketboxDatabaseGenerationRuntimeCredentials `
                            $stateRoot $intent $candidate
                    $hostAuthority =
                        Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                            $HostContract
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
                    $runtimeCredentials =
                        Read-TicketboxDatabaseGenerationRuntimeCredentials `
                            $stateRoot $intent $candidate
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
            }
            catch { $iterationPrimary = $_ }
            finally {
                if ($null -ne $maintenanceAuthority) {
                    try {
                        Close-TicketboxDatabaseGenerationMaintenanceAuthority `
                            $maintenanceAuthority $intent $hostAuthority `
                            $LifecycleLock
                    }
                    catch { $iterationCleanup += $_ }
                }
                if ($null -ne $credentials) {
                    try {
                        Close-TicketboxDatabaseGenerationCredentials $credentials
                    }
                    catch { $iterationCleanup += $_ }
                }
                if ($null -ne $runtimeCredentials) {
                    try {
                        Close-TicketboxDatabaseGenerationRuntimeCredentials `
                            $runtimeCredentials
                    }
                    catch { $iterationCleanup += $_ }
                }
                $httpBootstrapSecret = ""
            }
            Throw-TicketboxOperationFailure `
                $iterationPrimary $iterationCleanup
            if ($null -ne $completed) { break }
        }
    }
    catch { $primary = $_ }
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
