#Requires -Version 5.1

function Add-TicketboxInstalledPayloadFile {
    param(
        [Parameter(Mandatory = $true)][object]$Records,
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$InstalledPath
    )
    $canonical = $InstalledPath.Replace("\", "/")
    if (
        [string]::IsNullOrWhiteSpace($canonical) -or
        $canonical.StartsWith("/", [System.StringComparison]::Ordinal) -or
        $canonical.Contains("//") -or
        $canonical -cmatch "[^\x20-\x7e]" -or
        $canonical.Split('/') -contains ".." -or
        $Records.ContainsKey($canonical)
    ) {
        throw "installed payload path is not unique canonical ASCII: $canonical"
    }
    $item = Get-Item -LiteralPath $SourcePath
    $Records.Add($canonical, [ordered]@{
        path = $canonical
        size = [int64]$item.Length
        sha256 = Get-TicketboxFileSha256 $item.FullName
    })
}

function Add-TicketboxInstalledPayloadTree {
    param(
        [Parameter(Mandatory = $true)][object]$Records,
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$InstalledRoot
    )
    foreach ($file in @(
        Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force |
            Sort-Object FullName
    )) {
        $relative = Get-TicketboxRelativePath $SourceRoot $file.FullName
        Add-TicketboxInstalledPayloadFile `
            -Records $Records `
            -SourcePath $file.FullName `
            -InstalledPath ($InstalledRoot.TrimEnd('/') + "/" + $relative)
    }
}

function New-TicketboxInstalledPayloadManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$StagedBackendRoot,
        [Parameter(Mandatory = $true)][string]$StagedDesktopRoot,
        [Parameter(Mandatory = $true)][string]$StagedPayloadDir
    )
    $records = [System.Collections.Generic.SortedDictionary[string, object]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    Add-TicketboxInstalledPayloadTree $records `
        (Join-Path $StagedBackendRoot "dist\ticketbox-backend") `
        "releases/$Version/backend"
    Add-TicketboxInstalledPayloadTree $records `
        (Join-Path $StagedDesktopRoot "dist\ticketbox-manager") `
        "releases/$Version/manager"
    Add-TicketboxInstalledPayloadTree $records `
        (Join-Path $StagedBackendRoot "packaging\vendor\pg") `
        "postgresql"
    foreach ($file in @(
        @{
            Source = Join-Path $StagedBackendRoot "packaging\vendor\vc-runtime\vc_redist.x64.exe"
            Destination = "bin/vc_redist.x64.exe"
        },
        @{
            Source = Join-Path $StagedBackendRoot "packaging\vendor\shawl\shawl.exe"
            Destination = "bin/shawl.exe"
        },
        @{
            Source = Join-Path $StagedPayloadDir "TicketboxLifecycle.exe"
            Destination = "bin/TicketboxLifecycle.exe"
        },
        @{
            Source = Join-Path $StagedBackendRoot "packaging\ticketbox.ico"
            Destination = "ticketbox.ico"
        }
    )) {
        Add-TicketboxInstalledPayloadFile $records $file.Source $file.Destination
    }
    return [ordered]@{
        algorithm = "SHA-256"
        files = @($records.Values)
    }
}
