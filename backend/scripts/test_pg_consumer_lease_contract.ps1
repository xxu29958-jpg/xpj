#Requires -Version 5.1

function Get-XpjTestPostgresConsumerLeaseDirectory {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    return Join-Path ([XpjTestWindowsPath]::GetLegacyTempPath()) "xpj-test-postgres-consumers-$Port"
}

function Enter-XpjTestPostgresConsumerLease {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [ValidateRange(1, 7200)][int]$TimeoutSeconds = 300
    )

    $lifecycleMutex = Enter-XpjTestPostgresLifecycleMutex `
        -Port $Port `
        -TimeoutSeconds $TimeoutSeconds
    $stream = $null
    $leasePath = $null
    try {
        $leaseDirectory = Get-XpjTestPostgresConsumerLeaseDirectory $Port
        [void][System.IO.Directory]::CreateDirectory($leaseDirectory)
        $leaseDirectoryItem = Get-Item -LiteralPath $leaseDirectory -Force -ErrorAction Stop
        if (($leaseDirectoryItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Test PostgreSQL consumer lease directory must not be a reparse point: $leaseDirectory"
        }
        $owner = Get-Process -Id $PID -ErrorAction Stop
        $leasePath = Join-Path $leaseDirectory "$PID-$([Guid]::NewGuid().ToString('N')).lease.json"
        $stream = New-Object System.IO.FileStream(
            $leasePath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::ReadWrite
        )
        $payload = [ordered]@{
            Kind = $script:XpjTestPostgresConsumerLeaseKind
            Port = $Port
            ProcessId = $PID
            ProcessStartedAtUtc = $owner.StartTime.ToUniversalTime().ToString('O')
        } | ConvertTo-Json -Compress
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($payload)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Lock(0, 1)
        return [pscustomobject]@{
            Path = $leasePath
            Stream = $stream
        }
    }
    catch {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ($null -ne $leasePath -and (Test-Path -LiteralPath $leasePath -PathType Leaf)) {
            Remove-Item -LiteralPath $leasePath -Force -ErrorAction SilentlyContinue
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
    }
}

function Wait-XpjTestPostgresConsumersDrained {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [ValidateRange(1, 7200)][int]$TimeoutSeconds = 300
    )

    $leaseDirectory = Get-XpjTestPostgresConsumerLeaseDirectory $Port
    if (-not (Test-Path -LiteralPath $leaseDirectory)) {
        return
    }
    $directoryItem = Get-Item -LiteralPath $leaseDirectory -Force -ErrorAction Stop
    if (-not $directoryItem.PSIsContainer -or ($directoryItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Test PostgreSQL consumer lease directory is invalid: $leaseDirectory"
    }
    $deadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ($true) {
        $liveLeases = 0
        foreach ($leasePath in @(Get-ChildItem -LiteralPath $leaseDirectory -Filter '*.lease.json' -File -Force)) {
            if (($leasePath.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Test PostgreSQL consumer lease must not be a reparse point: $($leasePath.FullName)"
            }
            if ($leasePath.Name -notmatch '^\d+-[0-9a-f]{32}\.lease\.json$') {
                throw "Test PostgreSQL consumer lease has an invalid name: $($leasePath.FullName)"
            }
            $probe = $null
            $locked = $false
            try {
                $probe = New-Object System.IO.FileStream(
                    $leasePath.FullName,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::ReadWrite,
                    ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete)
                )
                try {
                    $probe.Lock(0, 1)
                    $locked = $true
                }
                catch [System.IO.IOException] {
                    $liveLeases++
                    continue
                }
                $probe.Unlock(0, 1)
                $locked = $false
                $probe.Dispose()
                $probe = $null
                Remove-Item -LiteralPath $leasePath.FullName -Force -ErrorAction Stop
            }
            catch [System.IO.FileNotFoundException] {
                continue
            }
            finally {
                if ($null -ne $probe) {
                    if ($locked) {
                        $probe.Unlock(0, 1)
                    }
                    $probe.Dispose()
                }
            }
        }
        if ($liveLeases -eq 0) {
            Remove-Item -LiteralPath $leaseDirectory -Force -ErrorAction SilentlyContinue
            return
        }
        if ([datetime]::UtcNow -ge $deadline) {
            throw "Timed out waiting for $liveLeases test PostgreSQL consumer lease(s) on port $Port."
        }
        Start-Sleep -Milliseconds 100
    }
}
