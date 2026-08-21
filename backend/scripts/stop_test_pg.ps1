#Requires -Version 5.1
<#
.SYNOPSIS
  Stop and delete the throwaway test PostgreSQL started by start_test_pg.ps1.

.DESCRIPTION
  Proves the listener, postmaster PID, executable and exact -D data directory,
  then asks pg_ctl to perform a bounded fast shutdown. A force stop is only a
  fallback after ownership is re-proved and uses pinned Process objects instead
  of a reusable numeric PID. The production cluster on 5432 shares the same
  binaries, so this script never kills by executable path.

.PARAMETER Port
  TCP port of the throwaway cluster. Zero selects the contract profile.

.PARAMETER DataDir
  Cluster data directory. Must be a non-reparse child of the dynamically
  resolved protected test runtime root. Default: xpj_pg_test<Port> under it.

.PARAMETER AllowCiPort
  Selects the contract's Gitea profile. Reserved host ports always fail.
#>
[CmdletBinding()]
param(
    [int]$Port = 0,
    [string]$DataDir = '',
    [switch]$AllowCiPort
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'test_pg_storage_contract.ps1')
. (Join-Path $PSScriptRoot 'test_pg_auth_contract.ps1')
$contract = Get-XpjTestPostgresContract
$giteaPort = [int]$contract.ports.gitea
$localPort = [int]$contract.ports.local
$forbiddenHostPorts = @($contract.forbidden_host_ports | ForEach-Object { [int]$_ })
if ($Port -eq 0) { $Port = if ($AllowCiPort) { $giteaPort } else { $localPort } }
if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Get-XpjTestPostgresDefaultDataDir -Port $Port
}
$DataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir

if ($Port -in $forbiddenHostPorts -or ($Port -eq $giteaPort -and -not $AllowCiPort)) {
    throw "Refusing port ${Port}: reserved host ports are forbidden and the Gitea port requires the CI lifecycle switch."
}
if ($AllowCiPort -and $Port -ne $giteaPort) {
    throw "The CI lifecycle switch is valid only for the configured Gitea port $giteaPort."
}

$lifecycleLock = Enter-XpjTestPostgresLifecycleLock -DataDir $DataDir -Port $Port
try {
    $pendingProvisioning = Resolve-XpjTestPostgresProvisioning -DataDir $DataDir -Port $Port
    if ($null -ne $pendingProvisioning) {
        Remove-XpjTestPostgresBootstrapPasswordFileIfPresent `
            -DataDir $pendingProvisioning.Provisioning.StagingDir
        if (-not $pendingProvisioning.Completed) {
            Remove-XpjTestPostgresProvisioningGeneration `
                -DataDir $DataDir `
                -Port $Port `
                -InstanceId $pendingProvisioning.Provisioning.InstanceId
            Write-Host "Removed the proven interrupted PostgreSQL provisioning generation."
        }
    }
    Remove-XpjTestPostgresBootstrapPasswordFileIfPresent -DataDir $DataDir
    $markerPaths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $DataDir
    $deletionPath = Get-XpjTestPostgresDeletionMarkerPath -DataDir $DataDir
    $dataKind = Get-TicketboxPathEntryKindNoFollow -Path $DataDir
    $hostKind = Get-TicketboxPathEntryKindNoFollow -Path $markerPaths.Host
    $deletionKind = Get-TicketboxPathEntryKindNoFollow -Path $deletionPath
    if (
        $dataKind -eq 'Missing' -and
        $hostKind -eq 'Missing' -and
        $deletionKind -eq 'Missing'
    ) {
        Write-Host 'Test PostgreSQL cluster is already absent.'
        return
    }
    $postgresBin = if ($deletionKind -eq 'File') {
        [string](
            Read-XpjTestPostgresDeletionMarker -DataDir $DataDir -Port $Port
        ).PostgresBin
    }
    elseif ($hostKind -eq 'File') {
        [string](Assert-XpjTestPostgresOwnership -DataDir $DataDir -AllowProvisioning).PostgresBin
    }
    else {
        throw "Refusing to stop a PostgreSQL data directory without a host ownership marker or deletion receipt: $DataDir"
    }
    $postgresExe = Join-Path $postgresBin 'postgres.exe'
    Remove-XpjTestPostgresCluster -DataDir $DataDir -Port $Port -PostgresExe $postgresExe
}
finally {
    Exit-XpjTestPostgresLifecycleLock -Mutex $lifecycleLock
}

$global:LASTEXITCODE = 0
