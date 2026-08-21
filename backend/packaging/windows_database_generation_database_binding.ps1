#Requires -Version 5.1

function New-TicketboxDatabaseGenerationExecutionAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceBinding,
        [Parameter(Mandatory = $true)][object]$Result
    )
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $Result `
        -ExpectedNames @(
            "schema", "source_revision", "target_revision",
            "generation_program_sha256", "result", "alembic_revision"
        ) `
        -Label "database generation execution result"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$Result.generation_program_sha256) `
        "database generation execution program"
    if (
        [string]$Result.schema -cne "ticketbox-managed-schema-upgrade-result-v2" -or
        [string]$Result.source_revision -cne [string]$SourceBinding.Payload.source_revision -or
        [string]$Result.target_revision -cne [string]$Intent.Payload.target_revision -or
        [string]$Result.alembic_revision -cne [string]$Intent.Payload.target_revision -or
        [string]$Result.generation_program_sha256 -cne
            [string]$Intent.Payload.generation_program_sha256 -or
        [string]$Result.result -cnotin @(
            "target_committed",
            "target_observed_after_interruption"
        )
    ) {
        throw "database generation execution result 未绑定 exact intent/source。"
    }
    return [ordered]@{
        schema = "ticketbox-database-generation-execution-authority-v1"
        operation_id = [string]$Intent.Payload.operation_id
        source_revision = [string]$Result.source_revision
        target_revision = [string]$Result.target_revision
        generation_program_sha256 = [string]$Result.generation_program_sha256
        alembic_revision = [string]$Result.alembic_revision
    }
}

function Get-TicketboxDatabaseGenerationLiveIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $output = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation live identity" `
        -Sql @"
SELECT control.system_identifier::text || E'\t' ||
       database.oid::text || E'\t' ||
       current_database() || E'\t' ||
       (SELECT value FROM public.app_meta WHERE key = 'server_id') || E'\t' ||
       (SELECT value FROM public.app_meta WHERE key = 'data_generation')
FROM pg_catalog.pg_database AS database
CROSS JOIN pg_catalog.pg_control_system() AS control
WHERE database.datname = current_database();
"@
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $output `
        -FieldCount 5 `
        -Label "database generation live identity"
    if ($fields[0] -cnotmatch '^[1-9][0-9]*$') {
        throw "database generation live cluster identity 无效。"
    }
    $databaseOid = 0L
    if (
        -not [long]::TryParse([string]$fields[1], [ref]$databaseOid) -or
        $databaseOid -lt 1 -or $databaseOid -gt [uint32]::MaxValue
    ) {
        throw "database generation live database OID 无效。"
    }
    if ([string]$fields[2] -cne $($databasePolicy.DatabaseName)) {
        throw "database generation live database name 漂移。"
    }
    foreach ($index in 3, 4) {
        $parsed = [guid]::Empty
        if (
            -not [guid]::TryParseExact([string]$fields[$index], "D", [ref]$parsed) -or
            $parsed -eq [guid]::Empty -or
            $parsed.ToString("D") -cne [string]$fields[$index]
        ) {
            throw "database generation live logical identity 无效。"
        }
    }
    return [pscustomobject][ordered]@{
        ClusterSystemIdentifier = [string]$fields[0]
        DatabaseOid = [uint32]$databaseOid
        DatabaseName = [string]$fields[2]
        LogicalServerId = [string]$fields[3]
        LogicalDataGeneration = [string]$fields[4]
    }
}

function Set-TicketboxDatabaseGenerationDatabaseBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceBinding,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$ExecutionAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$RoleAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$RuntimeAclSha256,
        [Parameter(Mandatory = $true)][string]$WriterFenceSha256,
        [Parameter(Mandatory = $true)][string]$TargetRecoveryEvidenceSha256,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    foreach ($entry in @(
        @{ Value = $ExecutionAuthoritySha256; Label = "execution authority" },
        @{ Value = $RoleAuthoritySha256; Label = "role authority" },
        @{ Value = $RuntimeAclSha256; Label = "runtime ACL" },
        @{ Value = $WriterFenceSha256; Label = "writer fence" },
        @{ Value = $TargetRecoveryEvidenceSha256; Label = "target recovery" }
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            ([string]$entry.Value) `
            ("database generation binding " + [string]$entry.Label)
    }
    $identity = Get-TicketboxDatabaseGenerationLiveIdentity `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $SuperuserPassword
    if (
        [string]$identity.ClusterSystemIdentifier -cne
            [string]$SourceBinding.Payload.cluster_system_identifier -or
        [uint32]$identity.DatabaseOid -ne [uint32]$SourceBinding.Payload.database_oid
    ) {
        throw "database generation live identity 与 SourceBinding 漂移。"
    }
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-database-binding-v1"
        operation_id = [string]$Intent.Payload.operation_id
        installation_id = [string]$Intent.Payload.installation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        source_binding_sha256 = [string]$SourceBinding.PayloadSha256
        target_revision = [string]$Intent.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        cluster_system_identifier = [string]$identity.ClusterSystemIdentifier
        database_oid = [uint32]$identity.DatabaseOid
        database_name = [string]$identity.DatabaseName
        runtime_role = [string]$($databasePolicy.RuntimeRole)
        logical_server_id = [string]$identity.LogicalServerId
        logical_data_generation = [string]$identity.LogicalDataGeneration
        execution_authority_sha256 = $ExecutionAuthoritySha256
        role_authority_sha256 = $RoleAuthoritySha256
        runtime_acl_sha256 = $RuntimeAclSha256
        post_migration_writer_fence_sha256 = $WriterFenceSha256
        target_recovery_evidence_sha256 = $TargetRecoveryEvidenceSha256
    }
    $bindingJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
    $bindingSha256 = Get-TicketboxDatabaseGenerationTextSha256 $bindingJson
    $keyLiteral = ConvertTo-TicketboxPostgresqlSqlLiteral `
        $script:TicketboxDatabaseGenerationBindingKey
    $valueLiteral = ConvertTo-TicketboxPostgresqlSqlLiteral $bindingJson
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observed = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation binding publication" `
        -Sql @"
BEGIN;
INSERT INTO public.app_meta (key, value, updated_at)
VALUES ($keyLiteral, $valueLiteral, CURRENT_TIMESTAMP)
ON CONFLICT (key) DO NOTHING;
SELECT value FROM public.app_meta WHERE key = $keyLiteral;
COMMIT;
"@
    if ([string]$observed -cne $bindingJson) {
        throw "database generation binding 未通过同事务复读。"
    }
    return $bindingSha256
}
