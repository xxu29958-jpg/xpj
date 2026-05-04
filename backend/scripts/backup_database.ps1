param(
    [int]$Keep = 30
)

$ErrorActionPreference = "Stop"
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DataDir = Join-Path $BackendRoot "data"
$BackupDir = Join-Path $BackendRoot "backups"
$DatabasePath = Join-Path $DataDir "ticketbox.db"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

if (-not (Test-Path -LiteralPath $DatabasePath)) {
    throw "Database not found: $DatabasePath"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $BackupDir "ticketbox-$timestamp.db"
Copy-Item -LiteralPath $DatabasePath -Destination $target
Write-Host "已备份到 $target"

$resolvedBackupDir = (Resolve-Path $BackupDir).Path
$resolvedBackupRoot = $resolvedBackupDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
$backups = Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*.db" |
    Sort-Object LastWriteTime -Descending

if ($Keep -gt 0 -and $backups.Count -gt $Keep) {
    $backups | Select-Object -Skip $Keep | ForEach-Object {
        $candidate = $_.FullName
        $resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
        if (-not $resolvedCandidate.StartsWith($resolvedBackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to delete outside backup directory: $resolvedCandidate"
        }
        Remove-Item -LiteralPath $resolvedCandidate -Force
    }
}
