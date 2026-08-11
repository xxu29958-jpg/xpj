#Requires -Version 5.1

function Assert-TicketboxPostgresqlDatabaseCatalogDependencies {
    foreach ($commandName in @(
        "ConvertFrom-TicketboxPostgresqlHostEvidenceRow",
        "Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile"
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

function Assert-TicketboxPostgresqlDatabaseCatalogIdentifier {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -cnotmatch '^[a-z][a-z0-9_]{0,62}$') {
        throw "$Label is not a canonical PostgreSQL identifier."
    }
}

function ConvertTo-TicketboxPostgresqlDatabaseCatalogSqlLiteral {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value)

    if ($Value.IndexOf([char]0) -ge 0) {
        throw "PostgreSQL database-catalog SQL text contains NUL."
    }
    return "'" + $Value.Replace("'", "''") + "'"
}
