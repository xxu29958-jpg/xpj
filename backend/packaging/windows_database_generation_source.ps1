#Requires -Version 5.1

# Empty-source normalization is the only place that knows first-install
# bootstrap facts.  Its durable output is a SourceBinding; no later phase sees
# fresh/legacy/runtime modes or any C07 READY marker.

function New-TicketboxDatabaseGenerationEmptyRoleSql {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$RuntimeVerifier,
        [Parameter(Mandatory = $true)][string]$MigratorVerifier,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc
    )
    $operation = ([guid]$OperationId).ToString("D")
    if (
        $RuntimeVerifier -cnotmatch '^SCRAM-SHA-256\$4096:' -or
        $MigratorVerifier -cnotmatch '^SCRAM-SHA-256\$4096:'
    ) {
        throw "empty source 只接受 SCRAM-SHA-256 verifier。"
    }
    $runtimeVerifierSql = Escape-SqlLiteral $RuntimeVerifier
    $migratorVerifierSql = Escape-SqlLiteral $MigratorVerifier
    $validUntil = $MigratorValidUntilUtc.ToUniversalTime().ToString(
        "yyyy-MM-ddTHH:mm:ss.fffZ",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $operationSql = Escape-SqlLiteral $operation
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
        '$script:TicketboxC07OwnerRole',
        '$script:TicketboxC07MigratorRole',
        '$script:TicketboxC07RuntimeRole'
    );
    IF existing_count NOT IN (0, 3) THEN
        RAISE EXCEPTION 'partial database-generation role residue';
    END IF;
    IF existing_count = 0 THEN
        CREATE ROLE "$script:TicketboxC07OwnerRole"
            NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
        CREATE ROLE "$script:TicketboxC07RuntimeRole"
            NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0
            PASSWORD '$runtimeVerifierSql';
        CREATE ROLE "$script:TicketboxC07MigratorRole"
            LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
            PASSWORD '$migratorVerifierSql' VALID UNTIL '$validUntil';
        FOREACH role_name IN ARRAY ARRAY[
            '$script:TicketboxC07OwnerRole',
            '$script:TicketboxC07MigratorRole',
            '$script:TicketboxC07RuntimeRole'
        ] LOOP
            SELECT oid INTO STRICT role_oid FROM pg_roles WHERE rolname = role_name;
            expected_comment := format(
                'ticketbox-database-generation-role-v1|%s|%s|%s',
                '$operationSql', role_name, role_oid
            );
            EXECUTE format('COMMENT ON ROLE %I IS %L', role_name, expected_comment);
        END LOOP;
    ELSE
        FOREACH role_name IN ARRAY ARRAY[
            '$script:TicketboxC07OwnerRole',
            '$script:TicketboxC07MigratorRole',
            '$script:TicketboxC07RuntimeRole'
        ] LOOP
            SELECT oid, shobj_description(oid, 'pg_authid')
            INTO STRICT role_oid, actual_comment
            FROM pg_roles WHERE rolname = role_name;
            expected_comment := format(
                'ticketbox-database-generation-role-v1|%s|%s|%s',
                '$operationSql', role_name, role_oid
            );
            IF actual_comment IS DISTINCT FROM expected_comment THEN
                RAISE EXCEPTION 'database-generation role identity mismatch for %', role_name;
            END IF;
        END LOOP;
        IF (SELECT rolpassword FROM pg_authid
            WHERE rolname = '$script:TicketboxC07RuntimeRole')
              IS DISTINCT FROM '$runtimeVerifierSql'
           OR (SELECT rolpassword FROM pg_authid
            WHERE rolname = '$script:TicketboxC07MigratorRole')
              IS DISTINCT FROM '$migratorVerifierSql' THEN
            RAISE EXCEPTION 'database-generation role credential mismatch';
        END IF;
    END IF;
    ALTER ROLE "$script:TicketboxC07OwnerRole"
        NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS;
    ALTER ROLE "$script:TicketboxC07RuntimeRole"
        NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0;
    ALTER ROLE "$script:TicketboxC07MigratorRole"
        LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
        VALID UNTIL '$validUntil';
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE (granted.rolname IN (
                   '$script:TicketboxC07OwnerRole',
                   '$script:TicketboxC07MigratorRole',
                   '$script:TicketboxC07RuntimeRole'
               )
               OR member.rolname IN (
                   '$script:TicketboxC07OwnerRole',
                   '$script:TicketboxC07MigratorRole',
                   '$script:TicketboxC07RuntimeRole'
               ))
          AND NOT (
              granted.rolname = '$script:TicketboxC07OwnerRole'
              AND member.rolname = '$script:TicketboxC07MigratorRole'
              AND NOT membership.admin_option
              AND NOT membership.inherit_option
              AND membership.set_option
          )
    ) THEN
        RAISE EXCEPTION 'foreign database-generation role membership residue';
    END IF;
    GRANT "$script:TicketboxC07OwnerRole" TO "$script:TicketboxC07MigratorRole"
        WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
    REVOKE "$script:TicketboxC07OwnerRole" FROM "$script:TicketboxC07RuntimeRole";
