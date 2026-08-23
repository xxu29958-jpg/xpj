# Read-only validation of immutable database-generation evidence chains.

#Requires -Version 5.1

$script:TicketboxDatabaseGenerationRestorePrefix = "ticketbox_generation_restore_"

function Assert-TicketboxDatabaseGenerationSourceBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Binding,
        [Parameter(Mandatory = $true)][object]$Intent
    )
    $payload = $Binding.Payload
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload `
        -ExpectedNames @(
            "schema", "operation_id", "intent_sha256",
            "source_evidence_sha256", "source_kind", "source_revision",
            "cluster_system_identifier", "database_oid", "writer_fence_sha256"
        ) `
        -Label "database generation SourceBinding"
    foreach ($digest in @(
        [string]$Binding.PayloadSha256,
        [string]$payload.intent_sha256,
        [string]$payload.source_evidence_sha256,
        [string]$payload.writer_fence_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "database generation SourceBinding"
    }
    $operationId = ([guid][string]$payload.operation_id).ToString("D")
    $kind = [string]$payload.source_kind
    $empty = (
        $kind -ceq "empty" -and
        [string]$payload.source_revision -ceq "base" -and
        [string]::IsNullOrEmpty([string]$Intent.Payload.source_request_sha256)
    )
    $current = (
        $kind -ceq "current_generation" -and
        [string]$payload.source_revision -ceq [string]$Intent.Payload.target_revision -and
        -not [string]::IsNullOrEmpty([string]$Intent.Payload.source_request_sha256)
    )
    if (
        [string]$payload.schema -cne "ticketbox-database-generation-source-binding-v1" -or
        $operationId -cne [string]$payload.operation_id -or
        $operationId -cne [string]$Intent.Payload.operation_id -or
        [string]$payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]::IsNullOrWhiteSpace([string]$payload.cluster_system_identifier) -or
        [uint32]$payload.database_oid -lt 1 -or
        -not ($empty -or $current)
    ) {
        throw "database generation SourceBinding is not closed or intent-bound."
    }
    return $Binding
}

