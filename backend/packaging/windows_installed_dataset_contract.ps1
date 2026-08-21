#Requires -Version 5.1

<#
.SYNOPSIS
  Closed installed-dataset authority and restore-state contracts.
.DESCRIPTION
  Readers in this module do not mutate.  The request writer is the first
  restore mutation.  The next-action reducer is IO-free; physical changes stay
  in the restore owner.
#>

function Assert-TicketboxInstalledDatasetSubject {
    param([Parameter(Mandatory = $true)][string]$RequestedDataRoot)

    $identity = Read-TicketboxPersistentInstallationIdentity `
        -DataRoot $RequestedDataRoot
    if (
        [string]$identity.State -cne "READY" -or
        -not (Test-TicketboxPathEquals $RequestedDataRoot ([string]$identity.DataRoot))
    ) {
        throw "installed dataset operation requires the exact READY installation identity."
    }
    $manifestPath = Join-Path ([string]$identity.InstallDir) `
        "installer\BUILD_PROVENANCE.json"
    $manifest = Read-TicketboxInstalledBuildManifest $manifestPath
    if (
        [string]$manifest.Sha256 -cne [string]$identity.BuildManifestSha256 -or
        [string]$manifest.BackendVersion -cne [string]$identity.BackendVersionFloor
    ) {
        throw "installed build provenance differs from the READY installation identity."
    }
    $releasePath = Join-Path ([string]$identity.InstallDir) `
        "installer\windows-release-config.json"
    $release = Read-TicketboxWindowsReleaseConfig $releasePath
    if (
        [string]$release.pg_service_name -cne [string]$identity.PgServiceName -or
        [string]$release.backend_service_name -cne [string]$identity.BackendServiceName
    ) {
        throw "installed release config differs from the READY installation identity."
    }
    return [pscustomobject][ordered]@{
        Identity = $identity
        Manifest = $manifest
        Release = $release
    }
}

function Assert-TicketboxInstalledDatasetServiceAuthority {
    param([Parameter(Mandatory = $true)][object]$Subject)

    $identity = $Subject.Identity
    $release = $Subject.Release
    foreach ($serviceName in @(
        [string]$identity.BackendServiceName,
        [string]$identity.PgServiceName
    )) {
        Assert-TicketboxReleaseServiceIdentity `
            -Name $serviceName `
            -InstalledConfig $release `
            -TargetConfig $release | Out-Null
    }
    Assert-TicketboxPgServiceCommand `
        -Name ([string]$identity.PgServiceName) `
        -ExpectedExecutable (Join-Path ([string]$identity.InstallDir) "pg\bin\pg_ctl.exe") `
        -ExpectedServiceName ([string]$identity.PgServiceName) `
        -ExpectedDataRoot (Join-Path ([string]$identity.DataRoot) "pgdata")
}

function Read-TicketboxInstalledDatasetAuthority {
    param([Parameter(Mandatory = $true)][object]$Subject)

    $stateRoot = Get-TicketboxDatabaseGenerationStateRoot (
        Get-TicketboxInstallerStateDirectory
    )
    $intent = Read-TicketboxDatabaseGenerationActiveIntent $stateRoot
    $candidate = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot ([string]$intent.Payload.operation_id) "candidate"
    $current = Read-TicketboxDatabaseGenerationCurrent
    if (
        [string]$current.Payload.operation_id -cne [string]$intent.Payload.operation_id -or
        [string]$current.Payload.installation_id -cne [string]$Subject.Identity.InstallationId -or
        [string]$current.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$current.Payload.candidate_sha256 -cne [string]$candidate.PayloadSha256
    ) {
        throw "installed dataset authority does not match Generation CURRENT."
    }
    Assert-TicketboxDatabaseGenerationCommitReadyArtifact `
        -ExpectedOperationId ([string]$intent.Payload.operation_id) `
        -ExpectedCurrentSha256 ([string]$current.PayloadSha256) | Out-Null
    $credentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
        -StateRoot $stateRoot `
        -Intent $intent `
        -Candidate $candidate
    return [pscustomobject][ordered]@{
        StateRoot = $stateRoot
        Intent = $intent
        Candidate = $candidate
        Current = $current
        Credentials = $credentials
    }
}

