# Immutable dump/restore evidence for the fixed install-time target proof.

#Requires -Version 5.1

$script:TicketboxDatabaseGenerationRecoveryTimeoutMs = 1200000

function Assert-TicketboxDatabaseGenerationToolIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedPath,
        [Parameter(Mandatory = $true)][long]$ExpectedSize,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $path = ConvertTo-TicketboxWin32CanonicalPath $Path
    $expectedPath = ConvertTo-TicketboxWin32CanonicalPath $ExpectedPath
    if (
        -not (Test-TicketboxPathEquals $path $expectedPath) -or
        $ExpectedSize -lt 1 -or
        $ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$' -or
        (Get-TicketboxPathEntryKindNoFollow $path) -cne "File"
    ) {
        throw "$Label 与 build-owned tool contract 不一致。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (
        [int64]$item.Length -ne $ExpectedSize -or
        (Get-TicketboxPortableFileSha256 $path).ToLowerInvariant() -cne
            $ExpectedSha256
    ) {
        throw "$Label bytes 与 build-owned tool contract 不一致。"
    }
    return $path
}

function Get-TicketboxDatabaseGenerationRestoreMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][uint32]$DatabaseOid
    )
    return @(
        "ticketbox-database-generation-restore-v1",
        [string]$Attempt.Payload.operation_id,
        [string]$Attempt.Payload.create_attempt_id,
        [string]$Attempt.Payload.intent_sha256,
        [string]$Attempt.Payload.source_binding_sha256,
        [string]$DatabaseOid
    ) -join "|"
}

function New-TicketboxDatabaseGenerationRecoveryArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    return New-TicketboxDatabaseGenerationChainedArtifact `
        $StateRoot $OperationId $Kind $Payload $LifecycleLock
}

function Get-TicketboxDatabaseGenerationRecoveryAttempt {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceBinding,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $operationId = [string]$Intent.Payload.operation_id
    $existing = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "target-recovery-attempt" -AllowAbsent
    if ($null -ne $existing) {
        [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
            $Intent $SourceBinding $existing $null $null $null $null)
        return $existing
    }
    $createAttemptId = [Guid]::NewGuid().ToString("D")
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-recovery-attempt-v1"
        operation_id = $operationId
        intent_sha256 = [string]$Intent.PayloadSha256
        source_binding_sha256 = [string]$SourceBinding.PayloadSha256
        target_revision = [string]$Intent.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        create_attempt_id = $createAttemptId
        restore_database = Get-TicketboxDatabaseGenerationRestoreDatabaseName $createAttemptId
        source_cluster_system_identifier =
            [string]$SourceBinding.Payload.cluster_system_identifier
        source_database_oid = [string]$SourceBinding.Payload.database_oid
    }
    return New-TicketboxDatabaseGenerationRecoveryArtifact `
        $StateRoot $operationId "target-recovery-attempt" $payload $LifecycleLock
}