END
`$ticketbox_generation_roles`$;
COMMIT;
"@
}

function Get-TicketboxDatabaseGenerationRoleOid {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$Role
    )
    $roleLiteral = Escape-SqlLiteral $Role
    $raw = [string](Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation role identity observation" `
        -Sql "SELECT COALESCE((SELECT oid::text FROM pg_roles WHERE rolname = '$roleLiteral'), '');")
    $value = $raw.Trim()
    $oid = [uint32]0
    if (-not [uint32]::TryParse($value, [ref]$oid) -or $oid -lt 1) {
        throw "database generation expected owner role is absent."
    }
    return $oid
}

function Assert-TicketboxDatabaseGenerationEmptySchema {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $raw = Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
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
    $fields = ConvertFrom-TicketboxC07SingleRow `
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
        [Parameter(Mandatory = $true)][object]$SuperuserCapability,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $null = Assert-TicketboxC07SuperuserCapability `
        $SuperuserCapability $operationId $LifecycleLock
    $superuserPassword = $SuperuserCapability.Secret
    $temporaryDatabase = "ticketbox_generation_" + ([guid]$operationId).ToString("N")
    $targetCatalog = Get-TicketboxC07DatabaseCatalogObservation `
        $HostAuthority $superuserPassword $script:TicketboxC07DatabaseName
    $temporaryCatalog = Get-TicketboxC07DatabaseCatalogObservation `
        $HostAuthority $superuserPassword $temporaryDatabase
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
                database_name = $script:TicketboxC07DatabaseName
                temporary_database = $temporaryDatabase
                observed_target_absent = $true
            }) $LifecycleLock
    }
    if (
        [string]$attempt.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$attempt.Payload.cluster_system_identifier -cne
            [string]$targetCatalog.ClusterSystemIdentifier -or
        [string]$attempt.Payload.database_name -cne $script:TicketboxC07DatabaseName -or
        [string]$attempt.Payload.temporary_database -cne $temporaryDatabase -or
        -not [bool]$attempt.Payload.observed_target_absent -or
        ($targetCatalog.Exists -and $temporaryCatalog.Exists)
    ) {
        throw "database generation source create-attempt or cluster identity drifted."
    }
    if ($targetCatalog.Exists) {
        $expectedOwnerOid = Get-TicketboxDatabaseGenerationRoleOid `
            $HostAuthority $superuserPassword $script:TicketboxC07OwnerRole
        $expectedMarker = (
            "ticketbox-database-generation-empty-source-v1|$operationId|" +
            "$($targetCatalog.ClusterSystemIdentifier)|$($targetCatalog.DatabaseOid)"
        )
        if (
            [uint32]$targetCatalog.OwnerRoleOid -ne $expectedOwnerOid -or
            [string]$targetCatalog.Marker -cne $expectedMarker
        ) {
            throw "database generation existing database is not this operation's empty source."
        }
        Assert-TicketboxDatabaseGenerationEmptySchema `
            $HostAuthority $superuserPassword
    }
    $validUntil = [DateTime]::UtcNow.AddHours(1)
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation empty-source roles" `
        -Sql (New-TicketboxDatabaseGenerationEmptyRoleSql `
            -OperationId $operationId `
            -RuntimeVerifier ([string]$Credentials.RuntimeVerifier) `
            -MigratorVerifier ([string]$Credentials.MigratorVerifier) `
            -MigratorValidUntilUtc $validUntil) | Out-Null
    $catalog = $targetCatalog
    if (-not $catalog.Exists) {
        if (-not $temporaryCatalog.Exists) {
            Invoke-TicketboxC07Sql `
                -Authority $HostAuthority `
                -Database "postgres" `
                -Role "postgres" `
                -Password $superuserPassword `
                -Label "database generation operation-bound database create" `
                -Sql @"
CREATE DATABASE "$temporaryDatabase"
    OWNER "$script:TicketboxC07OwnerRole" TEMPLATE template0 ENCODING 'UTF8'
    ALLOW_CONNECTIONS false;
"@ | Out-Null
            $temporaryCatalog = Get-TicketboxC07DatabaseCatalogObservation `
                $HostAuthority $superuserPassword $temporaryDatabase
        }
        $expectedOwnerOid = Get-TicketboxDatabaseGenerationRoleOid `
            $HostAuthority $superuserPassword $script:TicketboxC07OwnerRole
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
        if ([string]::IsNullOrEmpty([string]$temporaryCatalog.Marker)) {
            $temporaryMarkerSql = Escape-SqlLiteral $temporaryMarker
            Invoke-TicketboxC07Sql `
                -Authority $HostAuthority `
                -Database "postgres" `
                -Role "postgres" `
                -Password $superuserPassword `
                -Label "database generation operation-bound database identity" `
                -Sql "COMMENT ON DATABASE `"$temporaryDatabase`" IS '$temporaryMarkerSql';" | Out-Null
        }
        elseif ([string]$temporaryCatalog.Marker -cne $temporaryMarker) {
            throw "database generation temporary database identity drifted."
        }
        Invoke-TicketboxC07Sql `
            -Authority $HostAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $superuserPassword `
            -Label "database generation operation-bound database publish" `
            -Sql "ALTER DATABASE `"$temporaryDatabase`" RENAME TO `"$script:TicketboxC07DatabaseName`";" | Out-Null
        $catalog = Get-TicketboxC07DatabaseCatalogObservation `
            $HostAuthority $superuserPassword $script:TicketboxC07DatabaseName
    }
    $expectedOwnerOid = Get-TicketboxDatabaseGenerationRoleOid `
        $HostAuthority $superuserPassword $script:TicketboxC07OwnerRole
    if (-not $catalog.Exists -or [uint32]$catalog.OwnerRoleOid -ne $expectedOwnerOid) {
        throw "database generation empty source 缺少 exact database/owner。"
    }
    $expectedComment = (
        "ticketbox-database-generation-empty-source-v1|$operationId|" +
        "$($catalog.ClusterSystemIdentifier)|$($catalog.DatabaseOid)"
    )
    if ([string]::IsNullOrEmpty([string]$catalog.Marker)) {
        throw "database generation published database lost its operation identity."
    }
    elseif ([string]$catalog.Marker -cne $expectedComment) {
        throw "database generation empty source database identity 漂移。"
    }
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation empty-source admission" `
        -Sql @"
BEGIN;
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName" FROM PUBLIC;
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName"
    FROM "$script:TicketboxC07RuntimeRole", "$script:TicketboxC07MigratorRole";
GRANT CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    TO "$script:TicketboxC07MigratorRole";
ALTER DATABASE "$script:TicketboxC07DatabaseName" ALLOW_CONNECTIONS true;
COMMIT;
"@ | Out-Null
    Assert-TicketboxDatabaseGenerationEmptySchema `
        $HostAuthority $superuserPassword
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation empty-source ACL" `
        -Sql (Get-TicketboxC07DatabasePrivilegeSql -PreserveRuntimeFence) | Out-Null
    Assert-TicketboxC07MigratorCredential $HostAuthority $Credentials.MigratorPassword
    Assert-TicketboxC07RoleCatalog $HostAuthority $superuserPassword -PreserveRuntimeFence
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $HostAuthority `
        -SuperuserPassword $superuserPassword `
        -PreserveRuntimeFence
    $fence = Get-TicketboxDatabaseGenerationFrozenFence $HostAuthority $superuserPassword
    $final = Get-TicketboxC07DatabaseCatalogObservation `
        $HostAuthority $superuserPassword $script:TicketboxC07DatabaseName
    if (
        -not $final.Exists -or -not $final.AllowsConnections -or
        [string]$final.Marker -cne $expectedComment -or
        [uint32]$final.DatabaseOid -ne [uint32]$catalog.DatabaseOid
    ) {
        throw "database generation empty SourceBinding live identity 未收敛。"
    }
    return [ordered]@{
        schema = "ticketbox-database-generation-source-binding-v1"
        operation_id = $operationId
        intent_sha256 = [string]$Intent.PayloadSha256
        create_attempt_sha256 = [string]$attempt.PayloadSha256
        source_kind = "empty"
        source_revision = "base"
        cluster_system_identifier = [string]$final.ClusterSystemIdentifier
        database_oid = [uint32]$final.DatabaseOid
        writer_fence_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
        )
    }
}
