# Bounded lifecycle cleanup adapter for the immutable recovery archive.

#Requires -Version 5.1

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
