#Requires -Version 5.1

# Runtime projection, health evidence, and failure compensation for restore.

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

function Invoke-TicketboxInstalledRestoredOriginalsVerification {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][object]$Paths
    )
    $evidence = $Subject.Manifest.DatabaseMaintenanceHelper
    $helper = Join-Path ([string]$Subject.Identity.InstallDir) `
        "program\ticketbox-backend\ticketbox-database-maintenance.exe"
    $lease = $null
    $primary = $null
    $cleanup = @()
    $decoded = $null
    try {
        $lease = Open-TicketboxVerifiedDatabaseMaintenanceHelperLease `
            -Path $helper `
            -ExpectedRelativePath ([string]$evidence.RelativePath) `
            -ExpectedSize ([int64]$evidence.Size) `
            -ExpectedSha256 ([string]$evidence.Sha256)
        $process = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $lease.Path `
            -Arguments @(
                "--verify-restored-originals",
                "--backup-generation", [string]$Inspection.GenerationPath,
                "--restored-upload-root", [string]$Paths.stable_uploads
            ) `
            -StandardInputText "" `
            -TimeoutMilliseconds ([int]$Subject.Release.dataset_payload_verification_timeout_ms) `
            -Label "restored originals verification" `
            -ChildEnvironment (New-TicketboxDatabaseGenerationHelperChildEnvironment `
                -PgPassFilePath "")
        if ([int]$process.ExitCode -ne 0 -or $process.StandardError.Trim().Length -ne 0) {
            throw "restored originals verification failed; native output is suppressed."
        }
        $decoded = (Get-TicketboxDatabaseGenerationJsonLine `
            -StandardOutput ([string]$process.StandardOutput) `
            -Label "restored originals verification") | ConvertFrom-Json
        Assert-TicketboxDatabaseGenerationExactProperties `
            -Value $decoded `
            -ExpectedNames @(
                "schema", "backup_id", "dataset_id", "restore_epoch",
                "schema_revision", "original_count", "result"
            ) `
            -Label "restored originals verification"
        if (
            [string]$decoded.schema -cne "ticketbox-restored-originals-verification-v1" -or
            [string]$decoded.backup_id -cne [string]$Inspection.Evidence.backup_id -or
            [string]$decoded.dataset_id -cne [string]$Inspection.Evidence.dataset_id -or
            [int64]$decoded.restore_epoch -ne [int64]$Inspection.Evidence.restore_epoch -or
            [string]$decoded.schema_revision -cne [string]$Inspection.Evidence.schema_revision -or
            [int64]$decoded.original_count -ne [int64]$Inspection.Evidence.original_count -or
            [string]$decoded.result -cne "restored_originals_verified"
        ) {
            throw "restored originals verification differs from the selected backup."
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
    Throw-TicketboxOperationFailure $primary $cleanup
    return $decoded
}

function New-TicketboxInstalledDatasetRuntimeVerification {
    param(
        [Parameter(Mandatory = $true)][object]$IntentContext,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $intent = $IntentContext.Artifact
    $payload = [ordered]@{
        schema = "ticketbox-installed-dataset-runtime-verification-v1"
        operation_id = [string]$intent.Payload.operation_id
        intent_sha256 = [string]$intent.PayloadSha256
        source_request_sha256 = [string]$Request.PayloadSha256
        current_sha256 = [string]$Current.PayloadSha256
        backup_manifest_sha256 = [string]$Request.Payload.backup_manifest_sha256
        backup_id = [string]$Request.Payload.backup_id
        dataset_id = [string]$Request.Payload.dataset_id
        restore_epoch = [Math]::Max(
            [int64]$Request.Payload.backup_restore_epoch,
            [int64]$Request.Payload.active_restore_epoch
        ) + 1
        original_count = [int64]$Inspection.Evidence.original_count
        health_contract = "ticketbox-installation-health-v2"
        result = "restored_runtime_verified"
    }
    return New-TicketboxDatabaseGenerationChainedArtifact `
        -StateRoot $IntentContext.StateRoot `
        -OperationId ([string]$intent.Payload.operation_id) `
        -Kind "runtime-verification" `
        -Payload $payload `
        -LifecycleLock $LifecycleLock
}

function Set-TicketboxInstalledDatasetBackendDesiredState {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][bool]$ShouldRun
    )
    Assert-TicketboxInstalledDatasetServiceAuthority $Subject
    $identity = $Subject.Identity
    $release = $Subject.Release
    $shawl = Join-Path ([string]$identity.InstallDir) "shawl\shawl.exe"
    if ($ShouldRun) {
        [void](Start-TicketboxOwnedServiceIfExists `
            -Name ([string]$identity.BackendServiceName) `
            -ExpectedExecutable $shawl `
            -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
            -PollMilliseconds ([int]$release.service_poll_interval_ms))
        return
    }
    Stop-TicketboxOwnedServiceIfExists `
        -Name ([string]$identity.BackendServiceName) `
        -ExpectedExecutable $shawl `
        -TimeoutMilliseconds ([int]$release.service_state_timeout_ms) `
        -PollMilliseconds ([int]$release.service_poll_interval_ms) `
        -BackendPort ([int]$identity.BackendPort) `
        -ExpectedRuntimeExecutables @(
            (Join-Path ([string]$identity.InstallDir) `
                "program\ticketbox-backend\ticketbox-backend.exe"),
            $shawl
        )
}

function Complete-TicketboxInstalledDatasetRestoreTerminalReplay {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][AllowNull()][object]$Request,
        [Parameter(Mandatory = $true)][object]$TerminalResult,
        [Parameter(Mandatory = $true)][string]$BackupGeneration,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $terminal = $TerminalResult.Artifact.Payload
    if ($null -ne $Request) {
        if (
            [string]$Request.Payload.operation_id -cne
                [string]$terminal.restore_attempt_id -or
            [string]$Request.PayloadSha256 -cne [string]$terminal.request_sha256 -or
            [string]$Request.Payload.backup_generation -cne $BackupGeneration -or
            [string]$Request.Payload.release_manifest_sha256 -cne
                [string]$terminal.release_manifest_sha256
        ) {
            throw "terminal restore result differs from its remaining request."
        }
        if ([string]$TerminalResult.Disposition -ceq "current") {
            Set-TicketboxInstalledDatasetBackendDesiredState `
                -Subject $Subject `
                -ShouldRun ([bool]$Request.Payload.restart_backend)
        }
        Remove-TicketboxInstalledDatasetOperation $Request $LifecycleLock
    }
    return [ordered]@{
        schema = "ticketbox-complete-dataset-restore-result-v1"
        restore_attempt_id = [string]$terminal.restore_attempt_id
        backup_id = [string]$terminal.backup_id
        dataset_id = [string]$terminal.dataset_id
        restore_epoch = [int64]$terminal.restore_epoch
        generation_operation_id = [string]$terminal.generation_operation_id
        result = if ([string]$TerminalResult.Disposition -ceq "current") {
            "current_published"
        }
        else { "superseded" }
    }
}

function Restore-TicketboxInstalledDatasetPredecessorRuntime {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Contracts,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    [void](Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition `
        -Request $Request -Intent $Intent -Current $Current)
    $projectionContractSha256 =
        Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 `
            $Contracts.Projection
    if (
        $projectionContractSha256 -cne
            [string]$Request.Payload.predecessor_intent_payload.projection_contract_sha256
    ) {
        throw "dataset restore predecessor projection contract differs from durable authority."
    }
    $intent = [pscustomobject]@{
        PayloadSha256 = [string]$Request.Payload.predecessor_intent_sha256
        Payload = $Request.Payload.predecessor_intent_payload
    }
    $candidate = Read-TicketboxDatabaseGenerationOperationArtifact `
        -StateRoot $StateRoot `
        -OperationId ([string]$intent.Payload.operation_id) `
        -Kind "candidate"
    $target = $Request.Payload.predecessor_current_payload
    if (
        [string]$target.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$target.candidate_sha256 -cne [string]$candidate.PayloadSha256
    ) {
        throw "dataset restore predecessor runtime artifacts differ from CURRENT."
    }
    $credentials = $null
    $primary = $null
    $cleanup = @()
    try {
        $credentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
            -StateRoot $StateRoot -Intent $intent -Candidate $candidate
        $hostAuthority = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority `
            $Contracts.Host
        Set-TicketboxInstalledDatasetRestorePhysicalSelection `
            -Paths $Paths -Selection "Predecessor"
        Set-TicketboxInstalledDatasetPublishedAcls $Subject $Paths
        [void](Start-TicketboxOwnedServiceIfExists `
            -Name ([string]$Subject.Identity.PgServiceName) `
            -ExpectedExecutable (Join-Path ([string]$Subject.Identity.InstallDir) `
                "pg\bin\pg_ctl.exe") `
            -TimeoutMilliseconds ([int]$Subject.Release.service_state_timeout_ms) `
            -PollMilliseconds ([int]$Subject.Release.service_poll_interval_ms))
        [void](Publish-TicketboxDatabaseGenerationRuntimeProjection `
            $intent $candidate $credentials $hostAuthority `
            $Contracts.Projection $LifecycleLock)
        [void](Restore-TicketboxInstalledDatabaseGenerationPredecessor `
            -PredecessorCurrentPayload $target `
            -LifecycleLock $LifecycleLock)
    }
    catch { $primary = $_ }
    finally {
        if ($null -ne $credentials) {
            try { Close-TicketboxDatabaseGenerationRuntimeCredentials $credentials }
            catch { $cleanup += $_ }
        }
    }
    Throw-TicketboxOperationFailure $primary $cleanup
}

function Invoke-TicketboxInstalledDatasetRestoreFailureCompensation {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Contracts,
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $failureCurrent = Read-TicketboxDatabaseGenerationCurrent
    $successorOperationId = ([guid][string]$Paths.operation_id).ToString("D")
    $failureIntent = Read-TicketboxDatabaseGenerationActiveIntent $StateRoot
    $currentDisposition = Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition `
        -Request $Request -Intent $failureIntent -Current $failureCurrent
    $durableRuntimeVerification = `
        Read-TicketboxDatabaseGenerationOperationArtifact `
            -StateRoot $StateRoot `
            -OperationId $successorOperationId `
            -Kind "runtime-verification" `
            -AllowAbsent
    if ($null -ne $durableRuntimeVerification) {
        if ($currentDisposition -cne "successor_current") {
            throw "verified dataset restore no longer owns CURRENT."
        }
        [void](Assert-TicketboxInstalledDatasetRuntimeVerification `
            -Verification $durableRuntimeVerification `
            -Intent $failureIntent `
            -Request $Request `
            -Current $failureCurrent `
            -Inspection $Inspection)
        Set-TicketboxInstalledDatasetBackendDesiredState `
            -Subject $Subject `
            -ShouldRun ([bool]$Request.Payload.restart_backend)
        return "committed"
    }

    $failures = @()
    try {
        Remove-TicketboxPostgresqlRestoreCandidateService $Subject $Paths
    }
    catch { $failures += $_ }
    try {
        Stop-TicketboxInstalledDatasetWriters $Subject
        Restore-TicketboxInstalledDatasetPredecessorRuntime `
            -Subject $Subject -Request $Request -Paths $Paths `
            -StateRoot $StateRoot -Contracts $Contracts -Intent $failureIntent `
            -Current $failureCurrent -LifecycleLock $LifecycleLock
        Set-TicketboxInstalledDatasetBackendDesiredState `
            -Subject $Subject `
            -ShouldRun ([bool]$Request.Payload.restart_backend)
    }
    catch { $failures += $_ }
    if ($failures.Count -gt 0) {
        Throw-TicketboxOperationFailure $null $failures
    }
    return "rolled_back"
}
