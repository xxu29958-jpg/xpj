#Requires -Version 5.1

. (Join-Path $PSScriptRoot 'test_pg_credential_contract.ps1')
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

    $requiredMajor = 17
    $expectedVersion = $null
    foreach ($executable in @(
        'postgres.exe',
        'psql.exe',
        'pg_ctl.exe',
        'initdb.exe',
        'pg_controldata.exe'
    )) {
        $path = Join-Path $PostgresBin $executable
        $version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($path)
        $versionIdentity = @(
            $version.ProductMajorPart,
            $version.ProductMinorPart,
            $version.ProductBuildPart,
            $version.ProductPrivatePart
        ) -join '.'
        if ($version.ProductMajorPart -ne $requiredMajor) {
            throw (
                "Test PostgreSQL toolset must use major $requiredMajor " +
                "for the RC1 runtime contract ($executable=$($version.ProductVersion))."
            )
        }
        if ($null -eq $expectedVersion) {
            $expectedVersion = $versionIdentity
        }
        elseif ($versionIdentity -cne $expectedVersion) {
            throw (
                'Test PostgreSQL executables must come from one exact toolset ' +
                "($executable=$versionIdentity, expected=$expectedVersion)."
            )
        }
    }
}

function Assert-XpjTestPostgresLegacyOnlineIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$SystemIdentifier
    )

    [void](Assert-XpjTestPostgresListenerOwnership `
        -ExpectedPort $Port `
        -ExpectedDataDirectory $DataDirectory)
    $query = @"
SELECT CASE WHEN
    lower(replace(current_setting('data_directory'), '/', E'\\')) =
        lower(replace(:'expected_data_directory', '/', E'\\'))
    AND (SELECT system_identifier::text FROM pg_control_system()) =
        :'expected_system_identifier'
    AND current_setting('port') = :'expected_port'
    AND current_setting('listen_addresses') = '127.0.0.1'
    AND (
        SELECT count(*) = 0
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
          AND backend_type = 'client backend'
    )
THEN 'XPJ_TEST_POSTGRES_LEGACY_IDENTITY_OK'
ELSE 'XPJ_TEST_POSTGRES_LEGACY_IDENTITY_MISMATCH'
END
"@
    $arguments = @(
        '--no-psqlrc',
        '--no-password',
        '--quiet',
        '--tuples-only',
        '--no-align',
        '--host', '127.0.0.1',
        '--port', [string]$Port,
        '--username', 'postgres',
        '--dbname', 'postgres',
        '--set', "expected_data_directory=$DataDirectory",
        '--set', "expected_system_identifier=$SystemIdentifier",
        '--set', "expected_port=$Port",
        '--command', $query
    )
    $hbaMode = Get-XpjTestPostgresHbaAuthenticationMode $DataDirectory
    $result = if ($hbaMode -ceq 'legacy-trust') {
        Invoke-XpjTestPostgresPasswordlessCommand `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDirectory `
            -ArgumentList $arguments `
            -RequiredAuthentication 'none'
    }
    else {
        [void](Read-XpjTestPostgresCredential $DataDirectory)
        Invoke-XpjTestPostgresCredentialCommand `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDirectory `
            -Port $Port `
            -ArgumentList $arguments
    }
    if (
        $result.TimedOut -or
        $result.ExitCode -ne 0 -or
        [string]$result.Output -notmatch
            '(?m)^XPJ_TEST_POSTGRES_LEGACY_IDENTITY_OK\s*$'
    ) {
        throw (
            'Legacy test PostgreSQL online identity proof failed before ' +
            "offline SCRAM conversion (exit=$($result.ExitCode))."
        )
    }
}

function Initialize-XpjTestPostgresScramCredentialOffline {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    [void](Assert-XpjTestPostgresQuiescent `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port)
    $credential = Read-XpjTestPostgresCredential $DataDirectory
    $standardInput = @"
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SET password_encryption = 'scram-sha-256';
ALTER ROLE postgres PASSWORD '$credential';
"@
    $result = Invoke-XpjTestPostgresBoundedProcess `
        -FilePath (Join-Path $PostgresBin 'postgres.exe') `
        -ArgumentList @(
            '--single',
            '-D', $DataDirectory,
            '-c', 'password_encryption=scram-sha-256',
            '-c', 'log_statement=none',
            '-c', 'log_min_error_statement=panic',
            'postgres'
        ) `
        -StandardInput $standardInput `
        -TimeoutSeconds (Get-XpjTestPostgresProcessTimeoutSeconds)
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
            'Could not establish the protected test PostgreSQL SCRAM credential offline ' +
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

function Get-XpjTestPostgresScramAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$DataDirectory,
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
    if (
        $Marker.Authentication -ceq 'scram-sha-256' -and
        $hbaMode -cne 'scram-sha-256'
    ) {
        throw 'SCRAM-marked test PostgreSQL no longer has a SCRAM HBA contract.'
    }
    return [pscustomobject]@{
        CredentialPath = $credentialPath
        HbaMode = $hbaMode
    }
}

function Prepare-XpjTestPostgresScramAuthenticationOffline {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)]$Marker
    )

    [void](Assert-XpjTestPostgresQuiescent `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port)
    $authority = Get-XpjTestPostgresScramAuthority `
        -DataDirectory $DataDirectory `
        -Marker $Marker
    $updatedMarker = $Marker
    if ($Marker.Authentication -ceq 'legacy-trust') {
        Initialize-XpjTestPostgresScramCredentialOffline `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDirectory `
            -Port $Port
        if ($env:XPJ_TEST_POSTGRES_AUTH_FAULT_PHASE -ceq 'after-password') {
            throw 'Injected test PostgreSQL authentication fault after password rotation.'
        }
        Set-XpjTestPostgresScramHba $DataDirectory
        if ($env:XPJ_TEST_POSTGRES_AUTH_FAULT_PHASE -ceq 'after-hba') {
            throw 'Injected test PostgreSQL authentication fault after HBA publication.'
        }
        $updatedMarker = Set-XpjTestPostgresScramMarker `
            -Marker $Marker `
            -DataDirectory $DataDirectory
    }
    elseif ($authority.HbaMode -cne 'scram-sha-256') {
        throw 'SCRAM-marked test PostgreSQL no longer has a SCRAM HBA contract.'
    }
    Protect-XpjTestPostgresDirectoryTree $DataDirectory
    return [pscustomobject]@{
        Marker = $updatedMarker
        CredentialPath = [string]$authority.CredentialPath
    }
}

function Assert-XpjTestPostgresScramAuthenticationOnline {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)]$Marker
    )

    $authority = Get-XpjTestPostgresScramAuthority `
        -DataDirectory $DataDirectory `
        -Marker $Marker
    if ($Marker.Authentication -cne 'scram-sha-256') {
        throw 'Legacy test PostgreSQL reached the online SCRAM assertion before conversion.'
    }
    Assert-XpjTestPostgresScramCredential `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory `
        -Port $Port
    Protect-XpjTestPostgresDirectoryTree $DataDirectory
    return [pscustomobject]@{
        Marker = $Marker
        CredentialPath = [string]$authority.CredentialPath
    }
}
