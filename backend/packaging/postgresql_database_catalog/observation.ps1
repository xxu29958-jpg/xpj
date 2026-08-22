#Requires -Version 5.1

$script:TicketboxPostgresqlDatabaseCatalogTimeoutMs = 30000

function Get-TicketboxPostgresqlDatabaseCatalogObservation {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$TargetDatabase,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds =
            $script:TicketboxPostgresqlDatabaseCatalogTimeoutMs
    )

    Assert-TicketboxPostgresqlDatabaseCatalogDependencies
    $sql = New-TicketboxPostgresqlDatabaseCatalogObservationQuery `
        -TargetDatabase $TargetDatabase
    $result = Invoke-TicketboxPostgresqlDatabaseCommandResult `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql $sql `
        -Label "PostgreSQL database-catalog observation" `
        -TimeoutMilliseconds $TimeoutMilliseconds
    if ([int]$result.ExitCode -ne 0) {
        throw "PostgreSQL database-catalog observation failed (native output suppressed)."
    }
    return ConvertFrom-TicketboxPostgresqlDatabaseCatalogObservation `
        -Output ([string]$result.StandardOutput) `
        -TargetDatabase $TargetDatabase
}
