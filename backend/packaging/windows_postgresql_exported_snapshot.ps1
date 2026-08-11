#Requires -Version 5.1

<#
.SYNOPSIS
  Hosts a bounded PostgreSQL exported-snapshot session.
.DESCRIPTION
  Provides generic psql process transport, live-session checks, bounded stream
  reads/shutdown, and exact no-widen deadline-evidence validation. Product SQL,
  inventory schemas, lifecycle identity, and generation policy stay with the
  caller. This adapter accepts data only and exposes no policy callback.
#>

$componentRoot = Join-Path $PSScriptRoot "postgresql_exported_snapshot"
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
        throw "PostgreSQL exported-snapshot loader 缺少安全函数：$requiredLoaderGuard"
    }
}
foreach ($component in @(
    "primitives.ps1",
    "session.ps1",
    "deadline_evidence.ps1"
)) {
    $componentPath = Join-Path $componentRoot $component
    Assert-NoTicketboxAncestorReparsePoints $componentPath
    if (
        (Get-TicketboxPathEntryKindNoFollow $componentPath) -cne "File"
    ) {
        throw "PostgreSQL exported-snapshot 组件不是可信普通文件：$componentPath"
    }
    . $componentPath
}

function Assert-TicketboxPostgresqlExportedSnapshotDependencies {
    foreach ($name in @(
        "Assert-NoTicketboxAncestorReparsePoints",
        "ConvertTo-TicketboxNativeCommandLineArgument",
        "Get-TicketboxPathEntryKindNoFollow"
    )) {
        if (
            $null -eq (
                Get-Command $name -CommandType Function -ErrorAction SilentlyContinue
            )
        ) {
            throw "PostgreSQL exported-snapshot 缺少依赖函数：$name"
        }
    }
}
