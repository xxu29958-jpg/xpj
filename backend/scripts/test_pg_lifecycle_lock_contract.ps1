#Requires -Version 5.1

function Enter-XpjTestPostgresLifecycleMutex {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [ValidateRange(1, 7200)][int]$TimeoutSeconds = 300
    )

    $mutex = New-Object System.Threading.Mutex(
        $false,
        "Global\XpjTestPostgresLifecycle-$Port"
    )
    try {
        try {
            $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))
        }
        catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            throw "Timed out waiting for the test PostgreSQL lifecycle mutex on port $Port."
        }
        return $mutex
    }
    catch {
        $mutex.Dispose()
        throw
    }
}

function Exit-XpjTestPostgresLifecycleMutex {
    param([Parameter(Mandatory = $true)][System.Threading.Mutex]$Mutex)

    try {
        $Mutex.ReleaseMutex()
    }
    finally {
        $Mutex.Dispose()
    }
}

function Invoke-XpjTestPostgresLifecycleLocked {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][scriptblock]$Operation,
        [ValidateRange(1, 7200)][int]$TimeoutSeconds = 300
    )

    $mutex = Enter-XpjTestPostgresLifecycleMutex `
        -Port $Port `
        -TimeoutSeconds $TimeoutSeconds
    try {
        # Registration also takes the lifecycle mutex, so while this writer is
        # inside the gate no new reader can become a database consumer.
        Wait-XpjTestPostgresConsumersDrained `
            -DataDirectory $DataDirectory `
            -Port $Port `
            -TimeoutSeconds $TimeoutSeconds
        & $Operation
    }
    finally {
        Exit-XpjTestPostgresLifecycleMutex $mutex
    }
}
