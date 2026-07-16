#Requires -Version 5.1

function Resolve-XpjTestPostgresDataDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Test PostgreSQL data directory must not be empty.'
    }
    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw 'Test PostgreSQL data directory must be an absolute path.'
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $trimmedPath = $fullPath.TrimEnd([char[]]@('\', '/'))
    $trimmedRoot = [System.IO.Path]::GetPathRoot($fullPath).TrimEnd([char[]]@('\', '/'))
    if ([string]::Equals($trimmedPath, $trimmedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Test PostgreSQL data directory must not be a filesystem root.'
    }
    return $trimmedPath
}

function Assert-XpjTestPostgresLifecycleRequest {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    if ($Port -eq 5432) {
        throw 'Refusing port 5432: it is reserved for production.'
    }
    if ($Purpose -eq 'local' -and $Port -eq 5433) {
        throw 'Refusing port 5433 in local mode: it is reserved for CI.'
    }
    if ($Purpose -eq 'ci' -and $Port -ne 5433) {
        throw 'CI test PostgreSQL must use the reserved CI port 5433.'
    }
}

function Resolve-XpjTestPostgresBin {
    param([string]$RequestedBin = '')

    if (-not [string]::IsNullOrWhiteSpace($RequestedBin)) {
        $postgresBin = [System.IO.Path]::GetFullPath($RequestedBin)
    }
    else {
        $programFiles = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::ProgramFiles
        )
        $pgctl = if ([string]::IsNullOrWhiteSpace($programFiles)) {
            $null
        }
        else {
            Get-ChildItem (Join-Path $programFiles 'PostgreSQL\*\bin\pg_ctl.exe') -ErrorAction SilentlyContinue |
                Sort-Object {
                    $version = 0.0
                    if (
                        [double]::TryParse(
                            $_.Directory.Parent.Name,
                            [System.Globalization.NumberStyles]::Float,
                            [System.Globalization.CultureInfo]::InvariantCulture,
                            [ref]$version
                        )
                    ) { $version } else { -1.0 }
                } -Descending |
                Select-Object -First 1
        }
        if (-not $pgctl) {
            throw 'PostgreSQL not installed (checked the OS Program Files root).'
        }
        $postgresBin = $pgctl.DirectoryName
    }

    foreach ($executable in @('initdb.exe', 'pg_ctl.exe', 'pg_controldata.exe', 'postgres.exe', 'psql.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $postgresBin $executable) -PathType Leaf)) {
            throw "PostgreSQL runtime is incomplete: missing $executable in $postgresBin"
        }
    }
    return $postgresBin
}

function Get-XpjTestPostgresMarkerPath {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    return Join-Path $DataDirectory $script:XpjTestPostgresMarkerName
}

function Read-XpjTestPostgresOwnershipMarker {
    param([Parameter(Mandatory = $true)][string]$DataDirectory)

    $markerPath = Get-XpjTestPostgresMarkerPath $DataDirectory
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "Refusing unowned PostgreSQL data directory: ownership marker is missing ($markerPath)."
    }
    try {
        $marker = (
            Read-XpjTestPostgresProtectedUtf8File `
                -Path $markerPath `
                -Label 'Test PostgreSQL ownership marker'
        ) | ConvertFrom-Json
    }
    catch {
        throw "Test PostgreSQL ownership marker is invalid JSON: $markerPath"
    }
    $schemaVersion = 0
    $markerPort = 0
    $systemIdentifier = [string]$marker.system_identifier
    $instanceId = [string]$marker.instance_id
    $purpose = [string]$marker.purpose
    $authentication = [string]$marker.authentication
    if (
        -not [int]::TryParse([string]$marker.schema_version, [ref]$schemaVersion) -or
        $schemaVersion -notin @(2, 3) -or
        [string]$marker.kind -cne $script:XpjTestPostgresMarkerKind -or
        $purpose -notin @('local', 'ci') -or
        -not [int]::TryParse([string]$marker.port, [ref]$markerPort) -or
        $markerPort -lt 1 -or
        $markerPort -gt 65535 -or
        $instanceId -notmatch '^[0-9a-f]{32}$' -or
        $systemIdentifier -notmatch '^\d{10,20}$'
    ) {
        throw "Test PostgreSQL ownership marker has an invalid contract: $markerPath"
    }
    if (
        ($schemaVersion -eq 2 -and -not [string]::IsNullOrWhiteSpace($authentication)) -or
        ($schemaVersion -eq 3 -and $authentication -cne 'scram-sha-256')
    ) {
        throw "Test PostgreSQL ownership marker has an invalid authentication contract: $markerPath"
    }
    return [pscustomobject]@{
        Path = $markerPath
        Purpose = $purpose
        Port = $markerPort
        InstanceId = $instanceId
        SystemIdentifier = $systemIdentifier
        Authentication = if ($schemaVersion -eq 3) { $authentication } else { 'legacy-trust' }
    }
}

function Get-XpjTestPostgresControlSystemIdentifier {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory
    )

    $hadLcAll = Test-Path Env:LC_ALL
    $previousLcAll = $env:LC_ALL
    $hadPgColor = Test-Path Env:PG_COLOR
    $previousPgColor = $env:PG_COLOR
    $previousPreference = $ErrorActionPreference
    try {
        $env:LC_ALL = 'C'
        $env:PG_COLOR = 'never'
        $ErrorActionPreference = 'Continue'
        $processTimeout = Get-XpjTestPostgresProcessTimeoutSeconds
        $result = Invoke-XpjTestPostgresBoundedProcess `
            -FilePath (Join-Path $PostgresBin 'pg_controldata.exe') `
            -ArgumentList @('-D', $DataDirectory) `
            -TimeoutSeconds $processTimeout
    }
    finally {
        $ErrorActionPreference = $previousPreference
        if ($hadLcAll) { $env:LC_ALL = $previousLcAll } else { Remove-Item Env:LC_ALL -ErrorAction SilentlyContinue }
        if ($hadPgColor) { $env:PG_COLOR = $previousPgColor } else { Remove-Item Env:PG_COLOR -ErrorAction SilentlyContinue }
    }
    $text = [string]$result.Output
    if ($result.TimedOut) {
        throw "pg_controldata exceeded its $processTimeout second process budget."
    }
    if ($result.ExitCode -ne 0) {
        throw "pg_controldata failed for test cluster (exit=$($result.ExitCode)): $text"
    }
    $match = [regex]::Match(
        $text,
        '(?mi)^\s*Database system identifier\s*:\s*(\d+)\s*$'
    )
    if (-not $match.Success) {
        throw 'pg_controldata did not return a parseable database system identifier.'
    }
    return $match.Groups[1].Value
}

function Get-XpjTestPostgresControlState {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory
    )

    $hadLcAll = Test-Path Env:LC_ALL
    $previousLcAll = $env:LC_ALL
    $hadPgColor = Test-Path Env:PG_COLOR
    $previousPgColor = $env:PG_COLOR
    try {
        $env:LC_ALL = 'C'
        $env:PG_COLOR = 'never'
        $result = Invoke-XpjTestPostgresBoundedProcess `
            -FilePath (Join-Path $PostgresBin 'pg_controldata.exe') `
            -ArgumentList @('-D', $DataDirectory) `
            -TimeoutSeconds (Get-XpjTestPostgresProcessTimeoutSeconds)
    }
    finally {
        if ($hadLcAll) { $env:LC_ALL = $previousLcAll } else { Remove-Item Env:LC_ALL -ErrorAction SilentlyContinue }
        if ($hadPgColor) { $env:PG_COLOR = $previousPgColor } else { Remove-Item Env:PG_COLOR -ErrorAction SilentlyContinue }
    }
    if ($result.TimedOut -or $result.ExitCode -ne 0) {
        throw 'pg_controldata could not prove the PostgreSQL cluster state.'
    }
    $match = [regex]::Match(
        [string]$result.Output,
        '(?mi)^\s*Database cluster state\s*:\s*(?<state>[^\r\n]+?)\s*$'
    )
    if (-not $match.Success) {
        throw 'pg_controldata did not return a parseable database cluster state.'
    }
    return $match.Groups['state'].Value.Trim().ToLowerInvariant()
}

function New-XpjTestPostgresOwnershipMarker {
    param(
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$SystemIdentifier,
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [ValidateSet('scram-sha-256')][string]$Authentication = 'scram-sha-256'
    )

    if ($SystemIdentifier -notmatch '^\d{10,20}$') {
        throw 'Cannot create test PostgreSQL ownership marker with an invalid system identifier.'
    }
    if ($InstanceId -notmatch '^[0-9a-f]{32}$') {
        throw 'Cannot create test PostgreSQL ownership marker with an invalid instance identifier.'
    }
    $markerPath = Get-XpjTestPostgresMarkerPath $DataDirectory
    if (Test-Path -LiteralPath $markerPath) {
        throw "Test PostgreSQL ownership marker already exists: $markerPath"
    }
    $temporaryPath = "$markerPath.tmp-$PID-$([Guid]::NewGuid().ToString('N'))"
    $payload = [ordered]@{
        schema_version = 3
        kind = $script:XpjTestPostgresMarkerKind
        purpose = $Purpose
        port = $Port
        instance_id = $InstanceId
        system_identifier = $SystemIdentifier
        authentication = $Authentication
    } | ConvertTo-Json -Compress
    try {
        Write-XpjTestPostgresProtectedUtf8File `
            -Path $temporaryPath `
            -Content ($payload + [Environment]::NewLine)
        [System.IO.File]::Move($temporaryPath, $markerPath)
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $markerPath `
            -Label 'Test PostgreSQL ownership marker'
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
    return Read-XpjTestPostgresOwnershipMarker $DataDirectory
}

function Assert-XpjTestPostgresDataOwnership {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    if (-not (Test-Path -LiteralPath $DataDirectory -PathType Container)) {
        throw "Test PostgreSQL data directory does not exist: $DataDirectory"
    }
    $dataItem = Get-Item -LiteralPath $DataDirectory -Force -ErrorAction Stop
    if (($dataItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Test PostgreSQL data directory must not be a reparse point: $DataDirectory"
    }
    $marker = Read-XpjTestPostgresOwnershipMarker $DataDirectory
    Assert-XpjTestPostgresDirectoryTreeAcl $DataDirectory
    if ($marker.Purpose -cne $Purpose -or $marker.Port -ne $Port) {
        throw "Test PostgreSQL marker purpose/port does not match the requested lifecycle."
    }
    $actualIdentifier = Get-XpjTestPostgresControlSystemIdentifier `
        -PostgresBin $PostgresBin `
        -DataDirectory $DataDirectory
    if ($actualIdentifier -cne $marker.SystemIdentifier) {
        throw "Test PostgreSQL system identifier does not match its ownership marker."
    }
    return $marker
}

function New-XpjTestPostgresDataDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    if (Test-Path -LiteralPath $DataDirectory) {
        throw "Refusing to initialize over an existing path: $DataDirectory"
    }
    $parent = Split-Path -Parent $DataDirectory
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "Test PostgreSQL data directory parent does not exist: $parent"
    }
    $leaf = Split-Path -Leaf $DataDirectory
    $staging = Join-Path $parent ".$leaf.xpj-init-$([Guid]::NewGuid().ToString('N'))"
    $receiptPath = "$staging.receipt.json"
    $receiptCreated = $false
    $stagingCreated = $false
    $stagingHandle = $null
    $directoryIdentity = $null
    $instanceId = [Guid]::NewGuid().ToString('N')
    $credentialBootstrapPath = $null
    try {
        if (Test-Path -LiteralPath $staging) {
            throw "Generated PostgreSQL staging directory already exists: $staging"
        }
        [void][System.IO.Directory]::CreateDirectory($staging)
        $stagingCreated = $true
        Protect-XpjTestPostgresDirectoryTree $staging
        $stagingHandle = [XpjTestDirectoryMoveHandle]::OpenIdentity($staging)
        $directoryIdentity = $stagingHandle.Identity
        New-XpjTestPostgresStagingReceipt `
            -ReceiptPath $receiptPath `
            -StagingDirectory $staging `
            -FinalDataDirectory $DataDirectory `
            -Purpose $Purpose `
            -Port $Port `
            -InstanceId $instanceId `
            -DirectoryIdentity $directoryIdentity
        $receiptCreated = $true
        $credentialBootstrapPath = Get-XpjTestPostgresStagingCredentialPath $receiptPath
        Write-XpjTestPostgresProtectedUtf8File `
            -Path $credentialBootstrapPath `
            -Content ((New-XpjTestPostgresCredential) + [Environment]::NewLine)
        $initTimeout = [Math]::Min(600, (Get-XpjTestPostgresProcessTimeoutSeconds) * 2)
        $initResult = Invoke-XpjTestPostgresBoundedProcess `
            -FilePath (Join-Path $PostgresBin 'initdb.exe') `
            -ArgumentList @(
                '-D', $staging,
                '-U', 'postgres',
                '--auth-host=scram-sha-256',
                '--auth-local=scram-sha-256',
                '--set=password_encryption=scram-sha-256',
                '--pwfile', $credentialBootstrapPath,
                '-E', 'UTF8',
                '--locale=C'
            ) `
            -TimeoutSeconds $initTimeout
        if ($initResult.TimedOut) {
            throw "initdb exceeded its $initTimeout second process budget; final data directory was not published."
        }
        if ($initResult.ExitCode -ne 0) {
            throw "initdb failed (exit=$($initResult.ExitCode)); final data directory was not published: $($initResult.Output)"
        }
        $credentialPath = Get-XpjTestPostgresCredentialPath $staging
        [System.IO.File]::Move($credentialBootstrapPath, $credentialPath)
        $credentialBootstrapPath = $null
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $credentialPath `
            -Label 'Test PostgreSQL SCRAM credential'
        Protect-XpjTestPostgresDirectoryTree $staging

        $systemIdentifier = Get-XpjTestPostgresControlSystemIdentifier `
            -PostgresBin $PostgresBin `
            -DataDirectory $staging
        [void](New-XpjTestPostgresOwnershipMarker `
            -DataDirectory $staging `
            -Purpose $Purpose `
            -Port $Port `
            -SystemIdentifier $systemIdentifier `
            -InstanceId $instanceId)
        $stagingMarker = Assert-XpjTestPostgresDataOwnership `
            -PostgresBin $PostgresBin `
            -DataDirectory $staging `
            -Purpose $Purpose `
            -Port $Port
        if ($stagingMarker.InstanceId -cne $instanceId) {
            throw 'New PostgreSQL staging marker does not match its lifecycle receipt.'
        }
        if (Test-Path -LiteralPath $DataDirectory) {
            throw 'Another lifecycle published the final data directory.'
        }
        $stagingHandle.Dispose()
        $stagingHandle = [XpjTestDirectoryMoveHandle]::Open($staging)
        if ($stagingHandle.Identity -cne $directoryIdentity) {
            throw 'PostgreSQL staging directory was replaced before publication.'
        }
        $stagingHandle.RenameTo($DataDirectory)
        $stagingHandle.Dispose()
        $stagingHandle = [XpjTestDirectoryMoveHandle]::OpenIdentity($DataDirectory)
        if ($stagingHandle.Identity -cne $directoryIdentity) {
            throw 'Published PostgreSQL directory does not match its staging identity.'
        }
        $marker = Assert-XpjTestPostgresDataOwnership `
            -PostgresBin $PostgresBin `
            -DataDirectory $DataDirectory `
            -Purpose $Purpose `
            -Port $Port
        if ($marker.InstanceId -cne $instanceId -or $stagingHandle.Identity -cne $directoryIdentity) {
            throw 'Published PostgreSQL directory does not match its staging lifecycle identity.'
        }
        Remove-Item -LiteralPath $receiptPath -Force -ErrorAction Stop
        $receiptCreated = $false
        return $marker
    }
    catch {
        $failure = $_
        if ($null -ne $stagingHandle) {
            $stagingHandle.Dispose()
            $stagingHandle = $null
        }
        if ($receiptCreated -and (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
            try {
                $receipt = Read-XpjTestPostgresStagingReceipt `
                    -ReceiptPath $receiptPath `
                    -FinalDataDirectory $DataDirectory `
                    -Purpose $Purpose `
                    -Port $Port
                if (-not (Test-Path -LiteralPath $staging) -and (Test-Path -LiteralPath $DataDirectory)) {
                    Assert-XpjTestPostgresPublishedStagingReceipt `
                        -PostgresBin $PostgresBin `
                        -Receipt $receipt `
                        -Purpose $Purpose `
                        -Port $Port
                }
                Remove-XpjTestPostgresStagingPair `
                    -Receipt $receipt `
                    -ReceiptPath $receiptPath
            }
            catch {
                throw "Test PostgreSQL publication failed and cleanup refused: $($_.Exception.Message)"
            }
        }
        elseif ($stagingCreated -and (Test-Path -LiteralPath $staging -PathType Container)) {
            try {
                Remove-XpjTestPostgresDirectoryBounded `
                    -Directory $staging `
                    -ExpectedDirectoryIdentity $directoryIdentity
            }
            catch {
                throw "Test PostgreSQL publication failed before its receipt was durable; cleanup refused: $($_.Exception.Message)"
            }
        }
        throw $failure
    }
    finally {
        if ($null -ne $stagingHandle) {
            $stagingHandle.Dispose()
        }
    }
}
