#Requires -Version 5.1

<#
.SYNOPSIS
  Creates one complete installed Ticketbox dataset backup generation.
.DESCRIPTION
  This is the sole installed backup mutation owner. It validates the installed
  identity and Generation CURRENT, stops the backend writer, proves the
  PostgreSQL session barrier, invokes the frozen maintenance helper, and then
  restores the backend service to its previous state.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [ValidateSet("manual")][string]$BackupKind = "manual"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

foreach ($name in @(
    "windows_installation_safety.ps1",
    "windows_lifecycle_lock.ps1",
    "windows_deadline_budget.ps1",
    "windows_release_config.ps1",
    "windows_service_lifecycle.ps1",
    "windows_database_safety.ps1",
    "windows_pg_recovery_tools.ps1",
    "windows_postgresql_credentials.ps1",
    "windows_postgresql_database_command.ps1",
    "windows_database_generation.ps1",
    "windows_installed_dataset_reader.ps1",
    "windows_installed_dataset_operation.ps1"
)) {
    $dependency = Join-Path $scriptRoot $name
    if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) {
        throw "complete dataset backup dependency is missing: $name"
    }
    . $dependency
}
foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `
    -Root $scriptRoot)) {
    . $dependency
}

function Get-TicketboxInstalledBackupBarrier {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Authority
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $hostAuthority = [pscustomobject]@{
        Schema = "ticketbox-postgresql-host-authority-v1"
        PsqlPath = Join-Path ([string]$Subject.Identity.InstallDir) "pg\bin\psql.exe"
        Port = [int]$Subject.Identity.PgPort
    }
    $raw = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $hostAuthority `
        -Database ([string]$policy.DatabaseName) `
        -Role ([string]$policy.BackupRole) `
        -Password $Authority.Credentials.BackupPassword `
        -Label "complete dataset backup writer barrier" `
        -Sql @"
SELECT current_database() || E'\t' || current_user || E'\t' ||
       authority.dataset_id::text || E'\t' || authority.restore_epoch::text || E'\t' ||
       authority.schema_revision || E'\t' ||
       (SELECT count(*) FROM pg_stat_activity
        WHERE datname = current_database() AND backend_type = 'client backend'
          AND pid <> pg_backend_pid())::text
FROM public.dataset_authority AS authority
WHERE authority.singleton_id = 1;
"@
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $raw -FieldCount 6 -Label "complete dataset backup writer barrier"
    if (
        [string]$fields[0] -cne [string]$policy.DatabaseName -or
        [string]$fields[1] -cne [string]$policy.BackupRole -or
        [string]$fields[2] -cnotmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' -or
        [string]$fields[3] -cnotmatch '^(0|[1-9][0-9]*)$' -or
        [string]::IsNullOrWhiteSpace([string]$fields[4]) -or
        [string]$fields[5] -cne "0"
    ) {
        throw "complete dataset backup could not prove the zero-writer barrier."
    }
    $payload = [ordered]@{
        schema = "ticketbox-dataset-backup-writer-barrier-v1"
        current_sha256 = [string]$Authority.Current.PayloadSha256
        dataset_id = [string]$fields[2]
        restore_epoch = [int64]$fields[3]
        schema_revision = [string]$fields[4]
        backend_service_state = "stopped"
        other_client_session_count = 0
    }
    return [pscustomobject][ordered]@{
        Payload = [pscustomobject]$payload
        PayloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
        )
    }
}

