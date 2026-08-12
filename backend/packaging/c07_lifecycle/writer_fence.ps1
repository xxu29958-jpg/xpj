#Requires -Version 5.1

$writerFenceComponentRoot = Join-Path $PSScriptRoot "writer_fence"
foreach ($requiredLoaderGuard in @(
    "Assert-NoTicketboxAncestorReparsePoints",
    "Get-TicketboxPathEntryKindNoFollow"
)) {
    if (
        $null -eq (
            Get-Command `
                $requiredLoaderGuard `
                -CommandType Function `
                -ErrorAction SilentlyContinue
        )
    ) {
        throw "C07 writer-fence loader is missing: $requiredLoaderGuard"
    }
}
foreach ($component in @("policy.ps1", "adapter.ps1")) {
    $componentPath = Join-Path $writerFenceComponentRoot $component
    Assert-NoTicketboxAncestorReparsePoints $componentPath
    if ((Get-TicketboxPathEntryKindNoFollow $componentPath) -cne "File") {
        throw "C07 writer-fence component is not a trusted file: $componentPath"
    }
    . $componentPath
}
