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
    Assert-XpjTestPostgresProtectedAuthorityFile `
        -Path $path `
        -Label 'Test PostgreSQL SCRAM credential'
    $content = [System.IO.File]::ReadAllText(
        $path,
        (New-Object System.Text.UTF8Encoding($false, $true))
    )
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

. (Join-Path $PSScriptRoot 'test_pg_psql_command_contract.ps1')

function Set-XpjTestPostgresScramMarker {
    param(
        [Parameter(Mandatory = $true)]$Marker,
        [Parameter(Mandatory = $true)][string]$DataDirectory
    )

    $markerPath = Get-XpjTestPostgresMarkerPath $DataDirectory
    $payload = [ordered]@{
        schema_version = 3
        kind = $script:XpjTestPostgresMarkerKind
        purpose = [string]$Marker.Purpose
        port = [int]$Marker.Port
        instance_id = [string]$Marker.InstanceId
        system_identifier = [string]$Marker.SystemIdentifier
        authentication = 'scram-sha-256'
    } | ConvertTo-Json -Compress
    $temporaryPath = "$markerPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    $backupPath = "$markerPath.replace-backup"
    try {
        Write-XpjTestPostgresProtectedUtf8File `
            -Path $temporaryPath `
            -Content ($payload + [Environment]::NewLine)
        if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction Stop
        }
        [System.IO.File]::Replace($temporaryPath, $markerPath, $backupPath)
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $markerPath `
            -Label 'Test PostgreSQL ownership marker'
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
    }
    return Read-XpjTestPostgresOwnershipMarker $DataDirectory
}

function Set-XpjTestPostgresScramHba {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    $hbaPath = Join-Path $DataDirectory 'pg_hba.conf'
    $temporaryPath = "$hbaPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    $backupPath = "$hbaPath.replace-backup"
    $content = @(
        '# Managed disposable test-cluster authentication.'
        'host all all 127.0.0.1/32 scram-sha-256'
        'host all all ::1/128 scram-sha-256'
        ''
    ) -join [Environment]::NewLine
    try {
        Write-XpjTestPostgresProtectedUtf8File -Path $temporaryPath -Content $content
        if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction Stop
        }
        [System.IO.File]::Replace($temporaryPath, $hbaPath, $backupPath)
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
    }
}

function Get-XpjTestPostgresHbaAuthenticationMode {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    $methods = @()
    foreach ($rawLine in @(
        Get-Content -LiteralPath (Join-Path $DataDirectory 'pg_hba.conf') -Encoding UTF8
    )) {
        $line = ([string]$rawLine).Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) {
            continue
        }
        $parts = @($line -split '\s+')
        if ($parts[0] -ceq 'local' -and $parts.Count -ge 4) {
            $methods += $parts[3]
        }
        elseif ($parts[0] -match '^host' -and $parts.Count -ge 5) {
            $methods += $parts[4]
        }
        else {
            throw 'Test PostgreSQL pg_hba.conf contains an unsupported active record.'
        }
    }
    if ($methods.Count -eq 0) {
        throw 'Test PostgreSQL pg_hba.conf has no active authentication records.'
    }
    $uniqueMethods = @($methods | Sort-Object -Unique)
    if ($uniqueMethods.Count -eq 1 -and $uniqueMethods[0] -ceq 'trust') {
        return 'legacy-trust'
    }
    if ($uniqueMethods.Count -eq 1 -and $uniqueMethods[0] -ceq 'scram-sha-256') {
        return 'scram-sha-256'
    }
    throw 'Test PostgreSQL pg_hba.conf has an unsupported mixed authentication contract.'
}

function Get-XpjTestPostgresPsqlProbeArguments {
    param([Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port)

    return @(
        '--no-psqlrc',
        '--no-password',
        '--quiet',
        '--host', '127.0.0.1',
        '--port', [string]$Port,
        '--username', 'postgres',
        '--dbname', 'postgres',
        '--command',
        'SELECT 1 / (current_setting(''password_encryption'') = ''scram-sha-256'')::int'
    )
}

function Assert-XpjTestPostgresRequiredAuthClient {
    param([Parameter(Mandatory = $true)][string]$PostgresBin)

    $psqlPath = Join-Path $PostgresBin 'psql.exe'
    $version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($psqlPath)
    if ($version.ProductMajorPart -lt 17) {
        throw (
            'Test PostgreSQL requires psql/libpq 17 or newer for require_auth ' +
            "(actual=$($version.ProductVersion))."
        )
    }
}

function Initialize-XpjTestPostgresScramCredentialFromNoChallengeBootstrap {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $credential = Read-XpjTestPostgresCredential $DataDirectory
    $standardInput = @"
\set ON_ERROR_STOP on
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SET password_encryption = 'scram-sha-256';
\set xpj_scram_credential '$credential'
ALTER ROLE postgres PASSWORD :'xpj_scram_credential';
\unset xpj_scram_credential
\q
"@
    $result = Invoke-XpjTestPostgresPasswordlessCommand `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -ArgumentList @(
            '--no-psqlrc',
            '--no-password',
            '--quiet',
            '--host', '127.0.0.1',
            '--port', [string]$Port,
            '--username', 'postgres',
            '--dbname', 'postgres'
        ) `
        -StandardInput $standardInput `
        -RequiredAuthentication 'none'
    if (
        $result.TimedOut -or
        $result.ExitCode -ne 0 -or
        ([string]$result.Output).Contains($credential)
    ) {
        $detail = if (([string]$result.Output).Contains($credential)) {
            'native diagnostics contained secret material and were suppressed'
        }
        else {
            ([string]$result.Output).Trim()
        }
        throw (
            'Could not establish the protected test PostgreSQL SCRAM credential ' +
            "(exit=$($result.ExitCode), timed_out=$($result.TimedOut)): $detail"
        )
    }
}

