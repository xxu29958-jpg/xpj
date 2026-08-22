# Durable terminal replay evidence for one installed dataset restore operation.

function Get-TicketboxInstalledDatasetRestoreResultPath {
    param([Parameter(Mandatory = $true)][string]$StateRoot)
    return Join-Path $StateRoot "dataset-restore-result.json"
}

function Assert-TicketboxInstalledDatasetRestoreResult {
    param([Parameter(Mandatory = $true)][object]$Result)
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
    $attempt = ([guid][string]$payload.restore_attempt_id).ToString("D")
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
        [string]$payload.backup_generation -cne "ticketbox-backup-$backupId" -or
        [string]$payload.backup_id -cne $backupId -or
        [string]$payload.dataset_id -cne $datasetId -or
        [string]$payload.generation_operation_id -cne $operationId -or
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
    $path = Get-TicketboxInstalledDatasetRestoreResultPath $StateRoot
    $result = Read-TicketboxDatabaseGenerationEnvelope `
        -Path $path `
        -ExpectedKind "dataset-restore-result" `
        -AllowAbsent:$AllowAbsent
    if ($null -eq $result) { return $null }
    $validated = Assert-TicketboxInstalledDatasetRestoreResult $result
    $attempt = ([guid]$RestoreAttemptId).ToString("D")
    if ([string]$validated.Payload.restore_attempt_id -cne $attempt) {
        if ($AllowAbsent) { return $null }
        throw "bounded dataset restore result belongs to another attempt."
    }
    if (
        [string]$validated.Payload.backup_generation -cne $BackupGeneration -or
        [string]$validated.Payload.release_manifest_sha256 -cne
            $ExpectedReleaseManifestSha256.ToLowerInvariant()
    ) {
        throw "dataset restore result differs from the requested backup/release."
    }
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

function New-TicketboxInstalledDatasetRestoreResultEnvelope {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Get-TicketboxInstalledDatasetRestoreResultPath $StateRoot
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (New-TicketboxDatabaseGenerationEnvelopeText `
            "dataset-restore-result" $Payload) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    return Read-TicketboxDatabaseGenerationEnvelope $path "dataset-restore-result"
}

function Replace-TicketboxInstalledDatasetRestoreResultEnvelope {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedPayloadSha256,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        $ExpectedPayloadSha256 "dataset restore result CAS predecessor"
    $path = Get-TicketboxInstalledDatasetRestoreResultPath $StateRoot
    $existing = Read-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-result"
    if ([string]$existing.PayloadSha256 -cne $ExpectedPayloadSha256) {
        throw "dataset restore result CAS predecessor changed."
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (New-TicketboxDatabaseGenerationEnvelopeText `
            "dataset-restore-result" $Payload) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount `
        -ReplaceExisting
    return Read-TicketboxDatabaseGenerationEnvelope $path "dataset-restore-result"
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
    $path = Get-TicketboxInstalledDatasetRestoreResultPath $StateRoot
    $expected = [ordered]@{
        schema = "ticketbox-complete-dataset-restore-result-v2"
        restore_attempt_id = [string]$Request.Payload.operation_id
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
        $existing = Assert-TicketboxInstalledDatasetRestoreResult $existing
        if (
            [string]$existing.Payload.restore_attempt_id -cne
                [string]$Request.Payload.operation_id
        ) {
            if (
                [string]$existing.Payload.current_sha256 -ceq
                    [string]$Current.PayloadSha256
            ) {
                throw "another restore result still owns CURRENT."
            }
            $replaced = Replace-TicketboxInstalledDatasetRestoreResultEnvelope `
                -StateRoot $StateRoot `
                -ExpectedPayloadSha256 ([string]$existing.PayloadSha256) `
                -Payload $expected `
                -LifecycleLock $LifecycleLock
            return Assert-TicketboxInstalledDatasetRestoreResult $replaced
        }
        if (
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload) -cne
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $expected)
        ) {
            throw "existing dataset restore result differs from exact terminal state."
        }
        return Assert-TicketboxInstalledDatasetRestoreResult $existing
    }
    $written = New-TicketboxInstalledDatasetRestoreResultEnvelope `
        $StateRoot $expected $LifecycleLock
    return Assert-TicketboxInstalledDatasetRestoreResult $written
}
