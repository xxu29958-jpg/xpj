#Requires -Version 5.1

if (-not ('XpjTestProtectedFile' -as [type])) {
    $protectedFileSource = Join-Path $PSScriptRoot 'test_pg_protected_file.cs'
    if (-not (Test-Path -LiteralPath $protectedFileSource -PathType Leaf)) {
        throw "Test PostgreSQL protected-file helper is missing: $protectedFileSource"
    }
    Add-Type -Path $protectedFileSource -ErrorAction Stop
}

function Get-XpjTestPostgresCurrentUserSid {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().User
}

function Get-XpjTestPostgresCurrentOwnerSid {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().Owner
}

function Get-XpjTestPostgresAcl {
    param([Parameter(Mandatory = $true)][System.IO.FileSystemInfo]$Item)

    if ($null -ne ('System.IO.FileSystemAclExtensions' -as [type])) {
        return [System.IO.FileSystemAclExtensions]::GetAccessControl($Item)
    }
    return $Item.GetAccessControl()
}

function Set-XpjTestPostgresAcl {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileSystemInfo]$Item,
        [Parameter(Mandatory = $true)]$Acl
    )

    if ($null -ne ('System.IO.FileSystemAclExtensions' -as [type])) {
        [System.IO.FileSystemAclExtensions]::SetAccessControl($Item, $Acl)
        return
    }
    $Item.SetAccessControl($Acl)
}

function New-XpjTestPostgresTrustedAcl {
    param([Parameter(Mandatory = $true)][bool]$IsDirectory)

    $acl = if ($IsDirectory) {
        New-Object System.Security.AccessControl.DirectorySecurity
    }
    else {
        New-Object System.Security.AccessControl.FileSecurity
    }
    $currentSid = Get-XpjTestPostgresCurrentUserSid
    $ownerSid = Get-XpjTestPostgresCurrentOwnerSid
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($ownerSid)
    $inheritance = if ($IsDirectory) {
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        [System.Security.AccessControl.InheritanceFlags]::None
    }
    $trustedSids = @(
        $currentSid
        New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
        New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    ) | Sort-Object -Property Value -Unique
    foreach ($sid in $trustedSids) {
        [void]$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )))
    }
    return $acl
}

function Write-XpjTestPostgresProtectedUtf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Get-Item `
        -LiteralPath ([System.IO.Path]::GetDirectoryName($fullPath)) `
        -Force `
        -ErrorAction Stop
    if (
        -not $parent.PSIsContainer -or
        ($parent.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Protected PostgreSQL authority parent must be a real directory: $fullPath"
    }

    $stream = $null
    $created = $false
    $completed = $false
    try {
        $stream = [XpjTestProtectedFile]::CreateNew(
            $fullPath,
            (Get-XpjTestPostgresCurrentUserSid).Value
        )
        $created = $true
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Content)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $completed = $true
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ($created -and -not $completed) {
            Remove-Item -LiteralPath $fullPath -Force -ErrorAction SilentlyContinue
        }
    }
    Assert-XpjTestPostgresProtectedAuthorityFile `
        -Path $fullPath `
        -Label 'Protected PostgreSQL authority file'
}

function Read-XpjTestPostgresProtectedUtf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $stream = [XpjTestProtectedFile]::OpenReadShared($fullPath)
    try {
        # The retained handle denies delete sharing, so ACL validation and
        # content reading refer to one immutable file object.
        Assert-XpjTestPostgresProtectedAuthorityFile `
            -Path $fullPath `
            -Label $Label
        $reader = New-Object System.IO.StreamReader(
            $stream,
            (New-Object System.Text.UTF8Encoding($false, $true)),
            $false,
            4096,
            $true
        )
        try {
            return $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Test-XpjTestPostgresTrustedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$RequireProtected
    )

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $acl = Get-XpjTestPostgresAcl $item
    $currentSid = Get-XpjTestPostgresCurrentUserSid
    $ownerSid = Get-XpjTestPostgresCurrentOwnerSid
    if (
        ($RequireProtected -and -not $acl.AreAccessRulesProtected) -or
        $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -cne
            $ownerSid.Value
    ) {
        return $false
    }
    $trustedSidValues = @(
        $currentSid.Value
        'S-1-5-18'
        'S-1-5-32-544'
    ) | Sort-Object -Unique
    $rules = @($acl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    ))
    if ($rules.Count -ne $trustedSidValues.Count) {
        return $false
    }
    foreach ($rule in $rules) {
        if (
            $rule.AccessControlType -ne
                [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.IdentityReference.Value -cnotin $trustedSidValues -or
            ($rule.FileSystemRights -band
                [System.Security.AccessControl.FileSystemRights]::FullControl) -ne
                [System.Security.AccessControl.FileSystemRights]::FullControl
        ) {
            return $false
        }
    }
    return $true
}

function Assert-XpjTestPostgresProtectedAuthorityFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (
        $item.PSIsContainer -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "$Label must be a regular file: $Path"
    }
    if (-not (Test-XpjTestPostgresTrustedAcl -Path $Path -RequireProtected)) {
        throw "$Label ACL is not trusted: $Path"
    }
}

function Assert-XpjTestPostgresDirectoryTreeAcl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (
        -not $item.PSIsContainer -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Test PostgreSQL ACL target must be a real directory: $Path"
    }
    if (-not (Test-XpjTestPostgresTrustedAcl -Path $Path -RequireProtected)) {
        throw "Test PostgreSQL data directory ACL is not trusted: $Path"
    }
    foreach ($child in @(Get-ChildItem -LiteralPath $Path -Force -Recurse -ErrorAction Stop)) {
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Test PostgreSQL data tree must not contain reparse points: $($child.FullName)"
        }
        if (-not (Test-XpjTestPostgresTrustedAcl -Path $child.FullName)) {
            throw "Test PostgreSQL data tree ACL is not trusted: $($child.FullName)"
        }
    }
}

function Protect-XpjTestPostgresDirectoryTree {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (
        -not $item.PSIsContainer -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Test PostgreSQL ACL target must be a real directory: $Path"
    }
    $expectedOwnerSid = Get-XpjTestPostgresCurrentOwnerSid
    $actualOwnerSid = (Get-XpjTestPostgresAcl $item).GetOwner(
        [System.Security.Principal.SecurityIdentifier]
    )
    if ($actualOwnerSid.Value -cne $expectedOwnerSid.Value) {
        throw "Test PostgreSQL data directory must be owned by the current runner token: $Path"
    }
    if (-not (Test-XpjTestPostgresTrustedAcl -Path $Path -RequireProtected)) {
        Set-XpjTestPostgresAcl `
            -Item $item `
            -Acl (New-XpjTestPostgresTrustedAcl -IsDirectory $true)
    }

    $children = @(Get-ChildItem -LiteralPath $Path -Force -Recurse -ErrorAction Stop)
    foreach ($child in $children) {
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Test PostgreSQL data tree must not contain reparse points: $($child.FullName)"
        }
        if (-not (Test-XpjTestPostgresTrustedAcl -Path $child.FullName)) {
            Set-XpjTestPostgresAcl `
                -Item $child `
                -Acl (New-XpjTestPostgresTrustedAcl -IsDirectory $child.PSIsContainer)
        }
    }
    Assert-XpjTestPostgresDirectoryTreeAcl $Path
}