function New-TicketboxInstalledDatabaseGenerationContracts {
    param([Parameter(Mandatory = $true)][object]$Subject)

    $identity = $Subject.Identity
    $manifest = $Subject.Manifest
    $release = $Subject.Release
    $programRoot = Join-Path ([string]$identity.InstallDir) `
        "program\ticketbox-backend"
    $programPath = Join-Path $programRoot `
        ([string]$manifest.DatabaseGenerationProgram.RelativePath)
    $program = Read-TicketboxDatabaseGenerationProgramContract `
        -Path $programPath `
        -ExpectedSha256 (([string]$manifest.DatabaseGenerationProgram.Sha256).ToLowerInvariant())
    $host = New-TicketboxDatabaseGenerationHostContract `
        -BackendServiceName ([string]$identity.BackendServiceName) `
        -DataRoot ([string]$identity.DataRoot) `
        -InstallDir ([string]$identity.InstallDir) `
        -PgCtlPath (Join-Path ([string]$identity.InstallDir) "pg\bin\pg_ctl.exe") `
        -PgServiceName ([string]$identity.PgServiceName) `
        -PgDumpPath (Join-Path ([string]$identity.InstallDir) "pg\bin\pg_dump.exe") `
        -PgDumpSize ([int64]$manifest.PgDump.Size) `
        -PgDumpSha256 (([string]$manifest.PgDump.Sha256).ToLowerInvariant()) `
        -PgRestorePath (Join-Path ([string]$identity.InstallDir) "pg\bin\pg_restore.exe") `
        -PgRestoreSize ([int64]$manifest.PgRestore.Size) `
        -PgRestoreSha256 (([string]$manifest.PgRestore.Sha256).ToLowerInvariant()) `
        -ReleaseConfig $release
    $projection = New-TicketboxDatabaseGenerationProjectionContract `
        -BackendServiceName ([string]$identity.BackendServiceName) `
        -EnvPath (Join-Path ([string]$identity.DataRoot) "app\.env") `
        -StopTimeoutMilliseconds ([int]$release.stop_timeout_ms) `
        -BackendPort ([int]$identity.BackendPort) `
        -PgBin (Join-Path ([string]$identity.InstallDir) "pg\bin") `
        -Timezone ([string]$release.default_timezone) `
        -PublicBaseUrl "" `
        -PsqlPath (Join-Path ([string]$identity.InstallDir) "pg\bin\psql.exe") `
        -PgData (Join-Path ([string]$identity.DataRoot) "pgdata") `
        -DatabaseToolTimeoutMilliseconds ([int]$release.database_tool_timeout_ms)
    $releaseIdentity = [pscustomobject][ordered]@{
        InstallationOperationId = [string]$identity.OperationId
        InstallationId = [string]$identity.InstallationId
        BackendVersionFloor = [string]$identity.BackendVersionFloor
        MaintenanceHelperPath = Join-Path $programRoot `
            ([string]$manifest.DatabaseMaintenanceHelper.RelativePath)
        MaintenanceHelperRelativePath =
            [string]$manifest.DatabaseMaintenanceHelper.RelativePath
        MaintenanceHelperSize = [int64]$manifest.DatabaseMaintenanceHelper.Size
        MaintenanceHelperSha256 =
            ([string]$manifest.DatabaseMaintenanceHelper.Sha256).ToLowerInvariant()
        DatabaseGenerationProgramPath = $programPath
        DatabaseGenerationProgramRelativePath = [string]$program.RelativePath
        DatabaseGenerationProgramSize = [int64]$program.Size
        DatabaseGenerationProgramSha256 =
            ([string]$program.Sha256).ToLowerInvariant()
    }
    return [pscustomobject][ordered]@{
        Program = $program
        Host = $host
        Projection = $projection
        ReleaseIdentity = $releaseIdentity
    }
}

function Invoke-TicketboxInstalledDatasetBackupInspection {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][string]$BackupGeneration
    )

    if ($BackupGeneration -cnotmatch `
        '^ticketbox-backup-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') {
        throw "backup generation must be an explicit canonical identifier."
    }
    $backupRoot = Join-Path ([string]$Subject.Identity.DataRoot) "backups"
    $generationPath = Join-Path $backupRoot $BackupGeneration
    if (-not (Test-TicketboxPathEquals (Split-Path -Parent $generationPath) $backupRoot)) {
        throw "backup generation escaped the installed backup root."
    }
    $helperPath = Join-Path `
        ([string]$Subject.Identity.InstallDir) `
        "program\ticketbox-backend\ticketbox-database-maintenance.exe"
    $evidence = $Subject.Manifest.DatabaseMaintenanceHelper
    $lease = $null
    $primary = $null
    $cleanup = @()
    $decoded = $null
    try {
        $lease = Open-TicketboxVerifiedDatabaseMaintenanceHelperLease `
            -Path $helperPath `
            -ExpectedRelativePath ([string]$evidence.RelativePath) `
            -ExpectedSize ([int64]$evidence.Size) `
            -ExpectedSha256 ([string]$evidence.Sha256)
        $process = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $lease.Path `
            -Arguments @("--inspect-dataset-backup", "--backup-generation", $generationPath) `
            -StandardInputText "" `
            -TimeoutMilliseconds ([int]$Subject.Release.database_tool_timeout_ms) `
            -Label "complete dataset backup inspection" `
            -ChildEnvironment (New-TicketboxDatabaseGenerationHelperChildEnvironment)
        if ([int]$process.ExitCode -ne 0 -or $process.StandardError.Trim().Length -ne 0) {
            throw "complete dataset backup inspection failed; native output is suppressed."
        }
        $jsonLine = Get-TicketboxDatabaseGenerationJsonLine `
            -StandardOutput ([string]$process.StandardOutput) `
            -Label "complete dataset backup inspection"
        $decoded = $jsonLine | ConvertFrom-Json
        Assert-TicketboxDatabaseGenerationExactProperties `
            $decoded `
            @(
                "schema", "operation_id", "backup_id", "backup_kind",
                "generation", "dataset_id",
                "restore_epoch", "schema_revision", "release_id",
                "writer_fence_sha256", "manifest_sha256", "original_count"
            ) `
            "complete dataset backup inspection"
        if (
            [string]$decoded.schema -cne "ticketbox-complete-dataset-backup-inspection-v1" -or
            ([guid][string]$decoded.operation_id).ToString("D") -cne
                [string]$decoded.operation_id -or
            [string]$decoded.generation -cne $BackupGeneration -or
            "ticketbox-backup-$([string]$decoded.backup_id)" -cne $BackupGeneration -or
            [string]$decoded.backup_kind -cne "manual" -or
            [string]$decoded.release_id -cne [string]$Subject.Manifest.Sha256 -or
            [string]$decoded.writer_fence_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$decoded.manifest_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$decoded.schema_revision -cne ([string](
                Read-TicketboxDatabaseGenerationProgramContract `
                    -Path (Join-Path ([string]$Subject.Identity.InstallDir) `
                        "program\ticketbox-backend\DATABASE_GENERATION_PROGRAM.json") `
                    -ExpectedSha256 (([string]$Subject.Manifest.DatabaseGenerationProgram.Sha256).ToLowerInvariant())
            ).TargetRevision) -or
            [int64]$decoded.restore_epoch -lt 0 -or
            [int64]$decoded.original_count -lt 0
        ) {
            throw "complete dataset backup inspection is not bound to the installed release."
        }
    }
    catch { $primary = $_ }
    finally {
        if ($null -ne $lease) {
            try { Assert-TicketboxDatabaseMaintenanceHelperLeaseUnchanged $lease }
            catch { $cleanup += $_ }
            try { Close-TicketboxDatabaseMaintenanceHelperLease $lease }
            catch { $cleanup += $_ }
        }
    }
    Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
    return [pscustomobject][ordered]@{
        GenerationPath = $generationPath
        Evidence = $decoded
    }
}

function Resolve-TicketboxInstalledDatasetRestorePredecessor {
    param(
        [Parameter(Mandatory = $true)][object]$ActiveIntent,
        [Parameter(Mandatory = $true)][object]$Current
    )
    $activeOperation = ([guid][string]$ActiveIntent.Payload.operation_id).ToString("D")
    $currentOperation = ([guid][string]$Current.Payload.operation_id).ToString("D")
    $activeSha = [string]$ActiveIntent.PayloadSha256
    $currentSha = [string]$Current.PayloadSha256
    if (
        $activeSha -cnotmatch '^[0-9a-f]{64}$' -or
        $currentSha -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw "installed dataset restore predecessor digest is invalid."
    }
    if ($activeOperation -ceq $currentOperation) {
        if ([string]$Current.Payload.intent_sha256 -cne $activeSha) {
            throw "committed Generation CURRENT does not bind its active intent."
        }
        return [pscustomobject][ordered]@{
            Schema = "ticketbox-installed-dataset-restore-predecessor-v1"
            HasPendingSuccessor = $false
            PayloadSha256 = $currentSha
        }
    }
    if (
        [string]$ActiveIntent.Payload.expected_predecessor_sha256 -cne $currentSha
    ) {
        throw "pending Generation successor does not bind CURRENT."
    }
    return [pscustomobject][ordered]@{
        Schema = "ticketbox-installed-dataset-restore-predecessor-v1"
        HasPendingSuccessor = $true
        PayloadSha256 = $currentSha
    }
}

function Get-TicketboxInstalledDatasetRestoreRequestPath {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$PredecessorCurrent,
        [Parameter(Mandatory = $true)][string]$BackupId
    )
    $canonicalBackupId = ([guid]$BackupId).ToString("D")
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$PredecessorCurrent.PayloadSha256) "dataset restore predecessor"
    return Join-Path $StateRoot (
        "dataset-restore-request-$([string]$PredecessorCurrent.PayloadSha256)-$canonicalBackupId.json"
    )
}

function Get-TicketboxInstalledDatasetRestoreRequest {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$PredecessorCurrent,
        [Parameter(Mandatory = $true)][string]$BackupId,
        [switch]$AllowAbsent
    )
    $path = Get-TicketboxInstalledDatasetRestoreRequestPath `
        $StateRoot $PredecessorCurrent $BackupId
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
            "schema", "request_id", "backup_generation",
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
    $requestId = ([guid][string]$payload.request_id).ToString("D")
    $backupId = ([guid][string]$payload.backup_id).ToString("D")
    $datasetId = ([guid][string]$payload.dataset_id).ToString("D")
    $activeDatasetId = ([guid][string]$payload.active_dataset_id).ToString("D")
    $predecessorIntentSha = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson `
            $payload.predecessor_intent_payload
    )
    if (
        [string]$payload.schema -cne
            "ticketbox-installed-dataset-restore-request-v1" -or
        $requestId -cne [string]$payload.request_id -or
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
        [Parameter(Mandatory = $true)][string]$ActiveDatasetId,
        [Parameter(Mandatory = $true)][int64]$ActiveRestoreEpoch,
        [Parameter(Mandatory = $true)][bool]$RestartBackend,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $backup = $Inspection.Evidence
    $path = Get-TicketboxInstalledDatasetRestoreRequestPath `
        $Authority.StateRoot $Authority.Current ([string]$backup.backup_id)
    $existing = Read-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-request" -AllowAbsent
    $immutable = [ordered]@{
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
    $payload = [ordered]@{ schema = "ticketbox-installed-dataset-restore-request-v1" }
    $payload.request_id = [guid]::NewGuid().ToString("D")
    foreach ($name in @($immutable.Keys)) { $payload[$name] = $immutable[$name] }
    $written = Write-TicketboxDatabaseGenerationEnvelope `
        $path "dataset-restore-request" $payload $LifecycleLock
    return Assert-TicketboxInstalledDatasetRestoreRequest $written
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

function Get-TicketboxInstalledDatasetRestorePaths {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$OperationId
    )
    $operation = ([guid]$OperationId).ToString("D")
    $candidateRoot = Join-Path $DataRoot "restore-candidates\$operation"
    $rollbackRoot = Join-Path $DataRoot "restore-rollbacks\$operation"
    return [pscustomobject][ordered]@{
        stable_pgdata = Join-Path $DataRoot "pgdata"
        stable_uploads = Join-Path $DataRoot "app\uploads"
        candidate_pgdata = Join-Path $candidateRoot "pgdata"
        candidate_uploads = Join-Path $candidateRoot "uploads"
        rollback_pgdata = Join-Path $rollbackRoot "pgdata"
        rollback_uploads = Join-Path $rollbackRoot "uploads"
        candidate_root = $candidateRoot
        rollback_root = $rollbackRoot
    }
}

function Assert-TicketboxInstalledPostgresToolArtifact {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)]
        [ValidateSet("PgDump", "PgRestore")][string]$Tool
    )
    $relativePath = if ($Tool -ceq "PgDump") {
        "pg\bin\pg_dump.exe"
    }
    else {
        "pg\bin\pg_restore.exe"
    }
    $evidence = $Subject.Manifest.$Tool
    $path = Join-Path ([string]$Subject.Identity.InstallDir) $relativePath
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (
        [int64]$item.Length -ne [int64]$evidence.Size -or
        (Get-TicketboxPortableFileSha256 $path).ToLowerInvariant() -cne
            ([string]$evidence.Sha256).ToLowerInvariant()
    ) {
        throw "installed PostgreSQL tool differs from build provenance: $Tool"
    }
    return $path
}

function Resolve-TicketboxInstalledDatasetRestorePhysicalState {
    param([Parameter(Mandatory = $true)][object]$Paths)
    $present = @{}
    foreach ($name in @(
        "stable_pgdata", "stable_uploads", "candidate_pgdata",
        "candidate_uploads", "rollback_pgdata", "rollback_uploads"
    )) {
        $kind = Get-TicketboxPathEntryKindNoFollow ([string]$Paths.$name)
        if ($kind -notin @("Missing", "Directory")) {
            throw "dataset restore physical path is not a plain directory: $name"
        }
        $present[$name] = $kind -ceq "Directory"
    }
    $containers = @{}
    foreach ($name in @("candidate_root", "rollback_root")) {
        $kind = Get-TicketboxPathEntryKindNoFollow ([string]$Paths.$name)
        if ($kind -notin @("Missing", "Directory")) {
            throw "dataset restore container path is not a plain directory: $name"
        }
        $containers[$name] = $kind
    }
    $signature = @(
        "stable_pgdata", "stable_uploads", "candidate_pgdata",
        "candidate_uploads", "rollback_pgdata", "rollback_uploads"
    ) | ForEach-Object { if ($present[$_]) { "1" } else { "0" } }
    switch ($signature -join "") {
        "111000" { return "candidate_building" }
        "111100" { return "candidate_ready" }
        "011110" { return "old_pg_staged" }
        "001111" { return "old_staged" }
        "100111" { return "candidate_pg_published" }
        "110011" { return "candidate_published" }
        { $_ -in @("110001", "110010") } { return "rollback_retiring" }
        "110000" {
            if (
                $containers.candidate_root -ceq "Directory" -or
                $containers.rollback_root -ceq "Directory"
            ) {
                return "cleanup_pending"
            }
            return "complete"
        }
        default { throw "dataset restore physical state is not classifiable."
        }
    }
}

function Resolve-TicketboxInstalledDatasetRestoreNextAction {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "complete", "candidate_building", "candidate_ready",
            "old_pg_staged", "old_staged", "candidate_pg_published",
            "candidate_published", "rollback_retiring", "cleanup_pending"
        )][string]$PhysicalState,
        [Parameter(Mandatory = $true)]
        [ValidateSet("absent", "present")][string]$RestoredSourceState,
        [Parameter(Mandatory = $true)]
        [ValidateSet("absent", "present")][string]$PublishedCurrentState,
        [Parameter(Mandatory = $true)]
        [ValidateSet("absent", "present")][string]$RuntimeVerificationState
    )
    if (
        $RuntimeVerificationState -ceq "present" -and
        $PublishedCurrentState -ceq "absent"
    ) {
        throw "dataset restore runtime verification exists before CURRENT publication."
    }
    switch ($PhysicalState) {
        "complete" {
            if (
                $RestoredSourceState -ceq "present" -and
                $PublishedCurrentState -ceq "present" -and
                $RuntimeVerificationState -ceq "present"
            ) {
                return "done"
            }
            if ($PublishedCurrentState -ceq "present") {
                throw "dataset restore rollback retired before runtime verification."
            }
            if ($RestoredSourceState -ceq "present") {
                throw "dataset restore lost its candidate before CURRENT publication."
            }
            return "build_candidate"
        }
        "candidate_building" {
            if (
                $RestoredSourceState -ceq "present" -or
                $PublishedCurrentState -ceq "present"
            ) {
                throw "dataset restore building state conflicts with published authority."
            }
            return "restore_candidate"
        }
        "candidate_ready" {
            if ($RestoredSourceState -ceq "absent") { return "restore_candidate" }
            if ($PublishedCurrentState -ceq "present") {
                throw "dataset restore CURRENT exists before physical publication."
            }
            return "promote_candidate"
        }
        { $_ -in @("old_pg_staged", "old_staged", "candidate_pg_published") } {
            if (
                $RestoredSourceState -ceq "absent" -or
                $PublishedCurrentState -ceq "present"
            ) {
                throw "dataset restore partial promotion lacks its immutable source evidence."
            }
            return "promote_candidate"
        }
        "candidate_published" {
            if ($RestoredSourceState -ceq "absent") {
                throw "published dataset candidate lacks restored-source evidence."
            }
            if ($PublishedCurrentState -ceq "absent") { return "publish_current" }
            if ($RuntimeVerificationState -ceq "absent") { return "verify_runtime" }
            return "retire_rollback"
        }
        { $_ -in @("rollback_retiring", "cleanup_pending") } {
            if (
                $RestoredSourceState -ceq "absent" -or
                $PublishedCurrentState -ceq "absent" -or
                $RuntimeVerificationState -ceq "absent"
            ) {
                throw "dataset restore cleanup lacks committed runtime verification."
            }
            return "retire_rollback"
        }
        default { throw "unknown dataset restore physical state."
        }
    }
}

function Set-TicketboxInstalledDatasetRestorePhysicalSelection {
    param(
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)]
        [ValidateSet("Candidate", "Predecessor")][string]$Selection
    )
    while ($true) {
        $state = Resolve-TicketboxInstalledDatasetRestorePhysicalState $Paths
        if ($Selection -ceq "Predecessor") {
            switch ($state) {
                { $_ -in @("complete", "candidate_building", "candidate_ready") } {
                    if (
                        (Get-TicketboxPathEntryKindNoFollow ([string]$Paths.rollback_root)) -ceq
                            "Directory"
                    ) {
                        [IO.Directory]::Delete([string]$Paths.rollback_root, $false)
                    }
                    return
                }
                "candidate_published" {
                    [IO.Directory]::CreateDirectory([string]$Paths.candidate_root) | Out-Null
                    [IO.Directory]::Move(
                        [string]$Paths.stable_uploads, [string]$Paths.candidate_uploads
                    )
                }
                "candidate_pg_published" {
                    [IO.Directory]::Move(
                        [string]$Paths.stable_pgdata, [string]$Paths.candidate_pgdata
                    )
                }
                "old_staged" {
                    [IO.Directory]::Move(
                        [string]$Paths.rollback_uploads, [string]$Paths.stable_uploads
                    )
                }
                "old_pg_staged" {
                    [IO.Directory]::Move(
                        [string]$Paths.rollback_pgdata, [string]$Paths.stable_pgdata
                    )
                }
                default {
                    throw "dataset restore predecessor selection was invoked from an invalid state."
                }
            }
            continue
        }
        switch ($state) {
            "candidate_ready" {
                [IO.Directory]::CreateDirectory([string]$Paths.rollback_root) | Out-Null
                [IO.Directory]::Move(
                    [string]$Paths.stable_pgdata, [string]$Paths.rollback_pgdata
                )
            }
            "old_pg_staged" {
                [IO.Directory]::Move(
                    [string]$Paths.stable_uploads, [string]$Paths.rollback_uploads
                )
            }
            "old_staged" {
                [IO.Directory]::Move(
                    [string]$Paths.candidate_pgdata, [string]$Paths.stable_pgdata
                )
            }
            "candidate_pg_published" {
                [IO.Directory]::Move(
                    [string]$Paths.candidate_uploads, [string]$Paths.stable_uploads
                )
            }
            "candidate_published" { return }
            default { throw "dataset restore promotion was invoked from an invalid state."
            }
        }
    }
}

function Remove-TicketboxInstalledDatasetRestoreRollback {
    param(
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $state = Resolve-TicketboxInstalledDatasetRestorePhysicalState $Paths
    if ($state -notin @("candidate_published", "rollback_retiring", "cleanup_pending")) {
        throw "dataset restore rollback may retire only after candidate publication."
    }
    foreach ($path in @($Paths.rollback_pgdata, $Paths.rollback_uploads)) {
        Remove-TicketboxDataRootExact -Path ([string]$path)
    }
    if ((Get-TicketboxPathEntryKindNoFollow ([string]$Paths.rollback_root)) -ceq "Directory") {
        [IO.Directory]::Delete([string]$Paths.rollback_root, $false)
    }
    if ((Get-TicketboxPathEntryKindNoFollow ([string]$Paths.candidate_root)) -ceq "Directory") {
        [IO.Directory]::Delete([string]$Paths.candidate_root, $false)
    }
    if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $Paths) -cne "complete") {
        throw "dataset restore rollback retirement did not reach complete state."
    }
}
