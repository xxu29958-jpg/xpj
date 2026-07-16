#Requires -Version 5.1

$script:XpjTestPostgresDeletionReceiptKind = 'xiaopiaojia-test-postgres-deletion'

if (-not ('XpjTestDirectoryMoveHandle' -as [type])) {
    $directoryMoveSource = Join-Path $PSScriptRoot 'test_pg_directory_move.cs'
    if (-not (Test-Path -LiteralPath $directoryMoveSource -PathType Leaf)) {
        throw "Test PostgreSQL directory move helper is missing: $directoryMoveSource"
    }
    Add-Type -Path $directoryMoveSource -ErrorAction Stop
}

function Get-XpjTestPostgresDeletionReceiptPath {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    $parent = Split-Path -Parent $DataDirectory
    $leaf = Split-Path -Leaf $DataDirectory
    return Join-Path $parent ".$leaf.xpj-delete.receipt.json"
}

function New-XpjTestPostgresDeletionReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$SystemIdentifier
    )

    if ($SystemIdentifier -notmatch '^\d{10,20}$') {
        throw 'Cannot authorize test PostgreSQL deletion with an invalid system identifier.'
    }
    $directoryHandle = [XpjTestDirectoryMoveHandle]::OpenIdentity($DataDirectory)
    try {
    $marker = Assert-XpjTestPostgresDataOwnership `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Purpose $Purpose `
        -Port $Port
    if ($marker.SystemIdentifier -cne $SystemIdentifier) {
        throw 'Cannot authorize deletion for a different PostgreSQL system identifier.'
    }
    [void](Assert-XpjTestPostgresQuiescent -DataDirectory $DataDirectory -Port $Port)
    $receiptPath = Get-XpjTestPostgresDeletionReceiptPath $DataDirectory
    if (Test-Path -LiteralPath $receiptPath) {
        throw "Test PostgreSQL deletion receipt already exists: $receiptPath"
    }
    $parent = Split-Path -Parent $DataDirectory
    $leaf = Split-Path -Leaf $DataDirectory
    $tombstone = Join-Path $parent ".$leaf.xpj-delete-$([Guid]::NewGuid().ToString('N'))"
    if (Test-Path -LiteralPath $tombstone) {
        throw "Test PostgreSQL deletion tombstone already exists: $tombstone"
    }
    $owner = Get-Process -Id $PID -ErrorAction Stop
    $payload = [ordered]@{
        Kind = $script:XpjTestPostgresDeletionReceiptKind
        DataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
        TombstoneDirectory = [System.IO.Path]::GetFullPath($tombstone)
        Phase = 'source'
        Purpose = $Purpose
        Port = $Port
        InstanceId = $marker.InstanceId
        SystemIdentifier = $SystemIdentifier
        DirectoryIdentity = $directoryHandle.Identity
        OwnerProcessId = $PID
        OwnerStartedAtUtc = $owner.StartTime.ToUniversalTime().ToString('O')
    }
    $temporaryPath = "$receiptPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        Write-XpjTestPostgresProtectedUtf8File `
            -Path $temporaryPath `
            -Content ($payload | ConvertTo-Json -Compress)
        [System.IO.File]::Move($temporaryPath, $receiptPath)
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $receiptPath `
            -Label 'Test PostgreSQL deletion receipt'
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
    return $receiptPath
    }
    finally {
        $directoryHandle.Dispose()
    }
}

function Read-XpjTestPostgresDeletionReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    Assert-XpjTestPostgresProtectedAuthorityFile `
        -Path $ReceiptPath `
        -Label 'Test PostgreSQL deletion receipt'
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 -ErrorAction Stop |
        ConvertFrom-Json -ErrorAction Stop
    $expectedDataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
    $actualDataDirectory = [System.IO.Path]::GetFullPath([string]$receipt.DataDirectory)
    $actualTombstone = [System.IO.Path]::GetFullPath([string]$receipt.TombstoneDirectory)
    $expectedReceipt = Get-XpjTestPostgresDeletionReceiptPath $expectedDataDirectory
    $expectedParent = Split-Path -Parent $expectedDataDirectory
    $tombstoneParent = Split-Path -Parent $actualTombstone
    $expectedLeaf = [regex]::Escape((Split-Path -Leaf $expectedDataDirectory))
    if (
        [string]$receipt.Kind -cne $script:XpjTestPostgresDeletionReceiptKind -or
        -not [string]::Equals($actualDataDirectory, $expectedDataDirectory, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($ReceiptPath, $expectedReceipt, [System.StringComparison]::OrdinalIgnoreCase) -or
        [string]$receipt.Purpose -cne $Purpose -or
        [int]$receipt.Port -ne $Port -or
        [string]$receipt.InstanceId -notmatch '^[0-9a-f]{32}$' -or
        [string]$receipt.SystemIdentifier -notmatch '^\d{10,20}$' -or
        [string]$receipt.DirectoryIdentity -notmatch '^[0-9a-f]{8}:[0-9a-f]{8}:[0-9a-f]{8}$' -or
        [string]$receipt.Phase -notin @('source', 'tombstone') -or
        -not [string]::Equals($tombstoneParent, $expectedParent, [System.StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $actualTombstone) -notmatch "^\.$expectedLeaf\.xpj-delete-[0-9a-f]{32}$"
    ) {
        throw "Deletion receipt does not authorize this test PostgreSQL lifecycle: $ReceiptPath"
    }
    return $receipt
}

function Assert-XpjTestPostgresDeletionDirectoryInstance {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)]$Receipt,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)]$DirectoryHandle
    )

    if ($DirectoryHandle.Identity -cne [string]$Receipt.DirectoryIdentity) {
        throw 'Deletion receipt does not match this filesystem directory instance.'
    }
    $marker = Assert-XpjTestPostgresDataOwnership `
        -PostgresBin $PostgresBin `
        -DataDirectory $Directory `
        -Purpose $Purpose `
        -Port $Port
    if (
        $marker.InstanceId -cne [string]$Receipt.InstanceId -or
        $marker.SystemIdentifier -cne [string]$Receipt.SystemIdentifier
    ) {
        throw 'Deletion receipt does not match this PostgreSQL directory instance.'
    }
    [void](Assert-XpjTestPostgresQuiescent -DataDirectory $Directory -Port $Port)
}

