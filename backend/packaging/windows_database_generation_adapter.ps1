#Requires -Version 5.1

function ConvertTo-TicketboxDatabaseGenerationSecureString {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch '^[A-Za-z0-9]{32,1024}$') {
        throw "$Label 不符合受保护随机凭据 shape。"
    }
    $secure = New-Object Security.SecureString
    foreach ($character in $Value.ToCharArray()) { $secure.AppendChar($character) }
    $secure.MakeReadOnly()
    return $secure
}

function New-TicketboxDatabaseGenerationSecret {
    $bytes = New-Object byte[] 48
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) }
    finally { $random.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Read-TicketboxDatabaseGenerationCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [switch]$AllowAbsent
    )
    $operationId = [string]$Intent.Payload.operation_id
    $artifact = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "credentials" -AllowAbsent:$AllowAbsent
    if ($null -eq $artifact) { return $null }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $artifact.Payload `
        @(
            "intent_sha256", "migrator_password", "migrator_scram_salt",
            "operation_id", "runtime_password", "runtime_scram_salt", "schema"
        ) `
        "database generation credentials"
    if (
        [string]$artifact.Payload.schema -cne "ticketbox-database-generation-credentials-v1" -or
        [string]$artifact.Payload.operation_id -cne $operationId -or
        [string]$artifact.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$artifact.Payload.runtime_password -ceq [string]$artifact.Payload.migrator_password
    ) {
        throw "database generation credentials 未绑定 exact intent。"
    }
    try {
        $runtimeSalt = [Convert]::FromBase64String(
            [string]$artifact.Payload.runtime_scram_salt
        )
        $migratorSalt = [Convert]::FromBase64String(
            [string]$artifact.Payload.migrator_scram_salt
        )
    }
    catch { throw "database generation SCRAM salt 不是规范 base64。" }
    if (
        $runtimeSalt.Length -ne 16 -or $migratorSalt.Length -ne 16 -or
        [Convert]::ToBase64String($runtimeSalt) -cne
            [string]$artifact.Payload.runtime_scram_salt -or
        [Convert]::ToBase64String($migratorSalt) -cne
            [string]$artifact.Payload.migrator_scram_salt
    ) {
        throw "database generation SCRAM salt 不是 canonical 16-byte 值。"
    }
    $runtimePassword = ConvertTo-TicketboxDatabaseGenerationSecureString `
        ([string]$artifact.Payload.runtime_password) "runtime password"
    $migratorPassword = ConvertTo-TicketboxDatabaseGenerationSecureString `
        ([string]$artifact.Payload.migrator_password) "migrator password"
    return [pscustomobject]@{
        Artifact = $artifact
        RuntimePassword = $runtimePassword
        MigratorPassword = $migratorPassword
        RuntimeVerifier = ConvertTo-TicketboxC07ScramVerifier `
            -Password $runtimePassword -Salt $runtimeSalt
        MigratorVerifier = ConvertTo-TicketboxC07ScramVerifier `
            -Password $migratorPassword -Salt $migratorSalt
    }
}

function New-TicketboxDatabaseGenerationCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $existing = Read-TicketboxDatabaseGenerationCredentials `
        -StateRoot $StateRoot -Intent $Intent -AllowAbsent
    if ($null -ne $existing) { return $existing }
    $runtime = New-TicketboxDatabaseGenerationSecret
    $migrator = New-TicketboxDatabaseGenerationSecret
    while ($migrator -ceq $runtime) {
        $migrator = New-TicketboxDatabaseGenerationSecret
    }
    $runtimeSalt = New-Object byte[] 16
    $migratorSalt = New-Object byte[] 16
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($runtimeSalt)
        $random.GetBytes($migratorSalt)
    }
    finally { $random.Dispose() }
    while (
        ([Convert]::ToBase64String($migratorSalt)) -ceq
        ([Convert]::ToBase64String($runtimeSalt))
    ) {
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($migratorSalt) }
        finally { $random.Dispose() }
    }
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-credentials-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        runtime_password = $runtime
        runtime_scram_salt = [Convert]::ToBase64String($runtimeSalt)
        migrator_password = $migrator
        migrator_scram_salt = [Convert]::ToBase64String($migratorSalt)
    }
    $path = Get-TicketboxDatabaseGenerationArtifactPath `
        $StateRoot "credentials" ([string]$Intent.Payload.operation_id)
    [void](Write-TicketboxDatabaseGenerationEnvelope `
        $path "credentials" $payload $LifecycleLock)
    return Read-TicketboxDatabaseGenerationCredentials -StateRoot $StateRoot -Intent $Intent
}

function Remove-TicketboxDatabaseGenerationCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Get-TicketboxDatabaseGenerationArtifactPath `
        $StateRoot "credentials" ([string]$Intent.Payload.operation_id)
    if ((Get-TicketboxPathEntryKindNoFollow $path) -ceq "Missing") { return }
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
}

