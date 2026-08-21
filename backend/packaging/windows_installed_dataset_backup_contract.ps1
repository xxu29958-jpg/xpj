#Requires -Version 5.1

<#
.SYNOPSIS
  Durable, closed request contract for one installed complete-dataset backup.
.DESCRIPTION
  The request is the first backup mutation. It survives interruption so a retry
  reuses the same operation and backup identifiers and restores the captured
  backend service state after the published generation is verified.
#>

$script:TicketboxInstalledDatasetBackupRequestName = "dataset-backup-active.json"
$script:TicketboxInstalledDatasetBackupAclAccounts = @(
    "SYSTEM",
    "BUILTIN\Administrators"
)

function Get-TicketboxInstalledDatasetBackupRequestPath {
    param([Parameter(Mandatory = $true)][string]$StateRoot)
    return Join-Path $StateRoot $script:TicketboxInstalledDatasetBackupRequestName
}

function Assert-TicketboxInstalledDatasetBackupRequest {
    param([Parameter(Mandatory = $true)][object]$Request)

    $payload = $Request.Payload
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $payload `
        -ExpectedNames @(
            "schema", "operation_id", "backup_id", "backup_kind",
            "installation_id", "current_sha256", "release_manifest_sha256",
            "restart_backend"
        ) `
        -Label "installed dataset backup request"
    $operationId = ([guid][string]$payload.operation_id).ToString("D")
    $backupId = ([guid][string]$payload.backup_id).ToString("D")
    $installationId = ([guid][string]$payload.installation_id).ToString("D")
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$payload.current_sha256) "installed dataset backup CURRENT"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$payload.release_manifest_sha256) "installed dataset backup release"
    if (
        [string]$payload.schema -cne "ticketbox-installed-dataset-backup-request-v1" -or
        $operationId -cne [string]$payload.operation_id -or
        $backupId -cne [string]$payload.backup_id -or
        $installationId -cne [string]$payload.installation_id -or
        [string]$payload.backup_kind -cne "manual" -or
        $payload.restart_backend -isnot [bool]
    ) {
        throw "installed dataset backup request is not closed or canonical."
    }
    return $Request
}

function Read-TicketboxInstalledDatasetBackupRequest {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [switch]$AllowAbsent
    )

    $path = Get-TicketboxInstalledDatasetBackupRequestPath $StateRoot
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -ceq "Missing" -and $AllowAbsent) { return $null }
    if ($kind -cne "File") {
        throw "installed dataset backup request is not a protected file."
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxInstalledDatasetBackupAclAccounts `
        -OwnerAccount "SYSTEM"
    try { $envelope = $artifact.Text | ConvertFrom-Json }
    catch { throw "installed dataset backup request is not valid JSON." }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $envelope @("kind", "payload", "payload_sha256", "schema") `
        "installed dataset backup envelope"
    if (
        [string]$envelope.schema -cne "ticketbox-installed-dataset-backup-envelope-v1" -or
        [string]$envelope.kind -cne "dataset-backup-request"
    ) {
        throw "installed dataset backup request kind/schema drifted."
    }
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope.payload
    $payloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
    if (
        [string]$envelope.payload_sha256 -cne $payloadSha256 -or
        $artifact.Text -cne (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope)
    ) {
        throw "installed dataset backup request digest drifted."
    }
    return Assert-TicketboxInstalledDatasetBackupRequest ([pscustomobject]@{
        Path = $path
        Payload = $envelope.payload
        PayloadSha256 = $payloadSha256
    })
}

function Get-OrCreateTicketboxInstalledDatasetBackupRequest {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][ValidateSet("manual")][string]$BackupKind,
        [Parameter(Mandatory = $true)][bool]$RestartBackend,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )

    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $stateRoot = [string]$Authority.StateRoot
    $existing = Read-TicketboxInstalledDatasetBackupRequest $stateRoot -AllowAbsent
    if ($null -ne $existing) {
        if (
            [string]$existing.Payload.installation_id -cne
                [string]$Subject.Identity.InstallationId -or
            [string]$existing.Payload.current_sha256 -cne
                [string]$Authority.Current.PayloadSha256 -or
            [string]$existing.Payload.release_manifest_sha256 -cne
                ([string]$Subject.Manifest.Sha256).ToLowerInvariant()
        ) {
            throw "pending dataset backup request differs from installed authority."
        }
        return $existing
    }
    $payload = [ordered]@{
        schema = "ticketbox-installed-dataset-backup-request-v1"
        operation_id = [guid]::NewGuid().ToString("D")
        backup_id = [guid]::NewGuid().ToString("D")
        backup_kind = $BackupKind
        installation_id = ([guid][string]$Subject.Identity.InstallationId).ToString("D")
        current_sha256 = [string]$Authority.Current.PayloadSha256
        release_manifest_sha256 = ([string]$Subject.Manifest.Sha256).ToLowerInvariant()
        restart_backend = $RestartBackend
    }
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
    $envelope = [ordered]@{
        schema = "ticketbox-installed-dataset-backup-envelope-v1"
        kind = "dataset-backup-request"
        payload_sha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
        payload = $payload
    }
    $path = Get-TicketboxInstalledDatasetBackupRequestPath $stateRoot
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope) `
        -FullControlAccounts $script:TicketboxInstalledDatasetBackupAclAccounts `
        -OwnerAccount "SYSTEM"
    return Read-TicketboxInstalledDatasetBackupRequest $stateRoot
}

function Remove-TicketboxInstalledDatasetBackupRequest {
    param(
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )

    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observed = Read-TicketboxInstalledDatasetBackupRequest `
        (Split-Path -Parent ([string]$Request.Path))
    if ([string]$observed.PayloadSha256 -cne [string]$Request.PayloadSha256) {
        throw "installed dataset backup request changed before retirement."
    }
    [IO.File]::Delete([string]$Request.Path)
    if ((Get-TicketboxPathEntryKindNoFollow ([string]$Request.Path)) -cne "Missing") {
        throw "installed dataset backup request retirement did not persist."
    }
}