function Assert-TicketboxInstalledCompleteBackupResult {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$WriterBarrier,
        [Parameter(Mandatory = $true)][object]$Result,
        [Parameter(Mandatory = $true)][object]$Inspection
    )

    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $WriterBarrier.Payload `
        -ExpectedNames @(
            "schema", "current_sha256", "dataset_id", "restore_epoch",
            "schema_revision", "backend_service_state", "other_client_session_count"
        ) `
        -Label "complete dataset backup writer barrier"
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $Result `
        -ExpectedNames @(
            "schema", "backup_id", "generation", "dataset_id",
            "restore_epoch", "size_bytes"
        ) `
        -Label "complete dataset backup result"
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $Inspection.Evidence `
        -ExpectedNames @(
            "schema", "operation_id", "backup_id", "backup_kind",
            "generation", "source_installation_id", "dataset_id", "restore_epoch", "schema_revision",
            "release_id", "writer_fence_sha256", "manifest_sha256",
            "original_count"
        ) `
        -Label "complete dataset backup inspection"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$WriterBarrier.PayloadSha256) "complete dataset backup writer barrier"
    $backupId = ([guid][string]$Result.backup_id).ToString("D")
    $datasetId = ([guid][string]$Result.dataset_id).ToString("D")
    $barrierDatasetId = ([guid][string]$WriterBarrier.Payload.dataset_id).ToString("D")
    $barrierSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $WriterBarrier.Payload
    )
    $evidence = $Inspection.Evidence
    if (
        [string]$WriterBarrier.Payload.schema -cne
            "ticketbox-dataset-backup-writer-barrier-v1" -or
        [string]$WriterBarrier.Payload.current_sha256 -cne
            [string]$Request.Payload.current_sha256 -or
        [string]$WriterBarrier.PayloadSha256 -cne $barrierSha256 -or
        $barrierDatasetId -cne [string]$WriterBarrier.Payload.dataset_id -or
        [int64]$WriterBarrier.Payload.restore_epoch -lt 0 -or
        [string]::IsNullOrWhiteSpace(
            [string]$WriterBarrier.Payload.schema_revision
        ) -or
        [string]$WriterBarrier.Payload.backend_service_state -cne "stopped" -or
        [int64]$WriterBarrier.Payload.other_client_session_count -ne 0 -or
        [string]$Result.schema -cne "ticketbox-complete-dataset-backup-result-v1" -or
        $backupId -cne [string]$Result.backup_id -or
        $backupId -cne [string]$Request.Payload.backup_id -or
        $datasetId -cne [string]$Result.dataset_id -or
        [string]$Result.generation -cne "ticketbox-backup-$backupId" -or
        [int64]$Result.size_bytes -lt 1 -or
        [string]$evidence.operation_id -cne [string]$Request.Payload.operation_id -or
        [string]$evidence.backup_id -cne $backupId -or
        [string]$evidence.backup_kind -cne [string]$Request.Payload.backup_kind -or
        [string]$evidence.generation -cne [string]$Result.generation -or
        [string]$evidence.source_installation_id -cne
            [string]$Request.Payload.installation_id -or
        [string]$evidence.source_installation_id -cne
            [string]$Subject.Identity.InstallationId -or
        [string]$evidence.dataset_id -cne $datasetId -or
        [string]$evidence.dataset_id -cne [string]$WriterBarrier.Payload.dataset_id -or
        [int64]$evidence.restore_epoch -ne [int64]$Result.restore_epoch -or
        [int64]$evidence.restore_epoch -ne [int64]$WriterBarrier.Payload.restore_epoch -or
        [string]$evidence.schema_revision -cne
            [string]$WriterBarrier.Payload.schema_revision -or
        [string]$evidence.release_id -cne
            [string]$Request.Payload.release_manifest_sha256 -or
        [string]$evidence.release_id -cne [string]$Subject.Manifest.Sha256 -or
        [string]$evidence.writer_fence_sha256 -cne
            [string]$WriterBarrier.PayloadSha256
    ) {
        throw "complete dataset backup result is not bound to the durable request and writer barrier."
    }
    return $Result
}

