#Requires -Version 5.1

# One installed instance may have only one durable dataset operation.
$script:TicketboxInstalledDatasetOperationAclAccounts = @(
    "SYSTEM",
    "BUILTIN\Administrators"
)

function Get-TicketboxInstalledDatasetOperationPath {
    param([Parameter(Mandatory = $true)][string]$StateRoot)
    return Join-Path $StateRoot "dataset-operation-active.json"
}

function Assert-TicketboxInstalledDatasetOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Operation,
        [Parameter(Mandatory = $true)][ValidateSet("backup", "restore")]
        [string]$ExpectedOperationKind
    )
    $payload = $Operation.Payload
    $commonNames = @(
        "schema", "operation_kind", "operation_id", "installation_id",
        "current_sha256", "release_manifest_sha256", "restart_backend"
    )
    $specificNames = if ($ExpectedOperationKind -ceq "backup") {
        @("backup_id", "backup_kind")
    }
    else {
        @(
            "backup_generation", "backup_manifest_sha256", "backup_id",
            "dataset_id", "backup_restore_epoch", "target_revision",
            "predecessor_intent_sha256", "predecessor_current_payload",
            "predecessor_intent_payload", "active_dataset_id",
            "active_restore_epoch", "public_base_url"
        )
    }
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload `
        -ExpectedNames @($commonNames + $specificNames) `
        -Label "installed dataset operation"
    $operationId = ([guid][string]$payload.operation_id).ToString("D")
    $installationId = ([guid][string]$payload.installation_id).ToString("D")
    foreach ($digest in @(
        [string]$payload.current_sha256,
        [string]$payload.release_manifest_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "installed dataset operation"
    }
    if (
        [string]$payload.schema -cne "ticketbox-installed-dataset-operation-v1" -or
        [string]$payload.operation_kind -cne $ExpectedOperationKind -or
        $operationId -cne [string]$payload.operation_id -or
        $installationId -cne [string]$payload.installation_id -or
        $payload.restart_backend -isnot [bool]
    ) {
        throw "installed dataset operation is not closed or canonical."
    }
    $backupId = ([guid][string]$payload.backup_id).ToString("D")
    if ($backupId -cne [string]$payload.backup_id) {
        throw "installed dataset operation backup id is not canonical."
    }
    if ($ExpectedOperationKind -ceq "backup") {
        if ([string]$payload.backup_kind -cne "manual") {
            throw "installed dataset backup operation kind is not supported."
        }
        return $Operation
    }
    foreach ($digest in @(
        [string]$payload.backup_manifest_sha256,
        [string]$payload.predecessor_intent_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "installed dataset restore operation"
    }
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
        $datasetId -cne [string]$payload.dataset_id -or
        $activeDatasetId -cne [string]$payload.active_dataset_id -or
        [string]$payload.backup_generation -cne "ticketbox-backup-$backupId" -or
        [int64]$payload.backup_restore_epoch -lt 0 -or
        [int64]$payload.active_restore_epoch -lt 0 -or
        $publicBaseUrl -cne [string]$payload.public_base_url -or
        [string]::IsNullOrWhiteSpace([string]$payload.target_revision) -or
        $predecessorIntentSha -cne [string]$payload.predecessor_intent_sha256 -or
        $predecessorCurrentSha -cne [string]$payload.current_sha256 -or
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
        throw "installed dataset restore operation is not self-bound."
    }
    return $Operation
}

function Read-TicketboxInstalledDatasetOperation {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][ValidateSet("backup", "restore")]
        [string]$ExpectedOperationKind,
        [switch]$AllowAbsent
    )
    $path = Get-TicketboxInstalledDatasetOperationPath $StateRoot
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -ceq "Missing" -and $AllowAbsent) { return $null }
    if ($kind -cne "File") {
        throw "installed dataset operation is not a protected file."
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxInstalledDatasetOperationAclAccounts `
        -OwnerAccount "SYSTEM"
    try { $envelope = $artifact.Text | ConvertFrom-Json }
    catch { throw "installed dataset operation is not valid JSON." }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $envelope @("kind", "payload", "payload_sha256", "schema") `
        "installed dataset operation envelope"
    if (
        [string]$envelope.schema -cne "ticketbox-installed-dataset-operation-envelope-v1" -or
        [string]$envelope.kind -cne "dataset-operation"
    ) {
        throw "installed dataset operation envelope drifted."
    }
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope.payload
    $payloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
    if (
        [string]$envelope.payload_sha256 -cne $payloadSha256 -or
        $artifact.Text -cne (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope)
    ) {
        throw "installed dataset operation digest drifted."
    }
    $actualKind = [string]$envelope.payload.operation_kind
    if ($actualKind -notin @("backup", "restore")) {
        throw "installed dataset operation kind is unknown."
    }
    $operation = Assert-TicketboxInstalledDatasetOperation `
        -Operation ([pscustomobject]@{
            Path = $path
            Payload = $envelope.payload
            PayloadSha256 = $payloadSha256
        }) `
        -ExpectedOperationKind $actualKind
    if ($actualKind -cne $ExpectedOperationKind) {
        throw "installed dataset $actualKind operation is already active."
    }
    return $operation
}

function Write-TicketboxInstalledDatasetOperation {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][ValidateSet("backup", "restore")]
        [string]$OperationKind,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $Payload
    $envelope = [ordered]@{
        schema = "ticketbox-installed-dataset-operation-envelope-v1"
        kind = "dataset-operation"
        payload_sha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
        payload = $Payload
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path (Get-TicketboxInstalledDatasetOperationPath $StateRoot) `
        -Text (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope) `
        -FullControlAccounts $script:TicketboxInstalledDatasetOperationAclAccounts `
        -OwnerAccount "SYSTEM"
    return Read-TicketboxInstalledDatasetOperation `
        $StateRoot $OperationKind
}

function Start-TicketboxInstalledDatasetBackupOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][ValidateSet("manual")][string]$BackupKind,
        [Parameter(Mandatory = $true)][bool]$RestartBackend,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $existing = Read-TicketboxInstalledDatasetOperation `
        $Authority.StateRoot "backup" -AllowAbsent
    if ($null -ne $existing) {
        if (
            [string]$existing.Payload.installation_id -cne
                [string]$Subject.Identity.InstallationId -or
            [string]$existing.Payload.current_sha256 -cne
                [string]$Authority.Current.PayloadSha256 -or
            [string]$existing.Payload.release_manifest_sha256 -cne
                ([string]$Subject.Manifest.Sha256).ToLowerInvariant()
        ) {
            throw "active dataset backup operation differs from installed authority."
        }
        return $existing
    }
    $payload = [ordered]@{
        schema = "ticketbox-installed-dataset-operation-v1"
        operation_kind = "backup"
        operation_id = [guid]::NewGuid().ToString("D")
        installation_id = ([guid][string]$Subject.Identity.InstallationId).ToString("D")
        current_sha256 = [string]$Authority.Current.PayloadSha256
        release_manifest_sha256 = ([string]$Subject.Manifest.Sha256).ToLowerInvariant()
        restart_backend = $RestartBackend
        backup_id = [guid]::NewGuid().ToString("D")
        backup_kind = $BackupKind
    }
    return Write-TicketboxInstalledDatasetOperation `
        $Authority.StateRoot $payload "backup" $LifecycleLock
}

function Start-TicketboxInstalledDatasetRestoreOperation {
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
    $operationId = ([guid]$RestoreAttemptId).ToString("D")
    $immutable = [ordered]@{
        schema = "ticketbox-installed-dataset-operation-v1"
        operation_kind = "restore"
        operation_id = $operationId
        installation_id = ([guid][string]$Subject.Identity.InstallationId).ToString("D")
        current_sha256 = [string]$Authority.Current.PayloadSha256
        release_manifest_sha256 = ([string]$Subject.Manifest.Sha256).ToLowerInvariant()
        restart_backend = $RestartBackend
        backup_generation = [string]$backup.generation
        backup_manifest_sha256 = [string]$backup.manifest_sha256
        backup_id = ([guid][string]$backup.backup_id).ToString("D")
        dataset_id = ([guid][string]$backup.dataset_id).ToString("D")
        backup_restore_epoch = [int64]$backup.restore_epoch
        target_revision = [string]$backup.schema_revision
        predecessor_intent_sha256 = [string]$Authority.Intent.PayloadSha256
        predecessor_current_payload = $Authority.Current.Payload
        predecessor_intent_payload = $Authority.Intent.Payload
        active_dataset_id = ([guid]$ActiveDatasetId).ToString("D")
        active_restore_epoch = $ActiveRestoreEpoch
        public_base_url = ConvertTo-TicketboxDatabaseGenerationPublicBaseUrl `
            $PublicBaseUrl
    }
    $existing = Read-TicketboxInstalledDatasetOperation `
        $Authority.StateRoot "restore" -AllowAbsent
    if ($null -ne $existing) {
        if (
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload) -cne
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $immutable)
        ) {
            throw "active dataset restore operation differs from immutable input."
        }
        return $existing
    }
    return Write-TicketboxInstalledDatasetOperation `
        $Authority.StateRoot $immutable "restore" $LifecycleLock
}

function Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition {
    param(
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Current
    )
    $request = Assert-TicketboxInstalledDatasetOperation $Request "restore"
    $predecessorSha256 = [string]$request.Payload.current_sha256
    if (
        [string]$Intent.PayloadSha256 -ceq
            [string]$request.Payload.predecessor_intent_sha256 -and
        [string]$Current.PayloadSha256 -ceq $predecessorSha256
    ) {
        return "request_only"
    }
    $successor = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    if (
        [string]$Intent.Payload.source_request_sha256 -cne
            [string]$request.PayloadSha256 -or
        [string]$Intent.Payload.expected_predecessor_sha256 -cne
            $predecessorSha256
    ) {
        throw "dataset restore active intent differs from its durable operation."
    }
    if ([string]$Current.PayloadSha256 -ceq $predecessorSha256) {
        return "successor_pending"
    }
    if (
        [string]$Current.Payload.operation_id -ceq $successor -and
        [string]$Current.Payload.intent_sha256 -ceq
            [string]$Intent.PayloadSha256 -and
        [string]$Current.Payload.expected_predecessor_sha256 -ceq
            $predecessorSha256
    ) {
        return "successor_current"
    }
    throw "dataset restore observed a foreign CURRENT authority."
}

function Remove-TicketboxInstalledDatasetOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Operation,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $kind = [string]$Operation.Payload.operation_kind
    $observed = Read-TicketboxInstalledDatasetOperation `
        (Split-Path -Parent ([string]$Operation.Path)) $kind
    if ([string]$observed.PayloadSha256 -cne [string]$Operation.PayloadSha256) {
        throw "installed dataset operation changed before retirement."
    }
    [IO.File]::Delete([string]$Operation.Path)
    if ((Get-TicketboxPathEntryKindNoFollow ([string]$Operation.Path)) -cne "Missing") {
        throw "installed dataset operation retirement did not persist."
    }
}
