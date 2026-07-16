#Requires -Version 5.1

function Invoke-XpjTestPostgresCredentialCommand {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [AllowNull()][string]$StandardInput = $null,
        [AllowNull()][string]$Credential = $null,
        [hashtable]$AdditionalEnvironment = @{}
    )

    $passFile = New-XpjTestPostgresPgPassFile `
        -DataDirectory $DataDirectory `
        -Port $Port `
        -Credential $Credential
    try {
        $variables = @{
            PGPASSFILE = $passFile
            PGCONNECT_TIMEOUT = '3'
            PGREQUIREAUTH = 'scram-sha-256'
        }
        foreach ($entry in $AdditionalEnvironment.GetEnumerator()) {
            $name = [string]$entry.Key
            if ($name -in @('PGPASSFILE', 'PGREQUIREAUTH')) {
                throw "Additional environment must not override protected libpq variable $name."
            }
            $variables[$name] = [string]$entry.Value
        }
        return Invoke-XpjTestPostgresIsolatedLibpqEnvironment `
            -Variables $variables `
            -Operation {
                Invoke-XpjTestPostgresBoundedProcess `
                    -FilePath (Join-Path $PostgresBin 'psql.exe') `
                    -ArgumentList $ArgumentList `
                    -StandardInput $StandardInput `
                    -TimeoutSeconds (Get-XpjTestPostgresProcessTimeoutSeconds)
            }
    }
    finally {
        Remove-XpjTestPostgresPgPassFile `
            -DataDirectory $DataDirectory `
            -Path $passFile
    }
}

function Invoke-XpjTestPostgresPasswordlessCommand {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [AllowNull()][string]$StandardInput = $null,
        [ValidateSet('none', 'scram-sha-256')][string]$RequiredAuthentication = 'scram-sha-256'
    )

    $missingPassFile = Join-Path $DataDirectory (
        ".xpj-missing-pgpass-$PID-$([Guid]::NewGuid().ToString('N'))"
    )
    return Invoke-XpjTestPostgresIsolatedLibpqEnvironment `
        -Variables @{
            PGPASSFILE = $missingPassFile
            PGCONNECT_TIMEOUT = '3'
            PGREQUIREAUTH = $RequiredAuthentication
        } `
        -Operation {
            Invoke-XpjTestPostgresBoundedProcess `
                -FilePath (Join-Path $PostgresBin 'psql.exe') `
                -ArgumentList $ArgumentList `
                -StandardInput $StandardInput `
                -TimeoutSeconds (Get-XpjTestPostgresProcessTimeoutSeconds)
        }
}
