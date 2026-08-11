#Requires -Version 5.1

function Enter-TicketboxWindowsTokenPrivilege {
    param(
        [ValidateNotNullOrEmpty()]
        [Parameter(Mandatory = $true)]
        [string]$PrivilegeName
    )

    Initialize-TicketboxWindowsTokenPrivilegeMethods
    return [TicketboxWindowsSecurityPrivilegeScope]::Enter($PrivilegeName)
}

function Close-TicketboxWindowsTokenPrivilegeScopes {
    param([object[]]$Scopes = @())

    $disposeFailure = $null
    for ($index = $Scopes.Count - 1; $index -ge 0; $index--) {
        $scope = $Scopes[$index]
        if ($null -eq $scope -or $null -eq $scope.PSObject.Methods["Dispose"]) {
            continue
        }
        try {
            $null = $scope.Dispose()
        }
        catch {
            if ($null -eq $disposeFailure) {
                $disposeFailure = $_.Exception
            }
        }
    }
    if ($null -ne $disposeFailure) {
        throw $disposeFailure
    }
}

function New-TicketboxWindowsTokenPrivilegeScope {
    param(
        [Parameter(Mandatory = $true)][string]$PrivilegeName,
        [AllowNull()][scriptblock]$PrivilegeScopeFactory = $null
    )

    $scopeResults = @(
        if ($null -eq $PrivilegeScopeFactory) {
            Enter-TicketboxWindowsTokenPrivilege -PrivilegeName $PrivilegeName
        }
        else {
            & $PrivilegeScopeFactory $PrivilegeName
        }
    )
    if ($scopeResults.Count -ne 1 -or $null -eq $scopeResults[0]) {
        Close-TicketboxWindowsTokenPrivilegeScopes -Scopes $scopeResults
        throw "Windows token privilege scope factory 必须返回一个 scope。"
    }
    return $scopeResults[0]
}

function Invoke-TicketboxWindowsTokenPrivilegeScopes {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string[]]$PrivilegeNames,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [AllowNull()][scriptblock]$PrivilegeScopeFactory = $null,
        [object[]]$ArgumentList = @()
    )

    $scopes = [System.Collections.Generic.List[object]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    try {
        foreach ($privilegeName in $PrivilegeNames) {
            if (
                [string]::IsNullOrWhiteSpace($privilegeName) -or
                -not $seen.Add($privilegeName)
            ) {
                throw "Windows token privilege names 必须非空且互不重复。"
            }
            $scopes.Add((New-TicketboxWindowsTokenPrivilegeScope `
                -PrivilegeName $privilegeName `
                -PrivilegeScopeFactory $PrivilegeScopeFactory))
        }
        return & $Action @ArgumentList
    }
    finally {
        Close-TicketboxWindowsTokenPrivilegeScopes -Scopes @($scopes)
    }
}

function Invoke-TicketboxWindowsTokenPrivilegeScope {
    param(
        [ValidateNotNullOrEmpty()]
        [Parameter(Mandatory = $true)]
        [string]$PrivilegeName,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [AllowNull()][scriptblock]$PrivilegeScopeFactory = $null,
        [object[]]$ArgumentList = @()
    )

    return Invoke-TicketboxWindowsTokenPrivilegeScopes `
        -PrivilegeNames @($PrivilegeName) `
        -Action $Action `
        -PrivilegeScopeFactory $PrivilegeScopeFactory `
        -ArgumentList $ArgumentList
    }