function Assert-TicketboxDatabaseGenerationSourceBindingChain {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Binding,
        [Parameter(Mandatory = $true)][object]$Intent
    )
    $bindingArtifact = Assert-TicketboxDatabaseGenerationSourceBinding `
        -Binding $Binding `
        -Intent $Intent
    $payload = $bindingArtifact.Payload
    $operationId = [string]$payload.operation_id
    $artifactKind = if ([string]$payload.source_kind -ceq "empty") {
        "source-create-attempt"
    }
    else { "restored-source" }
    $evidence = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId $artifactKind
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$evidence.PayloadSha256) `
        "database generation SourceBinding evidence"
    if ([string]$evidence.PayloadSha256 -cne [string]$payload.source_evidence_sha256) {
        throw "database generation SourceBinding references foreign evidence."
    }
    if ($artifactKind -ceq "source-create-attempt") {
        Assert-TicketboxDatabaseGenerationExactProperties `
            -Value $evidence.Payload `
            -ExpectedNames @(
                "schema", "operation_id", "intent_sha256",
                "cluster_system_identifier", "database_name",
                "temporary_database", "observed_target_absent"
            ) `
            -Label "database generation source create-attempt evidence"
        $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
        $expectedTemporaryDatabase = "ticketbox_generation_" + (
            ([guid]$operationId).ToString("N")
        )
        if (
            [string]$evidence.Payload.schema -cne
                "ticketbox-database-generation-source-create-attempt-v1" -or
            [string]$evidence.Payload.operation_id -cne $operationId -or
            [string]$evidence.Payload.intent_sha256 -cne
                [string]$Intent.PayloadSha256 -or
            [string]$evidence.Payload.cluster_system_identifier -cne
                [string]$payload.cluster_system_identifier -or
            [string]$evidence.Payload.database_name -cne
                [string]$databasePolicy.DatabaseName -or
            [string]$evidence.Payload.temporary_database -cne
                $expectedTemporaryDatabase -or
            -not [bool]$evidence.Payload.observed_target_absent
        ) {
            throw "database generation SourceBinding empty evidence drifted."
        }
        return $bindingArtifact
    }
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $evidence.Payload `
        -ExpectedNames @(
            "schema", "operation_id", "intent_sha256",
            "source_request_sha256", "predecessor_current_sha256",
            "backup_manifest_sha256", "backup_id", "dataset_id",
            "restore_epoch", "source_revision",
            "cluster_system_identifier", "database_oid",
            "writer_fence_sha256", "result"
        ) `
        -Label "database generation restored source evidence"
    foreach ($digest in @(
        [string]$evidence.Payload.source_request_sha256,
        [string]$evidence.Payload.predecessor_current_sha256,
        [string]$evidence.Payload.backup_manifest_sha256,
        [string]$evidence.Payload.writer_fence_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "database generation restored source evidence"
    }
    $backupId = ([guid][string]$evidence.Payload.backup_id).ToString("D")
    $datasetId = ([guid][string]$evidence.Payload.dataset_id).ToString("D")
    if (
        [string]$evidence.Payload.schema -cne
            "ticketbox-database-generation-restored-source-v1" -or
        [string]$evidence.Payload.operation_id -cne $operationId -or
        [string]$evidence.Payload.intent_sha256 -cne
            [string]$Intent.PayloadSha256 -or
        [string]$evidence.Payload.source_request_sha256 -cne
            [string]$Intent.Payload.source_request_sha256 -or
        [string]$evidence.Payload.predecessor_current_sha256 -cne
            [string]$Intent.Payload.expected_predecessor_sha256 -or
        [string]$evidence.Payload.source_revision -cne [string]$payload.source_revision -or
        [string]$evidence.Payload.cluster_system_identifier -cne
            [string]$payload.cluster_system_identifier -or
        [uint32]$evidence.Payload.database_oid -ne [uint32]$payload.database_oid -or
        [string]$evidence.Payload.writer_fence_sha256 -cne
            [string]$payload.writer_fence_sha256 -or
        $backupId -cne [string]$evidence.Payload.backup_id -or
        $datasetId -cne [string]$evidence.Payload.dataset_id -or
        [int64]$evidence.Payload.restore_epoch -lt 0 -or
        [string]$evidence.Payload.result -cne "isolated_restore_candidate_ready"
    ) {
        throw "database generation SourceBinding restored evidence drifted."
    }
    return $bindingArtifact
}

function Get-TicketboxDatabaseGenerationRestoreDatabaseName {
    param([Parameter(Mandatory = $true)][string]$AttemptId)
    $attempt = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($AttemptId, "D", [ref]$attempt) -or
        $attempt -eq [Guid]::Empty -or
        $attempt.ToString("D") -cne $AttemptId
    ) {
        throw "database generation restore attempt ID 无效。"
    }
    return $script:TicketboxDatabaseGenerationRestorePrefix + $attempt.ToString("N")
}

