#Requires -Version 5.1

function Assert-TicketboxPostgresqlDatabaseCatalogDependencies {
    foreach ($commandName in @(
        "Assert-TicketboxPostgresqlDatabaseIdentifier",
        "ConvertTo-TicketboxPostgresqlSqlLiteral",
        "ConvertFrom-TicketboxPostgresqlHostEvidenceRow",
        "Invoke-TicketboxPostgresqlDatabaseCommandResult"
    )) {
        if (
            $null -eq (
                Get-Command `
                    -Name $commandName `
                    -CommandType Function `
                    -ErrorAction SilentlyContinue
            )
        ) {
            throw "PostgreSQL database-catalog dependency is missing: $commandName"
        }
    }
}
