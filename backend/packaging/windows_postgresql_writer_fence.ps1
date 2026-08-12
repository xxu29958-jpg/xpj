#Requires -Version 5.1

$writerFenceRoot = Join-Path $PSScriptRoot "postgresql_writer_fence"
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
        throw "PostgreSQL writer-fence loader is missing: $requiredLoaderGuard"
    }
}
foreach ($component in @(
    "primitives.ps1",
    "observation_query.ps1",
    "observation_codec.ps1",
    "observation.ps1",
    "reconcile_policy.ps1",
    "precondition_guard.ps1",
    "session_drain.ps1",
    "reconciler.ps1"
)) {
    $componentPath = Join-Path $writerFenceRoot $component
    Assert-NoTicketboxAncestorReparsePoints $componentPath
    if ((Get-TicketboxPathEntryKindNoFollow $componentPath) -cne "File") {
        throw "PostgreSQL writer-fence component is not a trusted file: $componentPath"
    }
    . $componentPath
}
