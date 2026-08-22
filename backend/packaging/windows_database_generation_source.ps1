#Requires -Version 5.1

# Empty-source classification and creation. Its durable output is a normalized
# SourceBinding; downstream stages never receive installer modes.

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
