#Requires -Version 5.1

function Get-TicketboxPostgresqlWriterFenceObservation {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][string]$ManagedSchemaName,
        [Parameter(Mandatory = $true)][string]$AdvisoryLockLabel,
        [Parameter(Mandatory = $true)][string]$ApplicationName,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 30000,
        [ValidateRange(1, 3600000)][int]$StatementTimeoutMilliseconds = 5000,
        [ValidateRange(1, 3600000)][int]$LockTimeoutMilliseconds = 1000
    )

    Assert-TicketboxPostgresqlWriterFenceDependencies
    if (
        $StatementTimeoutMilliseconds -gt $TimeoutMilliseconds -or
        $LockTimeoutMilliseconds -gt $StatementTimeoutMilliseconds -or
        [string]::IsNullOrWhiteSpace($AdvisoryLockLabel) -or
        $AdvisoryLockLabel.Length -gt 128 -or
        [string]::IsNullOrWhiteSpace($ApplicationName) -or
        $ApplicationName.Length -gt 63
    ) {
        throw "PostgreSQL writer-fence observation parameters are invalid."
    }
    $sql = New-TicketboxPostgresqlWriterFenceObservationSql `
        -ManagedSchemaName $ManagedSchemaName `
        -AdvisoryLockLabel $AdvisoryLockLabel `
        -ApplicationName $ApplicationName `
        -StatementTimeoutMilliseconds $StatementTimeoutMilliseconds `
        -LockTimeoutMilliseconds $LockTimeoutMilliseconds
    $output = Invoke-TicketboxPostgresqlWriterFenceSql `
        -PsqlPath $PsqlPath `
        -DatabaseUrl $DatabaseUrl `
        -Password $Password `
        -Sql $sql `
        -Label "PostgreSQL writer-fence observation" `
        -TimeoutMilliseconds $TimeoutMilliseconds
    return ConvertFrom-TicketboxPostgresqlWriterFenceObservationJson $output
}
