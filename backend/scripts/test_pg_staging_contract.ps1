#Requires -Version 5.1

$script:XpjTestPostgresStagingReceiptKind = 'xiaopiaojia-test-postgres-staging'

if (-not ('XpjTestDirectoryMoveHandle' -as [type])) {
    $directoryMoveSource = Join-Path $PSScriptRoot 'test_pg_directory_move.cs'
    if (-not (Test-Path -LiteralPath $directoryMoveSource -PathType Leaf)) {
        throw "Test PostgreSQL directory instance helper is missing: $directoryMoveSource"
    }
    Add-Type -Path $directoryMoveSource -ErrorAction Stop
}

function Get-XpjTestPostgresStagingCredentialPath {
    param([Parameter(Mandatory = $true)][string]$ReceiptPath)

    return "$ReceiptPath.credential"
}

function New-XpjTestPostgresStagingReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][string]$StagingDirectory,
        [Parameter(Mandatory = $true)][string]$FinalDataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [Parameter(Mandatory = $true)][string]$DirectoryIdentity
    )

    if ($InstanceId -notmatch '^[0-9a-f]{32}$') {
        throw 'PostgreSQL staging receipt requires a valid instance identifier.'
    }
    if ($DirectoryIdentity -notmatch '^[0-9a-f]{8}:[0-9a-f]{8}:[0-9a-f]{8}$') {
        throw 'PostgreSQL staging receipt requires a valid directory identity.'
    }
    $owner = Get-Process -Id $PID -ErrorAction Stop
    $payload = [ordered]@{
        Kind = $script:XpjTestPostgresStagingReceiptKind
        StagingDirectory = [System.IO.Path]::GetFullPath($StagingDirectory)
        FinalDataDirectory = [System.IO.Path]::GetFullPath($FinalDataDirectory)
        Purpose = $Purpose
        Port = $Port
        InstanceId = $InstanceId
        DirectoryIdentity = $DirectoryIdentity
        CredentialBootstrapPath = Get-XpjTestPostgresStagingCredentialPath $ReceiptPath
        OwnerProcessId = $PID
        OwnerStartedAtUtc = $owner.StartTime.ToUniversalTime().ToString('O')
    }
    $temporaryPath = "$ReceiptPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        Write-XpjTestPostgresProtectedUtf8File `
            -Path $temporaryPath `
            -Content ($payload | ConvertTo-Json -Compress)
        [System.IO.File]::Move($temporaryPath, $ReceiptPath)
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $ReceiptPath `
            -Label 'PostgreSQL staging receipt'
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Read-XpjTestPostgresStagingReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][string]$FinalDataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    Assert-XpjTestPostgresProtectedAuthorityFile `
        -Path $ReceiptPath `
        -Label 'PostgreSQL staging receipt'
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 -ErrorAction Stop |
        ConvertFrom-Json -ErrorAction Stop
    $expectedFinal = [System.IO.Path]::GetFullPath($FinalDataDirectory)
    $actualFinal = [System.IO.Path]::GetFullPath([string]$receipt.FinalDataDirectory)
    $staging = [System.IO.Path]::GetFullPath([string]$receipt.StagingDirectory)
    $expectedReceipt = "$staging.receipt.json"
    $expectedCredential = Get-XpjTestPostgresStagingCredentialPath $expectedReceipt
    $actualCredential = [System.IO.Path]::GetFullPath(
        [string]$receipt.CredentialBootstrapPath
    )
    $ownerProcessId = 0
    $ownerStartedAtUtc = [datetime]::MinValue
    if (
        [string]$receipt.Kind -cne $script:XpjTestPostgresStagingReceiptKind -or
        -not [string]::Equals($actualFinal, $expectedFinal, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($expectedReceipt, $ReceiptPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($expectedCredential, $actualCredential, [System.StringComparison]::OrdinalIgnoreCase) -or
        [string]$receipt.Purpose -cne $Purpose -or
        [int]$receipt.Port -ne $Port -or
        [string]$receipt.InstanceId -notmatch '^[0-9a-f]{32}$' -or
        [string]$receipt.DirectoryIdentity -notmatch '^[0-9a-f]{8}:[0-9a-f]{8}:[0-9a-f]{8}$' -or
        -not [int]::TryParse([string]$receipt.OwnerProcessId, [ref]$ownerProcessId) -or
        $ownerProcessId -lt 1 -or
        -not [datetime]::TryParse(
            [string]$receipt.OwnerStartedAtUtc,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$ownerStartedAtUtc
        )
    ) {
        throw "Staging receipt does not authorize this lifecycle: $ReceiptPath"
    }
    $parent = Split-Path -Parent $expectedFinal
    if (-not [string]::Equals(
        (Split-Path -Parent $staging),
        $parent,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Staging receipt points outside the final data-directory parent: $ReceiptPath"
    }
    return $receipt
}

function Test-XpjTestPostgresReceiptOwnedByCurrentProcess {
    param([Parameter(Mandatory = $true)]$Receipt)

    $owner = Get-Process -Id ([int]$Receipt.OwnerProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $owner -or [int]$Receipt.OwnerProcessId -ne $PID) {
        return $false
    }
    $recorded = [datetime]::Parse(
        [string]$Receipt.OwnerStartedAtUtc,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    ).ToUniversalTime()
    return [Math]::Abs(($owner.StartTime.ToUniversalTime() - $recorded).TotalSeconds) -le 1
}

function Assert-XpjTestPostgresReceiptOwnerInactiveOrCurrent {
    param([Parameter(Mandatory = $true)]$Receipt)

    if (Test-XpjTestPostgresReceiptOwnedByCurrentProcess $Receipt) {
        return
    }
    $owner = Get-Process -Id ([int]$Receipt.OwnerProcessId) -ErrorAction SilentlyContinue
    if ($null -ne $owner) {
        $recorded = [datetime]::Parse(
            [string]$Receipt.OwnerStartedAtUtc,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime()
        if ([Math]::Abs(($owner.StartTime.ToUniversalTime() - $recorded).TotalSeconds) -le 1) {
            throw "Receipt owner process is still alive: $($Receipt.OwnerProcessId)"
        }
    }
}

function Remove-XpjTestPostgresStagingPair {
    param(
        [Parameter(Mandatory = $true)]$Receipt,
        [Parameter(Mandatory = $true)][string]$ReceiptPath
    )

    Assert-XpjTestPostgresReceiptOwnerInactiveOrCurrent $Receipt
    $staging = [System.IO.Path]::GetFullPath([string]$Receipt.StagingDirectory)
    if (Test-Path -LiteralPath $staging) {
        $item = Get-Item -LiteralPath $staging -Force -ErrorAction Stop
        if (-not $item.PSIsContainer) {
            throw "PostgreSQL staging path is not a directory: $staging"
        }
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "PostgreSQL staging path must not be a reparse point: $staging"
        }
        # The child reopens and compares the filesystem identity before holding
        # that exact directory instance throughout recursive deletion.
        Remove-XpjTestPostgresDirectoryBounded `
            -Directory $staging `
            -ExpectedDirectoryIdentity ([string]$Receipt.DirectoryIdentity)
    }
    $credentialPath = [System.IO.Path]::GetFullPath(
        [string]$Receipt.CredentialBootstrapPath
    )
    if (Test-Path -LiteralPath $credentialPath) {
        $credentialItem = Get-Item -LiteralPath $credentialPath -Force -ErrorAction Stop
        if (
            $credentialItem.PSIsContainer -or
            ($credentialItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-XpjTestPostgresTrustedAcl -Path $credentialPath -RequireProtected)
        ) {
            throw "PostgreSQL staging credential is not a protected file: $credentialPath"
        }
        Remove-Item -LiteralPath $credentialPath -Force -ErrorAction Stop
    }
    Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction Stop
}

function Assert-XpjTestPostgresPublishedStagingReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)]$Receipt,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $finalDirectory = [System.IO.Path]::GetFullPath([string]$Receipt.FinalDataDirectory)
    $directoryHandle = [XpjTestDirectoryMoveHandle]::OpenIdentity($finalDirectory)
    try {
        if ($directoryHandle.Identity -cne [string]$Receipt.DirectoryIdentity) {
            throw 'Published PostgreSQL directory does not match its staging receipt identity.'
        }
        $marker = Assert-XpjTestPostgresDataOwnership `
            -PostgresBin $PostgresBin `
            -DataDirectory $finalDirectory `
            -Purpose $Purpose `
            -Port $Port
        if ($marker.InstanceId -cne [string]$Receipt.InstanceId) {
            throw 'Published PostgreSQL marker does not match its staging receipt identity.'
        }
    }
    finally {
        $directoryHandle.Dispose()
    }
}

function Remove-XpjTestPostgresAbandonedStaging {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$DataDirectory,
        [Parameter(Mandatory = $true)][ValidateSet('local', 'ci')][string]$Purpose,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $parent = Split-Path -Parent $DataDirectory
    $leaf = Split-Path -Leaf $DataDirectory
    foreach ($receiptPath in @(
        Get-ChildItem `
            -LiteralPath $parent `
            -Filter ".$leaf.xpj-init-*.receipt.json" `
            -File `
            -ErrorAction Stop |
            Select-Object -ExpandProperty FullName
    )) {
        $receipt = Read-XpjTestPostgresStagingReceipt `
            -ReceiptPath $receiptPath `
            -FinalDataDirectory $DataDirectory `
            -Purpose $Purpose `
            -Port $Port
        $stagingExists = Test-Path -LiteralPath ([string]$receipt.StagingDirectory)
        if (-not $stagingExists -and (Test-Path -LiteralPath $DataDirectory)) {
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
}
