#Requires -Version 5.1

function Assert-TicketboxPostgresqlWriterFenceDependencies {
    foreach ($commandName in @(
        "Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile"
    )) {
        if (
            $null -eq (
                Get-Command $commandName -CommandType Function -ErrorAction SilentlyContinue
            )
        ) {
            throw "PostgreSQL writer-fence dependency is missing: $commandName"
        }
    }
}

function Assert-TicketboxPostgresqlWriterFenceIdentifier {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -cnotmatch '^[a-z][a-z0-9_]{0,62}$') {
        throw "$Label is not a canonical PostgreSQL identifier."
    }
}

function ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value)

    if ($Value.IndexOf([char]0) -ge 0) {
        throw "PostgreSQL writer-fence SQL text contains NUL."
    }
    return "'" + $Value.Replace("'", "''") + "'"
}

function ConvertTo-TicketboxPostgresqlWriterFenceTextArray {
    param(
        [AllowEmptyCollection()]
        [Parameter(Mandatory = $true)]
        [string[]]$Values,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Values.Count -gt 128) {
        throw "$Label contains too many PostgreSQL roles."
    }
    $seen = @{}
    $literals = @()
    foreach ($value in $Values) {
        Assert-TicketboxPostgresqlWriterFenceIdentifier $value $Label
        if ($seen.ContainsKey($value)) {
            throw "$Label contains a duplicate PostgreSQL role."
        }
        $seen[$value] = $true
        $literals += ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $value
    }
    return "ARRAY[" + ($literals -join ", ") + "]::text[]"
}

function New-TicketboxPostgresqlWriterFenceRelationWriteAuthoritySql {
    param([Parameter(Mandatory = $true)][string]$RoleOidSql)

    if ($RoleOidSql -cnotmatch '^[a-z][a-z0-9_]*\.oid$') {
        throw "PostgreSQL writer-fence role OID expression is not trusted."
    }
    return @"
(
    relation.relkind IN ('r', 'p', 'f')
    AND (
        has_any_column_privilege($RoleOidSql, relation.oid, 'INSERT')
        OR has_any_column_privilege($RoleOidSql, relation.oid, 'UPDATE')
        OR has_table_privilege($RoleOidSql, relation.oid, 'DELETE')
        OR has_table_privilege($RoleOidSql, relation.oid, 'TRUNCATE')
        OR has_table_privilege($RoleOidSql, relation.oid, 'REFERENCES')
        OR has_table_privilege($RoleOidSql, relation.oid, 'TRIGGER')
    )
)
OR (
    relation.relkind = 'v'
    AND (
        EXISTS (
            SELECT 1
            FROM information_schema.views AS view_capability
            WHERE view_capability.table_schema = namespace.nspname
              AND view_capability.table_name = relation.relname
              AND (
                  (
                      has_any_column_privilege(
                          $RoleOidSql, relation.oid, 'INSERT'
                      )
                      AND (
                          view_capability.is_insertable_into = 'YES'
                          OR view_capability.is_trigger_insertable_into = 'YES'
                      )
                  )
                  OR (
                      has_any_column_privilege(
                          $RoleOidSql, relation.oid, 'UPDATE'
                      )
                      AND (
                          view_capability.is_updatable = 'YES'
                          OR view_capability.is_trigger_updatable = 'YES'
                      )
                  )
                  OR (
                      has_table_privilege(
                          $RoleOidSql, relation.oid, 'DELETE'
                      )
                      AND (
                          view_capability.is_updatable = 'YES'
                          OR view_capability.is_trigger_deletable = 'YES'
                      )
                  )
              )
        )
        OR (
            NOT EXISTS (
                SELECT 1
                FROM information_schema.views AS view_capability
                WHERE view_capability.table_schema = namespace.nspname
                  AND view_capability.table_name = relation.relname
            )
            AND (
                has_any_column_privilege(
                    $RoleOidSql, relation.oid, 'INSERT'
                )
                OR has_any_column_privilege(
                    $RoleOidSql, relation.oid, 'UPDATE'
                )
                OR has_table_privilege(
                    $RoleOidSql, relation.oid, 'DELETE'
                )
            )
        )
    )
)
"@
}

function Assert-TicketboxPostgresqlWriterFenceExactProperties {
    param(
        [AllowNull()][Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($null -eq $Value) { throw "$Label is missing." }
    $actual = @($Value.PSObject.Properties.Name)
    if (
        $actual.Count -ne $Names.Count -or
        @($Names | Where-Object { $_ -cnotin $actual }).Count -ne 0 -or
        @($actual | Where-Object { $_ -cnotin $Names }).Count -ne 0
    ) {
        throw "$Label has an invalid field set."
    }
}

function Invoke-TicketboxPostgresqlWriterFenceSql {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
    )

    $result = Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile `
        -PsqlPath $PsqlPath `
        -DatabaseUrl $DatabaseUrl `
        -Password $Password `
        -Sql $Sql `
        -Label $Label `
        -TimeoutMilliseconds $TimeoutMilliseconds
    if ([int]$result.ExitCode -ne 0) {
        throw "$Label failed (native output suppressed)."
    }
    return ([string]$result.StandardOutput).Trim()
}
