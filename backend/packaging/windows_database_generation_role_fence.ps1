#Requires -Version 5.1

function Get-TicketboxDatabaseGenerationFrozenFence {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role "postgres"
    $capturedPsql = [string]$HostAuthority.PsqlPath
    $capturedUrl = $databaseUrl
    $allowedRoleNames = @(
        "postgres", $($databasePolicy.OwnerRole),
        $($databasePolicy.MigratorRole), $($databasePolicy.RuntimeRole),
        $($databasePolicy.BackupRole)
    )
    return Invoke-TicketboxWithPlainPostgresqlSecret `
        -Secret $SuperuserPassword `
        -Action ({
            param([string]$PlainPassword)
            $observation = Get-TicketboxPostgresqlWriterFenceObservation `
                -PsqlPath $capturedPsql `
                -DatabaseUrl $capturedUrl `
                -Password $PlainPassword `
                -ManagedSchemaName "public" `
                -AdvisoryLockLabel "xiaopiaojia:schema" `
                -ApplicationName "ticketbox-generation-fence" `
                -TimeoutMilliseconds 30000 `
                -StatementTimeoutMilliseconds 5000 `
                -LockTimeoutMilliseconds 1000
            $owner = @($observation.Roles | Where-Object {
                [string]$_.name -ceq $($databasePolicy.OwnerRole)
            })
            $migrator = @($observation.Roles | Where-Object {
                [string]$_.name -ceq $($databasePolicy.MigratorRole)
            })
            $runtime = @($observation.Roles | Where-Object {
                [string]$_.name -ceq $($databasePolicy.RuntimeRole)
            })
            $backup = @($observation.Roles | Where-Object {
                [string]$_.name -ceq $($databasePolicy.BackupRole)
            })
            $databaseAuthority = @($observation.Roles | Where-Object {
                [string]$_.name -ceq "postgres"
            })
            $unsafeUnregistered = @($observation.Roles | Where-Object {
                [string]$_.name -cnotin $allowedRoleNames -and
                (
                    [bool]$_.can_login -or [bool]$_.direct_connect -or
                    [bool]$_.effective_connect -or [bool]$_.is_superuser -or
                    [bool]$_.can_create_db -or [bool]$_.can_create_role -or
                    [bool]$_.can_replicate -or [bool]$_.can_bypass_rls -or
                    [bool]$_.is_database_owner -or [bool]$_.owns_managed_schema -or
                    [bool]$_.owns_managed_relations -or
                    [bool]$_.owns_security_definer_routines -or
                    [bool]$_.can_execute_unowned_security_definer_routines -or
                    [bool]$_.can_database_create -or
                    [bool]$_.can_managed_schema_create -or
                    [bool]$_.can_table_write -or [bool]$_.can_sequence_write -or
                    [bool]$_.can_assume_write_owner -or
                    @($_.predefined_role_usage).Count -ne 0 -or
                    @($_.predefined_role_set).Count -ne 0
                )
            })
            if (
                [bool]$observation.PublicConnect -or
                [int64]$observation.OtherClientSessionCount -ne 0 -or
                @($observation.ClientSessions).Count -ne 0 -or
                [int64]$observation.MaxPreparedTransactions -ne 0 -or
                [int64]$observation.PreparedTransactionCount -ne 0 -or
                [int64]$observation.LogicalSubscriptionCount -ne 0 -or
                [int64]$observation.LogicalApplyWorkerCount -ne 0 -or
                [int64]$observation.UnexpectedDatabaseWorkerCount -ne 0 -or
                -not [bool]$observation.AdvisoryFenceAvailable -or
                -not [bool]$observation.AdvisoryFenceReleased -or
                $unsafeUnregistered.Count -ne 0 -or
                $databaseAuthority.Count -ne 1 -or
                -not [bool]$databaseAuthority[0].can_login -or
                -not [bool]$databaseAuthority[0].is_superuser -or
                $owner.Count -ne 1 -or [bool]$owner[0].can_login -or
                $migrator.Count -ne 1 -or -not [bool]$migrator[0].can_login -or
                [int]$migrator[0].connection_limit -ne 1 -or
                -not [bool]$migrator[0].can_assume_write_owner -or
                $runtime.Count -ne 1 -or [bool]$runtime[0].can_login -or
                [int]$runtime[0].connection_limit -ne 0 -or
                [bool]$runtime[0].direct_connect -or
                [bool]$runtime[0].effective_connect -or
                [bool]$runtime[0].can_table_write -or
                [bool]$runtime[0].can_sequence_write -or
                [bool]$runtime[0].can_assume_write_owner -or
                $backup.Count -ne 1 -or [bool]$backup[0].can_login -or
                [int]$backup[0].connection_limit -ne 0 -or
                [bool]$backup[0].direct_connect -or
                [bool]$backup[0].effective_connect -or
                [bool]$backup[0].can_table_write -or
                [bool]$backup[0].can_sequence_write -or
                [bool]$backup[0].can_assume_write_owner
            ) {
                throw "database generation writer fence 未收敛。"
            }
            return $observation
        }.GetNewClosure())
}

function Renew-TicketboxDatabaseGenerationMigratorWindow {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$Credentials
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $validUntil = [DateTime]::UtcNow.AddHours(1).ToString(
        "yyyy-MM-ddTHH:mm:ss.fffZ",
        [Globalization.CultureInfo]::InvariantCulture
    )
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation migrator window" `
        -Sql @"
ALTER ROLE "$($databasePolicy.MigratorRole)"
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
    VALID UNTIL '$validUntil';
"@ | Out-Null
    Assert-TicketboxDatabaseCredential `
        -Authority $HostAuthority `
        -Password $Credentials.MigratorPassword `
        -CredentialKind "migrator"
}
