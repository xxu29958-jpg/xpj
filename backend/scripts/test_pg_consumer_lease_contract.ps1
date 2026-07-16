#Requires -Version 5.1

$script:XpjTestPostgresConsumerLeaseDirectoryName = '.xpj-test-postgres-consumers'

function Get-XpjTestPostgresConsumerLeaseDirectory {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    return Join-Path $DataDirectory $script:XpjTestPostgresConsumerLeaseDirectoryName
}

function Assert-XpjTestPostgresConsumerLeaseAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [Parameter(Mandatory = $true)][string]$SystemIdentifier
    )

    Assert-XpjTestPostgresProtectedAuthorityFile `
        -Path (Get-XpjTestPostgresMarkerPath $DataDirectory) `
        -Label 'Test PostgreSQL ownership marker'
    $marker = Read-XpjTestPostgresOwnershipMarker $DataDirectory
    if (
        $marker.Port -ne $Port -or
        $marker.InstanceId -cne $InstanceId -or
        $marker.SystemIdentifier -cne $SystemIdentifier
    ) {
        throw 'Test PostgreSQL consumer lease does not match the cluster generation.'
    }
}

function Enter-XpjTestPostgresConsumerLease {
    param(
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [Parameter(Mandatory = $true)][string]$SystemIdentifier,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [ValidateRange(1, 7200)][int]$TimeoutSeconds = 300
    )

    $lifecycleMutex = Enter-XpjTestPostgresLifecycleMutex `
        -Port $Port `
        -TimeoutSeconds $TimeoutSeconds
    $stream = $null
    $leasePath = $null
    $dataPathLease = $null
    $leaseDirectoryPathLease = $null
    try {
        $dataPathLease = [XpjTestDirectoryPathLease]::OpenPath($DataDirectory)
        Assert-XpjTestPostgresConsumerLeaseAuthority `
            -DataDirectory $DataDirectory `
            -Port $Port `
            -InstanceId $InstanceId `
            -SystemIdentifier $SystemIdentifier
        $leaseDirectory = Get-XpjTestPostgresConsumerLeaseDirectory $DataDirectory
        [void][System.IO.Directory]::CreateDirectory($leaseDirectory)
        Protect-XpjTestPostgresDirectoryTree $leaseDirectory
        $leaseDirectoryPathLease = [XpjTestDirectoryPathLease]::OpenPath($leaseDirectory)
        $owner = Get-Process -Id $PID -ErrorAction Stop
        $leaseName = "$PID-$([Guid]::NewGuid().ToString('N'))"
        $leasePath = Join-Path $leaseDirectory "$leaseName.lease"
        $payload = [ordered]@{
            Kind = $script:XpjTestPostgresConsumerLeaseKind
            Port = $Port
            DataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
            InstanceId = $InstanceId
            SystemIdentifier = $SystemIdentifier
            ProcessId = $PID
            ProcessStartedAtUtc = $owner.StartTime.ToUniversalTime().ToString('O')
        } | ConvertTo-Json -Compress
        $stream = [XpjTestProtectedFile]::CreateNewSharedLock(
            $leasePath,
            (Get-XpjTestPostgresCurrentUserSid).Value
        )
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($payload)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Position = 0
        $stream.Lock(0, 1)
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $leasePath `
            -Label 'Test PostgreSQL consumer lease'
        return [pscustomobject]@{
            Path = $leasePath
            Stream = $stream
            DataPathLease = $dataPathLease
            LeaseDirectoryPathLease = $leaseDirectoryPathLease
        }
    }
    catch {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ($null -ne $leasePath -and (Test-Path -LiteralPath $leasePath -PathType Leaf)) {
            Remove-Item -LiteralPath $leasePath -Force -ErrorAction SilentlyContinue
        }
        if ($null -ne $leaseDirectoryPathLease) {
            $leaseDirectoryPathLease.Dispose()
        }
        if ($null -ne $dataPathLease) {
            $dataPathLease.Dispose()
        }
        throw
    }
    finally {
        Exit-XpjTestPostgresLifecycleMutex $lifecycleMutex
    }
}

function Exit-XpjTestPostgresConsumerLease {
    param([Parameter(Mandatory = $true)]$Lease)

    try {
        $Lease.Stream.Unlock(0, 1)
    }
    finally {
        $Lease.Stream.Dispose()
        Remove-Item -LiteralPath ([string]$Lease.Path) -Force -ErrorAction SilentlyContinue
        $Lease.LeaseDirectoryPathLease.Dispose()
        $Lease.DataPathLease.Dispose()
    }
}

function Assert-XpjTestPostgresLiveConsumerLease {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileStream]$Stream,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [Parameter(Mandatory = $true)][string]$SystemIdentifier
    )

    try {
        $Stream.Position = 0
        $reader = New-Object System.IO.StreamReader(
            $Stream,
            (New-Object System.Text.UTF8Encoding($false, $true)),
            $false,
            1024,
            $true
        )
        try {
            $payload = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop
        }
        finally {
            $reader.Dispose()
            $Stream.Position = 0
        }
    }
    catch {
        throw "Live test PostgreSQL consumer lease payload is unreadable: $Path"
    }
    if (
        [string]$payload.Kind -cne $script:XpjTestPostgresConsumerLeaseKind -or
        [int]$payload.Port -ne $Port -or
        [string]$payload.InstanceId -cne $InstanceId -or
        [string]$payload.SystemIdentifier -cne $SystemIdentifier -or
        -not [string]::Equals(
            [System.IO.Path]::GetFullPath([string]$payload.DataDirectory),
            [System.IO.Path]::GetFullPath($DataDirectory),
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        [int]$payload.ProcessId -le 0 -or
        [string]::IsNullOrWhiteSpace([string]$payload.ProcessStartedAtUtc)
    ) {
        throw "Live test PostgreSQL consumer lease has invalid authority: $Path"
    }
}

function Wait-XpjTestPostgresConsumersDrained {
    param(
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [ValidateRange(1, 7200)][int]$TimeoutSeconds = 300
    )

    $leaseDirectory = Get-XpjTestPostgresConsumerLeaseDirectory $DataDirectory
    if (-not (Test-Path -LiteralPath $leaseDirectory)) {
        return
    }
    $dataPathLease = [XpjTestDirectoryPathLease]::OpenPath($DataDirectory)
    $leaseDirectoryPathLease = $null
    $drained = $false
    try {
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path (Get-XpjTestPostgresMarkerPath $DataDirectory) `
            -Label 'Test PostgreSQL ownership marker'
        $marker = Read-XpjTestPostgresOwnershipMarker $DataDirectory
        if ($marker.Port -ne $Port) {
            throw 'Test PostgreSQL consumer lease directory belongs to another port.'
        }
        $leaseDirectoryPathLease = [XpjTestDirectoryPathLease]::OpenPath($leaseDirectory)
        if (-not (Test-XpjTestPostgresTrustedAcl -Path $leaseDirectory)) {
            throw "Test PostgreSQL consumer lease directory ACL is invalid: $leaseDirectory"
        }
        $deadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
        while ($true) {
            $liveLeases = 0
            foreach ($leaseFile in @(
                Get-ChildItem -LiteralPath $leaseDirectory -Force -ErrorAction Stop
            )) {
                if (
                    $leaseFile.PSIsContainer -or
                    ($leaseFile.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
                ) {
                    throw "Test PostgreSQL consumer lease is invalid: $($leaseFile.FullName)"
                }
                if (
                    $leaseFile.Name -notmatch
                        '^\d+-[0-9a-f]{32}\.lease$'
                ) {
                    throw "Test PostgreSQL consumer lease is invalid: $($leaseFile.FullName)"
                }
                $probe = $null
                $probeOwnsLock = $false
                $leaseIsLive = $false
                try {
                    $probe = [System.IO.File]::Open(
                        $leaseFile.FullName,
                        [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::ReadWrite,
                        [System.IO.FileShare]::ReadWrite
                    )
                    if (-not (Test-XpjTestPostgresTrustedAcl `
                        -Path $leaseFile.FullName `
                        -RequireProtected
                    )) {
                        throw "Test PostgreSQL consumer lease ACL is invalid: $($leaseFile.FullName)"
                    }
                    try {
                        $probe.Lock(0, 1)
                        $probeOwnsLock = $true
                    }
                    catch [System.IO.IOException] {
                        $leaseIsLive = $true
                    }
                    if ($leaseIsLive) {
                        Assert-XpjTestPostgresLiveConsumerLease `
                            -Stream $probe `
                            -Path $leaseFile.FullName `
                            -DataDirectory $DataDirectory `
                            -Port $Port `
                            -InstanceId $marker.InstanceId `
                            -SystemIdentifier $marker.SystemIdentifier
                        $liveLeases++
                    }
                }
                catch [System.IO.FileNotFoundException] {
                    continue
                }
                finally {
                    if ($null -ne $probe) {
                        if ($probeOwnsLock) {
                            $probe.Unlock(0, 1)
                        }
                        $probe.Dispose()
                    }
                }
                if (-not $leaseIsLive) {
                    Remove-Item `
                        -LiteralPath $leaseFile.FullName `
                        -Force `
                        -ErrorAction SilentlyContinue
                }
            }
            if ($liveLeases -eq 0) {
                $drained = $true
                break
            }
            if ([datetime]::UtcNow -ge $deadline) {
                throw "Timed out waiting for $liveLeases test PostgreSQL consumer lease(s)."
            }
            Start-Sleep -Milliseconds 100
        }
    }
    finally {
        if ($null -ne $leaseDirectoryPathLease) {
            $leaseDirectoryPathLease.Dispose()
        }
        $dataPathLease.Dispose()
    }
    if ($drained) {
        if (Test-Path -LiteralPath $leaseDirectory) {
            Remove-Item -LiteralPath $leaseDirectory -Force -ErrorAction Stop
        }
    }
}
