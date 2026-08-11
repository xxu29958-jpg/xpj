#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackagingDirectory,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9]+$')]
    [string]$Suffix,
    [Parameter(Mandatory = $true)]
    [ValidateSet('Desktop51', 'Core7')]
    [string]$ExpectedHost
)

$ErrorActionPreference = 'Stop'

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Real SCM dependency contract requires an elevated process.'
}
if (
    $ExpectedHost -ceq 'Desktop51' -and
    (
        [string]$PSVersionTable.PSEdition -cne 'Desktop' -or
        [int]$PSVersionTable.PSVersion.Major -ne 5 -or
        [int]$PSVersionTable.PSVersion.Minor -ne 1
    )
) {
    throw 'Expected the Windows PowerShell 5.1 Desktop host.'
}
if (
    $ExpectedHost -ceq 'Core7' -and
    (
        [string]$PSVersionTable.PSEdition -cne 'Core' -or
        [int]$PSVersionTable.PSVersion.Major -lt 7
    )
) {
    throw 'Expected a PowerShell 7.x Core host.'
}

$packaging = [IO.Path]::GetFullPath($PackagingDirectory)
$safetyScript = Join-Path $packaging 'windows_installation_safety.ps1'
$lifecycleScript = Join-Path $packaging 'windows_service_lifecycle.ps1'
$databaseSafetyScript = Join-Path $packaging 'windows_database_safety.ps1'
foreach ($requiredScript in @(
    $safetyScript,
    $lifecycleScript,
    $databaseSafetyScript
)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "Missing production contract script: $requiredScript"
    }
}
. $safetyScript
. $lifecycleScript
. $databaseSafetyScript

$dependencyA = "TbxScmDepA$Suffix"
$dependencyB = "TbxScmDepB$Suffix"
$target = "TbxScmTarget$Suffix"
$serviceNames = @($dependencyA, $dependencyB, $target)
$createdServices = New-Object System.Collections.Generic.List[string]
$createExitCodes = New-Object System.Collections.Generic.List[int]
$commandPath = [IO.Path]::GetFullPath(
    (Join-Path ([Environment]::SystemDirectory) 'cmd.exe')
)
$imagePath = Join-TicketboxWindowsCommandLine @($commandPath, '/c', 'exit', '0')

