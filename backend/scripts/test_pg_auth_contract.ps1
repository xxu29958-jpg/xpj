#Requires -Version 5.1

function Enter-XpjCleanPostgresEnvironment {
    [CmdletBinding()]
    param()

    $saved = @{}
    foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
        if ($item.Name -match '^PG') {
            $saved[$item.Name] = [string]$item.Value
            Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
        }
    }
    return $saved
}

function Exit-XpjCleanPostgresEnvironment {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][hashtable]$Saved)

    foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
        if ($item.Name -match '^PG') {
            Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
        }
    }
    foreach ($entry in $Saved.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable([string]$entry.Key, [string]$entry.Value)
    }
}

function Get-XpjTestPostgresCredentialPath {
    param([Parameter(Mandatory = $true)][string]$DataDir)

    return Join-Path `
        (Resolve-XpjTestPostgresDataDir -DataDir $DataDir) `
        ([string](Get-XpjTestPostgresContract).credential_name)
}

function Get-XpjTestPostgresPassfilePath {
    param([Parameter(Mandatory = $true)][string]$DataDir)

    return Join-Path `
        (Resolve-XpjTestPostgresDataDir -DataDir $DataDir) `
        ([string](Get-XpjTestPostgresContract).passfile_name)
}

function Get-XpjTestPostgresSecretOwnerSid {
    return Get-XpjTestPostgresRuntimeOwnerSid
}

function Write-XpjTestPostgresProtectedSecret {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )

    $ownerSid = Get-XpjTestPostgresSecretOwnerSid
    $accounts = @($ownerSid, "SYSTEM", "BUILTIN\Administrators")
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text $Text `
        -FullControlAccounts $accounts `
        -OwnerAccount $ownerSid
}

function Assert-XpjTestPostgresProtectedSecret {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ((Get-TicketboxPathEntryKindNoFollow -Path $Path) -cne 'File') {
        throw "Test PostgreSQL secret is not a plain file: $Path"
    }
    $ownerSid = Get-XpjTestPostgresSecretOwnerSid
    $accounts = @($ownerSid, "SYSTEM", "BUILTIN\Administrators")
    Assert-TicketboxExactFileAcl `
        -Path $Path `
        -Accounts $accounts `
        -OwnerAccount $ownerSid
}

function New-XpjTestPostgresCredential {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Read-XpjTestPostgresCredential {
    param([Parameter(Mandatory = $true)][string]$DataDir)

    $path = Get-XpjTestPostgresCredentialPath -DataDir $DataDir
    Assert-XpjTestPostgresProtectedSecret -Path $path
    $credential = (Get-Content -Raw -Encoding UTF8 -LiteralPath $path).TrimEnd("`r", "`n")
    if ($credential -notmatch '^[A-Za-z0-9_-]{43}$') {
        throw "Test PostgreSQL credential has an invalid contract: $path"
    }
    return $credential
}

function Get-XpjTestPostgresPassfileText {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$HostAddress,
        [Parameter(Mandatory = $true)][string]$Credential
    )

    $parsedAddress = $null
    if (
        -not [Net.IPAddress]::TryParse($HostAddress, [ref]$parsedAddress) -or
        -not [Net.IPAddress]::IsLoopback($parsedAddress) -or
        $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork
    ) {
        throw 'Test PostgreSQL passfile host must be an IPv4 loopback literal.'
    }
    $applicationRole = [string](Get-XpjTestPostgresContract).application_role
    return @(
        foreach ($hostName in @("localhost", $parsedAddress.ToString())) {
            "${hostName}:${Port}:*:postgres:${Credential}"
            "${hostName}:${Port}:*:${applicationRole}:${Credential}"
        }
    ) -join "`n"
}

function Get-XpjTestPostgresHbaMode {
    param([Parameter(Mandatory = $true)][string]$DataDir)

    $path = Join-Path (Resolve-XpjTestPostgresDataDir -DataDir $DataDir) 'pg_hba.conf'
    if ((Get-TicketboxPathEntryKindNoFollow -Path $path) -cne 'File') {
        throw "Test PostgreSQL pg_hba.conf is missing: $path"
    }
    $methods = @()
    foreach ($rawLine in @(Get-Content -Encoding UTF8 -LiteralPath $path)) {
        $line = ([string]$rawLine).Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) { continue }
        $parts = @($line -split '\s+')
        if ($parts[0] -ceq 'local' -and $parts.Count -ge 4) {
            $methods += $parts[3]
        }
        elseif ($parts[0] -match '^host' -and $parts.Count -ge 5) {
            $methods += $parts[4]
        }
        else {
            throw "Unsupported active pg_hba.conf record: $line"
        }
    }
    $unique = @($methods | Sort-Object -Unique)
    if ($unique.Count -ne 1 -or $unique[0] -notin @('trust', 'scram-sha-256')) {
        throw 'Test PostgreSQL pg_hba.conf has an unsupported authentication contract.'
    }
    return [string]$unique[0]
}

