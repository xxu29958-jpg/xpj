#Requires -Version 5.1

function Get-TicketboxWindowsFileSecurityBytesCore {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $sections = [Security.AccessControl.AccessControlSections]::All
    if ($PSVersionTable.PSEdition -eq "Core") {
        $security = [System.IO.FileSystemAclExtensions]::GetAccessControl(
            $item,
            $sections
        )
    }
    else {
        $security = $item.GetAccessControl($sections)
    }
    return $security.GetSecurityDescriptorBinaryForm()
}

function Get-TicketboxWindowsFileSecurityBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateNotNullOrEmpty()]
        [string]$PrivilegeName = "SeSecurityPrivilege",
        [AllowNull()][scriptblock]$PrivilegeScopeFactory = $null
    )

    $readAction = {
        param([string]$CandidatePath)
        return Get-TicketboxWindowsFileSecurityBytesCore -Path $CandidatePath
    }
    return Invoke-TicketboxWindowsTokenPrivilegeScope `
        -PrivilegeName $PrivilegeName `
        -PrivilegeScopeFactory $PrivilegeScopeFactory `
        -Action $readAction `
        -ArgumentList @($Path)
}

function New-TicketboxWindowsFileCreationSecurity {
    param([Parameter(Mandatory = $true)][byte[]]$SecurityBytes)

    $captured = New-Object Security.AccessControl.FileSecurity
    try {
        $captured.SetSecurityDescriptorBinaryForm($SecurityBytes)
        $sections =
            [Security.AccessControl.AccessControlSections]::Access -bor
            [Security.AccessControl.AccessControlSections]::Owner -bor
            [Security.AccessControl.AccessControlSections]::Group
        $creation = New-Object Security.AccessControl.FileSecurity
        $creation.SetSecurityDescriptorSddlForm(
            $captured.GetSecurityDescriptorSddlForm($sections),
            $sections
        )
        return $creation
    }
    catch {
        throw "Windows file creation security descriptor 无效。"
    }
}

function Set-TicketboxWindowsFileSecurityBytesCore {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$SecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label,
        [Security.AccessControl.AccessControlSections]$Sections =
            [Security.AccessControl.AccessControlSections]::All
    )

    $security = New-Object Security.AccessControl.FileSecurity
    try {
        $security.SetSecurityDescriptorBinaryForm($SecurityBytes, $Sections)
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if ($PSVersionTable.PSEdition -eq "Core") {
            [System.IO.FileSystemAclExtensions]::SetAccessControl(
                $item,
                $security
            )
        }
        else {
            $item.SetAccessControl($security)
        }
    }
    catch {
        throw "$Label 无法恢复 captured full security descriptor。"
    }
}

function Set-TicketboxWindowsFileSecurityBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$SecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label,
        [Security.AccessControl.AccessControlSections]$Sections =
            [Security.AccessControl.AccessControlSections]::All,
        [ValidateNotNullOrEmpty()]
        [string[]]$PrivilegeNames = @(
            "SeSecurityPrivilege",
            "SeRestorePrivilege"
        ),
        [AllowNull()][scriptblock]$PrivilegeScopeFactory = $null,
        [AllowNull()][scriptblock]$AfterVerified = $null
    )

    $applyContext = [pscustomobject]@{
        Path = $Path
        SecurityBytes = $SecurityBytes
        Label = $Label
        Sections = $Sections
    }
    $applyAction = {
        param([object]$Context)
        Set-TicketboxWindowsFileSecurityBytesCore `
            -Path $Context.Path `
            -SecurityBytes $Context.SecurityBytes `
            -Label $Context.Label `
            -Sections $Context.Sections
        $persistedSecurity =
            Get-TicketboxWindowsFileSecurityBytesCore -Path $Context.Path
        if (-not (Test-TicketboxWindowsSecurityDescriptorEquals `
            -Left $persistedSecurity `
            -Right $Context.SecurityBytes)) {
            $securityDiagnostic =
                Get-TicketboxWindowsSecurityDescriptorDifferenceDiagnostic `
                    -Left $persistedSecurity `
                    -Right $Context.SecurityBytes
            throw (
                "$($Context.Label) full security descriptor 复读不一致。 " +
                $securityDiagnostic
            )
        }
    }
    $null = Invoke-TicketboxWindowsTokenPrivilegeScopes `
        -PrivilegeNames $PrivilegeNames `
        -PrivilegeScopeFactory $PrivilegeScopeFactory `
        -Action $applyAction `
        -ArgumentList @($applyContext)
    if ($null -ne $AfterVerified) {
        $null = & $AfterVerified $Path
    }
}
