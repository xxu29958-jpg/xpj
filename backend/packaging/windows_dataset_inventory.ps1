#Requires -Version 5.1

# Read-only, backend-independent projection of the installed backup inventory.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$DataRoot)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

foreach ($name in @(
    "windows_installation_safety.ps1",
    "windows_release_config.ps1",
    "windows_database_generation.ps1",
    "windows_installed_dataset_reader.ps1"
)) {
    $dependency = Join-Path $scriptRoot $name
    if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) {
        throw "installed backup inventory dependency is missing."
    }
    . $dependency
}
foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `
    -Root $scriptRoot)) {
    . $dependency
}

$subject = Assert-TicketboxInstalledDatasetSubject $DataRoot
$path = Join-Path ([string]$subject.Identity.DataRoot) "app\backup-inventory.json"
$pathKind = Get-TicketboxPathEntryKindNoFollow $path
if ($pathKind -ceq "Missing") {
    [pscustomobject][ordered]@{
        schema = "ticketbox-manager-backup-inventory-v1"
        generations = @()
    } | ConvertTo-Json -Depth 4 -Compress
    return
}
if ($pathKind -cne "File") {
    throw "installed backup inventory is not a plain file."
}
$backendService = "NT SERVICE\$([string]$subject.Identity.BackendServiceName)"
$artifact = Read-TicketboxProtectedUtf8Artifact `
    -Path $path `
    -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
    -ReadExecuteAccounts @($backendService) `
    -OwnerAccount "SYSTEM" `
    -MaximumBytes 65536
try { $inventory = $artifact.Text | ConvertFrom-Json }
catch { throw "installed backup inventory is not valid JSON." }
Assert-TicketboxDatabaseGenerationExactProperties `
    $inventory @("generations", "schema") "installed backup inventory"
if (
    [string]$inventory.schema -cne "ticketbox-complete-backup-inventory-v1" -or
    $inventory.generations -isnot [array] -or
    @($inventory.generations).Count -gt 3
) {
    throw "installed backup inventory contract drifted."
}
$projection = @()
foreach ($entry in @($inventory.generations)) {
    Assert-TicketboxDatabaseGenerationExactProperties `
        $entry `
        @(
            "backup_id", "created_at", "dataset_id", "generation",
            "kind", "restore_epoch", "size_bytes"
        ) `
        "installed backup inventory entry"
    $backupId = ([guid][string]$entry.backup_id).ToString("D")
    $datasetId = ([guid][string]$entry.dataset_id).ToString("D")
    if (
        $backupId -cne [string]$entry.backup_id -or
        $datasetId -cne [string]$entry.dataset_id -or
        [string]$entry.generation -cne "ticketbox-backup-$backupId" -or
        [string]$entry.kind -cne "manual" -or
        [string]$entry.created_at -cnotmatch `
            '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$' -or
        (
            $entry.restore_epoch -isnot [int] -and
            $entry.restore_epoch -isnot [long]
        ) -or
        (
            $entry.size_bytes -isnot [int] -and
            $entry.size_bytes -isnot [long]
        ) -or
        [int64]$entry.restore_epoch -lt 0 -or
        [int64]$entry.size_bytes -lt 1
    ) {
        throw "installed backup inventory entry is invalid."
    }
    $projection += [pscustomobject][ordered]@{
        generation = [string]$entry.generation
        backup_id = $backupId
        dataset_id = $datasetId
        restore_epoch = [int64]$entry.restore_epoch
        size_bytes = [int64]$entry.size_bytes
        created_at = [string]$entry.created_at
        kind = [string]$entry.kind
    }
}
[pscustomobject][ordered]@{
    schema = "ticketbox-manager-backup-inventory-v1"
    generations = $projection
} | ConvertTo-Json -Depth 4 -Compress