function Assert-ExactDependencySet {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Actual,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actualSet = @(
        $Actual |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
    $expectedSet = @(
        $Expected |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
    if ($actualSet.Count -ne $expectedSet.Count) {
        throw "$Label dependency count mismatch."
    }
    for ($index = 0; $index -lt $expectedSet.Count; $index++) {
        if (-not [string]::Equals(
            [string]$actualSet[$index],
            [string]$expectedSet[$index],
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "$Label dependency mismatch."
        }
    }
}

function Get-RegistryDependencySet([string]$Name) {
    $keyPath = "SYSTEM\CurrentControlSet\Services\$Name"
    $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($keyPath, $false)
    if ($null -eq $key) {
        throw "Missing SCM registry key for $Name."
    }
    try {
        $valueNames = @($key.GetValueNames())
        $dependencies = New-Object System.Collections.Generic.List[string]
        foreach ($definition in @(
            [pscustomobject]@{ Name = 'DependOnService'; Prefix = '' },
            [pscustomobject]@{ Name = 'DependOnGroup'; Prefix = '+' }
        )) {
            if (-not ($valueNames -contains $definition.Name)) {
                continue
            }
            if (
                $key.GetValueKind($definition.Name) -ne
                    [Microsoft.Win32.RegistryValueKind]::MultiString
            ) {
                throw "$($definition.Name) is not REG_MULTI_SZ for $Name."
            }
            $values = $key.GetValue(
                $definition.Name,
                $null,
                [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
            )
            if ($values -isnot [string[]]) {
                throw "$($definition.Name) did not return a string array for $Name."
            }
            foreach ($value in $values) {
                if ([string]::IsNullOrWhiteSpace([string]$value)) {
                    throw "$($definition.Name) contains an empty dependency for $Name."
                }
                $dependencies.Add(
                    [string]$definition.Prefix + [string]$value
                )
            }
        }
        return $dependencies.ToArray()
    }
    finally {
        $key.Dispose()
    }
}

function Assert-ProductionAndRegistryDependencies {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $registryDependencies = @(Get-RegistryDependencySet $Name)
    Assert-ExactDependencySet `
        -Actual $registryDependencies `
        -Expected $Expected `
        -Label "$Label registry"
    $productionDependencies = @(Get-TicketboxServiceDependencies $Name)
    Assert-ExactDependencySet `
        -Actual $productionDependencies `
        -Expected $Expected `
        -Label "$Label production"
    Assert-TicketboxServiceDependencies `
        -Name $Name `
        -ExpectedDependencies $Expected
    return $productionDependencies
}

function New-ProbeService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string[]]$Dependencies = @()
    )
    $arguments = @(
        'create',
        $Name,
        'binPath=',
        $imagePath,
        'start=',
        'demand',
        'obj=',
        'NT AUTHORITY\LocalService'
    )
    if ($Dependencies.Count -gt 0) {
        $arguments += @('depend=', ($Dependencies -join '/'))
    }
    $createResult = Invoke-TicketboxScProcess $arguments
    if (
        $null -eq $createResult -or
        $null -eq $createResult.PSObject.Properties['ExitCode']
    ) {
        throw "sc.exe create returned an invalid result for $Name."
    }
    $createExitCode = [int]$createResult.ExitCode
    if ($createExitCode -ne 0) {
        throw "sc.exe create failed for $Name (exit=$createExitCode)."
    }
    $createExitCodes.Add($createExitCode)
    $createdServices.Add($Name)
}

$operationFailure = $null
$result = $null
try {
    foreach ($serviceName in $serviceNames) {
        if (Test-TicketboxServiceExists $serviceName) {
            throw "Probe service already exists: $serviceName"
        }
    }

    New-ProbeService -Name $dependencyA
    New-ProbeService -Name $dependencyB
    New-ProbeService `
        -Name $target `
        -Dependencies @($dependencyA, $dependencyB)

    $twoDependencies = @(
        Assert-ProductionAndRegistryDependencies `
            -Name $target `
            -Expected @($dependencyA, $dependencyB) `
            -Label 'two-service'
    )

    $controller = New-Object System.ServiceProcess.ServiceController($target)
    $dependencyControllers = @()
    try {
        $dependencyControllers = @($controller.ServicesDependedOn)
        $controllerDependencies = @(
            $dependencyControllers | ForEach-Object { [string]$_.ServiceName }
        )
        Assert-ExactDependencySet `
            -Actual $controllerDependencies `
            -Expected @($dependencyA, $dependencyB) `
            -Label 'ServiceController'
    }
    finally {
        foreach ($dependencyController in $dependencyControllers) {
            $dependencyController.Dispose()
        }
        $controller.Dispose()
    }

    $mismatchRejected = $false
    try {
        Assert-TicketboxServiceDependencies `
            -Name $target `
            -ExpectedDependencies @($dependencyA)
    }
    catch {
        $mismatchRejected = $true
    }
    if (-not $mismatchRejected) {
        throw 'The exact dependency assertion accepted a missing dependency.'
    }

    Invoke-TicketboxScChecked @(
        'config', $target, 'depend=', $dependencyA
    ) | Out-Null
    $singleDependency = @(
        Assert-ProductionAndRegistryDependencies `
            -Name $target `
            -Expected @($dependencyA) `
            -Label 'single-service'
    )

    Invoke-TicketboxScChecked @(
        'config', $target, 'depend=', ''
    ) | Out-Null
    $emptyDependencies = @(
        Assert-ProductionAndRegistryDependencies `
            -Name $target `
            -Expected @() `
            -Label 'empty'
    )

    Invoke-TicketboxScChecked @(
        'config', $target, 'depend=', '+NetworkProvider'
    ) | Out-Null
    $groupDependency = @(
        Assert-ProductionAndRegistryDependencies `
            -Name $target `
            -Expected @('+NetworkProvider') `
            -Label 'load-order-group'
    )

    $result = [ordered]@{
        schema = 'ticketbox-real-scm-dependency-contract-v1'
        host = [string]$PSVersionTable.PSEdition
        powershell_version = $PSVersionTable.PSVersion.ToString()
        create_exit_codes = $createExitCodes.ToArray()
        two_dependencies = $twoDependencies
        single_dependency = $singleDependency
        empty_dependency_count = $emptyDependencies.Count
        group_dependency = $groupDependency
        mismatch_rejected = $mismatchRejected
    }
}
catch {
    $operationFailure = $_
}
finally {
    $cleanupFailures = New-Object System.Collections.Generic.List[string]
    for ($index = $createdServices.Count - 1; $index -ge 0; $index--) {
        $serviceName = $createdServices[$index]
        try {
            if (Test-TicketboxServiceExists $serviceName) {
                Invoke-TicketboxScChecked @('delete', $serviceName) | Out-Null
            }
            $deadline = [DateTime]::UtcNow.AddSeconds(15)
            while (
                (Test-TicketboxServiceExists $serviceName) -and
                [DateTime]::UtcNow -lt $deadline
            ) {
                Start-Sleep -Milliseconds 100
            }
            if (Test-TicketboxServiceExists $serviceName) {
                throw "Probe service deletion did not settle: $serviceName"
            }
        }
        catch {
            $cleanupFailures.Add("$serviceName`: $($_.Exception.Message)")
        }
    }
    if ($cleanupFailures.Count -gt 0) {
        throw "Real SCM probe cleanup failed: $($cleanupFailures -join ' | ')"
    }
}

if ($null -ne $operationFailure) {
    throw $operationFailure
}
$result | ConvertTo-Json -Compress
