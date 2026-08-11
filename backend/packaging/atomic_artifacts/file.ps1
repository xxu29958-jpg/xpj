#Requires -Version 5.1

function Assert-TicketboxArtifactSha256 {
    param(
        [AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch "^[0-9a-f]{64}$") {
        throw "$Label 不是 canonical lowercase SHA-256。"
    }
}

function Sync-TicketboxDurableArtifactFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    Assert-NoTicketboxAncestorReparsePoints $Path
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "File") {
        throw "durable artifact flush target 不是普通文件。"
    }
    Initialize-TicketboxAtomicArtifactNativeMethods
    $stream = $null
    try {
        $stream = [IO.FileStream]::new(
            $Path,
            [IO.FileMode]::Open,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::Read,
            1048576,
            [IO.FileOptions]::WriteThrough
        )
        $finalPath = [TicketboxAtomicArtifactNativeMethods]::GetFinalPath(
            $stream.SafeFileHandle
        )
        if (-not (Test-TicketboxPathEquals $finalPath $Path)) {
            throw "durable artifact flush handle identity 漂移。"
        }
        [TicketboxAtomicArtifactNativeMethods]::AssertHandleIsNotReparsePoint(
            $stream.SafeFileHandle
        )
        $stream.Flush($true)
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Copy-TicketboxVerifiedArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceSha256,
        [Parameter(Mandatory = $true)][int64]$ExpectedLength,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [Parameter(Mandatory = $true)][string]$OwnerAccount
    )
    if ($ExpectedLength -le 0) {
        throw "verified artifact expected length 无效。"
    }
    Assert-TicketboxArtifactSha256 `
        -Value $ExpectedSourceSha256 `
        -Label "verified artifact source expected digest"
    Assert-NoTicketboxAncestorReparsePoints $SourcePath
    if ((Get-TicketboxPathEntryKindNoFollow $SourcePath) -cne "File") {
        throw "verified artifact source 缺失或经过 reparse point。"
    }
    $destinationParent = Split-Path -Parent $DestinationPath
    Assert-NoTicketboxAncestorReparsePoints $destinationParent
    if (
        (Get-TicketboxPathEntryKindNoFollow $destinationParent) -cne
            "Directory"
    ) {
        throw "verified artifact destination parent 不是普通目录。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $DestinationPath) -cne "Missing") {
        throw "verified artifact destination 已存在；拒绝覆盖。"
    }

    Initialize-TicketboxAtomicArtifactNativeMethods
    $source = $null
    $destination = $null
    $destinationParentHandle = $null
    $destinationHandle = $null
    $sourceSha = [Security.Cryptography.SHA256]::Create()
    $destinationSha = [Security.Cryptography.SHA256]::Create()
    try {
        $destinationParentHandle =
            [TicketboxAtomicArtifactNativeMethods]::OpenDirectoryNoFollowNoDelete(
                $destinationParent
            )
        $finalDestinationParent =
            [TicketboxAtomicArtifactNativeMethods]::GetFinalPath(
                $destinationParentHandle
            )
        if (
            -not (Test-TicketboxPathEquals `
                $finalDestinationParent `
                $destinationParent)
        ) {
            throw "verified artifact destination parent handle identity 漂移。"
        }
        $source = [IO.FileStream]::new(
            $SourcePath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read,
            1048576,
            [IO.FileOptions]::SequentialScan
        )
        $finalSource = [TicketboxAtomicArtifactNativeMethods]::GetFinalPath(
            $source.SafeFileHandle
        )
        if (-not (Test-TicketboxPathEquals $finalSource $SourcePath)) {
            throw "verified artifact source handle identity 漂移。"
        }
        if ($source.Length -ne $ExpectedLength) {
            throw "verified artifact source 长度与权威长度不一致。"
        }
        $sourceDigest = ([BitConverter]::ToString(
            $sourceSha.ComputeHash($source)
        )).Replace("-", "").ToLowerInvariant()
        if ($sourceDigest -cne $ExpectedSourceSha256) {
            throw "verified artifact source bytes 与权威 digest 不一致。"
        }
        $source.Position = 0
        $destinationHandle =
            [TicketboxAtomicArtifactNativeMethods]::CreateNewFileNoFollow(
                $DestinationPath
            )
        $destination = [IO.FileStream]::new(
            $destinationHandle,
            [IO.FileAccess]::ReadWrite,
            1048576,
            $false
        )
        $destinationHandle = $null
        $finalDestination =
            [TicketboxAtomicArtifactNativeMethods]::GetFinalPath(
                $destination.SafeFileHandle
            )
        if (-not (Test-TicketboxPathEquals $finalDestination $DestinationPath)) {
            throw "verified artifact destination handle identity 漂移。"
        }
        $buffer = New-Object byte[] 1048576
        while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $destination.Write($buffer, 0, $read)
        }
        $destination.Flush($true)
        if ($destination.Length -ne $ExpectedLength) {
            throw "verified artifact destination 长度与权威长度不一致。"
        }
        $destination.Position = 0
        $destinationDigest = ([BitConverter]::ToString(
            $destinationSha.ComputeHash($destination)
        )).Replace("-", "").ToLowerInvariant()
        if ($destinationDigest -cne $sourceDigest) {
            throw "verified artifact destination 未通过 digest 复读。"
        }
        $destination.Flush($true)
        Set-TicketboxExactFileAcl `
            -Path $DestinationPath `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        Assert-TicketboxExactFileAcl `
            -Path $DestinationPath `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        $finalProtectedDestination =
            [TicketboxAtomicArtifactNativeMethods]::GetFinalPath(
                $destination.SafeFileHandle
            )
        if (
            -not (Test-TicketboxPathEquals `
                $finalProtectedDestination `
                $DestinationPath)
        ) {
            throw "verified artifact protected destination handle identity 漂移。"
        }
        return [pscustomobject]@{
            Sha256 = $sourceDigest
            SizeBytes = [int64]$ExpectedLength
        }
    }
    finally {
        if ($null -ne $destination) { $destination.Dispose() }
        if ($null -ne $destinationHandle) { $destinationHandle.Dispose() }
        if ($null -ne $destinationParentHandle) {
            $destinationParentHandle.Dispose()
        }
        if ($null -ne $source) { $source.Dispose() }
        $sourceSha.Dispose()
        $destinationSha.Dispose()
    }
}
