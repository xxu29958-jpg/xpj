#Requires -Version 5.1

<#
.SYNOPSIS
  Restore one explicitly selected complete Ticketbox dataset backup.
.DESCRIPTION
  Sole installed restore mutation owner. It persists the request before
  stopping services, restores into an isolated cluster, reconciles same-volume
  promotion, and delegates CURRENT publication only to the H1 Generation Owner.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$BackupGeneration
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
    "windows_postgresql_candidate_cluster.ps1",
    "windows_bundled_database.ps1"
)) {
    $dependency = Join-Path $scriptRoot $name
    if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) {
        throw "complete dataset restore dependency is missing: $name"
    }
    . $dependency
}
foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `
    -Root $scriptRoot)) {
    . $dependency
}

function Get-TicketboxInstalledActiveDatasetObservation {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Authority
    )
    $host = [pscustomobject][ordered]@{
        Schema = "ticketbox-postgresql-host-authority-v1"
        PsqlPath = Join-Path ([string]$Subject.Identity.InstallDir) "pg\bin\psql.exe"
        Port = [int]$Subject.Identity.PgPort
    }
    $raw = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $host `
        -Database "ticketbox" `
        -Role "ticketbox_backup" `
        -Password $Authority.Credentials.BackupPassword `
        -Label "active dataset authority observation" `
        -Sql @"
SELECT dataset_id::text || E'\t' || restore_epoch::text || E'\t' ||
       schema_revision
FROM public.dataset_authority
WHERE singleton_id = 1;
"@
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $raw -FieldCount 3 `
        -Label "active dataset authority observation"
    return [pscustomobject][ordered]@{
        DatasetId = ([guid][string]$fields[0]).ToString("D")
        RestoreEpoch = [int64]$fields[1]
        SchemaRevision = [string]$fields[2]
    }
}

function Stop-TicketboxInstalledDatasetWriters {
    param([Parameter(Mandatory = $true)][object]$Subject)
    $identity = $Subject.Identity
    $release = $Subject.Release
    $shawl = Join-Path ([string]$identity.InstallDir) "shawl\shawl.exe"
    $backend = Join-Path ([string]$identity.InstallDir) `
        "program\ticketbox-backend\ticketbox-backend.exe"
    $pgCtl = Join-Path ([string]$identity.InstallDir) "pg\bin\pg_ctl.exe"
    Stop-TicketboxOwnedServiceIfExists `
        -Name ([string]$identity.BackendServiceName) `
        -ExpectedExecutable $shawl `
        -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$release.service_poll_interval_ms) `
        -BackendPort ([int]$identity.BackendPort) `
        -ExpectedRuntimeExecutables @($backend, $shawl)
    Stop-TicketboxOwnedServiceIfExists `
        -Name ([string]$identity.PgServiceName) `
        -ExpectedExecutable $pgCtl `
        -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$release.service_poll_interval_ms)
}