function Protect-TicketboxInstalledBackupInventory {
    param([Parameter(Mandatory = $true)][object]$Subject)

    $identity = $Subject.Identity
    $path = Join-Path ([string]$identity.DataRoot) "app\backup-inventory.json"
    $privileged = @("SYSTEM", "BUILTIN\Administrators")
    $backendService = "NT SERVICE\$([string]$identity.BackendServiceName)"
    Set-TicketboxExactFileAcl `
        -Path $path `
        -Accounts $privileged `
        -ReadExecuteAccounts @($backendService) `
        -OwnerAccount "SYSTEM"
    [void](Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $privileged `
        -ReadExecuteAccounts @($backendService) `
        -OwnerAccount "SYSTEM" `
        -MaximumBytes 65536)
}

function Invoke-TicketboxInstalledCompleteBackupHelper {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$WriterBarrier
    )

    $identity = $Subject.Identity
    $manifest = $Subject.Manifest
    $programRoot = Join-Path ([string]$identity.InstallDir) "program\ticketbox-backend"
    $helperPath = Join-Path $programRoot "ticketbox-database-maintenance.exe"
    $pgDump = Assert-TicketboxInstalledPostgresToolArtifact `
        -Subject $Subject -Tool "PgDump"
    $pgRestore = Assert-TicketboxInstalledPostgresToolArtifact `
        -Subject $Subject -Tool "PgRestore"
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority ([pscustomobject]@{
            Schema = "ticketbox-postgresql-host-authority-v1"
            PsqlPath = Join-Path ([string]$identity.InstallDir) "pg\bin\psql.exe"
            Port = [int]$identity.PgPort
        }) `
        -Database "ticketbox" `
        -Role "ticketbox_backup"
    $captured = @{
        HelperPath = $helperPath
        HelperEvidence = $manifest.DatabaseMaintenanceHelper
        DatabaseUrl = $databaseUrl
        BackupRoot = Join-Path ([string]$identity.DataRoot) "backups"
        InventoryPath = Join-Path ([string]$identity.DataRoot) "app\backup-inventory.json"
        UploadRoot = Join-Path ([string]$identity.DataRoot) "app\uploads"
        PgDump = $pgDump
        PgRestore = $pgRestore
        OperationId = [string]$Request.Payload.operation_id
        BackupId = [string]$Request.Payload.backup_id
        ReleaseId = [string]$manifest.Sha256
        Kind = [string]$Request.Payload.backup_kind
        Barrier = [string]$WriterBarrier.PayloadSha256
        CurrentSha256 = [string]$WriterBarrier.Payload.current_sha256
        InstallationId = [string]$Request.Payload.installation_id
        DatasetId = [string]$WriterBarrier.Payload.dataset_id
        RestoreEpoch = [int64]$WriterBarrier.Payload.restore_epoch
        SchemaRevision = [string]$WriterBarrier.Payload.schema_revision
        Timeout = [int]$Subject.Release.database_tool_timeout_ms
    }
    return Invoke-TicketboxWithPlainPostgresqlSecret `
        -Secret $Authority.Credentials.BackupPassword `
        -Action ({
            param([string]$PlainPassword)
            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $captured.DatabaseUrl `
                -Password $PlainPassword
            $lease = $null
            $primary = $null
            $cleanup = @()
            $result = $null
            try {
                $lease = Open-TicketboxVerifiedDatabaseMaintenanceHelperLease `
                    -Path $captured.HelperPath `
                    -ExpectedRelativePath ([string]$captured.HelperEvidence.RelativePath) `
                    -ExpectedSize ([int64]$captured.HelperEvidence.Size) `
                    -ExpectedSha256 ([string]$captured.HelperEvidence.Sha256)
                $process = Invoke-TicketboxBoundedNativeProcess `
                    -FilePath $lease.Path `
                    -Arguments @(
                        "--complete-dataset-backup",
                        "--backup-root", $captured.BackupRoot,
                        "--inventory-path", $captured.InventoryPath,
                        "--upload-root", $captured.UploadRoot,
                        "--database-url", $captured.DatabaseUrl,
                        "--pgpassfile", $passfile.Path,
                        "--pg-dump-path", $captured.PgDump,
                        "--pg-restore-path", $captured.PgRestore,
                        "--operation-id", $captured.OperationId,
                        "--backup-id", $captured.BackupId,
                        "--release-id", $captured.ReleaseId,
                        "--backup-kind", $captured.Kind,
                        "--writer-fence-sha256", $captured.Barrier,
                        "--expected-current-sha256", $captured.CurrentSha256,
                        "--expected-installation-id", $captured.InstallationId,
                        "--expected-dataset-id", $captured.DatasetId,
                        "--expected-restore-epoch", [string]$captured.RestoreEpoch,
                        "--expected-schema-revision", $captured.SchemaRevision
                    ) `
                    -StandardInputText "" `
                    -TimeoutMilliseconds $captured.Timeout `
                    -Label "complete dataset backup" `
                    -ChildEnvironment (New-TicketboxDatabaseGenerationHelperChildEnvironment `
                        -PgPassFilePath $passfile.Path)
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace([string]$process.StandardError)
                ) {
                    throw "complete dataset backup helper was rejected; native output is suppressed."
                }
                $jsonLine = Get-TicketboxDatabaseGenerationJsonLine `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -Label "complete dataset backup helper"
                $decoded = $jsonLine | ConvertFrom-Json
                Assert-TicketboxDatabaseGenerationExactProperties `
                    -Value $decoded `
                    -ExpectedNames @(
                        "schema", "backup_id", "generation", "dataset_id",
                        "restore_epoch", "size_bytes"
                    ) `
                    -Label "complete dataset backup result"
                $result = $decoded
            }
            catch { $primary = $_ }
            finally {
                if ($null -ne $lease) {
                    try { Assert-TicketboxDatabaseMaintenanceHelperLeaseUnchanged $lease }
                    catch { $cleanup += $_ }
                    try { Close-TicketboxDatabaseMaintenanceHelperLease $lease }
                    catch { $cleanup += $_ }
                }
                if ($null -ne $passfile) {
                    try {
                        Remove-TicketboxProtectedPgPassArtifact `
                            -Path $passfile.Path `
                            -FullControlAccounts $passfile.FullControlAccounts `
                            -OwnerAccount $passfile.OwnerAccount
                    }
                    catch { $cleanup += $_ }
                }
            }
            Throw-TicketboxOperationFailure $primary $cleanup
            return $result
        }.GetNewClosure())
}

