# Durable request, candidate-verification, activation-verification, and terminal result artifacts.

function Get-TicketboxInstalledDatasetRestoreRequestPath {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$RestoreAttemptId
    )
    $attempt = ([guid]$RestoreAttemptId).ToString("D")
    return Join-Path $StateRoot "dataset-restore-request-$attempt.json"
}

function Get-TicketboxInstalledDatasetRestoreRequest {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$RestoreAttemptId,
        [switch]$AllowAbsent
    )
    $path = Get-TicketboxInstalledDatasetRestoreRequestPath `
        $StateRoot $RestoreAttemptId
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
            "predecessor_intent_payload", "release_manifest_sha256",
            "active_dataset_id", "active_restore_epoch", "restart_backend"
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
    $predecessorIntentSha = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson `
            $payload.predecessor_intent_payload
    )
    if (
        [string]$payload.schema -cne
            "ticketbox-installed-dataset-restore-request-v2" -or
        $attemptId -cne [string]$payload.restore_attempt_id -or
        $backupId -cne [string]$payload.backup_id -or
        $datasetId -cne [string]$payload.dataset_id -or
        $activeDatasetId -cne [string]$payload.active_dataset_id -or
        [string]$payload.backup_generation -cne "ticketbox-backup-$backupId" -or
        [int64]$payload.backup_restore_epoch -lt 0 -or
        [int64]$payload.active_restore_epoch -lt 0 -or
        $payload.restart_backend -isnot [bool] -or
        [string]::IsNullOrWhiteSpace([string]$payload.target_revision) -or
        $predecessorIntentSha -cne [string]$payload.predecessor_intent_sha256
    ) {
        throw "installed dataset restore request is not canonical or self-bound."
    }
    return $Request
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
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $backup = $Inspection.Evidence
    $attemptId = ([guid]$RestoreAttemptId).ToString("D")
    $path = Get-TicketboxInstalledDatasetRestoreRequestPath `
        $Authority.StateRoot $attemptId
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
        predecessor_intent_payload = $Authority.Intent.Payload
        release_manifest_sha256 =
            ([string]$Subject.Manifest.Sha256).ToLowerInvariant()
        active_dataset_id = ([guid]$ActiveDatasetId).ToString("D")
        active_restore_epoch = $ActiveRestoreEpoch
        restart_backend = $RestartBackend
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
    $payload = [ordered]@{ schema = "ticketbox-installed-dataset-restore-request-v2" }
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
        [Parameter(Mandatory = $true)][object]$Current,
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
        [string]$payload.generation_operation_id -cne
            ([guid][string]$Current.Payload.operation_id).ToString("D") -or
        [string]$payload.current_sha256 -cne [string]$Current.PayloadSha256 -or
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
    return Assert-TicketboxInstalledDatasetRestoreResult `
        $result $RestoreAttemptId $BackupGeneration `
        $Current $ExpectedReleaseManifestSha256
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
            $Current `
            ([string]$Request.Payload.release_manifest_sha256)
    }
    $written = Write-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-result" $expected $LifecycleLock
    return Assert-TicketboxInstalledDatasetRestoreResult `
        $written `
        ([string]$Request.Payload.restore_attempt_id) `
        ([string]$Request.Payload.backup_generation) `
        $Current `
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