function Get-TicketboxDatabaseGenerationRecoveryArchive {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $operationId = [string]$Attempt.Payload.operation_id
    $pgBin = Split-Path -Parent ([string]$HostAuthority.PsqlPath)
    $pgDump = Assert-TicketboxDatabaseGenerationToolIdentity `
        -Path (Join-Path $pgBin "pg_dump.exe") `
        -ExpectedPath ([string]$HostContract.pg_dump_path) `
        -ExpectedSize ([int64]$HostContract.pg_dump_size) `
        -ExpectedSha256 ([string]$HostContract.pg_dump_sha256) `
        -Label "pg_dump.exe"
    $pgRestore = Assert-TicketboxDatabaseGenerationToolIdentity `
        -Path (Join-Path $pgBin "pg_restore.exe") `
        -ExpectedPath ([string]$HostContract.pg_restore_path) `
        -ExpectedSize ([int64]$HostContract.pg_restore_size) `
        -ExpectedSha256 ([string]$HostContract.pg_restore_sha256) `
        -Label "pg_restore.exe"
    $existing = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "target-recovery-archive" -AllowAbsent
    if ($null -ne $existing) {
        if (
            (Get-TicketboxPortableFileSha256 $pgDump).ToLowerInvariant() -cne
                [string]$existing.Payload.pg_dump_sha256 -or
            (Get-TicketboxPortableFileSha256 $pgRestore).ToLowerInvariant() -cne
                [string]$existing.Payload.pg_restore_sha256
        ) { throw "recovery archive PostgreSQL tool identity 漂移。" }
        [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
            $null $null $Attempt $existing $null $null $null)
        [void](Assert-TicketboxDatabaseGenerationRecoveryArchive $StateRoot $existing)
        return $existing
    }
    $paths = Get-TicketboxDatabaseGenerationRecoveryArchivePaths $StateRoot $operationId
    Remove-TicketboxDatabaseGenerationRecoveryFile `
        $StateRoot $paths.PartialPath $LifecycleLock
    # An archive without its immutable metadata is unowned. Never bless it as
    # this operation's evidence; replace it with a new writer-fenced dump.
    Remove-TicketboxDatabaseGenerationRecoveryFile `
        $StateRoot $paths.Path $LifecycleLock
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role "postgres"
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $capturedDump = $pgDump
    $capturedUrl = $databaseUrl
    $capturedOutput = $paths.PartialPath
    $exitCode = Invoke-TicketboxWithPlainPostgresqlSecret `
        -Secret $SuperuserPassword `
        -Action ({
            param([string]$PlainPassword)
            return Invoke-TicketboxPgDumpCustom `
                -PgDumpPath $capturedDump `
                -DatabaseUrl $capturedUrl `
                -OutputPath $capturedOutput `
                -Password $PlainPassword `
                -TimeoutMilliseconds $script:TicketboxDatabaseGenerationRecoveryTimeoutMs
        }.GetNewClosure())
    if ([int]$exitCode -ne 0) {
        throw "database generation target pg_dump 失败。"
    }
    [void](Assert-TicketboxDatabaseGenerationToolIdentity `
        -Path $pgDump `
        -ExpectedPath ([string]$HostContract.pg_dump_path) `
        -ExpectedSize ([int64]$HostContract.pg_dump_size) `
        -ExpectedSha256 ([string]$HostContract.pg_dump_sha256) `
        -Label "pg_dump.exe after execution")
    if (
        (Get-TicketboxPathEntryKindNoFollow $paths.PartialPath) -cne "File" -or
        (Get-Item -LiteralPath $paths.PartialPath -Force).Length -lt 1
    ) {
        throw "database generation target pg_dump 未产生 archive。"
    }
    Sync-TicketboxFileDurable $paths.PartialPath
    $partial = Get-Item -LiteralPath $paths.PartialPath -Force
    $partialSha256 = (
        Get-TicketboxPortableFileSha256 $paths.PartialPath
    ).ToLowerInvariant()
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    [void](Copy-TicketboxVerifiedArtifact `
        -SourcePath $paths.PartialPath `
        -DestinationPath $paths.Path `
        -ExpectedSourceSha256 $partialSha256 `
        -ExpectedLength ([int64]$partial.Length) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount)
    Remove-TicketboxDatabaseGenerationRecoveryFile `
        $StateRoot $paths.PartialPath $LifecycleLock
    if (
        (Invoke-TicketboxPgRestoreList `
            -PgRestorePath $pgRestore `
            -ArchivePath $paths.Path `
            -TimeoutMilliseconds $script:TicketboxDatabaseGenerationRecoveryTimeoutMs) -ne 0
    ) {
        throw "database generation target archive 未通过 pg_restore --list。"
    }
    [void](Assert-TicketboxDatabaseGenerationToolIdentity `
        -Path $pgRestore `
        -ExpectedPath ([string]$HostContract.pg_restore_path) `
        -ExpectedSize ([int64]$HostContract.pg_restore_size) `
        -ExpectedSha256 ([string]$HostContract.pg_restore_sha256) `
        -Label "pg_restore.exe after archive inspection")
    $item = Get-Item -LiteralPath $paths.Path -Force
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-recovery-archive-v1"
        operation_id = $operationId
        attempt_sha256 = [string]$Attempt.PayloadSha256
        archive_file_name = $paths.Name
        archive_size = [int64]$item.Length
        archive_sha256 = (Get-TicketboxPortableFileSha256 $paths.Path).ToLowerInvariant()
        pg_dump_sha256 = (Get-TicketboxPortableFileSha256 $pgDump).ToLowerInvariant()
        pg_restore_sha256 = (Get-TicketboxPortableFileSha256 $pgRestore).ToLowerInvariant()
    }
    return New-TicketboxDatabaseGenerationRecoveryArtifact `
        $StateRoot $operationId "target-recovery-archive" $payload $LifecycleLock
}
