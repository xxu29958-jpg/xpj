#Requires -Version 5.1

<#
.SYNOPSIS
  Observes PostgreSQL cluster and database catalog identity without mutation.
.DESCRIPTION
  Keeps catalog SQL, evidence parsing, and host invocation outside product
  policy. The caller supplies an already policy-approved connection target.
#>

$componentRoot = Join-Path $PSScriptRoot "postgresql_database_catalog"
foreach ($componentName in @(
    "primitives.ps1",
    "query.ps1",
    "codec.ps1",
    "observation.ps1"
)) {
    $componentPath = Join-Path $componentRoot $componentName
    if (-not (Test-Path -LiteralPath $componentPath -PathType Leaf)) {
        throw "Missing PostgreSQL database-catalog component: $componentPath"
    }
    . $componentPath
}
