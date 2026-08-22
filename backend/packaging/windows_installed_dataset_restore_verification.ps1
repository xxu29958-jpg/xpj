#Requires -Version 5.1

# Immutable candidate and post-CURRENT restore verification evidence.

function Assert-TicketboxInstalledDatasetCandidateVerification {
    param(
        [Parameter(Mandatory = $true)][object]$Verification,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$RestoredSource,
        [Parameter(Mandatory = $true)][object]$Inspection
    )
    $payload = $Verification.Payload
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload `
        -ExpectedNames @(
            "schema", "operation_id", "intent_sha256",
            "source_request_sha256", "restored_source_sha256",
            "backup_manifest_sha256", "backup_id", "dataset_id",
            "restore_epoch", "target_revision", "original_count",
            "generation_program_sha256", "resource_shape_sha256",
            "money_facts_sha256", "result"
        ) `
        -Label "installed dataset candidate verification"
    foreach ($field in @(
        "generation_program_sha256", "resource_shape_sha256", "money_facts_sha256"
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            ([string]$payload.$field) "installed dataset candidate $field"
    }
    $expectedEpoch = [Math]::Max(
        [int64]$Request.Payload.backup_restore_epoch,
        [int64]$Request.Payload.active_restore_epoch
    ) + 1
    if (
        [string]$Verification.Kind -cne "candidate-verification" -or
        [string]$payload.schema -cne
            "ticketbox-installed-dataset-candidate-verification-v1" -or
        [string]$payload.operation_id -cne [string]$Intent.Payload.operation_id -or
        [string]$payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$payload.source_request_sha256 -cne [string]$Request.PayloadSha256 -or
        [string]$payload.restored_source_sha256 -cne
            [string]$RestoredSource.PayloadSha256 -or
        [string]$payload.backup_manifest_sha256 -cne
            [string]$Request.Payload.backup_manifest_sha256 -or
        [string]$payload.backup_id -cne [string]$Request.Payload.backup_id -or
        [string]$payload.dataset_id -cne [string]$Request.Payload.dataset_id -or
        [int64]$payload.restore_epoch -ne $expectedEpoch -or
        [string]$payload.target_revision -cne [string]$Request.Payload.target_revision -or
        [int64]$payload.original_count -ne [int64]$Inspection.Evidence.original_count -or
        [string]$payload.generation_program_sha256 -cne
            [string]$Intent.Payload.generation_program_sha256 -or
        [string]$payload.result -cne "restored_candidate_verified"
    ) {
        throw "installed dataset candidate verification differs from durable authority."
    }
    return $Verification
}

function New-TicketboxInstalledDatasetCandidateVerification {
    param(
        [Parameter(Mandatory = $true)][object]$IntentContext,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$RestoredSource,
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][object]$VerificationResult,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $intent = $IntentContext.Artifact
    $payload = [ordered]@{
        schema = "ticketbox-installed-dataset-candidate-verification-v1"
        operation_id = [string]$intent.Payload.operation_id
        intent_sha256 = [string]$intent.PayloadSha256
        source_request_sha256 = [string]$Request.PayloadSha256
        restored_source_sha256 = [string]$RestoredSource.PayloadSha256
        backup_manifest_sha256 = [string]$Request.Payload.backup_manifest_sha256
        backup_id = [string]$VerificationResult.backup_id
        dataset_id = [string]$VerificationResult.dataset_id
        restore_epoch = [int64]$VerificationResult.restore_epoch
        target_revision = [string]$VerificationResult.schema_revision
        original_count = [int64]$VerificationResult.original_count
        generation_program_sha256 = [string]$VerificationResult.generation_program_sha256
        resource_shape_sha256 = [string]$VerificationResult.resource_shape_sha256
        money_facts_sha256 = [string]$VerificationResult.money_facts_sha256
        result = "restored_candidate_verified"
    }
    $written = New-TicketboxDatabaseGenerationChainedArtifact `
        -StateRoot $IntentContext.StateRoot `
        -OperationId ([string]$intent.Payload.operation_id) `
        -Kind "candidate-verification" `
        -Payload $payload `
        -LifecycleLock $LifecycleLock
    return Assert-TicketboxInstalledDatasetCandidateVerification `
        $written $intent $Request $RestoredSource $Inspection
}

function Assert-TicketboxInstalledDatasetRuntimeVerification {
    param(
        [Parameter(Mandatory = $true)][object]$Verification,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$Inspection
    )
    $payload = $Verification.Payload
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload `
        -ExpectedNames @(
            "schema", "operation_id", "intent_sha256", "source_request_sha256",
            "current_sha256", "backup_manifest_sha256", "backup_id", "dataset_id",
            "restore_epoch", "original_count", "health_contract", "result"
        ) `
        -Label "installed dataset runtime verification"
    $expectedEpoch = [Math]::Max(
        [int64]$Request.Payload.backup_restore_epoch,
        [int64]$Request.Payload.active_restore_epoch
    ) + 1
    if (
        [string]$Verification.Kind -cne "runtime-verification" -or
        [string]$payload.schema -cne "ticketbox-installed-dataset-runtime-verification-v1" -or
        [string]$payload.operation_id -cne [string]$Intent.Payload.operation_id -or
        [string]$payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$payload.source_request_sha256 -cne [string]$Request.PayloadSha256 -or
        [string]$payload.current_sha256 -cne [string]$Current.PayloadSha256 -or
        [string]$payload.backup_manifest_sha256 -cne
            [string]$Request.Payload.backup_manifest_sha256 -or
        [string]$payload.backup_id -cne [string]$Request.Payload.backup_id -or
        [string]$payload.dataset_id -cne [string]$Request.Payload.dataset_id -or
        [int64]$payload.restore_epoch -ne $expectedEpoch -or
        [int64]$payload.original_count -ne [int64]$Inspection.Evidence.original_count -or
        [string]$payload.health_contract -cne "ticketbox-installation-health-v2" -or
        [string]$payload.result -cne "restored_runtime_verified"
    ) {
        throw "installed dataset runtime verification differs from durable authority."
    }
    return $Verification
}
