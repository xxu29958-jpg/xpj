# Fixed target verification and isolated restore execution.

#Requires -Version 5.1

function Get-TicketboxDatabaseGenerationTargetVerification {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][string]$Database,
        [switch]$IsRestore
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $helper = Assert-TicketboxDatabaseGenerationHelper `
        -MigrationHelperPath ([string]$ReleaseIdentity.MigrationHelperPath) `
        -MigrationHelperEvidence (Get-TicketboxDatabaseGenerationMigrationHelperEvidence $ReleaseIdentity) `
        -ExpectedMigrationHelperPath ([string]$ReleaseIdentity.MigrationHelperPath)
    $program = Assert-TicketboxDatabaseGenerationProgram `
        -ProgramPath ([string]$ReleaseIdentity.DatabaseGenerationProgramPath) `
        -ProgramEvidence (Get-TicketboxDatabaseGenerationProgramEvidence $ReleaseIdentity) `
        -ExpectedMigrationHelperPath ([string]$ReleaseIdentity.MigrationHelperPath)
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database $Database `
        -Role $($databasePolicy.MigratorRole)
    $capturedUrl = $databaseUrl
    $capturedDatabase = $Database
    $capturedHelper = $helper
    $capturedProgram = $program
    $capturedOperation = [string]$Intent.Payload.operation_id
    $capturedAttempt = if ($IsRestore) {
        [string]$Attempt.Payload.create_attempt_id
    } else { "" }
    $capturedTarget = [string]$Intent.Payload.target_revision
    $result = Invoke-TicketboxWithPlainPostgresqlSecret `
        -Secret $Credentials.MigratorPassword `
        -Action ({
            param([string]$PlainPassword)
            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $capturedUrl -Password $PlainPassword
            try {
                $arguments = @(
                    "--database-generation-verify-target",
                    "--database-url", $passfile.DatabaseUrl,
                    "--pgpassfile", $passfile.Path,
                    "--generation-program-path", $capturedProgram.Evidence.RelativePath,
                    "--expected-generation-program-sha256", $capturedProgram.Evidence.Sha256,
                    "--operation-id", $capturedOperation,
                    "--database", $capturedDatabase,
                    "--target-revision", $capturedTarget
                )
                if (-not [string]::IsNullOrEmpty($capturedAttempt)) {
                    $arguments += @("--restore-attempt-id", $capturedAttempt)
                }
                $process = Invoke-TicketboxDatabaseGenerationBoundHelper `
                    -MigrationHelperPath $capturedHelper.Path `
                    -MigrationHelperEvidence $capturedHelper.Evidence `
                    -ExpectedMigrationHelperPath $capturedHelper.Path `
                    -Arguments $arguments `
                    -PgPassFilePath $passfile.Path `
                    -StandardInputText "" `
                    -TimeoutMilliseconds $script:TicketboxDatabaseGenerationRecoveryTimeoutMs `
                    -Label "database generation target verification"
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace([string]$process.StandardError)
                ) {
                    throw "database generation target verification helper 被拒绝。"
                }
                return [string]$process.StandardOutput
            }
            finally {
                if ($null -ne $passfile) {
                    Remove-TicketboxProtectedPgPassArtifact `
                        -Path $passfile.Path `
                        -FullControlAccounts $passfile.FullControlAccounts `
                        -OwnerAccount $passfile.OwnerAccount
                }
            }
        }.GetNewClosure())
    try { $payload = $result.Trim() | ConvertFrom-Json }
    catch { throw "database generation target verification stdout 无效。" }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $payload `
        @(
            "schema", "operation_id", "database", "target_revision",
            "generation_program_sha256", "alembic_revision",
            "resource_shape_sha256", "money_facts_sha256"
        ) `
        "database generation target verification result"
    foreach ($field in @(
        "generation_program_sha256", "resource_shape_sha256", "money_facts_sha256"
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 ([string]$payload.$field) $field
    }
    if (
        [string]$payload.schema -cne
            "ticketbox-database-generation-target-verification-v1" -or
        [string]$payload.operation_id -cne [string]$Intent.Payload.operation_id -or
        [string]$payload.database -cne $Database -or
        [string]$payload.target_revision -cne [string]$Intent.Payload.target_revision -or
        [string]$payload.alembic_revision -cne [string]$Intent.Payload.target_revision -or
        [string]$payload.generation_program_sha256 -cne
            [string]$Intent.Payload.generation_program_sha256
    ) {
        throw "database generation target verification binding 漂移。"
    }
    return $payload
}

