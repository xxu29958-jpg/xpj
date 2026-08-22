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
    [Parameter(Mandatory = $true)][string]$BackupGeneration,
    [Parameter(Mandatory = $true)][string]$RestoreAttemptId
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$RestoreAttemptId = ([guid]$RestoreAttemptId).ToString("D")
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
    "windows_backend_health.ps1",
    "windows_database_generation.ps1",
    "windows_installed_dataset_reader.ps1",
    "windows_installed_dataset_restore_artifacts.ps1",
    "windows_installed_dataset_restore_verification.ps1",
    "windows_dataset_restore_filesystem.ps1",
    "windows_dataset_restore_reducer.ps1",
    "windows_dataset_restore_database.ps1",
    "windows_dataset_restore_runtime.ps1",
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

$lock = $null
$subject = $null
$authority = $null
$credentials = $null
$candidate = $null
$request = $null
$paths = $null
$published = $null
$operationId = $null
$stateRoot = $null
$contracts = $null
$runtimeVerification = $null
$active = $null
$inspection = $null
$terminalReplay = $false
$primary = $null
$cleanup = @()
$result = $null
$restartBackend = $false
$resumeCommittedRestore = $false
$publicBaseUrl = $null
try {
    $lock = Enter-TicketboxLifecycleLock
    Assert-TicketboxLifecycleOperationLease $lock
    $stateRoot = Get-TicketboxDatabaseGenerationStateRoot (
        Get-TicketboxInstallerStateDirectory
    )
    $subject = Assert-TicketboxInstalledDatasetSubject $DataRoot
    Assert-TicketboxInstalledDatasetServiceAuthority $subject
    $script:AppData = Join-Path ([string]$subject.Identity.DataRoot) "app"
    $script:PgData = Join-Path ([string]$subject.Identity.DataRoot) "pgdata"
    $script:PgPort = [int]$subject.Identity.PgPort
    $script:SecretByteCount = [int]$subject.Release.secret_byte_count
    $active = Read-TicketboxDatabaseGenerationActiveIntent $stateRoot
    $current = Read-TicketboxDatabaseGenerationCurrent
    $request = Get-TicketboxInstalledDatasetRestoreRequest `
        -StateRoot $stateRoot -AllowAbsent
    $terminalResult = Read-TicketboxInstalledDatasetRestoreResult `
        -StateRoot $stateRoot `
        -RestoreAttemptId $RestoreAttemptId `
        -BackupGeneration $BackupGeneration `
        -Current $current `
        -ExpectedReleaseManifestSha256 ([string]$subject.Manifest.Sha256) `
        -AllowAbsent
    if ($null -ne $terminalResult) {
        $result = Complete-TicketboxInstalledDatasetRestoreTerminalReplay `
            -Subject $subject -Request $request -TerminalResult $terminalResult `
            -BackupGeneration $BackupGeneration -LifecycleLock $lock
        $terminalReplay = $true
        $request = $null
    }
    if ($null -eq $result) {
    if ($null -ne $request) {
        $resumeOperationId = ([guid][string]$active.Payload.operation_id).ToString("D")
        if (
            [string]$active.Payload.source_request_sha256 -cne
                [string]$request.PayloadSha256
        ) {
            throw "active Generation successor differs from the restore request."
        }
        [void](Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition `
            -Request $request -Intent $active -Current $current `
            -SuccessorOperationId $resumeOperationId)
        $resumeCommittedRestore = $true
    }
    $inspection = Invoke-TicketboxInstalledDatasetBackupInspection `
        $subject $BackupGeneration
    [void](Assert-TicketboxInstalledPostgresToolArtifact `
        -Subject $subject -Tool "PgRestore")
    if ($null -eq $request) {
        $predecessor = Resolve-TicketboxInstalledDatasetRestorePredecessor `
            $active $current
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
        $publicBaseUrl = Read-TicketboxInstalledDatasetPublicBaseUrl `
            -Subject $subject
        $contracts = New-TicketboxInstalledDatabaseGenerationContracts `
            -Subject $subject -PublicBaseUrl $publicBaseUrl
        $projectionContractSha256 =
            Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 `
                $contracts.Projection
        if (
            $projectionContractSha256 -cne
                [string]$authority.Intent.Payload.projection_contract_sha256
        ) {
            throw "installed projection differs from predecessor Generation authority."
        }
        $request = New-TicketboxInstalledDatasetRestoreRequest `
            -Subject $subject `
            -Authority $authority `
            -Inspection $inspection `
            -RestoreAttemptId $RestoreAttemptId `
            -ActiveDatasetId ([string]$activeDataset.DatasetId) `
            -ActiveRestoreEpoch ([int64]$activeDataset.RestoreEpoch) `
            -RestartBackend $restartBackend `
            -PublicBaseUrl $publicBaseUrl `
            -LifecycleLock $lock
        Close-TicketboxDatabaseGenerationRuntimeCredentials $authority.Credentials
        $authority.Credentials = $null
    }
    if ($null -eq $contracts) {
        $contracts = New-TicketboxInstalledDatabaseGenerationContracts `
            -Subject $subject `
            -PublicBaseUrl ([string]$request.Payload.public_base_url)
    }
    $projectionContractSha256 =
        Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 `
            $contracts.Projection
    if (
        $projectionContractSha256 -cne
            [string]$request.Payload.predecessor_intent_payload.projection_contract_sha256 -or
        (
            [string]$active.Payload.source_request_sha256 -ceq
                [string]$request.PayloadSha256 -and
            $projectionContractSha256 -cne
                [string]$active.Payload.projection_contract_sha256
        )
    ) {
        throw "restore projection differs from durable Generation authority."
    }
    $restartBackend = [bool]$request.Payload.restart_backend
    if (
        [string]$request.Payload.restore_attempt_id -cne $RestoreAttemptId -or
        [string]$request.Payload.backup_generation -cne $BackupGeneration -or
        [string]$request.Payload.backup_manifest_sha256 -cne
            [string]$inspection.Evidence.manifest_sha256 -or
        [string]$request.Payload.dataset_id -cne [string]$request.Payload.active_dataset_id
    ) {
        throw "restore request differs from the explicitly selected backup."
    }

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
    $currentDisposition = Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition `
        -Request $request -Intent $active -Current $current `
        -SuccessorOperationId $operationId
    $published = if ($currentDisposition -ceq "successor") {
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
        $active = Read-TicketboxDatabaseGenerationActiveIntent $stateRoot
        $current = Read-TicketboxDatabaseGenerationCurrent
        $currentDisposition = Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition `
            -Request $request -Intent $active -Current $current `
            -SuccessorOperationId $operationId
        $intentContext = [pscustomobject]@{
            StateRoot = $stateRoot
            Artifact = $active
        }
        $published = if ($currentDisposition -ceq "successor") {
            $current
        }
        else { $null }
        $source = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "restored-source" -AllowAbsent
        $candidateVerification = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "candidate-verification" -AllowAbsent
        if ($null -ne $candidateVerification) {
            if ($null -eq $source) {
                throw "dataset restore candidate verification lacks restored-source authority."
            }
            [void](Assert-TicketboxInstalledDatasetCandidateVerification `
                -Verification $candidateVerification `
                -Intent $active `
                -Request $request `
                -RestoredSource $source `
                -Inspection $inspection)
        }
        $runtimeVerification = Read-TicketboxDatabaseGenerationOperationArtifact `
            $stateRoot $operationId "runtime-verification" -AllowAbsent
        if ($null -ne $runtimeVerification) {
            [void](Assert-TicketboxInstalledDatasetRuntimeVerification `
                -Verification $runtimeVerification `
                -Intent $active `
                -Request $request `
                -Current $published `
                -Inspection $inspection)
        }
        $physical = Resolve-TicketboxInstalledDatasetRestorePhysicalState $paths
        $next = Resolve-TicketboxInstalledDatasetRestoreNextAction `
            -PhysicalState $physical `
            -RestoredSource $source `
            -CandidateVerification $candidateVerification `
            -PublishedCurrent $published `
            -RuntimeVerification $runtimeVerification
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
                $verified = Invoke-TicketboxInstalledDatasetRestoreHelper `
                    -Subject $subject `
                    -IntentContext $intentContext `
                    -Request $request `
                    -Inspection $inspection `
                    -Paths $paths `
                    -Candidate $candidate `
                    -Credentials $credentials `
                    -ReleaseIdentity $contracts.ReleaseIdentity
                $source = New-TicketboxInstalledDatasetRestoredSource `
                    $intentContext $request $candidate $lock
                [void](New-TicketboxInstalledDatasetCandidateVerification `
                    -IntentContext $intentContext `
                    -Request $request `
                    -RestoredSource $source `
                    -Inspection $inspection `
                    -VerificationResult $verified `
                    -LifecycleLock $lock)
            }
            "verify_candidate" {
                Stop-TicketboxInstalledDatasetWriters $subject
                if ($null -eq $candidate) {
                    Start-TicketboxPostgresqlRestoreCandidateService `
                        $subject $paths $lock
                    $candidate = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
                        $subject $operationId $credentials $bootstrapState $lock
                }
                $verified = Invoke-TicketboxInstalledDatasetRestoreHelper `
                    -Subject $subject `
                    -IntentContext $intentContext `
                    -Request $request `
                    -Inspection $inspection `
                    -Paths $paths `
                    -Candidate $candidate `
                    -Credentials $credentials `
                    -ReleaseIdentity $contracts.ReleaseIdentity
                [void](New-TicketboxInstalledDatasetCandidateVerification `
                    -IntentContext $intentContext `
                    -Request $request `
                    -RestoredSource $source `
                    -Inspection $inspection `
                    -VerificationResult $verified `
                    -LifecycleLock $lock)
            }
            "promote_candidate" {
                Stop-TicketboxInstalledDatasetWriters $subject
                if ($physical -ceq "candidate_ready") {
                    if ($null -eq $candidate) {
                        Start-TicketboxPostgresqlRestoreCandidateService `
                            $subject $paths $lock
                        $candidate = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
                            $subject $operationId $credentials $bootstrapState $lock
                    }
                    $verified = Invoke-TicketboxInstalledDatasetRestoreHelper `
                        -Subject $subject `
                        -IntentContext $intentContext `
                        -Request $request `
                        -Inspection $inspection `
                        -Paths $paths `
                        -Candidate $candidate `
                        -Credentials $credentials `
                        -ReleaseIdentity $contracts.ReleaseIdentity
                    [void](New-TicketboxInstalledDatasetCandidateVerification `
                        -IntentContext $intentContext `
                        -Request $request `
                        -RestoredSource $source `
                        -Inspection $inspection `
                        -VerificationResult $verified `
                        -LifecycleLock $lock)
                }
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
            "verify_runtime" {
                Assert-TicketboxInstalledDatasetServiceAuthority $subject
                [void](Start-TicketboxOwnedServiceIfExists `
                    -Name ([string]$subject.Identity.BackendServiceName) `
                    -ExpectedExecutable (Join-Path ([string]$subject.Identity.InstallDir) `
                        "shawl\shawl.exe") `
                    -TimeoutMilliseconds ([int]$subject.Release.service_state_timeout_ms) `
                    -PollMilliseconds ([int]$subject.Release.service_poll_interval_ms))
                Wait-TicketboxInstalledBackendHealth `
                    -BackendPort ([int]$subject.Identity.BackendPort) `
                    -BackendServiceName ([string]$subject.Identity.BackendServiceName) `
                    -ShawlExe (Join-Path ([string]$subject.Identity.InstallDir) "shawl\shawl.exe") `
                    -BackendExe (Join-Path ([string]$subject.Identity.InstallDir) `
                        "program\ticketbox-backend\ticketbox-backend.exe") `
                    -ProgramDir (Join-Path ([string]$subject.Identity.InstallDir) `
                        "program\ticketbox-backend") `
                    -AppData (Join-Path ([string]$subject.Identity.DataRoot) "app") `
                    -ReadyTimeoutMilliseconds ([int]$subject.Release.backend_ready_timeout_ms) `
                    -RequestTimeoutMilliseconds ([int]$subject.Release.backend_health_request_timeout_ms) `
                    -PollMilliseconds ([int]$subject.Release.backend_ready_poll_interval_ms) `
                    -MaximumResponseBytes 1048576
                [void](Invoke-TicketboxInstalledRestoredOriginalsVerification `
                    -Subject $subject `
                    -Inspection $inspection `
                    -Paths $paths)
                Set-TicketboxInstalledDatasetBackendDesiredState `
                    -Subject $subject -ShouldRun $restartBackend
                $runtimeVerification = New-TicketboxInstalledDatasetRuntimeVerification `
                    -IntentContext $intentContext `
                    -Request $request `
                    -Current $published `
                    -Inspection $inspection `
                    -LifecycleLock $lock
            }
            "retire_rollback" {
                Remove-TicketboxInstalledDatasetRestoreRollback $paths $lock
            }
            "done" {
                $result = [ordered]@{
                    schema = "ticketbox-complete-dataset-restore-result-v1"
                    restore_attempt_id = $RestoreAttemptId
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
    if ($null -ne $result -and -not $terminalReplay) {
        $terminalResult = New-TicketboxInstalledDatasetRestoreResult `
            -StateRoot $stateRoot `
            -Request $request `
            -Current $published `
            -Payload $result `
            -LifecycleLock $lock
        $result = $terminalResult.Payload
        Remove-TicketboxInstalledDatasetRestoreRequest $request $lock
    }
    }
}
catch {
    $primary = $_
    if (
        $null -ne $subject -and
        $null -ne $request -and
        $null -ne $paths -and
        $null -ne $stateRoot -and
        $null -ne $contracts -and
        $null -ne $inspection
    ) {
        try {
            [void](Invoke-TicketboxInstalledDatasetRestoreFailureCompensation `
                -Subject $subject -Request $request -Paths $paths `
                -StateRoot $stateRoot -Contracts $contracts `
                -Inspection $inspection `
                -LifecycleLock $lock)
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
$publicResult = [ordered]@{
    schema = "ticketbox-complete-dataset-restore-result-v1"
    restore_attempt_id = [string]$result.restore_attempt_id
    backup_id = [string]$result.backup_id
    dataset_id = [string]$result.dataset_id
    restore_epoch = [int64]$result.restore_epoch
    generation_operation_id = [string]$result.generation_operation_id
    result = [string]$result.result
}
$resultJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $publicResult
[Console]::Out.WriteLine($resultJson)
