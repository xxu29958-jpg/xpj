#Requires -Version 5.1
# Build-time supply for one official binary, never a runtime downloader/updater.

function Assert-TicketboxCloudflaredPayload {
    param([string]$Directory, [object]$Profile)
    $names = @(Get-ChildItem -LiteralPath $Directory -Force | ForEach-Object { $_.Name } | Sort-Object)
    if (($names -join ',') -cne 'cloudflared.exe,config.json,LICENSE,profile.json') {
        throw 'cloudflared payload must contain exactly its binary, empty config, license and profile.'
    }
    Assert-TicketboxNoReparsePath -Path $Directory -AllowedRoot $Directory -AllowRoot -InspectTree | Out-Null
    if ((Get-Content -Raw -LiteralPath (Join-Path $Directory 'config.json')).Trim() -cne '{}') {
        throw 'cloudflared local configuration must be explicitly empty.'
    }
    $exe = Join-Path $Directory 'cloudflared.exe'
    $stream = [System.IO.File]::Open($exe, 'Open', 'Read', 'Read')
    try {
        if ($stream.Length -ne [int64]$Profile.size -or
            (Get-TicketboxFileSha256 $exe) -cne [string]$Profile.sha256) {
            throw 'cloudflared official binary hash or size mismatch.'
        }
        $stream.Position = 0x3c
        $reader = New-Object System.IO.BinaryReader($stream)
        $offset = $reader.ReadUInt32()
        $stream.Position = $offset
        if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne [uint16]$Profile.pe_machine) {
            throw 'cloudflared must be the pinned amd64 PE binary.'
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $exe
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Thumbprint -ine [string]$Profile.signer_thumbprint) {
            throw 'cloudflared Authenticode identity does not match the pinned Cloudflare signer.'
        }
        $version = @(& $exe --version 2>&1)
        if ($LASTEXITCODE -ne 0 -or ($version -join "`n") -notmatch ('^cloudflared version ' + [regex]::Escape([string]$Profile.version) + ' \(built ')) {
            throw 'cloudflared version probe did not match the fixed release.'
        }
    }
    finally { $stream.Dispose() }
    if ((Get-TicketboxFileSha256 (Join-Path $Directory 'LICENSE')) -cne [string]$Profile.license_sha256) {
        throw 'cloudflared LICENSE checksum mismatch.'
    }
    $saved = Get-Content -Raw -LiteralPath (Join-Path $Directory 'profile.json') | ConvertFrom-Json
    if (($saved | ConvertTo-Json -Compress -Depth 8) -cne ($Profile | ConvertTo-Json -Compress -Depth 8)) {
        throw 'cloudflared payload profile changed.'
    }
}

function Publish-TicketboxCloudflaredVendor {
    param([string]$PackagingRoot, [string]$VendorDirectory, [string]$ArchiveDirectory)
    $profilePath = Join-Path $PackagingRoot 'cloudflared-profile.json'
    $profile = Get-Content -Raw -LiteralPath $profilePath | ConvertFrom-Json
    $archive = Get-TicketboxVerifiedVendorArchive $profile $ArchiveDirectory
    $lease = New-TicketboxVerifiedArchiveLease $archive ([string]$profile.sha256) 'Official cloudflared'
    try {
        $target = Join-Path $VendorDirectory 'cloudflared'
        if (Test-Path -LiteralPath $target) { Remove-TicketboxVendorPath $target }
        New-Item -ItemType Directory -Path $target | Out-Null
        Copy-Item -LiteralPath $lease.Path -Destination (Join-Path $target 'cloudflared.exe')
        Copy-Item -LiteralPath (Join-Path $PackagingRoot 'legal\cloudflared-LICENSE') -Destination (Join-Path $target 'LICENSE')
        Copy-Item -LiteralPath $profilePath -Destination (Join-Path $target 'profile.json')
        Copy-Item -LiteralPath (Join-Path $PackagingRoot 'cloudflared-empty.json') -Destination (Join-Path $target 'config.json')
        Assert-TicketboxCloudflaredPayload $target $profile
    }
    finally { $lease.Handle.Dispose() }
}
