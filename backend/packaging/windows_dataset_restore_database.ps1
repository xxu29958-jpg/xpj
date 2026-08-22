#Requires -Version 5.1

# Candidate database restore and immutable source evidence.

function Invoke-TicketboxInstalledDatasetRestoreHelper {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][object]$IntentContext,
        [Parameter(Mandatory = $true)][object]$Request,
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds
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
                "--active-installation-id", [string]$Request.Payload.installation_id,
                "--active-dataset-id", [string]$Request.Payload.active_dataset_id,
                "--active-restore-epoch", [string]$Request.Payload.active_restore_epoch,
                "--target-schema-revision", [string]$Request.Payload.target_revision,
                "--restore-role", "ticketbox_owner",
                "--generation-program-path",
                    [string]$ReleaseIdentity.DatabaseGenerationProgramRelativePath,
                "--expected-generation-program-sha256",
                    [string]$ReleaseIdentity.DatabaseGenerationProgramSha256,
                "--operation-id", [string]$IntentContext.Artifact.Payload.operation_id
            ) `
            -StandardInputText "" `
            -TimeoutMilliseconds $TimeoutMilliseconds `
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
                "schema_revision", "original_count", "generation_program_sha256",
                "resource_shape_sha256", "money_facts_sha256", "result"
            ) `
            "isolated complete dataset restore result"
        foreach ($field in @(
            "generation_program_sha256", "resource_shape_sha256", "money_facts_sha256"
        )) {
            Assert-TicketboxDatabaseGenerationLowerSha256 `
                ([string]$decoded.$field) "isolated restore $field"
        }
        $expectedEpoch = [Math]::Max(
            [int64]$Request.Payload.backup_restore_epoch,
            [int64]$Request.Payload.active_restore_epoch
        ) + 1
        if (
            [string]$decoded.schema -cne "ticketbox-isolated-dataset-restore-result-v2" -or
            [string]$decoded.result -cne "isolated_restore_candidate_verified" -or
            [string]$decoded.backup_id -cne [string]$Request.Payload.backup_id -or
            [string]$decoded.dataset_id -cne [string]$Request.Payload.dataset_id -or
            [int64]$decoded.restore_epoch -ne $expectedEpoch -or
            [string]$decoded.schema_revision -cne [string]$Request.Payload.target_revision -or
            [int64]$decoded.original_count -ne [int64]$Inspection.Evidence.original_count -or
            [string]$decoded.generation_program_sha256 -cne
                [string]$IntentContext.Artifact.Payload.generation_program_sha256
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
    Throw-TicketboxOperationFailure $primary $cleanup
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
        predecessor_current_sha256 = [string]$Request.Payload.current_sha256
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
