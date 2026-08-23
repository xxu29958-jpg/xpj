#Requires -Version 5.1

function Invoke-TicketboxDatabaseGenerationSourceBinding {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$MaintenanceAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
        $HostContract
    if ([string]::IsNullOrEmpty([string]$Intent.Payload.source_request_sha256)) {
        return Invoke-TicketboxDatabaseGenerationEmptySource `
            -StateRoot $StateRoot `
            -Intent $Intent `
            -Credentials $Credentials `
            -HostAuthority $hostAuthority `
            -MaintenanceAuthority $MaintenanceAuthority `
            -LifecycleLock $LifecycleLock
    }
    $restoredSource = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot ([string]$Intent.Payload.operation_id) "restored-source"
    return Invoke-TicketboxDatabaseGenerationRestoredSource `
        -Intent $Intent `
        -SourceEvidence $restoredSource `
        -HostAuthority $hostAuthority `
        -MaintenanceAuthority $MaintenanceAuthority `
        -LifecycleLock $LifecycleLock
}

function Invoke-TicketboxDatabaseGenerationRestoredSource {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceEvidence,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$MaintenanceAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    [void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
        $MaintenanceAuthority $Intent $HostAuthority $LifecycleLock)
    Assert-TicketboxDatabaseGenerationExactProperties `
        $SourceEvidence.Payload `
        @(
            "schema", "operation_id", "intent_sha256",
            "source_request_sha256", "predecessor_current_sha256",
            "backup_manifest_sha256", "backup_id", "dataset_id",
            "restore_epoch", "source_revision",
            "cluster_system_identifier", "database_oid",
            "writer_fence_sha256", "result"
        ) `
        "database generation restored source evidence"
    foreach ($digest in @(
        [string]$SourceEvidence.PayloadSha256,
        [string]$SourceEvidence.Payload.source_request_sha256,
        [string]$SourceEvidence.Payload.predecessor_current_sha256,
        [string]$SourceEvidence.Payload.backup_manifest_sha256,
        [string]$SourceEvidence.Payload.writer_fence_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "database generation restored source"
    }
    $backupId = ([guid][string]$SourceEvidence.Payload.backup_id).ToString("D")
    $datasetId = ([guid][string]$SourceEvidence.Payload.dataset_id).ToString("D")
    if (
        [string]$SourceEvidence.Payload.schema -cne
            "ticketbox-database-generation-restored-source-v1" -or
        [string]$SourceEvidence.Payload.operation_id -cne
            [string]$Intent.Payload.operation_id -or
        [string]$SourceEvidence.Payload.intent_sha256 -cne
            [string]$Intent.PayloadSha256 -or
        [string]$SourceEvidence.Payload.source_request_sha256 -cne
            [string]$Intent.Payload.source_request_sha256 -or
        [string]$SourceEvidence.Payload.predecessor_current_sha256 -cne
            [string]$Intent.Payload.expected_predecessor_sha256 -or
        [string]$SourceEvidence.Payload.source_revision -cne
            [string]$Intent.Payload.target_revision -or
        $backupId -cne [string]$SourceEvidence.Payload.backup_id -or
        $datasetId -cne [string]$SourceEvidence.Payload.dataset_id -or
        [int64]$SourceEvidence.Payload.restore_epoch -lt 0 -or
        [string]$SourceEvidence.Payload.result -cne
            "isolated_restore_candidate_ready"
    ) {
        throw "restored source evidence 与 exact generation intent 漂移。"
    }
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $live = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $MaintenanceAuthority.Secret `
        -TargetDatabase ([string]$databasePolicy.DatabaseName)
    $liveIdentity = Get-TicketboxDatabaseGenerationLiveIdentity `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $MaintenanceAuthority.Secret
    if (
        -not [bool]$live.Exists -or
        [string]$live.ClusterSystemIdentifier -cne
            [string]$SourceEvidence.Payload.cluster_system_identifier -or
        [uint32]$live.DatabaseOid -ne [uint32]$SourceEvidence.Payload.database_oid -or
        [string]$liveIdentity.ClusterSystemIdentifier -cne
            [string]$SourceEvidence.Payload.cluster_system_identifier -or
        [uint32]$liveIdentity.DatabaseOid -ne [uint32]$SourceEvidence.Payload.database_oid -or
        [string]$liveIdentity.DatasetId -cne [string]$SourceEvidence.Payload.dataset_id -or
        [int64]$liveIdentity.RestoreEpoch -ne [int64]$SourceEvidence.Payload.restore_epoch -or
        [string]$liveIdentity.SchemaRevision -cne
            [string]$SourceEvidence.Payload.source_revision
    ) {
        throw "restored source live dataset authority 漂移。"
    }
    $fence = Get-TicketboxDatabaseGenerationFrozenFence `
        $HostAuthority $MaintenanceAuthority.Secret
    $fenceSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
    )
    if ($fenceSha256 -cne [string]$SourceEvidence.Payload.writer_fence_sha256) {
        throw "restored source writer fence 漂移。"
    }
    return [ordered]@{
        schema = "ticketbox-database-generation-source-binding-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        source_evidence_sha256 = [string]$SourceEvidence.PayloadSha256
        source_kind = "current_generation"
        source_revision = [string]$SourceEvidence.Payload.source_revision
        cluster_system_identifier = [string]$live.ClusterSystemIdentifier
        database_oid = [uint32]$live.DatabaseOid
        writer_fence_sha256 = $fenceSha256
    }
}
