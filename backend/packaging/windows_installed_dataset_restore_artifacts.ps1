# Durable request, candidate-verification, activation-verification, and terminal result artifacts.

function Get-TicketboxInstalledDatasetRestoreRequestPath {
    param([Parameter(Mandatory = $true)][string]$StateRoot)
    return Join-Path $StateRoot "dataset-restore-request.json"
}

function Get-TicketboxInstalledDatasetRestoreRequest {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [switch]$AllowAbsent
    )
    $path = Get-TicketboxInstalledDatasetRestoreRequestPath $StateRoot
    $request = Read-TicketboxDatabaseGenerationEnvelope `
        -Path $path `
        -ExpectedKind "dataset-restore-request" `
        -AllowAbsent:$AllowAbsent
    if ($null -eq $request) { return $null }
    return Assert-TicketboxInstalledDatasetRestoreRequest $request
}

function Assert-TicketboxInstalledDatasetRestoreRequest {
    param([Parameter(Mandatory = $true)][object]$Request)
    $payload = $Request.Payload
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload `
        -ExpectedNames @(
            "schema", "restore_attempt_id", "backup_generation",
            "backup_manifest_sha256", "backup_id", "dataset_id",
            "backup_restore_epoch", "target_revision",
            "predecessor_current_sha256", "predecessor_intent_sha256",
            "predecessor_current_payload", "predecessor_intent_payload",
            "release_manifest_sha256",
            "active_dataset_id", "active_restore_epoch", "restart_backend",
            "public_base_url"
        ) `
        -Label "installed dataset restore request"
    foreach ($digest in @(
        [string]$payload.backup_manifest_sha256,
        [string]$payload.predecessor_current_sha256,
        [string]$payload.predecessor_intent_sha256,
        [string]$payload.release_manifest_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "installed dataset restore request"
    }
    $attemptId = ([guid][string]$payload.restore_attempt_id).ToString("D")
    $backupId = ([guid][string]$payload.backup_id).ToString("D")
    $datasetId = ([guid][string]$payload.dataset_id).ToString("D")
    $activeDatasetId = ([guid][string]$payload.active_dataset_id).ToString("D")
    $publicBaseUrl = ConvertTo-TicketboxDatabaseGenerationPublicBaseUrl `
        ([string]$payload.public_base_url)
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload.predecessor_intent_payload `
        -ExpectedNames (Get-TicketboxDatabaseGenerationPayloadProperties "intent") `
        -Label "installed dataset restore predecessor intent"
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload.predecessor_current_payload `
        -ExpectedNames (Get-TicketboxDatabaseGenerationPayloadProperties "current") `
        -Label "installed dataset restore predecessor CURRENT"
    $predecessorIntentSha = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson `
            $payload.predecessor_intent_payload
    )
    $predecessorCurrentSha = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson `
            $payload.predecessor_current_payload
    )
    if (
        [string]$payload.schema -cne
            "ticketbox-installed-dataset-restore-request-v4" -or
        $attemptId -cne [string]$payload.restore_attempt_id -or
        $backupId -cne [string]$payload.backup_id -or
        $datasetId -cne [string]$payload.dataset_id -or
        $activeDatasetId -cne [string]$payload.active_dataset_id -or
        [string]$payload.backup_generation -cne "ticketbox-backup-$backupId" -or
        [int64]$payload.backup_restore_epoch -lt 0 -or
        [int64]$payload.active_restore_epoch -lt 0 -or
        $payload.restart_backend -isnot [bool] -or
        $publicBaseUrl -cne [string]$payload.public_base_url -or
        [string]::IsNullOrWhiteSpace([string]$payload.target_revision) -or
        $predecessorIntentSha -cne [string]$payload.predecessor_intent_sha256 -or
        $predecessorCurrentSha -cne [string]$payload.predecessor_current_sha256 -or
        [string]$payload.predecessor_intent_payload.schema -cne
            "ticketbox-database-generation-intent-v2" -or
        [string]$payload.predecessor_current_payload.schema -cne
            "ticketbox-current-database-generation-v1" -or
        [string]$payload.predecessor_current_payload.operation_id -cne
            [string]$payload.predecessor_intent_payload.operation_id -or
        [string]$payload.predecessor_current_payload.installation_id -cne
            [string]$payload.predecessor_intent_payload.installation_id -or
        [string]$payload.predecessor_current_payload.intent_sha256 -cne
            $predecessorIntentSha -or
        [string]$payload.predecessor_current_payload.committed_revision -cne
            [string]$payload.target_revision
    ) {
        throw "installed dataset restore request is not canonical or self-bound."
    }
    return $Request
}

function Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition {
    param(
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][string]$SuccessorOperationId
    )
    $request = Assert-TicketboxInstalledDatasetRestoreRequest $Request
    $successor = ([guid]$SuccessorOperationId).ToString("D")
    $predecessorSha256 = [string]$request.Payload.predecessor_current_sha256
    if (
        [string]$Intent.Payload.operation_id -cne $successor -or
        [string]$Intent.Payload.source_request_sha256 -cne
            [string]$request.PayloadSha256 -or
        [string]$Intent.Payload.expected_predecessor_sha256 -cne
            $predecessorSha256
    ) {
        throw "dataset restore active intent differs from its durable request."
    }
    if ([string]$Current.PayloadSha256 -ceq $predecessorSha256) {
        return "predecessor"
    }
    if (
        [string]$Current.Payload.operation_id -ceq $successor -and
        [string]$Current.Payload.intent_sha256 -ceq
            [string]$Intent.PayloadSha256 -and
        [string]$Current.Payload.expected_predecessor_sha256 -ceq
            $predecessorSha256
    ) {
        return "successor"
    }
    throw "dataset restore observed a foreign CURRENT authority."
}

function New-TicketboxInstalledDatasetRestorePredecessorCurrentTransition {
    param(
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$RestoreRequest
    )
    $request = Assert-TicketboxInstalledDatasetRestoreRequest $RestoreRequest
    $targetPayload = $request.Payload.predecessor_current_payload
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $targetPayload `
        -ExpectedNames (Get-TicketboxDatabaseGenerationPayloadProperties "current") `
        -Label "dataset restore predecessor CURRENT"
    $targetSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $targetPayload
    )
    if (
        $targetSha256 -cne [string]$request.Payload.predecessor_current_sha256 -or
        [string]$Current.Payload.expected_predecessor_sha256 -cne $targetSha256 -or
        [string]$Current.Payload.operation_id -ceq [string]$targetPayload.operation_id
    ) {
        throw "dataset restore CURRENT rollback is not the exact immediate predecessor."
    }
    return [pscustomobject][ordered]@{
        schema = "ticketbox-database-generation-current-transition-v1"
        mode = "restore_predecessor"
        expected_current_sha256 = [string]$Current.PayloadSha256
        target_payload_sha256 = $targetSha256
        target_payload = $targetPayload
    }
}