function Get-XpjTestPostgresAuthenticationState {
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$HostAddress
    )

    $credentialKind = Get-TicketboxPathEntryKindNoFollow -Path (Get-XpjTestPostgresCredentialPath -DataDir $DataDir)
    $passfileKind = Get-TicketboxPathEntryKindNoFollow -Path (Get-XpjTestPostgresPassfilePath -DataDir $DataDir)
    $hbaMode = Get-XpjTestPostgresHbaMode -DataDir $DataDir
    if ($credentialKind -eq 'Missing' -and $passfileKind -eq 'Missing' -and $hbaMode -ceq 'trust') {
        return 'legacy-trust'
    }
    if ($credentialKind -eq 'File' -and $passfileKind -eq 'File' -and $hbaMode -ceq 'scram-sha-256') {
        $credential = Read-XpjTestPostgresCredential -DataDir $DataDir
        $passfile = Get-XpjTestPostgresPassfilePath -DataDir $DataDir
        Assert-XpjTestPostgresProtectedSecret -Path $passfile
        $legacyText = "localhost:${Port}:*:postgres:${credential}`n"
        if ((Get-Content -Raw -Encoding UTF8 -LiteralPath $passfile) -ceq $legacyText) {
            return 'legacy-superuser-only'
        }
    }
    [void](Assert-XpjTestPostgresAuthenticationFiles `
        -DataDir $DataDir -Port $Port -HostAddress $HostAddress)
    return 'scram-sha-256'
}

function Initialize-XpjTestPostgresAuthenticationFiles {
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$HostAddress,
        [Parameter(Mandatory = $true)][string]$Credential
    )

    if ($Credential -notmatch '^[A-Za-z0-9_-]{43}$') {
        throw 'Test PostgreSQL credential has an invalid contract.'
    }
    if ((Get-XpjTestPostgresHbaMode -DataDir $DataDir) -cne 'scram-sha-256') {
        throw 'Fresh test PostgreSQL did not establish SCRAM HBA records.'
    }
    Write-XpjTestPostgresProtectedSecret `
        -Path (Get-XpjTestPostgresCredentialPath -DataDir $DataDir) `
        -Text ($Credential + "`n")
    Write-XpjTestPostgresProtectedSecret `
        -Path (Get-XpjTestPostgresPassfilePath -DataDir $DataDir) `
        -Text ((Get-XpjTestPostgresPassfileText `
            -Port $Port -HostAddress $HostAddress -Credential $Credential) + "`n")
    [void](Assert-XpjTestPostgresAuthenticationFiles `
        -DataDir $DataDir -Port $Port -HostAddress $HostAddress)
}

function Assert-XpjTestPostgresAuthenticationFiles {
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$HostAddress
    )

    if ((Get-XpjTestPostgresHbaMode -DataDir $DataDir) -cne 'scram-sha-256') {
        throw 'Test PostgreSQL authentication is not SCRAM-SHA-256.'
    }
    $credential = Read-XpjTestPostgresCredential -DataDir $DataDir
    $passfile = Get-XpjTestPostgresPassfilePath -DataDir $DataDir
    Assert-XpjTestPostgresProtectedSecret -Path $passfile
    $expected = (Get-XpjTestPostgresPassfileText `
        -Port $Port -HostAddress $HostAddress -Credential $credential) + "`n"
    if ((Get-Content -Raw -Encoding UTF8 -LiteralPath $passfile) -cne $expected) {
        throw "Test PostgreSQL passfile does not match its credential authority: $passfile"
    }
    return $passfile
}

function New-XpjTestPostgresBootstrapPasswordFile {
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][string]$Credential
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $path = "$resolvedDataDir.bootstrap-password"
    $kind = Get-TicketboxPathEntryKindNoFollow -Path $path
    if ($kind -eq 'File') {
        Assert-XpjTestPostgresProtectedSecret -Path $path
        [IO.File]::Delete($path)
    }
    elseif ($kind -ne 'Missing') {
        throw "Test PostgreSQL bootstrap password path is not a plain file: $path"
    }
    Write-XpjTestPostgresProtectedSecret -Path $path -Text ($Credential + "`n")
    return $path
}

function Remove-XpjTestPostgresBootstrapPasswordFile {
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $expectedPath = "$resolvedDataDir.bootstrap-password"
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    if (-not [string]::Equals($resolvedPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a bootstrap password outside its authority: $resolvedPath"
    }
    if ((Get-TicketboxPathEntryKindNoFollow -Path $resolvedPath) -eq 'File') {
        Assert-XpjTestPostgresProtectedSecret -Path $resolvedPath
        [IO.File]::Delete($resolvedPath)
    }
    if ((Get-TicketboxPathEntryKindNoFollow -Path $resolvedPath) -ne 'Missing') {
        throw "Test PostgreSQL bootstrap password was not removed: $resolvedPath"
    }
}

function Remove-XpjTestPostgresBootstrapPasswordFileIfPresent {
    param([Parameter(Mandatory = $true)][string]$DataDir)

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $path = "$resolvedDataDir.bootstrap-password"
    $kind = Get-TicketboxPathEntryKindNoFollow -Path $path
    if ($kind -eq 'Missing') { return }
    if ($kind -cne 'File') {
        throw "Test PostgreSQL bootstrap password path is not a plain file: $path"
    }
    Remove-XpjTestPostgresBootstrapPasswordFile -DataDir $resolvedDataDir -Path $path
}
