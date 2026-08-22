#Requires -Version 5.1

function Invoke-TicketboxDatabaseGenerationTargetAuthorization {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceBinding,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$MaintenanceAuthority
    )
    $operationId = [string]$Intent.Payload.operation_id
    $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
        $HostContract
    [void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
        $MaintenanceAuthority $Intent $hostAuthority $LifecycleLock)
    $superuserPassword = $MaintenanceAuthority.Secret
    if ([string]$SourceBinding.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256) {
        throw "target authority 只接受已规范化的 exact SourceBinding。"
    }
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $liveSource = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $hostAuthority `
        -SuperuserPassword $superuserPassword `
        -TargetDatabase $($databasePolicy.DatabaseName)
    if (
        -not [bool]$liveSource.Exists -or
        [string]$liveSource.ClusterSystemIdentifier -cne
            [string]$SourceBinding.Payload.cluster_system_identifier -or
        [uint32]$liveSource.DatabaseOid -ne [uint32]$SourceBinding.Payload.database_oid
    ) {
        throw "target authority 在 mutation 前发现 SourceBinding identity 漂移。"
    }
    Renew-TicketboxDatabaseGenerationMigratorWindow `
        $hostAuthority $superuserPassword $Credentials
    $plan = [pscustomobject][ordered]@{
        generation_operation_id = $operationId
        source_revision = [string]$SourceBinding.Payload.source_revision
        target_revision = [string]$Intent.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        upgrade_required = (
            [string]$SourceBinding.Payload.source_revision -cne
                [string]$Intent.Payload.target_revision
        )
    }
    $result = Invoke-TicketboxPackagedManagedSchemaUpgrade `
        -HostAuthority $hostAuthority `
        -MigratorPassword $Credentials.MigratorPassword `
        -Plan $plan `
        -MaintenanceHelperPath ([string]$ReleaseIdentity.MaintenanceHelperPath) `
        -MaintenanceHelperEvidence (
            Get-TicketboxDatabaseMaintenanceHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMaintenanceHelperPath ([string]$ReleaseIdentity.MaintenanceHelperPath) `
        -ProgramPath ([string]$ReleaseIdentity.DatabaseGenerationProgramPath) `
        -ProgramEvidence (Get-TicketboxDatabaseGenerationProgramEvidence $ReleaseIdentity)
    Set-TicketboxDatabaseRuntimeAcl `
        -Authority $hostAuthority `
        -SuperuserPassword $superuserPassword `
        -PreserveRuntimeFence
    $fence = Get-TicketboxDatabaseGenerationFrozenFence `
        $hostAuthority $superuserPassword
    $roleSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        Get-TicketboxDatabaseRoleAuthorityEvidence $hostAuthority $superuserPassword
    )
    $aclSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        Get-TicketboxDatabaseRuntimeAclEvidence $hostAuthority $superuserPassword
    )
    $recovery = Invoke-TicketboxDatabaseGenerationTargetRecovery `
        -StateRoot $StateRoot `
        -Intent $Intent `
        -SourceBinding $SourceBinding `
        -Credentials $Credentials `
        -ReleaseIdentity $ReleaseIdentity `
        -LifecycleLock $LifecycleLock `
        -HostContract $HostContract `
        -HostAuthority $hostAuthority `
        -SuperuserPassword $superuserPassword
    $executionAuthority = New-TicketboxDatabaseGenerationExecutionAuthority `
        $Intent $SourceBinding $result
    $executionAuthoritySha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $executionAuthority
    )
    $writerFenceSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
    )
    $databaseBindingSha256 = Set-TicketboxDatabaseGenerationDatabaseBinding `
        -Intent $Intent `
        -SourceBinding $SourceBinding `
        -HostAuthority $hostAuthority `
        -SuperuserPassword $superuserPassword `
        -ExecutionAuthoritySha256 $executionAuthoritySha256 `
        -RoleAuthoritySha256 $roleSha256 `
        -RuntimeAclSha256 $aclSha256 `
        -WriterFenceSha256 $writerFenceSha256 `
        -TargetRecoveryEvidenceSha256 ([string]$recovery.PayloadSha256) `
        -LifecycleLock $LifecycleLock
    return [ordered]@{
        schema = "ticketbox-database-generation-target-authorization-v1"
        operation_id = $operationId
        intent_sha256 = [string]$Intent.PayloadSha256
        source_binding_sha256 = [string]$SourceBinding.PayloadSha256
        target_revision = [string]$Intent.Payload.target_revision
        execution_authority_sha256 = $executionAuthoritySha256
        role_authority_sha256 = $roleSha256
        runtime_acl_sha256 = $aclSha256
        post_migration_writer_fence_sha256 = $writerFenceSha256
        target_recovery_evidence_sha256 = [string]$recovery.PayloadSha256
        database_binding_sha256 = $databaseBindingSha256
    }
}