function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {
    param([Parameter(Mandatory = $true)][object]$HostContract)
    Assert-TicketboxDatabaseGenerationExactProperties `
        $HostContract `
        @(
            "backend_service_name", "data_root", "install_dir", "pg_ctl_path",
            "pg_service_name", "pg_dump_path", "pg_dump_size",
            "pg_dump_sha256", "pg_restore_path", "pg_restore_size",
            "pg_restore_sha256", "release_config"
        ) `
        "database generation host contract"
    $shapes = @(Get-TicketboxReleaseServiceIdentityShapes `
        -Config $HostContract.release_config `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -TargetConfig $HostContract.release_config)
    $authority = Resolve-TicketboxPostgresServiceHostAuthority `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -ExpectedPgCtlPath ([string]$HostContract.pg_ctl_path) `
        -DataRoot ([string]$HostContract.data_root) `
        -InstallDir ([string]$HostContract.install_dir) `
        -BackendServiceName ([string]$HostContract.backend_service_name) `
        -AllowedServiceIdentityShapes $shapes
    return [pscustomobject]@{
        Schema = "ticketbox-c07-host-db-authority-v1"
        ServiceName = [string]$authority.ServiceName
        ServiceProcessId = [int]$authority.ServiceProcessId
        PostmasterProcessId = [int]$authority.PostmasterProcessId
        PgCtlPath = [string]$authority.PgCtlPath
        PsqlPath = [string]$authority.PsqlPath
        PgData = [string]$authority.PgData
        PhysicalPgData = [string]$authority.PhysicalPgData
        Port = [int]$authority.Port
        UsesRuntimeBinding = [bool]$authority.UsesRuntimeBinding
        DataVolumeIdentity = [string]$authority.DataVolumeIdentity
    }
}
function Get-TicketboxDatabaseGenerationFrozenFence {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database "ticketbox" `
        -Role "postgres"
    $capturedPsql = [string]$HostAuthority.PsqlPath
    $capturedUrl = $databaseUrl
    $allowedRoleNames = @("postgres", $script:TicketboxC07OwnerRole,
        $script:TicketboxC07MigratorRole, $script:TicketboxC07RuntimeRole)
    return Invoke-TicketboxC07WithPlainSecret `
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
                [string]$_.name -ceq $script:TicketboxC07OwnerRole
            })
            $migrator = @($observation.Roles | Where-Object {
                [string]$_.name -ceq $script:TicketboxC07MigratorRole
            })
            $runtime = @($observation.Roles | Where-Object {
                [string]$_.name -ceq $script:TicketboxC07RuntimeRole
            })
            $databaseAuthority = @($observation.Roles | Where-Object { [string]$_.name -ceq "postgres" })
            $unsafeUnregistered = @($observation.Roles | Where-Object {
                [string]$_.name -cnotin $allowedRoleNames -and
                (
                    [bool]$_.can_login -or [bool]$_.direct_connect -or
                    [bool]$_.effective_connect -or [bool]$_.is_superuser -or
                    [bool]$_.can_create_db -or [bool]$_.can_create_role -or
                    [bool]$_.can_replicate -or [bool]$_.can_bypass_rls -or
                    [bool]$_.is_database_owner -or [bool]$_.owns_managed_schema -or
                    [bool]$_.owns_managed_relations -or [bool]$_.owns_security_definer_routines -or
                    [bool]$_.can_execute_unowned_security_definer_routines -or [bool]$_.can_database_create -or
                    [bool]$_.can_managed_schema_create -or [bool]$_.can_table_write -or
                    [bool]$_.can_sequence_write -or
                    [bool]$_.can_assume_write_owner -or
                    @($_.predefined_role_usage).Count -ne 0 -or @($_.predefined_role_set).Count -ne 0
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
                [bool]$runtime[0].direct_connect -or [bool]$runtime[0].effective_connect -or
                [bool]$runtime[0].can_table_write -or
                [bool]$runtime[0].can_sequence_write -or
                [bool]$runtime[0].can_assume_write_owner
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
    $validUntil = [DateTime]::UtcNow.AddHours(1).ToString(
        "yyyy-MM-ddTHH:mm:ss.fffZ",
        [Globalization.CultureInfo]::InvariantCulture
    )
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation migrator window" `
        -Sql @"
ALTER ROLE "$script:TicketboxC07MigratorRole"
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
    VALID UNTIL '$validUntil';
"@ | Out-Null
    Assert-TicketboxC07MigratorCredential `
        $HostAuthority `
        $Credentials.MigratorPassword
}

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
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-database-binding-v1"
        operation_id = [string]$Intent.Payload.operation_id
        installation_id = [string]$Intent.Payload.installation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        source_binding_sha256 = [string]$SourceBinding.PayloadSha256
        target_revision = [string]$Intent.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        execution_authority_sha256 = $ExecutionAuthoritySha256
        role_authority_sha256 = $RoleAuthoritySha256
        runtime_acl_sha256 = $RuntimeAclSha256
        post_migration_writer_fence_sha256 = $WriterFenceSha256
        target_recovery_evidence_sha256 = $TargetRecoveryEvidenceSha256
    }
    $bindingJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
    $bindingSha256 = Get-TicketboxDatabaseGenerationTextSha256 $bindingJson
    $keyLiteral = ConvertTo-TicketboxC07SqlLiteral `
        $script:TicketboxDatabaseGenerationBindingKey
    $valueLiteral = ConvertTo-TicketboxC07SqlLiteral $bindingJson
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $observed = Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
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

function Invoke-TicketboxDatabaseGenerationTargetAdapter {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceBinding,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$SuperuserCapability
    )
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $null = Assert-TicketboxC07SuperuserCapability `
        $SuperuserCapability $operationId $LifecycleLock
    $superuserPassword = $SuperuserCapability.Secret
    if (
        [string]$SourceBinding.Payload.source_kind -cne "empty" -or
        [string]$SourceBinding.Payload.source_revision -cne "base" -or
        [string]$SourceBinding.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256
    ) {
        throw "target adapter 只接受已规范化的 exact SourceBinding。"
    }
    Renew-TicketboxDatabaseGenerationMigratorWindow `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -Credentials $Credentials
    $plan = [pscustomobject][ordered]@{
        generation_operation_id = [string]$Intent.Payload.operation_id
        source_revision = [string]$SourceBinding.Payload.source_revision
        target_revision = [string]$Intent.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        upgrade_required = $true
    }
    $result = Invoke-TicketboxPackagedManagedSchemaUpgrade `
        -HostAuthority $HostAuthority `
        -MigratorPassword $Credentials.MigratorPassword `
        -Plan $plan `
        -MigrationHelperPath ([string]$ReleaseIdentity.MigrationHelperPath) `
        -MigrationHelperEvidence (Get-TicketboxDatabaseGenerationMigrationHelperEvidence $ReleaseIdentity) `
        -ExpectedMigrationHelperPath ([string]$ReleaseIdentity.MigrationHelperPath) `
        -ProgramPath ([string]$ReleaseIdentity.DatabaseGenerationProgramPath) `
        -ProgramEvidence (Get-TicketboxDatabaseGenerationProgramEvidence $ReleaseIdentity)
    Set-TicketboxManagedSchemaRuntimeAcl `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -PreserveRuntimeFence
    $fence = Get-TicketboxDatabaseGenerationFrozenFence $HostAuthority $SuperuserPassword
    $roleSha256 = (Get-TicketboxC07RoleAuthoritySha256 $HostAuthority $SuperuserPassword).ToLowerInvariant()
    $aclSha256 = (Get-TicketboxC07RuntimeAclSha256 $HostAuthority $SuperuserPassword).ToLowerInvariant()
    $recovery = Invoke-TicketboxDatabaseGenerationTargetRecovery `
        -StateRoot $StateRoot `
        -Intent $Intent `
        -SourceBinding $SourceBinding `
        -Credentials $Credentials `
        -ReleaseIdentity $ReleaseIdentity `
        -LifecycleLock $LifecycleLock `
        -HostContract $HostContract `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $SuperuserPassword
    $executionAuthority = New-TicketboxDatabaseGenerationExecutionAuthority `
        $Intent $SourceBinding $result
    $executionAuthoritySha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $executionAuthority
    )
    $writerFenceSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $fence
    )
    $recoverySha256 = [string]$recovery.PayloadSha256
    $databaseBindingSha256 = Set-TicketboxDatabaseGenerationDatabaseBinding `
        -Intent $Intent `
        -SourceBinding $SourceBinding `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -ExecutionAuthoritySha256 $executionAuthoritySha256 `
        -RoleAuthoritySha256 $roleSha256 `
        -RuntimeAclSha256 $aclSha256 `
        -WriterFenceSha256 $writerFenceSha256 `
        -TargetRecoveryEvidenceSha256 $recoverySha256 `
        -LifecycleLock $LifecycleLock
    return [ordered]@{
        schema = "ticketbox-database-generation-target-authorization-v1"
        operation_id = $operationId
        intent_sha256 = [string]$Intent.PayloadSha256
        source_binding_sha256 = [string]$SourceBinding.PayloadSha256
        target_revision = [string]$Intent.Payload.target_revision
        execution_authority_sha256 = $executionAuthoritySha256
        role_authority_sha256 = $roleSha256
        runtime_acl_sha256 = $aclSha256
        post_migration_writer_fence_sha256 = $writerFenceSha256
        target_recovery_evidence_sha256 = $recoverySha256
        database_binding_sha256 = $databaseBindingSha256
    }
}

$sourcePath = Join-Path $PSScriptRoot "windows_database_generation_source.ps1"
if ((Get-TicketboxPathEntryKindNoFollow $sourcePath) -cne "File") {
    throw "database generation source mechanism 不是可信普通文件：$sourcePath"
}
Assert-NoTicketboxAncestorReparsePoints $sourcePath
. $sourcePath
