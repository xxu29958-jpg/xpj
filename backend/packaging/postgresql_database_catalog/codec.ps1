#Requires -Version 5.1

function ConvertFrom-TicketboxPostgresqlDatabaseCatalogCommentHex {
    param(
        [AllowEmptyString()]
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value -cnotmatch '^(?:[0-9a-f]{2})*$') {
        throw "PostgreSQL database catalog comment encoding is invalid."
    }
    if ($Value.Length -eq 0) {
        return ""
    }
    $bytes = New-Object byte[] ($Value.Length / 2)
    for ($index = 0; $index -lt $bytes.Length; $index++) {
        $bytes[$index] = [Convert]::ToByte($Value.Substring($index * 2, 2), 16)
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        return $utf8.GetString($bytes)
    }
    catch {
        throw "PostgreSQL database catalog comment UTF-8 is invalid."
    }
}

function ConvertFrom-TicketboxPostgresqlDatabaseCatalogObservation {
    param(
        [AllowEmptyString()]
        [Parameter(Mandatory = $true)]
        [string]$Output,
        [Parameter(Mandatory = $true)][string]$TargetDatabase
    )

    Assert-TicketboxPostgresqlDatabaseIdentifier `
        -Value $TargetDatabase `
        -Label "Target database"
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $Output `
        -FieldCount 5 `
        -Label "PostgreSQL database-catalog observation"
    $clusterSystemIdentifier = [uint64]0
    if (
        $fields[0] -cnotmatch '^[1-9][0-9]{0,19}$' -or
        -not [uint64]::TryParse(
            $fields[0],
            [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$clusterSystemIdentifier
        ) -or
        $clusterSystemIdentifier -lt 1
    ) {
        throw "PostgreSQL cluster system identifier is invalid."
    }

    if ($fields[1].Length -eq 0) {
        if (
            $fields[2].Length -ne 0 -or
            $fields[3].Length -ne 0 -or
            $fields[4].Length -ne 0
        ) {
            throw "PostgreSQL absent database has partial catalog evidence."
        }
        return [pscustomobject][ordered]@{
            ClusterSystemIdentifier = [string]$fields[0]
            Database = $TargetDatabase
            DatabaseOid = [uint32]0
            OwnerRoleOid = [uint32]0
            AllowsConnections = $false
            Comment = ""
            Exists = $false
        }
    }

    $databaseOid = [uint32]0
    $ownerRoleOid = [uint32]0
    if (
        -not [uint32]::TryParse($fields[1], [ref]$databaseOid) -or
        $databaseOid -lt 1 -or
        -not [uint32]::TryParse($fields[2], [ref]$ownerRoleOid) -or
        $ownerRoleOid -lt 1 -or
        $fields[3] -cnotin @("true", "false")
    ) {
        throw "PostgreSQL database catalog OID or connection state is invalid."
    }
    $comment = ConvertFrom-TicketboxPostgresqlDatabaseCatalogCommentHex `
        -Value $fields[4]
    return [pscustomobject][ordered]@{
        ClusterSystemIdentifier = [string]$fields[0]
        Database = $TargetDatabase
        DatabaseOid = $databaseOid
        OwnerRoleOid = $ownerRoleOid
        AllowsConnections = $fields[3] -ceq "true"
        Comment = $comment
        Exists = $true
    }
}
