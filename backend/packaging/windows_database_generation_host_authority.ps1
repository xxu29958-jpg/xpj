#Requires -Version 5.1

function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {
    param([Parameter(Mandatory = $true)][object]$HostContract)
    Assert-TicketboxDatabaseGenerationExactProperties `
        $HostContract `
        @(
            "backend_service_name", "data_root", "install_dir", "pg_ctl_path",
            "pg_service_name", "pg_dump_path", "pg_dump_size",
            "pg_dump_sha256", "pg_restore_path", "pg_restore_size",
            "pg_restore_sha256", "release_config"
        ) `
        "database generation host contract"
    $shapes = @(Get-TicketboxReleaseServiceIdentityShapes `
        -Config $HostContract.release_config `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -TargetConfig $HostContract.release_config)
    $authority = Resolve-TicketboxPostgresServiceHostAuthority `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -ExpectedPgCtlPath ([string]$HostContract.pg_ctl_path) `
        -DataRoot ([string]$HostContract.data_root) `
        -InstallDir ([string]$HostContract.install_dir) `
        -BackendServiceName ([string]$HostContract.backend_service_name) `
        -AllowedServiceIdentityShapes $shapes
    return [pscustomobject]@{
        Schema = "ticketbox-postgresql-host-authority-v1"
        ServiceName = [string]$authority.ServiceName
        ServiceProcessId = [int]$authority.ServiceProcessId
        PostmasterProcessId = [int]$authority.PostmasterProcessId
        PgCtlPath = [string]$authority.PgCtlPath
        PsqlPath = [string]$authority.PsqlPath
        PgData = [string]$authority.PgData
        PhysicalPgData = [string]$authority.PhysicalPgData
        Port = [int]$authority.Port
        UsesRuntimeBinding = [bool]$authority.UsesRuntimeBinding
        DataVolumeIdentity = [string]$authority.DataVolumeIdentity
    }
}

function Get-TicketboxDatabaseGenerationHostAuthoritySha256 {
    param([Parameter(Mandatory = $true)][object]$HostAuthority)
    Assert-TicketboxDatabaseGenerationExactProperties `
        $HostAuthority `
        @(
            "DataVolumeIdentity", "PgCtlPath", "PgData", "PhysicalPgData",
            "Port", "PostmasterProcessId", "PsqlPath", "Schema",
            "ServiceName", "ServiceProcessId", "UsesRuntimeBinding"
        ) `
        "PostgreSQL host authority"
    if (
        [string]$HostAuthority.Schema -cne
            "ticketbox-postgresql-host-authority-v1" -or
        [int]$HostAuthority.ServiceProcessId -lt 1 -or
        [int]$HostAuthority.PostmasterProcessId -lt 1 -or
        [int]$HostAuthority.Port -lt 1 -or
        [int]$HostAuthority.Port -gt 65535
    ) {
        throw "PostgreSQL host authority shape 无效。"
    }
    return Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $HostAuthority
    )
}