function Assert-TicketboxDatabaseGenerationRecoveryChain {
    param(
        [AllowNull()][object]$Intent,
        [AllowNull()][object]$SourceBinding,
        [AllowNull()][object]$Attempt,
        [AllowNull()][object]$Archive,
        [AllowNull()][object]$Binding,
        [AllowNull()][object]$Verification,
        [AllowNull()][object]$Proof
    )
    if ($null -eq $Attempt) { throw "recovery chain 缺少 attempt。" }
    $operationId = ([Guid][string]$Attempt.Payload.operation_id).ToString("D")
    if (
        [string]$Attempt.Payload.restore_database -cne
            (Get-TicketboxDatabaseGenerationRestoreDatabaseName (
                [string]$Attempt.Payload.create_attempt_id
            ))
    ) {
        throw "recovery attempt restore identity 漂移。"
    }
    if ($null -ne $Intent -and (
        [string]$Attempt.Payload.operation_id -cne
            [string]$Intent.Payload.operation_id -or
        [string]$Attempt.Payload.intent_sha256 -cne
            [string]$Intent.PayloadSha256 -or
        [string]$Attempt.Payload.target_revision -cne
            [string]$Intent.Payload.target_revision -or
        [string]$Attempt.Payload.generation_program_sha256 -cne
            [string]$Intent.Payload.generation_program_sha256
    )) { throw "recovery attempt 未绑定 exact intent。" }
    if ($null -ne $SourceBinding -and (
        [string]$Attempt.Payload.source_binding_sha256 -cne
            [string]$SourceBinding.PayloadSha256 -or
        [string]$Attempt.Payload.source_cluster_system_identifier -cne
            [string]$SourceBinding.Payload.cluster_system_identifier -or
        [string]$Attempt.Payload.source_database_oid -cne
            [string]$SourceBinding.Payload.database_oid
    )) { throw "recovery attempt 未绑定 exact source。" }
    if ($null -ne $Archive -and (
        [string]$Archive.Payload.operation_id -cne $operationId -or
        [string]$Archive.Payload.attempt_sha256 -cne
            [string]$Attempt.PayloadSha256
    )) { throw "recovery archive 未绑定 exact attempt。" }
    if ($null -ne $Binding -and (
        [string]$Binding.Payload.operation_id -cne $operationId -or
        [string]$Binding.Payload.attempt_sha256 -cne
            [string]$Attempt.PayloadSha256 -or
        [string]$Binding.Payload.restore_database -cne
            [string]$Attempt.Payload.restore_database
    )) { throw "recovery binding 未绑定 exact attempt。" }
    if ($null -ne $Verification) {
        if ($null -eq $Archive -or $null -eq $Binding) {
            throw "recovery verification 缺少 archive/binding。"
        }
        if (
            [string]$Verification.Payload.operation_id -cne $operationId -or
            [string]$Verification.Payload.attempt_sha256 -cne
                [string]$Attempt.PayloadSha256 -or
            [string]$Verification.Payload.binding_sha256 -cne
                [string]$Binding.PayloadSha256 -or
            [string]$Verification.Payload.archive_sha256 -cne
                [string]$Archive.Payload.archive_sha256 -or
            [string]$Verification.Payload.target_revision -cne
                [string]$Attempt.Payload.target_revision -or
            [string]$Verification.Payload.generation_program_sha256 -cne
                [string]$Attempt.Payload.generation_program_sha256
        ) { throw "recovery verification authority chain 漂移。" }
    }
    if ($null -ne $Proof) {
        if (
            $null -eq $Intent -or $null -eq $SourceBinding -or
            $null -eq $Archive -or $null -eq $Binding -or
            $null -eq $Verification
        ) { throw "recovery proof 缺少完整 authority chain。" }
        if (
            [string]$Proof.Payload.operation_id -cne $operationId -or
            [string]$Proof.Payload.intent_sha256 -cne
                [string]$Intent.PayloadSha256 -or
            [string]$Proof.Payload.source_binding_sha256 -cne
                [string]$SourceBinding.PayloadSha256 -or
            [string]$Proof.Payload.target_revision -cne
                [string]$Intent.Payload.target_revision -or
            [string]$Proof.Payload.generation_program_sha256 -cne
                [string]$Intent.Payload.generation_program_sha256 -or
            [string]$Proof.Payload.attempt_sha256 -cne
                [string]$Attempt.PayloadSha256 -or
            [string]$Proof.Payload.archive_sha256 -cne
                [string]$Archive.Payload.archive_sha256 -or
            [string]$Proof.Payload.verification_sha256 -cne
                [string]$Verification.PayloadSha256 -or
            [string]$Proof.Payload.restore_database_oid -cne
                [string]$Binding.Payload.restore_database_oid
        ) { throw "recovery proof authority chain 漂移。" }
    }
    return $true
}

function Assert-TicketboxDatabaseGenerationRecoveryArchive {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Archive
    )
    $path = Join-Path $StateRoot ([string]$Archive.Payload.archive_file_name)
    if (
        -not (Test-TicketboxPathWithin $path $StateRoot) -or
        (Get-TicketboxPathEntryKindNoFollow $path) -cne "File"
    ) {
        throw "database generation recovery archive 缺失或越界。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    $item = Get-Item -LiteralPath $path -Force
    $sha256 = (Get-TicketboxPortableFileSha256 $path).ToLowerInvariant()
    if (
        [int64]$item.Length -ne [int64]$Archive.Payload.archive_size -or
        $sha256 -cne [string]$Archive.Payload.archive_sha256
    ) {
        throw "database generation recovery archive bytes 漂移。"
    }
    return $path
}
