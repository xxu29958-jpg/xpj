#Requires -Version 5.1

# Empty-source normalization is the only place that knows first-install
# bootstrap facts.  Its durable output is a SourceBinding; no later phase sees
# fresh/legacy/runtime modes or any retired READY marker.

function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {
    param([Parameter(Mandatory = $true)][object]$HostContract)
    Assert-TicketboxDatabaseGenerationExactProperties `
        $HostContract `
        @(
            "backend_service_name", "data_root", "install_dir", "pg_ctl_path",
            "pg_service_name", "pg_dump_path", "pg_dump_size",
            "pg_dump_sha256", "pg_restore_path", "pg_restore_size",
            "pg_restore_sha256", "release_config"
        ) `
        "database generation host contract"
    $shapes = @(Get-TicketboxReleaseServiceIdentityShapes `
        -Config $HostContract.release_config `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -TargetConfig $HostContract.release_config)
    $authority = Resolve-TicketboxPostgresServiceHostAuthority `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -ExpectedPgCtlPath ([string]$HostContract.pg_ctl_path) `
        -DataRoot ([string]$HostContract.data_root) `
        -InstallDir ([string]$HostContract.install_dir) `
        -BackendServiceName ([string]$HostContract.backend_service_name) `
        -AllowedServiceIdentityShapes $shapes
    return [pscustomobject]@{
        Schema = "ticketbox-postgresql-host-authority-v1"
        ServiceName = [string]$authority.ServiceName
        ServiceProcessId = [int]$authority.ServiceProcessId
        PostmasterProcessId = [int]$authority.PostmasterProcessId
        PgCtlPath = [string]$authority.PgCtlPath
        PsqlPath = [string]$authority.PsqlPath
        PgData = [string]$authority.PgData
        PhysicalPgData = [string]$authority.PhysicalPgData
        Port = [int]$authority.Port
        UsesRuntimeBinding = [bool]$authority.UsesRuntimeBinding
        DataVolumeIdentity = [string]$authority.DataVolumeIdentity
    }
}

