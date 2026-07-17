#Requires -Version 5.1

$script:XpjTestPostgresConsumerLeaseDirectoryName = '.xpj-test-postgres-consumers'
$script:XpjTestPostgresConsumerLeaseLockOffset = [int64]1073741824

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
        $lockOffset = $script:XpjTestPostgresConsumerLeaseLockOffset
        $stream.Position = $lockOffset
        $stream.Lock($lockOffset, 1)
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $leasePath `
            -Label 'Test PostgreSQL consumer lease'
        return [pscustomobject]@{
            Path = $leasePath
            Stream = $stream
            LockOffset = $lockOffset
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

    # Transfer every owned resource before invoking fallible cleanup. A caller
    # may safely retry this function after an exception without unlocking or
    # disposing a reused handle twice.
    $stream = $Lease.Stream
    $lockOffset = [int64]$Lease.LockOffset
    $leasePath = [string]$Lease.Path
    $leaseDirectoryPathLease = $Lease.LeaseDirectoryPathLease
    $dataPathLease = $Lease.DataPathLease
    $Lease.Stream = $null
    $Lease.Path = $null
    $Lease.LeaseDirectoryPathLease = $null
    $Lease.DataPathLease = $null

    $cleanupErrors = [System.Collections.Generic.List[System.Exception]]::new()
    if ($null -ne $stream) {
        try {
            $stream.Unlock($lockOffset, 1)
        }
        catch {
            $cleanupErrors.Add($_.Exception)
        }
        try {
            $stream.Dispose()
        }
        catch {
            $cleanupErrors.Add($_.Exception)
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($leasePath)) {
        try {
            if (Test-Path -LiteralPath $leasePath -PathType Leaf) {
                Remove-Item -LiteralPath $leasePath -Force -ErrorAction Stop
            }
            if (Test-Path -LiteralPath $leasePath) {
                throw "Test PostgreSQL consumer lease still exists after cleanup: $leasePath"
            }
        }
        catch {
            $cleanupErrors.Add($_.Exception)
        }
    }
    foreach ($pathLease in @($leaseDirectoryPathLease, $dataPathLease)) {
        if ($null -ne $pathLease) {
            try {
                $pathLease.Dispose()
            }
            catch {
                $cleanupErrors.Add($_.Exception)
            }
        }
    }
    if ($cleanupErrors.Count -gt 0) {
        throw [System.AggregateException]::new(
            'Test PostgreSQL consumer lease cleanup failed.',
            $cleanupErrors.ToArray()
        )
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
                        $probeLockOffset = $script:XpjTestPostgresConsumerLeaseLockOffset
                        $probe.Lock($probeLockOffset, 1)
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
                            $probe.Unlock($probeLockOffset, 1)
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
                $leaseLabel = if ($liveLeases -eq 1) { 'lease' } else { 'leases' }
                throw "Timed out waiting for $liveLeases test PostgreSQL consumer $leaseLabel."
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