function Get-TicketboxDatabaseGenerationRestoreRevision {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$Database
    )
    $table = (Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $Database `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation restore revision inspect" `
        -Sql @"
SELECT COALESCE(to_regclass('public.alembic_version')::text, '');
"@).Trim()
    if ([string]::IsNullOrEmpty($table)) { return "" }
    if ($table -cne "alembic_version" -and $table -cne "public.alembic_version") {
        throw "database generation restore revision table identity 漂移。"
    }
    return (Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $Database `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation restore revision read" `
        -Sql @"
SELECT COALESCE(string_agg(version_num, ',' ORDER BY version_num), '')
FROM public.alembic_version;
"@).Trim()
}

function Remove-TicketboxDatabaseGenerationRestoreDatabase {
    param(
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][object]$Binding,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $database = [string]$Attempt.Payload.restore_database
    $catalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -TargetDatabase $database
    if (-not $catalog.Exists) { return }
    if (
        [string]$catalog.ClusterSystemIdentifier -cne
            [string]$Attempt.Payload.source_cluster_system_identifier
    ) {
        throw "database generation restore cleanup cluster 漂移。"
    }
    $ownerOid = Get-TicketboxDatabaseRoleOid `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -RoleName $($databasePolicy.OwnerRole)
    if ([uint32]$catalog.OwnerRoleOid -ne [uint32]$ownerOid) {
        throw "database generation restore cleanup owner 漂移。"
    }
    if (
        [uint32]$catalog.DatabaseOid -ne [uint32]$Binding.Payload.restore_database_oid -or
        [string]$catalog.Comment -cne [string]$Binding.Payload.marker
    ) {
        throw "database generation restore cleanup OID/marker 漂移。"
    }
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation restore exact cleanup" `
        -Sql @"
ALTER DATABASE "$database" ALLOW_CONNECTIONS false;
REVOKE ALL ON DATABASE "$database" FROM PUBLIC;
REVOKE ALL ON DATABASE "$database" FROM "$($databasePolicy.MigratorRole)";
DROP DATABASE "$database" WITH (FORCE);
"@ | Out-Null
    if ((Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -TargetDatabase $database).Exists) {
        throw "database generation restore cleanup 未收敛。"
    }
}

function Get-TicketboxDatabaseGenerationRestoreBinding {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $operationId = [string]$Attempt.Payload.operation_id
    $existing = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "target-recovery-binding" -AllowAbsent
    $database = [string]$Attempt.Payload.restore_database
    $catalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -TargetDatabase $database
    $ownerOid = Get-TicketboxDatabaseRoleOid `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -RoleName $($databasePolicy.OwnerRole)
    if ($null -ne $existing) {
        [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
            $null $null $Attempt $null $existing $null $null)
        if (
            -not $catalog.Exists -or
            [string]$catalog.ClusterSystemIdentifier -cne
                [string]$Attempt.Payload.source_cluster_system_identifier -or
            [uint32]$catalog.DatabaseOid -ne [uint32]$existing.Payload.restore_database_oid -or
            [uint32]$catalog.OwnerRoleOid -ne [uint32]$ownerOid -or
            [string]$catalog.Comment -cne [string]$existing.Payload.marker -or
            -not [bool]$catalog.AllowsConnections
        ) {
            throw "database generation restore binding 与 live database 漂移。"
        }
        return $existing
    }
    if (-not $catalog.Exists) {
        Assert-TicketboxLifecycleOperationLease $LifecycleLock
        Invoke-TicketboxPostgresqlDatabaseCommand `
            -Authority $HostAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Label "database generation restore database create" `
            -Sql @"
CREATE DATABASE "$database"
    OWNER "$($databasePolicy.OwnerRole)" TEMPLATE template0 ENCODING 'UTF8'
    ALLOW_CONNECTIONS false;
"@ | Out-Null
        $catalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
            -Authority $HostAuthority `
            -SuperuserPassword $SuperuserPassword `
            -TargetDatabase $database
    }
    $marker = Get-TicketboxDatabaseGenerationRestoreMarker `
        $Attempt ([uint32]$catalog.DatabaseOid)
    if (
        -not $catalog.Exists -or
        [string]$catalog.ClusterSystemIdentifier -cne
            [string]$Attempt.Payload.source_cluster_system_identifier -or
        [uint32]$catalog.DatabaseOid -eq [uint32]$Attempt.Payload.source_database_oid -or
        [uint32]$catalog.OwnerRoleOid -ne [uint32]$ownerOid -or
        [string]$catalog.Comment -cnotin @("", $marker) -or
        (
            [string]::IsNullOrEmpty([string]$catalog.Comment) -and
            [bool]$catalog.AllowsConnections
        )
    ) {
        throw "database generation restore database identity 无效。"
    }
    $markerLiteral = ConvertTo-TicketboxPostgresqlSqlLiteral $marker
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation restore database bind" `
        -Sql @"
REVOKE ALL ON DATABASE "$database" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$database" TO "$($databasePolicy.MigratorRole)";
COMMENT ON DATABASE "$database" IS $markerLiteral;
ALTER DATABASE "$database" ALLOW_CONNECTIONS true;
"@ | Out-Null
    $bound = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -TargetDatabase $database
    if (
        -not $bound.Exists -or
        [uint32]$bound.DatabaseOid -ne [uint32]$catalog.DatabaseOid -or
        [uint32]$bound.OwnerRoleOid -ne [uint32]$ownerOid -or
        [string]$bound.Comment -cne $marker -or
        -not [bool]$bound.AllowsConnections
    ) {
        throw "database generation restore database binding 未收敛。"
    }
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-recovery-binding-v1"
        operation_id = $operationId
        attempt_sha256 = [string]$Attempt.PayloadSha256
        restore_database = $database
        restore_database_oid = [string]$bound.DatabaseOid
        marker = $marker
    }
    return New-TicketboxDatabaseGenerationRecoveryArtifact `
        $StateRoot $operationId "target-recovery-binding" $payload $LifecycleLock
}

function Invoke-TicketboxDatabaseGenerationArchiveRestore {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][object]$Archive,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $database = [string]$Attempt.Payload.restore_database
    $revision = Get-TicketboxDatabaseGenerationRestoreRevision `
        $HostAuthority $SuperuserPassword $database
    if (
        -not [string]::IsNullOrEmpty($revision) -and
        $revision -cne [string]$Attempt.Payload.target_revision
    ) {
        throw "database generation restore database revision 不是 empty/target。"
    }
    $publicOwner = (Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $database `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation restore public schema owner observation" `
        -Sql @"
SELECT pg_catalog.pg_get_userbyid(namespace.nspowner)
FROM pg_catalog.pg_namespace AS namespace
WHERE namespace.nspname OPERATOR(pg_catalog.=) 'public';
"@).Trim()
    if ($publicOwner -cnotin @("pg_database_owner", $databasePolicy.OwnerRole)) {
        throw "database generation restore public schema owner 漂移。"
    }
    if ($publicOwner -ceq "pg_database_owner") {
        Assert-TicketboxLifecycleOperationLease $LifecycleLock
        Invoke-TicketboxPostgresqlDatabaseCommand `
            -Authority $HostAuthority `
            -Database $database `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Label "database generation restore public schema ownership" `
            -Sql "ALTER SCHEMA public OWNER TO `"$($databasePolicy.OwnerRole)`";" | Out-Null
    }
    if ($revision -ceq [string]$Attempt.Payload.target_revision) { return }
    $archivePath = Assert-TicketboxDatabaseGenerationRecoveryArchive $StateRoot $Archive
    $pgRestore = Assert-TicketboxDatabaseGenerationToolIdentity `
        -Path (Join-Path (Split-Path -Parent $HostAuthority.PsqlPath) "pg_restore.exe") `
        -ExpectedPath ([string]$HostContract.pg_restore_path) `
        -ExpectedSize ([int64]$HostContract.pg_restore_size) `
        -ExpectedSha256 ([string]$HostContract.pg_restore_sha256) `
        -Label "isolated pg_restore.exe"
    if (
        (Get-TicketboxPortableFileSha256 $pgRestore).ToLowerInvariant() -cne
        [string]$Archive.Payload.pg_restore_sha256
    ) { throw "recovery restore tool identity 与 archive 漂移。" }
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority $HostAuthority -Database $database -Role "postgres"
    $capturedRestore = $pgRestore
    $capturedUrl = $databaseUrl
    $capturedArchive = $archivePath
    $restoreAction = {
        param([string]$ProtectedDatabaseUrl)
        $process = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $capturedRestore `
            -Arguments @(
                "--no-password", "--exit-on-error", "--single-transaction",
                "--no-owner", "--no-privileges",
                "--role=$($databasePolicy.OwnerRole)",
                "--dbname", $ProtectedDatabaseUrl, $capturedArchive
            ) `
            -TimeoutMilliseconds $script:TicketboxDatabaseGenerationRecoveryTimeoutMs `
            -Label "database generation isolated pg_restore"
        return [int]$process.ExitCode
    }.GetNewClosure()
    $capturedRestoreAction = $restoreAction
    $plainSecretAction = {
        param([string]$PlainPassword)
        return Invoke-TicketboxWithPgPassFile `
            -DatabaseUrl $capturedUrl `
            -Password $PlainPassword `
            -Action $capturedRestoreAction
    }.GetNewClosure()
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $exitCode = Invoke-TicketboxWithPlainPostgresqlSecret `
        -Secret $SuperuserPassword `
        -Action $plainSecretAction
    if ([int]$exitCode -ne 0) {
        throw "database generation isolated pg_restore 失败。"
    }
    [void](Assert-TicketboxDatabaseGenerationToolIdentity `
        -Path $pgRestore `
        -ExpectedPath ([string]$HostContract.pg_restore_path) `
        -ExpectedSize ([int64]$HostContract.pg_restore_size) `
        -ExpectedSha256 ([string]$HostContract.pg_restore_sha256) `
        -Label "isolated pg_restore.exe after execution")
}

function Invoke-TicketboxDatabaseGenerationTargetRecovery {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceBinding,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $operationId = [string]$Intent.Payload.operation_id
    $proof = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "target-recovery-proof" -AllowAbsent
    if ($null -ne $proof) {
        $archive = Read-TicketboxDatabaseGenerationOperationArtifact `
            $StateRoot $operationId "target-recovery-archive"
        $attempt = Read-TicketboxDatabaseGenerationOperationArtifact `
            $StateRoot $operationId "target-recovery-attempt"
        $binding = Read-TicketboxDatabaseGenerationOperationArtifact `
            $StateRoot $operationId "target-recovery-binding"
        $verification = Read-TicketboxDatabaseGenerationOperationArtifact `
            $StateRoot $operationId "target-recovery-verification"
        [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
            $Intent $SourceBinding $attempt $archive $binding $verification $proof)
        [void](Assert-TicketboxDatabaseGenerationRecoveryArchive $StateRoot $archive)
        if ((Get-TicketboxPostgresqlDatabaseCatalogObservation `
            -Authority $HostAuthority `
            -SuperuserPassword $SuperuserPassword `
            -TargetDatabase $attempt.Payload.restore_database).Exists) {
            throw "database generation target proof 与 restore residue 冲突。"
        }
        return $proof
    }
    $attempt = Get-TicketboxDatabaseGenerationRecoveryAttempt `
        $StateRoot $Intent $SourceBinding $LifecycleLock
    $archive = Get-TicketboxDatabaseGenerationRecoveryArchive `
        -StateRoot $StateRoot `
        -Attempt $attempt `
        -HostContract $HostContract `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -LifecycleLock $LifecycleLock
    $binding = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "target-recovery-binding" -AllowAbsent
    $verification = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "target-recovery-verification" -AllowAbsent
    if ($null -eq $verification) {
        $binding = Get-TicketboxDatabaseGenerationRestoreBinding `
            $StateRoot $attempt $HostAuthority $SuperuserPassword $LifecycleLock
        Invoke-TicketboxDatabaseGenerationArchiveRestore `
            -StateRoot $StateRoot `
            -Attempt $attempt `
            -Archive $archive `
            -HostContract $HostContract `
            -HostAuthority $HostAuthority `
            -SuperuserPassword $SuperuserPassword `
            -LifecycleLock $LifecycleLock
        $live = Get-TicketboxDatabaseGenerationTargetVerification `
            $Intent $attempt $Credentials $ReleaseIdentity $HostAuthority `
            $($databasePolicy.DatabaseName)
        $restored = Get-TicketboxDatabaseGenerationTargetVerification `
            $Intent $attempt $Credentials $ReleaseIdentity $HostAuthority `
            ([string]$attempt.Payload.restore_database) -IsRestore
        if (
            [string]$live.resource_shape_sha256 -cne
                [string]$restored.resource_shape_sha256 -or
            [string]$live.money_facts_sha256 -cne
                [string]$restored.money_facts_sha256
        ) {
            throw "database generation isolated restore semantic digest 漂移。"
        }
        $verificationPayload = [ordered]@{
            schema = "ticketbox-database-generation-recovery-verification-v1"
            operation_id = $operationId
            attempt_sha256 = [string]$attempt.PayloadSha256
            binding_sha256 = [string]$binding.PayloadSha256
            archive_sha256 = [string]$archive.Payload.archive_sha256
            live_result_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
                ConvertTo-TicketboxDatabaseGenerationCanonicalJson $live)
            restored_result_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
                ConvertTo-TicketboxDatabaseGenerationCanonicalJson $restored)
            target_revision = [string]$Intent.Payload.target_revision
            generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
            resource_shape_sha256 = [string]$live.resource_shape_sha256
            money_facts_sha256 = [string]$live.money_facts_sha256
        }
        $verification = New-TicketboxDatabaseGenerationRecoveryArtifact `
            $StateRoot $operationId "target-recovery-verification" `
            $verificationPayload $LifecycleLock
    }
    if ($null -eq $binding) {
        $binding = Read-TicketboxDatabaseGenerationOperationArtifact `
            $StateRoot $operationId "target-recovery-binding"
    }
    [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
        $Intent $SourceBinding $attempt $archive $binding $verification $null)
    Remove-TicketboxDatabaseGenerationRestoreDatabase `
        $attempt $binding $HostAuthority $SuperuserPassword $LifecycleLock
    $proofPayload = [ordered]@{
        schema = "ticketbox-database-generation-isolated-recovery-proof-v1"
        operation_id = $operationId
        intent_sha256 = [string]$Intent.PayloadSha256
        source_binding_sha256 = [string]$SourceBinding.PayloadSha256
        target_revision = [string]$Intent.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        attempt_sha256 = [string]$attempt.PayloadSha256
        archive_sha256 = [string]$archive.Payload.archive_sha256
        verification_sha256 = [string]$verification.PayloadSha256
        restore_database_oid = [string]$binding.Payload.restore_database_oid
        cleanup_state = "restore_database_absent"
        result = "isolated_restore_verified"
    }
    $proof = New-TicketboxDatabaseGenerationRecoveryArtifact `
        $StateRoot $operationId "target-recovery-proof" $proofPayload $LifecycleLock
    [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
        $Intent $SourceBinding $attempt $archive $binding $verification $proof)
    return $proof
}
