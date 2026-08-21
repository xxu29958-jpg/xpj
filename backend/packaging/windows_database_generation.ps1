#Requires -Version 5.1

$contractPath = Join-Path $PSScriptRoot "windows_database_generation_contract.ps1"
$artifactsPath = Join-Path $PSScriptRoot "windows_database_generation_artifacts.ps1"
$commitVerifierPath = Join-Path $PSScriptRoot "windows_database_generation_commit_verifier.ps1"
$policyPath = Join-Path $PSScriptRoot "windows_database_generation_policy.ps1"
foreach ($dependency in @(
    $contractPath,
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
        "windows_ticketbox_database_roles.ps1",
        "windows_service_contract.ps1",
        "windows_service_identity.ps1",
        "windows_service_lifecycle.ps1",
        "windows_postgresql_single_user.ps1",
        "windows_database_generation_credentials.ps1",
        "windows_database_generation_role_fence.ps1",
        "windows_database_generation_source.ps1",
        "windows_database_generation_program_adapter.ps1",
        "windows_database_generation_program_execution.ps1",
        "windows_database_generation_recovery_evidence.ps1",
        "windows_database_generation_target_recovery.ps1",
        "windows_database_generation_database_binding.ps1",
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
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
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
    Repair-TicketboxDatabaseGenerationServiceTransition `
        -StateRoot $stateRoot `
        -Intent $intent `
        -HostContract $HostContract `
        -LifecycleLock $LifecycleLock
    $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority $HostContract
    $publishedCurrent = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
    if (
        $null -ne $publishedCurrent -and
        [string]$publishedCurrent.Payload.operation_id -ceq $operationId
    ) {
        Assert-TicketboxDatabaseGenerationCommitReadyArtifact `
            -ExpectedOperationId $operationId `
            -ExpectedCurrentSha256 ([string]$publishedCurrent.PayloadSha256) | Out-Null
        $publishedCandidate = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "candidate"
        $publishedRuntimeCredentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
            -StateRoot $stateRoot `
            -Intent $intent `
            -Candidate $publishedCandidate
        $publishedPrimary = $null
        $publishedCleanup = @()
        $publishedResult = $null
        try {
            if ((Get-TicketboxPathEntryKindNoFollow $BootstrapRecoveryPath) -cne "Missing") {
                throw "Generation CURRENT 已发布但 bootstrap recovery artifact 仍存在。"
            }
            $publishedProjection = Read-TicketboxDatabaseGenerationRuntimeProjection `
                $intent $publishedCandidate $hostAuthority $ProjectionContract $LifecycleLock
            $publishedResult = New-TicketboxInstalledDatabaseGenerationResult `
                $publishedCurrent $publishedProjection
        }
        catch { $publishedPrimary = $_ }
        finally {
            try {
                Close-TicketboxDatabaseGenerationRuntimeCredentials `
                    $publishedRuntimeCredentials
            }
            catch { $publishedCleanup += $_ }
        }
        Throw-TicketboxDatabaseGenerationOperationFailure `
            $publishedPrimary $publishedCleanup
        return $publishedResult
    }
    if (
        $null -ne $publishedCurrent -and
        (
            [string]::IsNullOrEmpty(
                [string]$intent.Payload.expected_predecessor_sha256
            ) -or
            [string]$publishedCurrent.PayloadSha256 -cne
                [string]$intent.Payload.expected_predecessor_sha256
        )
    ) {
        throw "database generation predecessor CURRENT 与 durable intent 漂移。"
    }
    $resumeCandidate = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "candidate" -AllowAbsent
    $bootstrapRetired = $false
    $bootstrapRetirementProbeFailure = $null
    if ($null -ne $resumeCandidate) {
        $resumeRuntimeCredentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
            -StateRoot $stateRoot `
            -Intent $intent `
            -Candidate $resumeCandidate `
            -AllowAbsent
        if ($null -ne $resumeRuntimeCredentials) {
            $resumeCleanup = @()
            try {
                $bootstrapRetired = Test-TicketboxDatabaseGenerationBootstrapRetirement `
                    $intent $resumeCandidate $hostAuthority `
                    $resumeRuntimeCredentials.RuntimePassword
            }
            catch { $bootstrapRetirementProbeFailure = $_ }
            finally {
                try {
                    Close-TicketboxDatabaseGenerationRuntimeCredentials `
                        $resumeRuntimeCredentials
                }
                catch { $resumeCleanup += $_ }
            }
            if ($resumeCleanup.Count -gt 0) {
                Throw-TicketboxDatabaseGenerationOperationFailure `
                    $bootstrapRetirementProbeFailure $resumeCleanup
            }
        }
    }
    $bootstrapRecoveryState = $null
    $httpBootstrapSecret = ""
    $maintenanceAuthority = $null
    if (-not $bootstrapRetired) {
        if (
            (Get-TicketboxPathEntryKindNoFollow $BootstrapRecoveryPath) -ceq "Missing" -and
            $null -ne $bootstrapRetirementProbeFailure
        ) {
            throw $bootstrapRetirementProbeFailure
        }
        try {
            $bootstrapRecoveryState = Read-PostgresBootstrapRecoveryState `
                -Path $BootstrapRecoveryPath
            $httpBootstrapSecret = [string]$bootstrapRecoveryState.HttpBootstrapSecret
            if ($httpBootstrapSecret -cnotmatch '^[A-Za-z0-9_-]{32,128}$') {
                throw "HTTP bootstrap secret 不是受控 secret。"
            }
            $maintenanceAuthority = New-TicketboxDatabaseGenerationMaintenanceAuthority `
                -Intent $intent `
                -SuperuserPassword ([string]$bootstrapRecoveryState.SuperuserPassword) `
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
            $credentials = Read-TicketboxDatabaseGenerationCredentials `
                -StateRoot $stateRoot -Intent $intent -AllowAbsent
            $source = Read-TicketboxDatabaseGenerationOperationArtifact `
                $stateRoot $operationId "source-binding" -AllowAbsent
            $target = Read-TicketboxDatabaseGenerationOperationArtifact `
                $stateRoot $operationId "target-authorization" -AllowAbsent
            $candidate = Read-TicketboxDatabaseGenerationOperationArtifact `
                $stateRoot $operationId "candidate" -AllowAbsent
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
            $next = Resolve-TicketboxDatabaseGenerationNextAction `
                $credentials $source $target $candidate $currentForOperation
            switch ($next) {
                "ensure_credentials" {
                    $createdCredentials = New-TicketboxDatabaseGenerationCredentials `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -LifecycleLock $LifecycleLock
                    Close-TicketboxDatabaseGenerationCredentials $createdCredentials
                }
                "bind_source" {
                    $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                        $HostContract
                    if ([string]::IsNullOrEmpty(
                        [string]$intent.Payload.source_request_sha256
                    )) {
                        $evidence = Invoke-TicketboxDatabaseGenerationEmptySource `
                            -StateRoot $stateRoot `
                            -Intent $intent `
                            -Credentials $credentials `
                            -HostAuthority $hostAuthority `
                            -MaintenanceAuthority $maintenanceAuthority `
                            -LifecycleLock $LifecycleLock
                    }
                    else {
                        $restoredSource = `
                            Read-TicketboxDatabaseGenerationOperationArtifact `
                                $stateRoot $operationId "restored-source"
                        $evidence = Invoke-TicketboxDatabaseGenerationRestoredSource `
                            -Intent $intent `
                            -SourceEvidence $restoredSource `
                            -HostAuthority $hostAuthority `
                            -MaintenanceAuthority $maintenanceAuthority `
                            -LifecycleLock $LifecycleLock
                    }
                    [void](New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "source-binding" $evidence `
                        $LifecycleLock)
                }
                "authorize_target" {
                    $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                        $HostContract
                    [void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
                        $maintenanceAuthority $intent $hostAuthority $LifecycleLock)
                    $superuserPassword = $maintenanceAuthority.Secret
                    $emptySource = (
                        [string]$source.Payload.source_kind -ceq "empty" -and
                        [string]$source.Payload.source_revision -ceq "base" -and
                        [string]::IsNullOrEmpty(
                            [string]$intent.Payload.source_request_sha256
                        )
                    )
                    $currentGenerationSource = (
                        [string]$source.Payload.source_kind -ceq "current_generation" -and
                        [string]$source.Payload.source_revision -ceq
                            [string]$intent.Payload.target_revision -and
                        -not [string]::IsNullOrEmpty(
                            [string]$intent.Payload.source_request_sha256
                        )
                    )
                    if (
                        -not ($emptySource -or $currentGenerationSource) -or
                        [string]$source.Payload.intent_sha256 -cne
                            [string]$intent.PayloadSha256
                    ) {
                        throw "target authority 只接受已规范化的 exact SourceBinding。"
                    }
                    $liveSource = Get-TicketboxPostgresqlDatabaseCatalogObservation `
                        -Authority $hostAuthority `
                        -SuperuserPassword $superuserPassword `
                        -TargetDatabase $($databasePolicy.DatabaseName)
                    if (
                        -not [bool]$liveSource.Exists -or
                        [string]$liveSource.ClusterSystemIdentifier -cne
                            [string]$source.Payload.cluster_system_identifier -or
                        [uint32]$liveSource.DatabaseOid -ne [uint32]$source.Payload.database_oid
                    ) {
                        throw "target authority 在 mutation 前发现 SourceBinding identity 漂移。"
                    }
                    Renew-TicketboxDatabaseGenerationMigratorWindow `
                        $hostAuthority $superuserPassword $credentials
                    $plan = [pscustomobject][ordered]@{
                        generation_operation_id = $operationId
                        source_revision = [string]$source.Payload.source_revision
                        target_revision = [string]$intent.Payload.target_revision
                        generation_program_sha256 = [string]$intent.Payload.generation_program_sha256
                        upgrade_required = (
                            [string]$source.Payload.source_revision -cne
                                [string]$intent.Payload.target_revision
                        )
                    }
                    $result = Invoke-TicketboxPackagedManagedSchemaUpgrade `
                        -HostAuthority $hostAuthority `
                        -MigratorPassword $credentials.MigratorPassword `
                        -Plan $plan `
                        -MaintenanceHelperPath ([string]$ReleaseIdentity.MaintenanceHelperPath) `
                        -MaintenanceHelperEvidence (
                            Get-TicketboxDatabaseMaintenanceHelperEvidence $ReleaseIdentity
                        ) `
                        -ExpectedMaintenanceHelperPath ([string]$ReleaseIdentity.MaintenanceHelperPath) `
                        -ProgramPath ([string]$ReleaseIdentity.DatabaseGenerationProgramPath) `
                        -ProgramEvidence (
                            Get-TicketboxDatabaseGenerationProgramEvidence $ReleaseIdentity
                        )
                    Set-TicketboxDatabaseRuntimeAcl `
                        -Authority $hostAuthority `
                        -SuperuserPassword $superuserPassword `
                        -PreserveRuntimeFence
                    $fence = Get-TicketboxDatabaseGenerationFrozenFence `
                        $hostAuthority $superuserPassword
                    $roleSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
                        Get-TicketboxDatabaseRoleAuthorityEvidence `
                            $hostAuthority $superuserPassword
                    )
                    $aclSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
                        Get-TicketboxDatabaseRuntimeAclEvidence `
                            $hostAuthority $superuserPassword
                    )
                    $recovery = Invoke-TicketboxDatabaseGenerationTargetRecovery `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -SourceBinding $source `
                        -Credentials $credentials `
                        -ReleaseIdentity $ReleaseIdentity `
                        -LifecycleLock $LifecycleLock `
                        -HostContract $HostContract `
                        -HostAuthority $hostAuthority `
                        -SuperuserPassword $superuserPassword
                    $executionAuthority = New-TicketboxDatabaseGenerationExecutionAuthority `
                        $intent $source $result
                    $executionAuthoritySha256 = Get-TicketboxDatabaseGenerationTextSha256 (
                        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $executionAuthority
                    )
                    $writerFenceSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
                        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
                    )
                    $databaseBindingSha256 = Set-TicketboxDatabaseGenerationDatabaseBinding `
                        -Intent $intent `
                        -SourceBinding $source `
                        -HostAuthority $hostAuthority `
                        -SuperuserPassword $superuserPassword `
                        -ExecutionAuthoritySha256 $executionAuthoritySha256 `
                        -RoleAuthoritySha256 $roleSha256 `
                        -RuntimeAclSha256 $aclSha256 `
                        -WriterFenceSha256 $writerFenceSha256 `
                        -TargetRecoveryEvidenceSha256 ([string]$recovery.PayloadSha256) `
                        -LifecycleLock $LifecycleLock
                    $evidence = [ordered]@{
                        schema = "ticketbox-database-generation-target-authorization-v1"
                        operation_id = $operationId
                        intent_sha256 = [string]$intent.PayloadSha256
                        source_binding_sha256 = [string]$source.PayloadSha256
                        target_revision = [string]$intent.Payload.target_revision
                        execution_authority_sha256 = $executionAuthoritySha256
                        role_authority_sha256 = $roleSha256
                        runtime_acl_sha256 = $aclSha256
                        post_migration_writer_fence_sha256 = $writerFenceSha256
                        target_recovery_evidence_sha256 = [string]$recovery.PayloadSha256
                        database_binding_sha256 = $databaseBindingSha256
                    }
                    [void](New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "target-authorization" $evidence `
                        $LifecycleLock)
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
                "finalize_current" {
                    $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
                        $HostContract
                    $runtimeCredentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -Candidate $candidate `
                        -AllowAbsent
                    if ($null -eq $runtimeCredentials) {
                        if ($null -eq $credentials) {
                            throw "candidate 已封存但 durable runtime credentials 缺失。"
                        }
                        $runtimeCredentials = New-TicketboxDatabaseGenerationRuntimeCredentials `
                            -StateRoot $stateRoot `
                            -Intent $intent `
                            -Candidate $candidate `
                            -Credentials $credentials `
                            -HttpBootstrapSecret $httpBootstrapSecret `
                            -LifecycleLock $LifecycleLock
                    }
                    $retired = $false
                    $retirementProbeFailure = $null
                    try {
                        $retired = Test-TicketboxDatabaseGenerationBootstrapRetirement `
                            $intent $candidate $hostAuthority $runtimeCredentials.RuntimePassword
                    }
                    catch { $retirementProbeFailure = $_ }
                    if (-not $retired) {
                        if ($null -eq $maintenanceAuthority) {
                            if ($null -ne $retirementProbeFailure) {
                                throw $retirementProbeFailure
                            }
                            throw "bootstrap authority 未退役且 durable bootstrap credential 缺失。"
                        }
                        [void](Prepare-TicketboxDatabaseGenerationRuntimeProjection `
                            -Intent $intent `
                            -Candidate $candidate `
                            -RuntimeCredentials $runtimeCredentials `
                            -HostAuthority $hostAuthority `
                            -MaintenanceAuthority $maintenanceAuthority `
                            -ProjectionContract $ProjectionContract `
                            -LifecycleLock $LifecycleLock)
                        if (-not (Test-TicketboxDatabaseGenerationBootstrapRetirement `
                            $intent $candidate $hostAuthority $runtimeCredentials.RuntimePassword)) {
                            Close-TicketboxDatabaseGenerationMaintenanceAuthority `
                                $maintenanceAuthority $intent $hostAuthority $LifecycleLock
                            $maintenanceAuthority = $null
                            $hostAuthority = Retire-TicketboxDatabaseGenerationBootstrapAuthority `
                                -StateRoot $stateRoot `
                                -Intent $intent `
                                -Candidate $candidate `
                                -HostContract $HostContract `
                                -HostAuthority $hostAuthority `
                                -RuntimePassword $runtimeCredentials.RuntimePassword `
                                -LifecycleLock $LifecycleLock
                        }
                    }
                    if (-not (Test-TicketboxDatabaseGenerationBootstrapRetirement `
                        $intent $candidate $hostAuthority $runtimeCredentials.RuntimePassword)) {
                        throw "database generation bootstrap authority retirement 未通过 runtime 复读。"
                    }
                    [void](Publish-TicketboxDatabaseGenerationRuntimeProjection `
                        $intent $candidate $runtimeCredentials $hostAuthority `
                        $ProjectionContract $LifecycleLock)
                    Remove-PostgresBootstrapRecoveryState -Path $BootstrapRecoveryPath
                    Remove-TicketboxDatabaseGenerationCredentials `
                        -StateRoot $stateRoot -Intent $intent -LifecycleLock $LifecycleLock
                    $credentialsPath = Get-TicketboxDatabaseGenerationArtifactPath `
                        $stateRoot "credentials" $operationId
                    $transitionPath = Get-TicketboxDatabaseGenerationServiceTransitionPath $stateRoot
                    if (
                        (Get-TicketboxPathEntryKindNoFollow $BootstrapRecoveryPath) -cne "Missing" -or
                        (Get-TicketboxPathEntryKindNoFollow $credentialsPath) -cne "Missing" -or
                        (Get-TicketboxPathEntryKindNoFollow $transitionPath) -cne "Missing"
                    ) {
                        throw "terminal publication 前 bootstrap/transient credential 未清理。"
                    }
                    $projectionEvidence = Read-TicketboxDatabaseGenerationRuntimeProjection `
                        $intent $candidate $hostAuthority $ProjectionContract $LifecycleLock
                    $terminalPayload = [ordered]@{
                        schema = "ticketbox-database-generation-terminal-state-v1"
                        operation_id = $operationId
                        intent_sha256 = [string]$intent.PayloadSha256
                        candidate_sha256 = [string]$candidate.PayloadSha256
                        runtime_credentials_sha256 =
                            [string]$runtimeCredentials.Artifact.PayloadSha256
                        bootstrap_retirement_sha256 =
                            Get-TicketboxDatabaseGenerationTextSha256 (
                                Get-TicketboxDatabaseGenerationBootstrapRetirementJson `
                                    $intent $candidate
                            )
                        runtime_projection_sha256 = [string]$projectionEvidence.PayloadSha256
                        host_contract_sha256 = [string]$intent.Payload.host_contract_sha256
                        projection_contract_sha256 = $projectionContractSha256
                        transient_credentials_state = "absent"
                        bootstrap_recovery_state = "absent"
                        maintenance_service_transition_state = "absent"
                    }
                    $terminal = New-TicketboxDatabaseGenerationChainedArtifact `
                        $stateRoot $operationId "terminal-state" $terminalPayload $LifecycleLock
                    $current = Publish-TicketboxDatabaseGenerationCurrent `
                        $intent $candidate $terminal $LifecycleLock
                    Assert-TicketboxDatabaseGenerationCommitReadyArtifact `
                        -ExpectedOperationId $operationId `
                        -ExpectedCurrentSha256 ([string]$current.PayloadSha256) | Out-Null
                    $projection = Read-TicketboxDatabaseGenerationRuntimeProjection `
                        $intent $candidate $hostAuthority $ProjectionContract $LifecycleLock
                    $completed = New-TicketboxInstalledDatabaseGenerationResult $current $projection
                }
                "read_current" {
                    Assert-TicketboxDatabaseGenerationCommitReadyArtifact `
                        -ExpectedOperationId $operationId `
                        -ExpectedCurrentSha256 ([string]$current.PayloadSha256) | Out-Null
                    $runtimeCredentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
                        -StateRoot $stateRoot `
                        -Intent $intent `
                        -Candidate $candidate
                    $projection = Read-TicketboxDatabaseGenerationRuntimeProjection `
                        $intent $candidate $hostAuthority $ProjectionContract $LifecycleLock
                    $completed = New-TicketboxInstalledDatabaseGenerationResult $current $projection
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
    Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
    return $completed
}