$lock = $null
$subject = $null
$authority = $null
$request = $null
$primary = $null
$cleanup = @()
$backupResult = $null
$restartBackend = $false
try {
    $lock = Enter-TicketboxLifecycleLock
    Assert-TicketboxLifecycleOperationLease $lock
    $subject = Assert-TicketboxInstalledDatasetSubject $DataRoot
    Assert-TicketboxInstalledDatasetServiceAuthority $subject
    $identity = $subject.Identity
    $backendExecutable = Join-Path ([string]$identity.InstallDir) "shawl\shawl.exe"
    $backendRuntime = Join-Path ([string]$identity.InstallDir) "program\ticketbox-backend\ticketbox-backend.exe"
    $pgState = Wait-TicketboxServiceSettledState `
        -Name ([string]$identity.PgServiceName) `
        -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms)
    if ($pgState -cne "running") {
        throw "complete dataset backup requires the installed PostgreSQL service to be running."
    }
    $backendState = Wait-TicketboxServiceSettledState `
        -Name ([string]$identity.BackendServiceName) `
        -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms)
    $restartBackend = $backendState -ceq "running"
    $authority = Read-TicketboxInstalledDatasetAuthority $subject
    $request = Start-TicketboxInstalledDatasetBackupOperation `
        -Subject $subject `
        -Authority $authority `
        -BackupKind $BackupKind `
        -RestartBackend $restartBackend `
        -LifecycleLock $lock
    $restartBackend = [bool]$request.Payload.restart_backend
    $backupRoot = Join-Path ([string]$identity.DataRoot) "backups"
    $backupRootKind = Get-TicketboxPathEntryKindNoFollow $backupRoot
    if ($backupRootKind -ceq "Missing") {
        [IO.Directory]::CreateDirectory($backupRoot) | Out-Null
    }
    elseif ($backupRootKind -cne "Directory") {
        throw "complete dataset backup root is not a plain directory."
    }
    Set-TicketboxExactDirectoryAcl `
        -Path $backupRoot `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -Recurse
    Stop-TicketboxOwnedServiceIfExists `
        -Name ([string]$identity.BackendServiceName) `
        -ExpectedExecutable $backendExecutable `
        -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms) `
        -BackendPort ([int]$identity.BackendPort) `
        -ExpectedRuntimeExecutables @($backendRuntime, $backendExecutable)
    $barrier = Get-TicketboxInstalledBackupBarrier $subject $authority
    $backupResult = Invoke-TicketboxInstalledCompleteBackupHelper `
        $subject $authority $request $barrier
    Protect-TicketboxInstalledBackupInventory $subject
    $generation = [string]$backupResult.generation
    if ($generation -cnotmatch `
        '^ticketbox-backup-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') {
        throw "backup helper returned a noncanonical generation identifier."
    }
    $generationPath = Join-Path $backupRoot $generation
    if (-not (Test-TicketboxPathEquals (Split-Path -Parent $generationPath) $backupRoot)) {
        throw "backup helper generation escaped the installed backup root."
    }
    Set-TicketboxExactDirectoryAcl `
        -Path $generationPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -Recurse
    foreach ($entry in @(Get-ChildItem -LiteralPath $generationPath -Force -Recurse)) {
        $kind = Get-TicketboxPathEntryKindNoFollow ([string]$entry.FullName)
        if ($kind -ceq "Directory") {
            Set-TicketboxExactDirectoryAcl `
                -Path ([string]$entry.FullName) `
                -Accounts @("SYSTEM", "BUILTIN\Administrators") `
                -OwnerAccount "SYSTEM"
        }
        elseif ($kind -ceq "File") {
            Set-TicketboxExactFileAcl `
                -Path ([string]$entry.FullName) `
                -Accounts @("SYSTEM", "BUILTIN\Administrators") `
                -OwnerAccount "SYSTEM"
        }
        else {
            throw "backup generation contains a non-regular filesystem entry."
        }
    }
    $inspection = Invoke-TicketboxInstalledDatasetBackupInspection `
        $subject $generation
    $backupResult = Assert-TicketboxInstalledCompleteBackupResult `
        $subject $request $barrier $backupResult $inspection
}
catch { $primary = $_ }
finally {
    if ($restartBackend -and $null -ne $subject) {
        try {
            [void](Start-TicketboxOwnedServiceIfExists `
                -Name ([string]$subject.Identity.BackendServiceName) `
                -ExpectedExecutable (Join-Path ([string]$subject.Identity.InstallDir) "shawl\shawl.exe") `
                -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
                -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms))
        }
        catch { $cleanup += $_ }
    }
    if ($null -ne $authority -and $null -ne $authority.Credentials) {
        try { Close-TicketboxDatabaseGenerationRuntimeCredentials $authority.Credentials }
        catch { $cleanup += $_ }
    }
    if (
        $null -eq $primary -and $cleanup.Count -eq 0 -and
        $null -ne $backupResult -and $null -ne $request
    ) {
        try { Remove-TicketboxInstalledDatasetOperation $request $lock }
        catch { $cleanup += $_ }
    }
    if ($null -ne $lock) {
        try { Exit-TicketboxLifecycleLock $lock }
        catch { $cleanup += $_ }
    }
}
Throw-TicketboxOperationFailure $primary $cleanup
$backupResult | ConvertTo-Json -Depth 4 -Compress
