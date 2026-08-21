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
    "windows_installed_dataset_contract.ps1",
    "windows_installed_dataset_backup_contract.ps1"
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
    $host = [pscustomobject]@{
        Schema = "ticketbox-postgresql-host-authority-v1"
        PsqlPath = Join-Path ([string]$Subject.Identity.InstallDir) "pg\bin\psql.exe"
        Port = [int]$Subject.Identity.PgPort
    }
    $raw = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $host `
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
    return Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
    )
}

function Invoke-TicketboxInstalledCompleteBackupHelper {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][string]$WriterBarrierSha256
    )

    $identity = $Subject.Identity
    $manifest = $Subject.Manifest
    $programRoot = Join-Path ([string]$identity.InstallDir) "program\ticketbox-backend"
    $helperPath = Join-Path $programRoot "ticketbox-database-maintenance.exe"
    $pgDump = Join-Path ([string]$identity.InstallDir) "pg\bin\pg_dump.exe"
    $pgRestore = Join-Path ([string]$identity.InstallDir) "pg\bin\pg_restore.exe"
    foreach ($tool in @(
        @{ Path = $pgDump; Evidence = $manifest.PgDump },
        @{ Path = $pgRestore; Evidence = $manifest.PgRestore }
    )) {
        $item = Get-Item -LiteralPath ([string]$tool.Path) -Force -ErrorAction Stop
        if (
            [int64]$item.Length -ne [int64]$tool.Evidence.Size -or
            (Get-TicketboxPortableFileSha256 ([string]$tool.Path)).ToLowerInvariant() -cne
                ([string]$tool.Evidence.Sha256).ToLowerInvariant()
        ) {
            throw "installed PostgreSQL backup tool differs from build provenance."
        }
    }
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
        UploadRoot = Join-Path ([string]$identity.DataRoot) "app\uploads"
        PgDump = $pgDump
        PgRestore = $pgRestore
        OperationId = [string]$Request.Payload.operation_id
        BackupId = [string]$Request.Payload.backup_id
        ReleaseId = [string]$manifest.Sha256
        Kind = [string]$Request.Payload.backup_kind
        Barrier = $WriterBarrierSha256
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
                        "--upload-root", $captured.UploadRoot,
                        "--database-url", $captured.DatabaseUrl,
                        "--pgpassfile", $passfile.Path,
                        "--pg-dump-binary", $captured.PgDump,
                        "--pg-restore-binary", $captured.PgRestore,
                        "--operation-id", $captured.OperationId,
                        "--backup-id", $captured.BackupId,
                        "--release-id", $captured.ReleaseId,
                        "--backup-kind", $captured.Kind,
                        "--writer-fence-sha256", $captured.Barrier
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
                $canonicalBackupId = ([guid][string]$decoded.backup_id).ToString("D")
                $canonicalDatasetId = ([guid][string]$decoded.dataset_id).ToString("D")
                Assert-TicketboxDatabaseGenerationExactProperties `
                    -Value $decoded `
                    -ExpectedNames @(
                        "schema", "backup_id", "generation", "dataset_id",
                        "restore_epoch", "size_bytes"
                    ) `
                    -Label "complete dataset backup result"
                if (
                    [string]$decoded.schema -cne "ticketbox-complete-dataset-backup-result-v1" -or
                    $canonicalBackupId -cne [string]$captured.BackupId -or
                    $canonicalBackupId -cne [string]$decoded.backup_id -or
                    $canonicalDatasetId -cne [string]$decoded.dataset_id -or
                    [string]$decoded.generation -cne "ticketbox-backup-$([string]$decoded.backup_id)" -or
                    [int64]$decoded.restore_epoch -lt 0 -or
                    [int64]$decoded.size_bytes -lt 1
                ) {
                    throw "complete dataset backup result is not closed or canonical."
                }
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
            Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
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
    $request = Get-OrCreateTicketboxInstalledDatasetBackupRequest `
        -Subject $subject `
        -Authority $authority `
        -BackupKind $BackupKind `
        -RestartBackend $restartBackend `
        -LifecycleLock $lock
    $restartBackend = [bool]$request.Payload.restart_backend
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
        try { Remove-TicketboxInstalledDatasetBackupRequest $request $lock }
        catch { $cleanup += $_ }
    }
    if ($null -ne $lock) {
        try { Exit-TicketboxLifecycleLock $lock }
        catch { $cleanup += $_ }
    }
}
Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
$backupResult | ConvertTo-Json -Depth 4 -Compress
