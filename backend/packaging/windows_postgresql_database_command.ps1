#Requires -Version 5.1

<#
.SYNOPSIS
  Executes bounded PostgreSQL commands against an exact installed host authority.
.DESCRIPTION
  Owns canonical local connection construction and the SecureString to protected
  passfile boundary. Product database names, roles, ACLs, and lifecycle policy
  remain caller-owned.
#>

function Assert-TicketboxPostgresqlDatabaseCommandDependencies {
    foreach ($commandName in @(
        "Assert-TicketboxPostgresqlSecureString",
        "Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile",
        "Invoke-TicketboxWithPlainPostgresqlSecret"
    )) {
        if (-not (Get-Command $commandName -CommandType Function -ErrorAction SilentlyContinue)) {
            throw "PostgreSQL database-command dependency is missing: $commandName"
        }
    }
}

function Assert-TicketboxPostgresqlDatabaseIdentifier {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -cnotmatch '^[a-z][a-z0-9_]{0,62}$') {
        throw "$Label is not a canonical PostgreSQL identifier."
    }
}

function ConvertTo-TicketboxPostgresqlSqlLiteral {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value)

    if ($Value.IndexOf([char]0) -ge 0) {
        throw "PostgreSQL SQL text contains NUL."
    }
    return "'" + $Value.Replace("'", "''") + "'"
}

function ConvertTo-TicketboxPostgresqlSqlTextArray {
    param([Parameter(Mandatory = $true)][string[]]$Values)

    $items = @(
        foreach ($value in $Values) {
            Assert-TicketboxPostgresqlDatabaseIdentifier `
                -Value $value `
                -Label "PostgreSQL SQL array item"
            ConvertTo-TicketboxPostgresqlSqlLiteral $value
        }
    )
    return "ARRAY[" + ($items -join ", ") + "]::text[]"
}

function Assert-TicketboxPostgresqlDatabaseCommandHost {
    param([Parameter(Mandatory = $true)][object]$Authority)

    foreach ($propertyName in @("Schema", "PsqlPath", "Port")) {
        if ($propertyName -cnotin @($Authority.PSObject.Properties.Name)) {
            throw "PostgreSQL database-command host authority is missing $propertyName."
        }
    }
    if (
        [string]$Authority.Schema -cne "ticketbox-postgresql-host-authority-v1" -or
        [string]::IsNullOrWhiteSpace([string]$Authority.PsqlPath) -or
        -not [IO.Path]::IsPathRooted([string]$Authority.PsqlPath) -or
        [int]$Authority.Port -lt 1 -or
        [int]$Authority.Port -gt 65535
    ) {
        throw "PostgreSQL database-command host authority is invalid."
    }
}

function New-TicketboxPostgresqlLocalDatabaseUrl {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Role
    )

    Assert-TicketboxPostgresqlDatabaseCommandHost $Authority
    Assert-TicketboxPostgresqlDatabaseIdentifier -Value $Database -Label "database"
    Assert-TicketboxPostgresqlDatabaseIdentifier -Value $Role -Label "role"
    $encodedRole = [Uri]::EscapeDataString($Role)
    $encodedDatabase = [Uri]::EscapeDataString($Database)
    return "postgresql://${encodedRole}@127.0.0.1:$($Authority.Port)/" +
        "${encodedDatabase}?require_auth=scram-sha-256"
}

function Invoke-TicketboxPostgresqlDatabaseCommandResult {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000
    )

    Assert-TicketboxPostgresqlDatabaseCommandDependencies
    Assert-TicketboxPostgresqlSecureString $Password "$Label credential"
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority $Authority `
        -Database $Database `
        -Role $Role
    return Invoke-TicketboxWithPlainPostgresqlSecret -Secret $Password -Action {
        param([string]$PlainPassword)

        $commandResult = Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile `
            -PsqlPath ([string]$Authority.PsqlPath) `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -Sql $Sql `
            -Label $Label `
            -TimeoutMilliseconds $TimeoutMilliseconds
        if ($null -eq $commandResult) {
            throw "$Label returned no PostgreSQL native result."
        }
        $resultProperties = @($commandResult.PSObject.Properties.Name)
        if (
            "ExitCode" -cnotin $resultProperties -or
            "StandardOutput" -cnotin $resultProperties -or
            $commandResult.ExitCode -isnot [int] -or
            $commandResult.StandardOutput -isnot [string]
        ) {
            throw "$Label returned an invalid PostgreSQL native result."
        }
        return [pscustomobject][ordered]@{
            ExitCode = [int]$commandResult.ExitCode
            StandardOutput = [string]$commandResult.StandardOutput
        }
    }
}

function Invoke-TicketboxPostgresqlDatabaseCommand {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000
    )

    $result = Invoke-TicketboxPostgresqlDatabaseCommandResult @PSBoundParameters
    if ([int]$result.ExitCode -ne 0) {
        throw "$Label failed (exit=$($result.ExitCode)); native output suppressed."
    }
    return ([string]$result.StandardOutput).Trim()
}
