#Requires -Version 5.1

function New-TicketboxPostgresqlDatabaseCatalogObservationQuery {
    param([Parameter(Mandatory = $true)][string]$TargetDatabase)

    Assert-TicketboxPostgresqlDatabaseIdentifier `
        -Value $TargetDatabase `
        -Label "Target database"
    $databaseLiteral =
        ConvertTo-TicketboxPostgresqlSqlLiteral $TargetDatabase
    return @"
SELECT
    control.system_identifier::pg_catalog.text,
    COALESCE(database.oid::pg_catalog.text, ''),
    COALESCE(database.datdba::pg_catalog.text, ''),
    COALESCE(database.datallowconn::pg_catalog.text, ''),
    COALESCE(
        pg_catalog.encode(
            pg_catalog.convert_to(
                pg_catalog.shobj_description(
                    database.oid,
                    'pg_database'
                ),
                'UTF8'
            ),
            'hex'
        ),
        ''
    )
FROM pg_catalog.pg_control_system() AS control
LEFT JOIN pg_catalog.pg_database AS database
  ON database.datname OPERATOR(pg_catalog.=) $databaseLiteral;
"@
}