function Set-XpjTestPostgresDeletionReceiptPhase {
    param(
        [Parameter(Mandatory = $true)]$Receipt,
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][ValidateSet('source', 'tombstone')][string]$Phase
    )

    $Receipt.Phase = $Phase
    $temporaryPath = "$ReceiptPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    $backupPath = "$ReceiptPath.replace-backup"
    try {
        Write-XpjTestPostgresProtectedUtf8File `
            -Path $temporaryPath `
            -Content ($Receipt | ConvertTo-Json -Compress)
        if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction Stop
        }
        [System.IO.File]::Replace($temporaryPath, $ReceiptPath, $backupPath)
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $ReceiptPath `
            -Label 'Test PostgreSQL deletion receipt'
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Complete-XpjTestPostgresPendingDeletion {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $receiptPath = Get-XpjTestPostgresDeletionReceiptPath $DataDirectory
    if (-not (Test-Path -LiteralPath $receiptPath)) {
        return $false
    }
    $receipt = Read-XpjTestPostgresDeletionReceipt `
        -ReceiptPath $receiptPath `
        -DataDirectory $DataDirectory `
        -Purpose $Purpose `
        -Port $Port
    Assert-XpjTestPostgresReceiptOwnerInactiveOrCurrent $receipt
    $tombstone = [System.IO.Path]::GetFullPath([string]$receipt.TombstoneDirectory)
    if (
        [string]$receipt.Phase -eq 'source' -and
        -not (Test-Path -LiteralPath $tombstone) -and
        (Test-Path -LiteralPath $DataDirectory)
    ) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
        if ($listeners.Count -gt 0) {
            throw "Cannot publish a test PostgreSQL deletion tombstone while port $Port still has a listener."
        }
        $sourceHandle = [XpjTestDirectoryMoveHandle]::OpenIdentity($DataDirectory)
        try {
            Assert-XpjTestPostgresDeletionDirectoryInstance `
                -PostgresBin $PostgresBin `
                -Directory $DataDirectory `
                -Receipt $receipt `
                -Purpose $Purpose `
                -Port $Port `
                -DirectoryHandle $sourceHandle
        }
        finally {
            $sourceHandle.Dispose()
        }
        # Reopen with DELETE access. A replacement in the reopen window is
        # detected by its filesystem identity before this handle can rename it.
        $directoryMove = [XpjTestDirectoryMoveHandle]::Open($DataDirectory)
        try {
            if ($directoryMove.Identity -cne [string]$receipt.DirectoryIdentity) {
                throw 'Deletion source was replaced before tombstone publication.'
            }
            $directoryMove.RenameTo($tombstone)
        }
        finally {
            $directoryMove.Dispose()
        }
    }
    if (Test-Path -LiteralPath $tombstone) {
        $tombstoneHandle = [XpjTestDirectoryMoveHandle]::OpenIdentity($tombstone)
        try {
            if ([string]$receipt.Phase -ne 'tombstone') {
                Assert-XpjTestPostgresDeletionDirectoryInstance `
                    -PostgresBin $PostgresBin `
                    -Directory $tombstone `
                    -Receipt $receipt `
                    -Purpose $Purpose `
                    -Port $Port `
                    -DirectoryHandle $tombstoneHandle
                Set-XpjTestPostgresDeletionReceiptPhase `
                    -Receipt $receipt `
                    -ReceiptPath $receiptPath `
                    -Phase tombstone
                $receipt.Phase = 'tombstone'
            }
            elseif ($tombstoneHandle.Identity -cne [string]$receipt.DirectoryIdentity) {
                throw 'Deletion tombstone was replaced after partial cleanup.'
            }
        }
        finally {
            $tombstoneHandle.Dispose()
        }
        $item = Get-Item -LiteralPath $tombstone -Force -ErrorAction Stop
        if (-not $item.PSIsContainer) {
            throw "Test PostgreSQL deletion tombstone is not a directory: $tombstone"
        }
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Test PostgreSQL deletion tombstone must not be a reparse point: $tombstone"
        }
        # A receipt authorizes one directory generation, not deletion while that
        # generation is live. Recovery must re-prove quiescence on every retry.
        [void](Assert-XpjTestPostgresQuiescent `
            -DataDirectory $tombstone `
            -Port $Port)
        # The source name is no longer a deletion target. A later install/test
        # run may safely reuse it while this unique tombstone is being retried.
        Remove-XpjTestPostgresDirectoryBounded `
            -Directory $tombstone `
            -ExpectedDirectoryIdentity ([string]$receipt.DirectoryIdentity)
    }
    elseif ([string]$receipt.Phase -eq 'source') {
        throw 'Deletion receipt source disappeared before its tombstone was published.'
    }
    elseif (Test-Path -LiteralPath $DataDirectory -PathType Container) {
        $resumeRestoredSource = $false
        $restoredHandle = [XpjTestDirectoryMoveHandle]::OpenIdentity($DataDirectory)
        try {
            if ($restoredHandle.Identity -ceq [string]$receipt.DirectoryIdentity) {
                Assert-XpjTestPostgresDeletionDirectoryInstance `
                    -PostgresBin $PostgresBin `
                    -Directory $DataDirectory `
                    -Receipt $receipt `
                    -Purpose $Purpose `
                    -Port $Port `
                    -DirectoryHandle $restoredHandle
                Set-XpjTestPostgresDeletionReceiptPhase `
                    -Receipt $receipt `
                    -ReceiptPath $receiptPath `
                    -Phase source
                $resumeRestoredSource = $true
            }
        }
        finally {
            $restoredHandle.Dispose()
        }
        if ($resumeRestoredSource) {
            return Complete-XpjTestPostgresPendingDeletion `
                -PostgresBin $PostgresBin `
                -DataDirectory $DataDirectory `
                -Purpose $Purpose `
                -Port $Port
        }
    }
    Remove-Item -LiteralPath $receiptPath -Force -ErrorAction Stop
    Remove-Item -LiteralPath "$receiptPath.replace-backup" -Force -ErrorAction SilentlyContinue
    return $true
}
