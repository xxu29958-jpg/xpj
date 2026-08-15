# Immutable dump/restore evidence for the fixed install-time target proof.

#Requires -Version 5.1

$script:TicketboxDatabaseGenerationRestorePrefix = "ticketbox_c07_restore_"
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

function Get-TicketboxDatabaseGenerationRestoreDatabaseName {
    param([Parameter(Mandatory = $true)][string]$AttemptId)
    $attempt = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($AttemptId, "D", [ref]$attempt) -or
        $attempt -eq [Guid]::Empty -or
        $attempt.ToString("D") -cne $AttemptId
    ) {
        throw "database generation restore attempt ID 无效。"
    }
    return $script:TicketboxDatabaseGenerationRestorePrefix + $attempt.ToString("N")
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

function Get-TicketboxDatabaseGenerationRecoveryArchivePaths {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$OperationId
    )
    $name = "operation-$OperationId-target-recovery.dump"
    return [pscustomobject]@{
        Name = $name
        Path = Join-Path $StateRoot $name
        PartialPath = Join-Path $StateRoot ".$name.partial"
    }
}

function Remove-TicketboxDatabaseGenerationRecoveryFile {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    if (-not (Test-TicketboxPathWithin $Path $StateRoot)) {
        throw "database generation recovery file 越出 state root。"
    }
    $kind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($kind -ceq "Missing") { return }
    if ($kind -cne "File") {
        throw "database generation recovery residue 不是普通文件。"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    [IO.File]::Delete($Path)
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "Missing") {
        throw "database generation recovery residue 删除失败。"
    }
}

function Remove-TicketboxDatabaseGenerationTargetRecoveryArchive {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $operation = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($OperationId, "D", [ref]$operation) -or
        $operation -eq [Guid]::Empty -or
        $operation.ToString("D") -cne $OperationId
    ) {
        throw "database generation recovery cleanup operation ID 无效。"
    }
    $archive = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $OperationId "target-recovery-archive"
    $paths = Get-TicketboxDatabaseGenerationRecoveryArchivePaths `
        $StateRoot $OperationId
    if ([string]$archive.Payload.archive_file_name -cne $paths.Name) {
        throw "database generation recovery archive 路径身份漂移。"
    }
    $kind = Get-TicketboxPathEntryKindNoFollow $paths.Path
    if ($kind -ceq "Missing") { return }
    if ($kind -cne "File") {
        throw "database generation recovery archive 不是普通文件。"
    }
    [void](Assert-TicketboxDatabaseGenerationRecoveryArchive $StateRoot $archive)
    Remove-TicketboxDatabaseGenerationRecoveryFile `
        $StateRoot $paths.Path $LifecycleLock
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

