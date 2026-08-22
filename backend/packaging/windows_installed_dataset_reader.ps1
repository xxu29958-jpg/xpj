#Requires -Version 5.1

# Read-only installed dataset authority and packaged-tool evidence.

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
    Assert-TicketboxProtectedDirectoryAcl -Path $backupRoot
    Assert-TicketboxProtectedDirectoryAcl -Path $generationPath
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