function Assert-XpjTestPostgresScramCredential {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $arguments = Get-XpjTestPostgresPsqlProbeArguments $Port
    $credential = Read-XpjTestPostgresCredential $DataDirectory
    $accepted = Invoke-XpjTestPostgresCredentialCommand `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port `
        -ArgumentList $arguments
    if (
        $accepted.TimedOut -or
        $accepted.ExitCode -ne 0 -or
        ([string]$accepted.Output).Contains($credential)
    ) {
        throw 'Test PostgreSQL rejected its protected SCRAM credential.'
    }

    $wrongCredential = New-XpjTestPostgresCredential
    $wrong = Invoke-XpjTestPostgresCredentialCommand `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port `
        -ArgumentList $arguments `
        -Credential $wrongCredential
    if (
        $wrong.TimedOut -or
        $wrong.ExitCode -eq 0 -or
        ([string]$wrong.Output).Contains($wrongCredential)
    ) {
        throw 'Test PostgreSQL accepted an incorrect SCRAM credential.'
    }

    $passwordless = Invoke-XpjTestPostgresPasswordlessCommand `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -ArgumentList $arguments
    if ($passwordless.TimedOut -or $passwordless.ExitCode -eq 0) {
        throw 'Test PostgreSQL accepted a passwordless client after SCRAM migration.'
    }
    $noChallenge = Invoke-XpjTestPostgresPasswordlessCommand `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -ArgumentList $arguments `
        -RequiredAuthentication 'none'
    if ($noChallenge.TimedOut -or $noChallenge.ExitCode -eq 0) {
        throw 'Test PostgreSQL accepted a no-challenge client after SCRAM migration.'
    }
}

function Ensure-XpjTestPostgresScramAuthentication {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)]$Marker
    )

    Remove-XpjTestPostgresAbandonedPgPassFiles $DataDirectory
    $credentialPath = Get-XpjTestPostgresCredentialPath $DataDirectory
    if (-not (Test-Path -LiteralPath $credentialPath)) {
        if ($Marker.Authentication -cne 'legacy-trust') {
            throw 'SCRAM-marked test PostgreSQL is missing its credential authority.'
        }
        Write-XpjTestPostgresProtectedUtf8File `
            -Path $credentialPath `
            -Content ((New-XpjTestPostgresCredential) + [Environment]::NewLine)
    }
    [void](Read-XpjTestPostgresCredential $DataDirectory)
    $hbaMode = Get-XpjTestPostgresHbaAuthenticationMode $DataDirectory
    if ($Marker.Authentication -ceq 'legacy-trust') {
        if ($hbaMode -ceq 'legacy-trust') {
            Initialize-XpjTestPostgresScramCredentialFromNoChallengeBootstrap `
                -PostgresBin $PostgresBin `
                -DataDirectory $DataDirectory `
                -Port $Port
            if ($env:XPJ_TEST_POSTGRES_AUTH_FAULT_PHASE -ceq 'after-password') {
                throw 'Injected test PostgreSQL authentication fault after password rotation.'
            }
        }
        elseif ($hbaMode -cne 'scram-sha-256') {
            throw 'Legacy test PostgreSQL has an unsupported authentication state.'
        }
    }
    elseif ($hbaMode -cne 'scram-sha-256') {
        throw 'SCRAM-marked test PostgreSQL no longer has a SCRAM HBA contract.'
    }

    Set-XpjTestPostgresScramHba $DataDirectory
    $reload = Invoke-XpjTestPostgresBoundedProcess `
        -FilePath (Join-Path $PostgresBin 'pg_ctl.exe') `
        -ArgumentList @('-D', $DataDirectory, 'reload') `
        -TimeoutSeconds (Get-XpjTestPostgresProcessTimeoutSeconds)
    if ($reload.TimedOut -or $reload.ExitCode -ne 0) {
        throw 'Could not reload the test PostgreSQL SCRAM authentication contract.'
    }
    if (
        $Marker.Authentication -ceq 'legacy-trust' -and
        $env:XPJ_TEST_POSTGRES_AUTH_FAULT_PHASE -ceq 'after-hba-reload'
    ) {
        throw 'Injected test PostgreSQL authentication fault after HBA reload.'
    }

    Assert-XpjTestPostgresScramCredential `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port
    $updatedMarker = if ($Marker.Authentication -ceq 'legacy-trust') {
        Set-XpjTestPostgresScramMarker `
            -Marker $Marker `
            -DataDirectory $DataDirectory
    }
    else {
        $Marker
    }
    Protect-XpjTestPostgresDirectoryTree $DataDirectory
    return [pscustomobject]@{
        Marker = $updatedMarker
        CredentialPath = $credentialPath
    }
}