function Assert-TicketboxDatabaseGenerationRecoveryChain {
    param(
        [AllowNull()][object]$Intent,
        [AllowNull()][object]$SourceBinding,
        [AllowNull()][object]$Attempt,
        [AllowNull()][object]$Archive,
        [AllowNull()][object]$Binding,
        [AllowNull()][object]$Verification,
        [AllowNull()][object]$Proof
    )
    if ($null -eq $Attempt) { throw "recovery chain 缺少 attempt。" }
    $operationId = ([Guid][string]$Attempt.Payload.operation_id).ToString("D")
    if (
        [string]$Attempt.Payload.restore_database -cne
            (Get-TicketboxDatabaseGenerationRestoreDatabaseName (
                [string]$Attempt.Payload.create_attempt_id
            ))
    ) {
        throw "recovery attempt restore identity 漂移。"
    }
    if ($null -ne $Intent -and (
        [string]$Attempt.Payload.operation_id -cne
            [string]$Intent.Payload.operation_id -or
        [string]$Attempt.Payload.intent_sha256 -cne
            [string]$Intent.PayloadSha256 -or
        [string]$Attempt.Payload.target_revision -cne
            [string]$Intent.Payload.target_revision -or
        [string]$Attempt.Payload.generation_program_sha256 -cne
            [string]$Intent.Payload.generation_program_sha256
    )) { throw "recovery attempt 未绑定 exact intent。" }
    if ($null -ne $SourceBinding -and (
        [string]$Attempt.Payload.source_binding_sha256 -cne
            [string]$SourceBinding.PayloadSha256 -or
        [string]$Attempt.Payload.source_cluster_system_identifier -cne
            [string]$SourceBinding.Payload.cluster_system_identifier -or
        [string]$Attempt.Payload.source_database_oid -cne
            [string]$SourceBinding.Payload.database_oid
    )) { throw "recovery attempt 未绑定 exact source。" }
    if ($null -ne $Archive -and (
        [string]$Archive.Payload.operation_id -cne $operationId -or
        [string]$Archive.Payload.attempt_sha256 -cne
            [string]$Attempt.PayloadSha256
    )) { throw "recovery archive 未绑定 exact attempt。" }
    if ($null -ne $Binding -and (
        [string]$Binding.Payload.operation_id -cne $operationId -or
        [string]$Binding.Payload.attempt_sha256 -cne
            [string]$Attempt.PayloadSha256 -or
        [string]$Binding.Payload.restore_database -cne
            [string]$Attempt.Payload.restore_database
    )) { throw "recovery binding 未绑定 exact attempt。" }
    if ($null -ne $Verification) {
        if ($null -eq $Archive -or $null -eq $Binding) {
            throw "recovery verification 缺少 archive/binding。"
        }
        if (
            [string]$Verification.Payload.operation_id -cne $operationId -or
            [string]$Verification.Payload.attempt_sha256 -cne
                [string]$Attempt.PayloadSha256 -or
            [string]$Verification.Payload.binding_sha256 -cne
                [string]$Binding.PayloadSha256 -or
            [string]$Verification.Payload.archive_sha256 -cne
                [string]$Archive.Payload.archive_sha256 -or
            [string]$Verification.Payload.target_revision -cne
                [string]$Attempt.Payload.target_revision -or
            [string]$Verification.Payload.generation_program_sha256 -cne
                [string]$Attempt.Payload.generation_program_sha256
        ) { throw "recovery verification authority chain 漂移。" }
    }
    if ($null -ne $Proof) {
        if (
            $null -eq $Intent -or $null -eq $SourceBinding -or
            $null -eq $Archive -or $null -eq $Binding -or
            $null -eq $Verification
        ) { throw "recovery proof 缺少完整 authority chain。" }
        if (
            [string]$Proof.Payload.operation_id -cne $operationId -or
            [string]$Proof.Payload.intent_sha256 -cne
                [string]$Intent.PayloadSha256 -or
            [string]$Proof.Payload.source_binding_sha256 -cne
                [string]$SourceBinding.PayloadSha256 -or
            [string]$Proof.Payload.target_revision -cne
                [string]$Intent.Payload.target_revision -or
            [string]$Proof.Payload.generation_program_sha256 -cne
                [string]$Intent.Payload.generation_program_sha256 -or
            [string]$Proof.Payload.attempt_sha256 -cne
                [string]$Attempt.PayloadSha256 -or
            [string]$Proof.Payload.archive_sha256 -cne
                [string]$Archive.Payload.archive_sha256 -or
            [string]$Proof.Payload.verification_sha256 -cne
                [string]$Verification.PayloadSha256 -or
            [string]$Proof.Payload.restore_database_oid -cne
                [string]$Binding.Payload.restore_database_oid
        ) { throw "recovery proof authority chain 漂移。" }
    }
    return $true
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

function Assert-TicketboxDatabaseGenerationRecoveryArchive {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Archive
    )
    $path = Join-Path $StateRoot ([string]$Archive.Payload.archive_file_name)
    if (
        -not (Test-TicketboxPathWithin $path $StateRoot) -or
        (Get-TicketboxPathEntryKindNoFollow $path) -cne "File"
    ) {
        throw "database generation recovery archive 缺失或越界。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    $item = Get-Item -LiteralPath $path -Force
    $sha256 = (Get-TicketboxPortableFileSha256 $path).ToLowerInvariant()
    if (
        [int64]$item.Length -ne [int64]$Archive.Payload.archive_size -or
        $sha256 -cne [string]$Archive.Payload.archive_sha256
    ) {
        throw "database generation recovery archive bytes 漂移。"
    }
    return $path
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
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $HostAuthority -Database "ticketbox" -Role "postgres"
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $capturedDump = $pgDump
    $capturedUrl = $databaseUrl
    $capturedOutput = $paths.PartialPath
    $exitCode = Invoke-TicketboxC07WithPlainSecret `
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
