#Requires -Version 5.1

function Get-TicketboxPostgresqlDatabaseCatalogObservation {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][string]$TargetDatabase,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 30000
    )

    Assert-TicketboxPostgresqlDatabaseCatalogDependencies
    if (
        [string]::IsNullOrWhiteSpace($PsqlPath) -or
        [string]::IsNullOrWhiteSpace($DatabaseUrl) -or
        [string]::IsNullOrEmpty($Password)
    ) {
        throw "PostgreSQL database-catalog observation input is incomplete."
    }
    $sql = New-TicketboxPostgresqlDatabaseCatalogObservationQuery `
        -TargetDatabase $TargetDatabase
    $result = Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile `
        -PsqlPath $PsqlPath `
        -DatabaseUrl $DatabaseUrl `
        -Password $Password `
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
