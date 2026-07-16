#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TargetDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedDirectoryIdentity
)

$ErrorActionPreference = 'Stop'
if (-not ('XpjTestDirectoryMoveHandle' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'test_pg_directory_move.cs') -ErrorAction Stop
}
$target = [System.IO.Path]::GetFullPath($TargetDirectory)
if (-not [System.IO.Path]::IsPathRooted($target)) {
    throw 'PostgreSQL lifecycle deletion target must be absolute.'
}
$leaf = Split-Path -Leaf $target
if ($leaf -notmatch '^\..+\.xpj-(init|delete)-[A-Za-z0-9_-]+$') {
    throw "Refusing an unreserved PostgreSQL lifecycle deletion target: $target"
}
if ($ExpectedDirectoryIdentity -notmatch '^[0-9a-f]{8}:[0-9a-f]{8}:[0-9a-f]{8}$') {
    throw 'PostgreSQL lifecycle deletion requires a valid directory instance identity.'
}
if (-not (Test-Path -LiteralPath $target -PathType Container)) {
    throw "Verified PostgreSQL lifecycle deletion target disappeared: $target"
}
[XpjTestDirectoryMoveHandle]::DeleteTree($target, $ExpectedDirectoryIdentity)
