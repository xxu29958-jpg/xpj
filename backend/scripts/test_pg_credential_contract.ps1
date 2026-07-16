#Requires -Version 5.1

$script:XpjTestPostgresCredentialName = '.xpj-test-postgres-password'
$script:XpjTestPostgresPgPassPrefix = '.xpj-pgpass-'

function Get-XpjTestPostgresCredentialPath {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    return Join-Path $DataDirectory $script:XpjTestPostgresCredentialName
}

function New-XpjTestPostgresCredential {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Read-XpjTestPostgresCredential {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    $path = Get-XpjTestPostgresCredentialPath $DataDirectory
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Test PostgreSQL SCRAM credential is missing: $path"
    }
    $content = Read-XpjTestPostgresProtectedUtf8File `
        -Path $path `
        -Label 'Test PostgreSQL SCRAM credential'
    $match = [regex]::Match(
        $content,
        '\A(?<credential>[A-Za-z0-9_-]{43})(?:\r\n|\n)?\z',
        [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
    if (-not $match.Success) {
        throw "Test PostgreSQL SCRAM credential has an invalid contract: $path"
    }
    return $match.Groups['credential'].Value
}

function Invoke-XpjTestPostgresIsolatedLibpqEnvironment {
    param(
        [hashtable]$Variables = @{},
        [Parameter(Mandatory = $true)][scriptblock]$Operation
    )

    $previous = @{}
    foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
        if ($item.Name -match '^PG') {
            $previous[$item.Name] = [string]$item.Value
        }
    }
    try {
        foreach ($name in @($previous.Keys)) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        foreach ($entry in $Variables.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable(
                [string]$entry.Key,
                [string]$entry.Value
            )
        }
        & $Operation
    }
    finally {
        foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
            if ($item.Name -match '^PG') {
                Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
            }
        }
        foreach ($entry in $previous.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable(
                [string]$entry.Key,
                [string]$entry.Value
            )
        }
    }
}

function New-XpjTestPostgresPgPassFile {
    param(
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [AllowNull()][string]$Credential = $null
    )

    $resolvedCredential = if ([string]::IsNullOrEmpty($Credential)) {
        Read-XpjTestPostgresCredential $DataDirectory
    }
    else {
        $Credential
    }
    if ($resolvedCredential -notmatch '^[A-Za-z0-9_-]{43}$') {
        throw 'Test PostgreSQL passfile credential has an invalid contract.'
    }
    $path = Join-Path $DataDirectory (
        "$($script:XpjTestPostgresPgPassPrefix)$PID-$([Guid]::NewGuid().ToString('N'))"
    )
    Write-XpjTestPostgresProtectedUtf8File `
        -Path $path `
        -Content (
            "127.0.0.1:$Port" + ':*:postgres:' + $resolvedCredential +
            [Environment]::NewLine
        )
    return $path
}

function Remove-XpjTestPostgresPgPassFile {
    param(
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $fullDataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (
        -not [string]::Equals(
            [System.IO.Path]::GetDirectoryName($fullPath),
            $fullDataDirectory,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        -not [System.IO.Path]::GetFileName($fullPath).StartsWith(
            $script:XpjTestPostgresPgPassPrefix,
            [System.StringComparison]::Ordinal
        )
    ) {
        throw 'Refusing to remove a PostgreSQL passfile outside its protected data directory.'
    }
    Remove-Item -LiteralPath $fullPath -Force -ErrorAction SilentlyContinue
}

function Remove-XpjTestPostgresAbandonedPgPassFiles {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    foreach ($item in @(
        Get-ChildItem `
            -LiteralPath $DataDirectory `
            -Filter "$($script:XpjTestPostgresPgPassPrefix)*" `
            -Force `
            -ErrorAction Stop
    )) {
        if (
            $item.PSIsContainer -or
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-XpjTestPostgresTrustedAcl -Path $item.FullName -RequireProtected)
        ) {
            throw "Abandoned PostgreSQL passfile is not a protected regular file: $($item.FullName)"
        }
        Remove-XpjTestPostgresPgPassFile `
            -DataDirectory $DataDirectory `
            -Path $item.FullName
    }
}