function New-TicketboxDatabaseGenerationEmptyRoleSql {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$RuntimeVerifier,
        [Parameter(Mandatory = $true)][string]$MigratorVerifier,
        [Parameter(Mandatory = $true)][string]$BackupVerifier,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $operation = ([guid]$OperationId).ToString("D")
    if (
        $RuntimeVerifier -cnotmatch '^SCRAM-SHA-256\$4096:' -or
        $MigratorVerifier -cnotmatch '^SCRAM-SHA-256\$4096:' -or
        $BackupVerifier -cnotmatch '^SCRAM-SHA-256\$4096:'
    ) {
        throw "empty source 只接受 SCRAM-SHA-256 verifier。"
    }
    $runtimeVerifierSql = ConvertTo-TicketboxPostgresqlSqlLiteral $RuntimeVerifier
    $migratorVerifierSql = ConvertTo-TicketboxPostgresqlSqlLiteral $MigratorVerifier
    $backupVerifierSql = ConvertTo-TicketboxPostgresqlSqlLiteral $BackupVerifier
    $validUntil = $MigratorValidUntilUtc.ToUniversalTime().ToString(
        "yyyy-MM-ddTHH:mm:ss.fffZ",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $validUntilSql = ConvertTo-TicketboxPostgresqlSqlLiteral $validUntil
    $operationSql = ConvertTo-TicketboxPostgresqlSqlLiteral $operation
    return @"
SET log_statement = 'none';
SET log_min_duration_statement = -1;
SET log_min_error_statement = 'panic';
BEGIN;
DO `$ticketbox_generation_roles`$
DECLARE
    existing_count integer;
    role_name text;
    role_oid oid;
    expected_comment text;
    actual_comment text;
BEGIN
    SELECT count(*) INTO existing_count
    FROM pg_roles
    WHERE rolname IN (
        '$($databasePolicy.OwnerRole)',
        '$($databasePolicy.MigratorRole)',
        '$($databasePolicy.RuntimeRole)',
        '$($databasePolicy.BackupRole)'
    );
    IF existing_count NOT IN (0, 4) THEN
        RAISE EXCEPTION 'partial database-generation role residue';
    END IF;
    IF existing_count = 0 THEN
        CREATE ROLE "$($databasePolicy.OwnerRole)"
            NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
        CREATE ROLE "$($databasePolicy.RuntimeRole)"
            NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0
            PASSWORD $runtimeVerifierSql;
        CREATE ROLE "$($databasePolicy.MigratorRole)"
            LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
            PASSWORD $migratorVerifierSql VALID UNTIL $validUntilSql;
        CREATE ROLE "$($databasePolicy.BackupRole)"
            NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0
            PASSWORD $backupVerifierSql;
        FOREACH role_name IN ARRAY ARRAY[
            '$($databasePolicy.OwnerRole)',
            '$($databasePolicy.MigratorRole)',
            '$($databasePolicy.RuntimeRole)',
            '$($databasePolicy.BackupRole)'
        ] LOOP
            SELECT oid INTO STRICT role_oid FROM pg_roles WHERE rolname = role_name;
            expected_comment := format(
                'ticketbox-database-generation-role-v1|%s|%s|%s',
                $operationSql, role_name, role_oid
            );
            EXECUTE format('COMMENT ON ROLE %I IS %L', role_name, expected_comment);
        END LOOP;
    ELSE
        FOREACH role_name IN ARRAY ARRAY[
            '$($databasePolicy.OwnerRole)',
            '$($databasePolicy.MigratorRole)',
            '$($databasePolicy.RuntimeRole)',
            '$($databasePolicy.BackupRole)'
        ] LOOP
            SELECT oid, shobj_description(oid, 'pg_authid')
            INTO STRICT role_oid, actual_comment
            FROM pg_roles WHERE rolname = role_name;
            expected_comment := format(
                'ticketbox-database-generation-role-v1|%s|%s|%s',
                $operationSql, role_name, role_oid
            );
            IF actual_comment IS DISTINCT FROM expected_comment THEN
                RAISE EXCEPTION 'database-generation role identity mismatch for %', role_name;
            END IF;
        END LOOP;
        IF (SELECT rolpassword FROM pg_authid
            WHERE rolname = '$($databasePolicy.RuntimeRole)')
              IS DISTINCT FROM $runtimeVerifierSql
           OR (SELECT rolpassword FROM pg_authid
            WHERE rolname = '$($databasePolicy.MigratorRole)')
              IS DISTINCT FROM $migratorVerifierSql
           OR (SELECT rolpassword FROM pg_authid
            WHERE rolname = '$($databasePolicy.BackupRole)')
              IS DISTINCT FROM $backupVerifierSql THEN
            RAISE EXCEPTION 'database-generation role credential mismatch';
        END IF;
    END IF;
    ALTER ROLE "$($databasePolicy.OwnerRole)"
        NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS;
    ALTER ROLE "$($databasePolicy.RuntimeRole)"
        NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0;
    ALTER ROLE "$($databasePolicy.MigratorRole)"
        LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
        VALID UNTIL $validUntilSql;
    ALTER ROLE "$($databasePolicy.BackupRole)"
        NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0;
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE (granted.rolname IN (
                   '$($databasePolicy.OwnerRole)',
                   '$($databasePolicy.MigratorRole)',
                   '$($databasePolicy.RuntimeRole)',
                   '$($databasePolicy.BackupRole)'
               )
               OR member.rolname IN (
                   '$($databasePolicy.OwnerRole)',
                   '$($databasePolicy.MigratorRole)',
                   '$($databasePolicy.RuntimeRole)',
                   '$($databasePolicy.BackupRole)'
               ))
          AND NOT (
              granted.rolname = '$($databasePolicy.OwnerRole)'
              AND member.rolname = '$($databasePolicy.MigratorRole)'
              AND NOT membership.admin_option
              AND NOT membership.inherit_option
              AND membership.set_option
          )
    ) THEN
        RAISE EXCEPTION 'foreign database-generation role membership residue';
    END IF;
    GRANT "$($databasePolicy.OwnerRole)" TO "$($databasePolicy.MigratorRole)"
        WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
    REVOKE "$($databasePolicy.OwnerRole)" FROM "$($databasePolicy.RuntimeRole)";
    REVOKE "$($databasePolicy.OwnerRole)" FROM "$($databasePolicy.BackupRole)";
END
`$ticketbox_generation_roles`$;
COMMIT;
"@
}

function Assert-TicketboxDatabaseGenerationEmptySchema {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $raw = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation zero-write empty-source classification" `
        -Sql @"
SELECT
    count(*)::text,
    COALESCE(to_regclass('public.alembic_version')::text, '')
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
  AND namespace.nspname NOT LIKE 'pg_toast%'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f');
"@
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output ([string]$raw) `
        -FieldCount 2 `
        -Label "database generation empty-source schema observation"
    if ([string]$fields[0] -cne "0" -or -not [string]::IsNullOrEmpty([string]$fields[1])) {
        throw "database generation empty source contains schema or Alembic state."
    }
}

