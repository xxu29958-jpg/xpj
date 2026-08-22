#Requires -Version 5.1

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