function New-TicketboxInstalledDatasetRestoreRequest {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][string]$RestoreAttemptId,
        [Parameter(Mandatory = $true)][string]$ActiveDatasetId,
        [Parameter(Mandatory = $true)][int64]$ActiveRestoreEpoch,
        [Parameter(Mandatory = $true)][bool]$RestartBackend,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$PublicBaseUrl,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $backup = $Inspection.Evidence
    $attemptId = ([guid]$RestoreAttemptId).ToString("D")
    $path = Get-TicketboxInstalledDatasetRestoreRequestPath $Authority.StateRoot
    $existing = Read-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-request" -AllowAbsent
    $immutable = [ordered]@{
        restore_attempt_id = $attemptId
        backup_generation = [string]$backup.generation
        backup_manifest_sha256 = [string]$backup.manifest_sha256
        backup_id = ([guid][string]$backup.backup_id).ToString("D")
        dataset_id = ([guid][string]$backup.dataset_id).ToString("D")
        backup_restore_epoch = [int64]$backup.restore_epoch
        target_revision = [string]$backup.schema_revision
        predecessor_current_sha256 = [string]$Authority.Current.PayloadSha256
        predecessor_intent_sha256 = [string]$Authority.Intent.PayloadSha256
        predecessor_current_payload = $Authority.Current.Payload
        predecessor_intent_payload = $Authority.Intent.Payload
        release_manifest_sha256 =
            ([string]$Subject.Manifest.Sha256).ToLowerInvariant()
        active_dataset_id = ([guid]$ActiveDatasetId).ToString("D")
        active_restore_epoch = $ActiveRestoreEpoch
        restart_backend = $RestartBackend
        public_base_url = ConvertTo-TicketboxDatabaseGenerationPublicBaseUrl `
            $PublicBaseUrl
    }
    if ($null -ne $existing) {
        foreach ($name in @($immutable.Keys)) {
            if (
                (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload.$name) -cne
                (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $immutable[$name])
            ) {
                throw "existing dataset restore request differs from immutable input."
            }
        }
        return Assert-TicketboxInstalledDatasetRestoreRequest $existing
    }
    $payload = [ordered]@{ schema = "ticketbox-installed-dataset-restore-request-v4" }
    foreach ($name in @($immutable.Keys)) { $payload[$name] = $immutable[$name] }
    $written = Write-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-request" $payload $LifecycleLock
    return Assert-TicketboxInstalledDatasetRestoreRequest $written
}

function Get-TicketboxInstalledDatasetRestoreResultPath {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$RestoreAttemptId
    )
    $attempt = ([guid]$RestoreAttemptId).ToString("D")
    return Join-Path $StateRoot "dataset-restore-result-$attempt.json"
}

function Assert-TicketboxInstalledDatasetRestoreResult {
    param(
        [Parameter(Mandatory = $true)][object]$Result,
        [Parameter(Mandatory = $true)][string]$RestoreAttemptId,
        [Parameter(Mandatory = $true)][string]$BackupGeneration,
        [Parameter(Mandatory = $true)][string]$ExpectedReleaseManifestSha256
    )
    $payload = $Result.Payload
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload `
        -ExpectedNames @(
            "schema", "restore_attempt_id", "request_sha256",
            "release_manifest_sha256", "backup_generation", "backup_id",
            "dataset_id", "restore_epoch", "generation_operation_id",
            "current_sha256", "result"
        ) `
        -Label "installed dataset restore result"
    $attempt = ([guid]$RestoreAttemptId).ToString("D")
    $backupId = ([guid][string]$payload.backup_id).ToString("D")
    $datasetId = ([guid][string]$payload.dataset_id).ToString("D")
    $operationId = ([guid][string]$payload.generation_operation_id).ToString("D")
    foreach ($digest in @(
        [string]$payload.request_sha256,
        [string]$payload.current_sha256,
        [string]$payload.release_manifest_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "installed dataset restore result"
    }
    if (
        [string]$payload.schema -cne "ticketbox-complete-dataset-restore-result-v2" -or
        [string]$payload.restore_attempt_id -cne $attempt -or
        [string]$payload.backup_generation -cne $BackupGeneration -or
        [string]$payload.backup_generation -cne "ticketbox-backup-$backupId" -or
        [string]$payload.backup_id -cne $backupId -or
        [string]$payload.dataset_id -cne $datasetId -or
        [string]$payload.generation_operation_id -cne $operationId -or
        [string]$payload.release_manifest_sha256 -cne
            $ExpectedReleaseManifestSha256.ToLowerInvariant() -or
        [int64]$payload.restore_epoch -lt 1 -or
        [string]$payload.result -cne "current_published"
    ) {
        throw "installed dataset restore result is not canonical or attempt-bound."
    }
    return $Result
}

function Read-TicketboxInstalledDatasetRestoreResult {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$RestoreAttemptId,
        [Parameter(Mandatory = $true)][string]$BackupGeneration,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][string]$ExpectedReleaseManifestSha256,
        [switch]$AllowAbsent
    )
    $path = Get-TicketboxInstalledDatasetRestoreResultPath `
        $StateRoot $RestoreAttemptId
    $result = Read-TicketboxDatabaseGenerationEnvelope `
        -Path $path `
        -ExpectedKind "dataset-restore-result" `
        -AllowAbsent:$AllowAbsent
    if ($null -eq $result) { return $null }
    $validated = Assert-TicketboxInstalledDatasetRestoreResult `
        $result $RestoreAttemptId $BackupGeneration `
        $ExpectedReleaseManifestSha256
    $disposition = if (
        [string]$validated.Payload.generation_operation_id -ceq
            ([guid][string]$Current.Payload.operation_id).ToString("D") -and
        [string]$validated.Payload.current_sha256 -ceq [string]$Current.PayloadSha256
    ) { "current" }
    else { "superseded" }
    return [pscustomobject][ordered]@{
        Artifact = $validated
        Disposition = $disposition
    }
}

function New-TicketboxInstalledDatasetRestoreResult {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Get-TicketboxInstalledDatasetRestoreResultPath `
        $StateRoot ([string]$Request.Payload.restore_attempt_id)
    $expected = [ordered]@{
        schema = "ticketbox-complete-dataset-restore-result-v2"
        restore_attempt_id = [string]$Request.Payload.restore_attempt_id
        request_sha256 = [string]$Request.PayloadSha256
        release_manifest_sha256 = [string]$Request.Payload.release_manifest_sha256
        backup_generation = [string]$Request.Payload.backup_generation
        backup_id = [string]$Payload.backup_id
        dataset_id = [string]$Payload.dataset_id
        restore_epoch = [int64]$Payload.restore_epoch
        generation_operation_id = [string]$Payload.generation_operation_id
        current_sha256 = [string]$Current.PayloadSha256
        result = "current_published"
    }
    $existing = Read-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-result" -AllowAbsent
    if ($null -ne $existing) {
        if (
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload) -cne
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $expected)
        ) {
            throw "existing dataset restore result differs from exact terminal state."
        }
        return Assert-TicketboxInstalledDatasetRestoreResult `
            $existing `
            ([string]$Request.Payload.restore_attempt_id) `
            ([string]$Request.Payload.backup_generation) `
            ([string]$Request.Payload.release_manifest_sha256)
    }
    $written = Write-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-result" $expected $LifecycleLock
    return Assert-TicketboxInstalledDatasetRestoreResult `
        $written `
        ([string]$Request.Payload.restore_attempt_id) `
        ([string]$Request.Payload.backup_generation) `
        ([string]$Request.Payload.release_manifest_sha256)
}

function Remove-TicketboxInstalledDatasetRestoreRequest {
    param(
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observed = Read-TicketboxDatabaseGenerationEnvelope `
        -Path ([string]$Request.Path) `
        -ExpectedKind "dataset-restore-request"
    [void](Assert-TicketboxInstalledDatasetRestoreRequest $observed)
    if ([string]$observed.PayloadSha256 -cne [string]$Request.PayloadSha256) {
        throw "installed dataset restore request changed before retirement."
    }
    [IO.File]::Delete([string]$Request.Path)
    if ((Get-TicketboxPathEntryKindNoFollow ([string]$Request.Path)) -cne "Missing") {
        throw "installed dataset restore request retirement did not persist."
    }
}