function Invoke-TicketboxDatabaseGenerationEmptySource {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$MaintenanceAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $null = Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
        $MaintenanceAuthority $Intent $HostAuthority $LifecycleLock
    $superuserPassword = $MaintenanceAuthority.Secret
    $temporaryDatabase = "ticketbox_generation_" + ([guid]$operationId).ToString("N")
    $targetCatalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $superuserPassword `
        -TargetDatabase $($databasePolicy.DatabaseName)
    $temporaryCatalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $superuserPassword `
        -TargetDatabase $temporaryDatabase
    $attempt = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "source-create-attempt" -AllowAbsent
    if ($null -eq $attempt) {
        if ($targetCatalog.Exists -or $temporaryCatalog.Exists) {
            throw "database generation fresh-only source is not absent before mutation."
        }
        $attempt = New-TicketboxDatabaseGenerationChainedArtifact `
            $StateRoot $operationId "source-create-attempt" ([ordered]@{
                schema = "ticketbox-database-generation-source-create-attempt-v1"
                operation_id = $operationId
                intent_sha256 = [string]$Intent.PayloadSha256
                cluster_system_identifier = [string]$targetCatalog.ClusterSystemIdentifier
                database_name = $($databasePolicy.DatabaseName)
                temporary_database = $temporaryDatabase
                observed_target_absent = $true
            }) $LifecycleLock
    }
    if (
        [string]$attempt.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$attempt.Payload.cluster_system_identifier -cne
            [string]$targetCatalog.ClusterSystemIdentifier -or
        [string]$attempt.Payload.database_name -cne $($databasePolicy.DatabaseName) -or
        [string]$attempt.Payload.temporary_database -cne $temporaryDatabase -or
        -not [bool]$attempt.Payload.observed_target_absent -or
        ($targetCatalog.Exists -and $temporaryCatalog.Exists)
    ) {
        throw "database generation source create-attempt or cluster identity drifted."
    }
    if ($targetCatalog.Exists) {
        $expectedOwnerOid = Get-TicketboxDatabaseRoleOid `
            -Authority $HostAuthority `
            -SuperuserPassword $superuserPassword `
            -RoleName $($databasePolicy.OwnerRole)
        $expectedMarker = (
            "ticketbox-database-generation-empty-source-v1|$operationId|" +
            "$($targetCatalog.ClusterSystemIdentifier)|$($targetCatalog.DatabaseOid)"
        )
        if (
            [uint32]$targetCatalog.OwnerRoleOid -ne $expectedOwnerOid -or
            [string]$targetCatalog.Comment -cne $expectedMarker
        ) {
            throw "database generation existing database is not this operation's empty source."
        }
        Assert-TicketboxDatabaseGenerationEmptySchema `
            $HostAuthority $superuserPassword
    }
    $validUntil = [DateTime]::UtcNow.AddHours(1)
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation empty-source roles" `
        -Sql (New-TicketboxDatabaseGenerationEmptyRoleSql `
            -OperationId $operationId `
            -RuntimeVerifier ([string]$Credentials.RuntimeVerifier) `
            -MigratorVerifier ([string]$Credentials.MigratorVerifier) `
            -BackupVerifier ([string]$Credentials.BackupVerifier) `
            -MigratorValidUntilUtc $validUntil) | Out-Null
    $catalog = $targetCatalog
    if (-not $catalog.Exists) {
        if (-not $temporaryCatalog.Exists) {
            Invoke-TicketboxPostgresqlDatabaseCommand `
                -Authority $HostAuthority `
                -Database "postgres" `
                -Role "postgres" `
                -Password $superuserPassword `
                -Label "database generation operation-bound database create" `
                -Sql @"
CREATE DATABASE "$temporaryDatabase"
    OWNER "$($databasePolicy.OwnerRole)" TEMPLATE template0 ENCODING 'UTF8'
    ALLOW_CONNECTIONS false;
"@ | Out-Null
            $temporaryCatalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
                -Authority $HostAuthority `
                -SuperuserPassword $superuserPassword `
                -TargetDatabase $temporaryDatabase
        }
        $expectedOwnerOid = Get-TicketboxDatabaseRoleOid `
            -Authority $HostAuthority `
            -SuperuserPassword $superuserPassword `
            -RoleName $($databasePolicy.OwnerRole)
        if (
            -not $temporaryCatalog.Exists -or
            [uint32]$temporaryCatalog.OwnerRoleOid -ne $expectedOwnerOid
        ) {
            throw "database generation operation-bound database owner drifted."
        }
        $temporaryMarker = (
            "ticketbox-database-generation-empty-source-v1|$operationId|" +
            "$($temporaryCatalog.ClusterSystemIdentifier)|$($temporaryCatalog.DatabaseOid)"
        )
        if ([string]::IsNullOrEmpty([string]$temporaryCatalog.Comment)) {
            $temporaryMarkerSql = ConvertTo-TicketboxPostgresqlSqlLiteral $temporaryMarker
            Invoke-TicketboxPostgresqlDatabaseCommand `
                -Authority $HostAuthority `
                -Database "postgres" `
                -Role "postgres" `
                -Password $superuserPassword `
                -Label "database generation operation-bound database identity" `
                -Sql "COMMENT ON DATABASE `"$temporaryDatabase`" IS $temporaryMarkerSql;" | Out-Null
        }
        elseif ([string]$temporaryCatalog.Comment -cne $temporaryMarker) {
            throw "database generation temporary database identity drifted."
        }
        Invoke-TicketboxPostgresqlDatabaseCommand `
            -Authority $HostAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $superuserPassword `
            -Label "database generation operation-bound database publish" `
            -Sql "ALTER DATABASE `"$temporaryDatabase`" RENAME TO `"$($databasePolicy.DatabaseName)`";" | Out-Null
        $catalog = Get-TicketboxPostgresqlDatabaseCatalogObservation `
            -Authority $HostAuthority `
            -SuperuserPassword $superuserPassword `
            -TargetDatabase $($databasePolicy.DatabaseName)
    }
    $expectedOwnerOid = Get-TicketboxDatabaseRoleOid `
        -Authority $HostAuthority `
        -SuperuserPassword $superuserPassword `
        -RoleName $($databasePolicy.OwnerRole)
    if (-not $catalog.Exists -or [uint32]$catalog.OwnerRoleOid -ne $expectedOwnerOid) {
        throw "database generation empty source 缺少 exact database/owner。"
    }
    $expectedComment = (
        "ticketbox-database-generation-empty-source-v1|$operationId|" +
        "$($catalog.ClusterSystemIdentifier)|$($catalog.DatabaseOid)"
    )
    if ([string]::IsNullOrEmpty([string]$catalog.Comment)) {
        throw "database generation published database lost its operation identity."
    }
    elseif ([string]$catalog.Comment -cne $expectedComment) {
        throw "database generation empty source database identity 漂移。"
    }
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation empty-source admission" `
        -Sql @"
BEGIN;
REVOKE ALL ON DATABASE "$($databasePolicy.DatabaseName)" FROM PUBLIC;
REVOKE ALL ON DATABASE "$($databasePolicy.DatabaseName)"
    FROM "$($databasePolicy.RuntimeRole)", "$($databasePolicy.MigratorRole)";
GRANT CONNECT ON DATABASE "$($databasePolicy.DatabaseName)"
    TO "$($databasePolicy.MigratorRole)";
ALTER DATABASE "$($databasePolicy.DatabaseName)" ALLOW_CONNECTIONS true;
COMMIT;
"@ | Out-Null
    Assert-TicketboxDatabaseGenerationEmptySchema `
        $HostAuthority $superuserPassword
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation empty-source ACL" `
        -Sql (New-TicketboxDatabaseRuntimeAclSql -PreserveRuntimeFence) | Out-Null
    Assert-TicketboxDatabaseCredential `
        -Authority $HostAuthority `
        -Password $Credentials.MigratorPassword `
        -CredentialKind "migrator"
    Assert-TicketboxDatabaseRolePolicy `
        -Authority $HostAuthority `
        -SuperuserPassword $superuserPassword `
        -Phase "fenced"
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation empty-source ACL attestation" `
        -Sql (New-TicketboxDatabaseForeignAclGuardSql $databasePolicy) | Out-Null
    Assert-TicketboxDatabaseGenerationEmptySchema `
        $HostAuthority $superuserPassword
    $fence = Get-TicketboxDatabaseGenerationFrozenFence $HostAuthority $superuserPassword
    $final = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $superuserPassword `
        -TargetDatabase $($databasePolicy.DatabaseName)
    if (
        -not $final.Exists -or -not $final.AllowsConnections -or
        [string]$final.Comment -cne $expectedComment -or
        [uint32]$final.DatabaseOid -ne [uint32]$catalog.DatabaseOid
    ) {
        throw "database generation empty SourceBinding live identity 未收敛。"
    }
    return [ordered]@{
        schema = "ticketbox-database-generation-source-binding-v1"
        operation_id = $operationId
        intent_sha256 = [string]$Intent.PayloadSha256
        source_evidence_sha256 = [string]$attempt.PayloadSha256
        source_kind = "empty"
        source_revision = "base"
        cluster_system_identifier = [string]$final.ClusterSystemIdentifier
        database_oid = [uint32]$final.DatabaseOid
        writer_fence_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
        )
    }
}

function Invoke-TicketboxDatabaseGenerationRestoredSource {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceEvidence,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$MaintenanceAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    [void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
        $MaintenanceAuthority $Intent $HostAuthority $LifecycleLock)
    Assert-TicketboxDatabaseGenerationExactProperties `
        $SourceEvidence.Payload `
        @(
            "schema", "operation_id", "intent_sha256",
            "source_request_sha256", "predecessor_current_sha256",
            "backup_manifest_sha256", "backup_id", "dataset_id",
            "restore_epoch", "source_revision",
            "cluster_system_identifier", "database_oid",
            "writer_fence_sha256", "result"
        ) `
        "database generation restored source evidence"
    foreach ($digest in @(
        [string]$SourceEvidence.PayloadSha256,
        [string]$SourceEvidence.Payload.source_request_sha256,
        [string]$SourceEvidence.Payload.predecessor_current_sha256,
        [string]$SourceEvidence.Payload.backup_manifest_sha256,
        [string]$SourceEvidence.Payload.writer_fence_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $digest "database generation restored source"
    }
    $backupId = ([guid][string]$SourceEvidence.Payload.backup_id).ToString("D")
    $datasetId = ([guid][string]$SourceEvidence.Payload.dataset_id).ToString("D")
    if (
        [string]$SourceEvidence.Payload.schema -cne
            "ticketbox-database-generation-restored-source-v1" -or
        [string]$SourceEvidence.Payload.operation_id -cne
            [string]$Intent.Payload.operation_id -or
        [string]$SourceEvidence.Payload.intent_sha256 -cne
            [string]$Intent.PayloadSha256 -or
        [string]$SourceEvidence.Payload.source_request_sha256 -cne
            [string]$Intent.Payload.source_request_sha256 -or
        [string]$SourceEvidence.Payload.predecessor_current_sha256 -cne
            [string]$Intent.Payload.expected_predecessor_sha256 -or
        [string]$SourceEvidence.Payload.source_revision -cne
            [string]$Intent.Payload.target_revision -or
        $backupId -cne [string]$SourceEvidence.Payload.backup_id -or
        $datasetId -cne [string]$SourceEvidence.Payload.dataset_id -or
        [int64]$SourceEvidence.Payload.restore_epoch -lt 0 -or
        [string]$SourceEvidence.Payload.result -cne
            "isolated_restore_candidate_ready"
    ) {
        throw "restored source evidence 与 exact generation intent 漂移。"
    }
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $live = Get-TicketboxPostgresqlDatabaseCatalogObservation `
        -Authority $HostAuthority `
        -SuperuserPassword $MaintenanceAuthority.Secret `
        -TargetDatabase ([string]$databasePolicy.DatabaseName)
    $liveIdentity = Get-TicketboxDatabaseGenerationLiveIdentity `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $MaintenanceAuthority.Secret
    if (
        -not [bool]$live.Exists -or
        [string]$live.ClusterSystemIdentifier -cne
            [string]$SourceEvidence.Payload.cluster_system_identifier -or
        [uint32]$live.DatabaseOid -ne [uint32]$SourceEvidence.Payload.database_oid -or
        [string]$liveIdentity.ClusterSystemIdentifier -cne
            [string]$SourceEvidence.Payload.cluster_system_identifier -or
        [uint32]$liveIdentity.DatabaseOid -ne [uint32]$SourceEvidence.Payload.database_oid -or
        [string]$liveIdentity.DatasetId -cne [string]$SourceEvidence.Payload.dataset_id -or
        [int64]$liveIdentity.RestoreEpoch -ne [int64]$SourceEvidence.Payload.restore_epoch -or
        [string]$liveIdentity.SchemaRevision -cne
            [string]$SourceEvidence.Payload.source_revision
    ) {
        throw "restored source live dataset authority 漂移。"
    }
    $fence = Get-TicketboxDatabaseGenerationFrozenFence `
        $HostAuthority $MaintenanceAuthority.Secret
    $fenceSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
    )
    if ($fenceSha256 -cne [string]$SourceEvidence.Payload.writer_fence_sha256) {
        throw "restored source writer fence 漂移。"
    }
    return [ordered]@{
        schema = "ticketbox-database-generation-source-binding-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        source_evidence_sha256 = [string]$SourceEvidence.PayloadSha256
        source_kind = "current_generation"
        source_revision = [string]$SourceEvidence.Payload.source_revision
        cluster_system_identifier = [string]$live.ClusterSystemIdentifier
        database_oid = [uint32]$live.DatabaseOid
        writer_fence_sha256 = $fenceSha256
    }
}
