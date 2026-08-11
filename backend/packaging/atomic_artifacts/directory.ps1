#Requires -Version 5.1

function Publish-TicketboxVerifiedArtifactDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$GenerationRoot,
        [Parameter(Mandatory = $true)][string]$PartialRoot,
        [Parameter(Mandatory = $true)][string]$ReadyRoot,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [Parameter(Mandatory = $true)][string]$OwnerAccount
    )

    $partialParent = Split-Path -Parent $PartialRoot
    $readyParent = Split-Path -Parent $ReadyRoot
    if (
        -not (Test-TicketboxPathEquals $partialParent $GenerationRoot) -or
        -not (Test-TicketboxPathEquals $readyParent $GenerationRoot)
    ) {
        throw "atomic directory publish source/target 必须是 generation root 的直接子项。"
    }
    if (
        (Get-TicketboxVolumeIdentityForPath $PartialRoot) -cne
            (Get-TicketboxVolumeIdentityForPath $GenerationRoot)
    ) {
        throw "atomic directory publish 只允许同卷 rename。"
    }
    Assert-NoTicketboxAncestorReparsePoints $GenerationRoot
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $GenerationRoot `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    if (
        (Get-TicketboxPathEntryKindNoFollow $PartialRoot) -cne "Directory" -or
        (Get-TicketboxPathEntryKindNoFollow $ReadyRoot) -cne "Missing"
    ) {
        throw "atomic directory publish source/target 状态无效。"
    }

    Initialize-TicketboxAtomicArtifactNativeMethods
    $generationRootHandle = $null
    $readyHandle = $null
    try {
        $generationRootHandle =
            [TicketboxAtomicArtifactNativeMethods]::OpenDirectoryNoFollowNoDelete(
                $GenerationRoot
            )
        $finalGenerationRoot =
            [TicketboxAtomicArtifactNativeMethods]::GetFinalPath(
                $generationRootHandle
            )
        if (-not (Test-TicketboxPathEquals $finalGenerationRoot $GenerationRoot)) {
            throw "atomic directory publish generation root handle identity 漂移。"
        }
        [TicketboxAtomicArtifactNativeMethods]::MoveDirectoryWriteThrough(
            $PartialRoot,
            $ReadyRoot
        )
        $readyHandle =
            [TicketboxAtomicArtifactNativeMethods]::OpenDirectoryNoFollowNoDelete(
                $ReadyRoot
            )
        $finalReady = [TicketboxAtomicArtifactNativeMethods]::GetFinalPath(
            $readyHandle
        )
        if (-not (Test-TicketboxPathEquals $finalReady $ReadyRoot)) {
            throw "atomic directory publish READY handle identity 漂移。"
        }
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $ReadyRoot `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        return $ReadyRoot
    }
    finally {
        if ($null -ne $readyHandle) { $readyHandle.Dispose() }
        if ($null -ne $generationRootHandle) {
            $generationRootHandle.Dispose()
        }
    }
}