function Invoke-TicketboxInstalledDatasetRestoreHelper {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$Credentials
    )
    $policy = Get-TicketboxDatabaseAuthorizationContract
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority $Candidate.Authority `
        -Database ([string]$policy.DatabaseName) `
        -Role ([string]$policy.MigratorRole)
    $passfile = $null
    $lease = $null
    $primary = $null
    $cleanup = @()
    $decoded = $null
    try {
        $pgRestore = Assert-TicketboxInstalledPostgresToolArtifact `
            -Subject $Subject -Tool "PgRestore"
        $passfile = Invoke-TicketboxWithPlainPostgresqlSecret `
            -Secret $Credentials.MigratorPassword `
            -Action ({
                param([string]$PlainPassword)
                New-TicketboxProtectedPgPassFile `
                    -DatabaseUrl $databaseUrl `
                    -Password $PlainPassword
            }.GetNewClosure())
        $evidence = $Subject.Manifest.DatabaseMaintenanceHelper
        $helper = Join-Path ([string]$Subject.Identity.InstallDir) `
            "program\ticketbox-backend\ticketbox-database-maintenance.exe"
        $lease = Open-TicketboxVerifiedDatabaseMaintenanceHelperLease `
            -Path $helper `
            -ExpectedRelativePath ([string]$evidence.RelativePath) `
            -ExpectedSize ([int64]$evidence.Size) `
            -ExpectedSha256 ([string]$evidence.Sha256)
        $process = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $lease.Path `
            -Arguments @(
                "--isolated-dataset-restore",
                "--backup-generation", [string]$Inspection.GenerationPath,
                "--target-upload-root", [string]$Paths.candidate_uploads,
                "--database-url", $databaseUrl,
                "--pgpassfile", [string]$passfile.Path,
                "--pg-restore-path", $pgRestore,
                "--active-dataset-id", [string]$Request.Payload.active_dataset_id,
                "--active-restore-epoch", [string]$Request.Payload.active_restore_epoch,
                "--target-schema-revision", [string]$Request.Payload.target_revision,
                "--restore-role", "ticketbox_owner"
            ) `
            -StandardInputText "" `
            -TimeoutMilliseconds ([int]$Subject.Release.database_tool_timeout_ms) `
            -Label "isolated complete dataset restore" `
            -ChildEnvironment (New-TicketboxDatabaseGenerationHelperChildEnvironment `
                -PgPassFilePath ([string]$passfile.Path))
        if ([int]$process.ExitCode -ne 0 -or $process.StandardError.Trim().Length -ne 0) {
            throw "isolated complete dataset restore failed; native output is suppressed."
        }
        $decoded = (Get-TicketboxDatabaseGenerationJsonLine `
            -StandardOutput ([string]$process.StandardOutput) `
            -Label "isolated complete dataset restore") | ConvertFrom-Json
        Assert-TicketboxDatabaseGenerationExactProperties `
            $decoded `
            @(
                "schema", "backup_id", "dataset_id", "restore_epoch",
                "schema_revision", "original_count", "result"
            ) `
            "isolated complete dataset restore result"
        $expectedEpoch = [Math]::Max(
            [int64]$Request.Payload.backup_restore_epoch,
            [int64]$Request.Payload.active_restore_epoch
        ) + 1
        if (
            [string]$decoded.schema -cne "ticketbox-isolated-dataset-restore-result-v1" -or
            [string]$decoded.result -cne "isolated_restore_candidate_ready" -or
            [string]$decoded.backup_id -cne [string]$Request.Payload.backup_id -or
            [string]$decoded.dataset_id -cne [string]$Request.Payload.dataset_id -or
            [int64]$decoded.restore_epoch -ne $expectedEpoch -or
            [string]$decoded.schema_revision -cne [string]$Request.Payload.target_revision -or
            [int64]$decoded.original_count -ne [int64]$Inspection.Evidence.original_count
        ) {
            throw "isolated restore result differs from its durable request."
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
    return $decoded
}

function New-TicketboxInstalledDatasetRestoredSource {
    param(
        [Parameter(Mandatory = $true)][object]$IntentContext,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $intent = $IntentContext.Artifact
    $policy = Get-TicketboxDatabaseAuthorizationContract
    $catalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $Candidate.Authority `
        -SuperuserPassword $Candidate.SuperuserPassword `
        -TargetDatabase ([string]$policy.DatabaseName)
    if (-not $catalog.Exists) { throw "restored candidate database is absent." }
    $fence = Get-TicketboxDatabaseGenerationFrozenFence `
        $Candidate.Authority $Candidate.SuperuserPassword
    $fenceSha = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
    )
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-restored-source-v1"
        operation_id = [string]$intent.Payload.operation_id
        intent_sha256 = [string]$intent.PayloadSha256
        source_request_sha256 = [string]$Request.PayloadSha256
        predecessor_current_sha256 = [string]$Request.Payload.predecessor_current_sha256
        backup_manifest_sha256 = [string]$Request.Payload.backup_manifest_sha256
        backup_id = [string]$Request.Payload.backup_id
        dataset_id = [string]$Request.Payload.dataset_id
        restore_epoch = [Math]::Max(
            [int64]$Request.Payload.backup_restore_epoch,
            [int64]$Request.Payload.active_restore_epoch
        ) + 1
        source_revision = [string]$Request.Payload.target_revision
        cluster_system_identifier = [string]$catalog.ClusterSystemIdentifier
        database_oid = [uint32]$catalog.DatabaseOid
        writer_fence_sha256 = $fenceSha
        result = "isolated_restore_candidate_ready"
    }
    return New-TicketboxDatabaseGenerationChainedArtifact `
        $IntentContext.StateRoot `
        ([string]$intent.Payload.operation_id) `
        "restored-source" `
        $payload `
        $LifecycleLock
}

function Set-TicketboxInstalledDatasetPublishedAcls {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Paths
    )
    Set-TicketboxExactDirectoryAcl `
        -Path ([string]$Paths.stable_pgdata) `
        -Accounts @(
            "SYSTEM", "BUILTIN\Administrators",
            "NT SERVICE\$([string]$Subject.Identity.PgServiceName)"
        ) `
        -OwnerAccount "SYSTEM" `
        -Recurse
    Set-TicketboxExactDirectoryAcl `
        -Path ([string]$Paths.stable_uploads) `
        -Accounts @(
            "SYSTEM", "BUILTIN\Administrators",
            "NT SERVICE\$([string]$Subject.Identity.BackendServiceName)"
        ) `
        -OwnerAccount "SYSTEM" `
        -Recurse
}

$lock = $null
$subject = $null
$authority = $null
$credentials = $null
$candidate = $null
$request = $null
$primary = $null
$cleanup = @()
$result = $null
$restartBackend = $false
$resumeCommittedRestore = $false
try {
    $lock = Enter-TicketboxLifecycleLock
    Assert-TicketboxLifecycleOperationLease $lock
    $subject = Assert-TicketboxInstalledDatasetSubject $DataRoot
    Assert-TicketboxInstalledDatasetServiceAuthority $subject
    $script:AppData = Join-Path ([string]$subject.Identity.DataRoot) "app"
    $script:PgData = Join-Path ([string]$subject.Identity.DataRoot) "pgdata"
    $script:PgPort = [int]$subject.Identity.PgPort
    $script:SecretByteCount = [int]$subject.Release.secret_byte_count
    $inspection = Invoke-TicketboxInstalledDatasetBackupInspection `
        $subject $BackupGeneration
    [void](Assert-TicketboxInstalledPostgresToolArtifact `
        -Subject $subject -Tool "PgRestore")

    $stateRoot = Get-TicketboxDatabaseGenerationStateRoot (
        Get-TicketboxInstallerStateDirectory
    )
    $active = Read-TicketboxDatabaseGenerationActiveIntent $stateRoot
    $current = Read-TicketboxDatabaseGenerationCurrent
    $predecessor = Resolve-TicketboxInstalledDatasetRestorePredecessor `
        $active $current
    $request = Get-TicketboxInstalledDatasetRestoreRequest `
        -StateRoot $stateRoot `
        -PredecessorCurrent $predecessor `
        -BackupId ([string]$inspection.Evidence.backup_id) `
        -AllowAbsent
    if (
        $null -eq $request -and
        -not [bool]$predecessor.HasPendingSuccessor -and
        [string]$active.Payload.operation_id -ceq [string]$current.Payload.operation_id -and
        -not [string]::IsNullOrEmpty(
            [string]$active.Payload.expected_predecessor_sha256
        )
    ) {
        $priorPredecessor = [pscustomobject][ordered]@{
            Schema = "ticketbox-installed-dataset-restore-predecessor-v1"
            HasPendingSuccessor = $false
            PayloadSha256 = [string]$active.Payload.expected_predecessor_sha256
        }
        $priorRequest = Get-TicketboxInstalledDatasetRestoreRequest `
            -StateRoot $stateRoot `
            -PredecessorCurrent $priorPredecessor `
            -BackupId ([string]$inspection.Evidence.backup_id) `
            -AllowAbsent
        if ($null -ne $priorRequest) {
            if (
                [string]$priorRequest.PayloadSha256 -cne
                    [string]$active.Payload.source_request_sha256
            ) {
                throw "committed Generation successor differs from its pending restore request."
            }
            $request = $priorRequest
            $resumeCommittedRestore = $true
        }
    }
    if ($null -eq $request) {
        if ([bool]$predecessor.HasPendingSuccessor) {
            throw "an in-progress Generation successor lacks its durable restore request."
        }
        $backendState = Wait-TicketboxServiceSettledState `
            -Name ([string]$subject.Identity.BackendServiceName) `
            -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
            -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms)
        $restartBackend = $backendState -ceq "running"
        $authority = Read-TicketboxInstalledDatasetAuthority $subject
        $activeDataset = Get-TicketboxInstalledActiveDatasetObservation `
            $subject $authority
        if (
            [string]$inspection.Evidence.dataset_id -cne [string]$activeDataset.DatasetId -or
            [string]$inspection.Evidence.schema_revision -cne [string]$activeDataset.SchemaRevision
        ) {
            throw "restore requires a backup of the installed dataset and exact release schema."
        }
        $request = New-TicketboxInstalledDatasetRestoreRequest `
            -Subject $subject `
            -Authority $authority `
            -Inspection $inspection `
            -ActiveDatasetId ([string]$activeDataset.DatasetId) `
            -ActiveRestoreEpoch ([int64]$activeDataset.RestoreEpoch) `
            -RestartBackend $restartBackend `
            -LifecycleLock $lock
        Close-TicketboxDatabaseGenerationRuntimeCredentials $authority.Credentials
        $authority.Credentials = $null
    }
    $restartBackend = [bool]$request.Payload.restart_backend
    if (
        [string]$request.Payload.backup_generation -cne $BackupGeneration -or
        [string]$request.Payload.backup_manifest_sha256 -cne
            [string]$inspection.Evidence.manifest_sha256 -or
        [string]$request.Payload.dataset_id -cne [string]$request.Payload.active_dataset_id
    ) {
        throw "restore request differs from the explicitly selected backup."
    }

    $contracts = New-TicketboxInstalledDatabaseGenerationContracts $subject
    if (
        [string]$active.Payload.operation_id -ceq [string]$current.Payload.operation_id -and
        -not $resumeCommittedRestore
    ) {
        $intentContext = New-TicketboxDatabaseGenerationIntent `
            -InstallerState (Get-TicketboxInstallerStateDirectory) `
            -LifecycleLock $lock `
            -ExpectedPredecessorSha256 ([string]$current.PayloadSha256) `
            -SourceRequestSha256 ([string]$request.PayloadSha256) `
            -TargetBackendVersion ([string]$subject.Identity.BackendVersionFloor) `
            -MaintenanceHelperSize ([int64]$subject.Manifest.DatabaseMaintenanceHelper.Size) `
            -MaintenanceHelperSha256 (([string]$subject.Manifest.DatabaseMaintenanceHelper.Sha256).ToLowerInvariant()) `
            -ProgramContract $contracts.Program `
            -HostContract $contracts.Host `
            -ProjectionContract $contracts.Projection
        $active = $intentContext.Artifact
    }
    else {
        if (
            [string]$active.Payload.source_request_sha256 -cne [string]$request.PayloadSha256 -or
            [string]$active.Payload.expected_predecessor_sha256 -cne
                [string]$request.Payload.predecessor_current_sha256
        ) {
            throw "active Generation successor differs from the restore request."
        }
        $intentContext = [pscustomobject]@{
            StateRoot = $stateRoot
            Artifact = $active
        }
    }
    $operationId = [string]$active.Payload.operation_id
    $paths = Get-TicketboxInstalledDatasetRestorePaths `
        ([string]$subject.Identity.DataRoot) $operationId
    $published = if ([string]$current.Payload.operation_id -ceq $operationId) {
        $current
    }
    else { $null }
    $bootstrapState = $null
    if ($null -eq $published) {
        $bootstrapState = Get-OrCreatePostgresBootstrapRecoveryState
        $credentials = New-TicketboxDatabaseGenerationCredentials `
            -StateRoot $stateRoot `
            -Intent $active `
            -LifecycleLock $lock
    }

    while ($true) {
        Assert-TicketboxLifecycleOperationLease $lock
        $source = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "restored-source" -AllowAbsent
        $current = Read-TicketboxDatabaseGenerationCurrent
        $published = if ([string]$current.Payload.operation_id -ceq $operationId) {
            $current
        }
        else { $null }
        $physical = Resolve-TicketboxInstalledDatasetRestorePhysicalState $paths
        $sourceState = if ($null -eq $source) { "absent" } else { "present" }
        $publishedState = if ($null -eq $published) { "absent" } else { "present" }
        $next = Resolve-TicketboxInstalledDatasetRestoreNextAction `
            $physical $sourceState $publishedState
        switch ($next) {
            "build_candidate" {
                Stop-TicketboxInstalledDatasetWriters $subject
                Initialize-TicketboxPostgresqlRestoreCandidateCluster `
                    $subject $operationId $paths $bootstrapState $lock
                Start-TicketboxPostgresqlRestoreCandidateService `
                    $subject $paths $lock
                $candidate = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
                    $subject $operationId $credentials $bootstrapState $lock
            }
            "restore_candidate" {
                Stop-TicketboxInstalledDatasetWriters $subject
                if ($null -eq $candidate) {
                    Initialize-TicketboxPostgresqlRestoreCandidateCluster `
                        $subject $operationId $paths $bootstrapState $lock
                    Start-TicketboxPostgresqlRestoreCandidateService `
                        $subject $paths $lock
                    $candidate = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
                        $subject $operationId $credentials $bootstrapState $lock
                }
                [void](Invoke-TicketboxInstalledDatasetRestoreHelper `
                    $subject $request $inspection $paths $candidate $credentials)
                [void](New-TicketboxInstalledDatasetRestoredSource `
                    $intentContext $request $candidate $lock)
            }
            "promote_candidate" {
                Stop-TicketboxInstalledDatasetWriters $subject
                Remove-TicketboxPostgresqlRestoreCandidateService $subject $paths
                Set-TicketboxInstalledDatasetRestorePhysicalSelection `
                    -Paths $paths -Selection "Candidate"
            }
            "publish_current" {
                Set-TicketboxInstalledDatasetPublishedAcls $subject $paths
                Start-TicketboxOwnedServiceIfExists `
                    -Name ([string]$subject.Identity.PgServiceName) `
                    -ExpectedExecutable (Join-Path ([string]$subject.Identity.InstallDir) `
                        "pg\bin\pg_ctl.exe") `
                    -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
                    -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms) | Out-Null
                [void](Invoke-TicketboxInstalledDatabaseGeneration `
                    -IntentContext $intentContext `
                    -ReleaseIdentity $contracts.ReleaseIdentity `
                    -LifecycleLock $lock `
                    -HostContract $contracts.Host `
                    -ProjectionContract $contracts.Projection `
                    -BootstrapRecoveryPath (Get-PostgresBootstrapRecoveryPath))
            }
            "retire_rollback" {
                Remove-TicketboxInstalledDatasetRestoreRollback $paths $lock
            }
            "done" {
                $result = [ordered]@{
                    schema = "ticketbox-complete-dataset-restore-result-v1"
                    backup_id = [string]$request.Payload.backup_id
                    dataset_id = [string]$request.Payload.dataset_id
                    restore_epoch = [Math]::Max(
                        [int64]$request.Payload.backup_restore_epoch,
                        [int64]$request.Payload.active_restore_epoch
                    ) + 1
                    generation_operation_id = $operationId
                    result = "current_published"
                }
            }
        }
        if ($null -ne $result) { break }
    }
    if ($restartBackend -and $null -ne $result) {
        Assert-TicketboxInstalledDatasetServiceAuthority $subject
        [void](Start-TicketboxOwnedServiceIfExists `
            -Name ([string]$subject.Identity.BackendServiceName) `
            -ExpectedExecutable (Join-Path ([string]$subject.Identity.InstallDir) `
                "shawl\shawl.exe") `
            -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
            -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms))
    }
    if ($null -ne $result) {
        Remove-TicketboxInstalledDatasetRestoreRequest $request $lock
    }
}
catch {
    $primary = $_
    if (
        $null -ne $subject -and
        $null -ne $request -and
        $null -ne $paths -and
        -not [string]::IsNullOrWhiteSpace([string]$operationId)
    ) {
        try {
            $failureCurrent = Read-TicketboxDatabaseGenerationCurrent
            if ([string]$failureCurrent.Payload.operation_id -cne [string]$operationId) {
                try {
                    Remove-TicketboxPostgresqlRestoreCandidateService $subject $paths
                }
                catch { $cleanup += $_ }
                Stop-TicketboxInstalledDatasetWriters $subject
                Set-TicketboxInstalledDatasetRestorePhysicalSelection `
                    -Paths $paths -Selection "Predecessor"
                Set-TicketboxInstalledDatasetPublishedAcls $subject $paths
                [void](Start-TicketboxOwnedServiceIfExists `
                    -Name ([string]$subject.Identity.PgServiceName) `
                    -ExpectedExecutable (Join-Path ([string]$subject.Identity.InstallDir) `
                        "pg\bin\pg_ctl.exe") `
                    -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
                    -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms))
                if ([bool]$request.Payload.restart_backend) {
                    [void](Start-TicketboxOwnedServiceIfExists `
                        -Name ([string]$subject.Identity.BackendServiceName) `
                        -ExpectedExecutable (Join-Path ([string]$subject.Identity.InstallDir) `
                            "shawl\shawl.exe") `
                        -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
                        -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms))
                }
            }
        }
        catch { $cleanup += $_ }
    }
}
finally {
    if ($null -ne $candidate -and $null -ne $candidate.SuperuserPassword) {
        try { $candidate.SuperuserPassword.Dispose() }
        catch { $cleanup += $_ }
        $candidate.SuperuserPassword = $null
    }
    if ($null -ne $credentials) {
        try { Close-TicketboxDatabaseGenerationCredentials $credentials }
        catch { $cleanup += $_ }
        $credentials = $null
    }
    if ($null -ne $authority -and $null -ne $authority.Credentials) {
        try {
            Close-TicketboxDatabaseGenerationRuntimeCredentials `
                $authority.Credentials
        }
        catch { $cleanup += $_ }
    }
    if ($null -ne $lock) {
        try { Exit-TicketboxLifecycleLock $lock }
        catch { $cleanup += $_ }
    }
}
Throw-TicketboxDatabaseGenerationOperationFailure $primary $cleanup
if ($null -eq $result) { throw "complete dataset restore returned no result." }
$resultJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $result
[Console]::Out.WriteLine($resultJson)
