#Requires -Version 5.1

function Enter-TicketboxSealedPythonBuildEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$PyInstallerConfigDirectory
    )
    if (-not [System.IO.Path]::IsPathRooted($PyInstallerConfigDirectory)) {
        throw "PyInstaller build config directory must be absolute."
    }
    $configDirectory = [System.IO.Path]::GetFullPath($PyInstallerConfigDirectory)
    $environment = [Environment]::GetEnvironmentVariables("Process")
    [string[]]$names = @(
        $environment.Keys |
            ForEach-Object { [string]$_ } |
            Where-Object {
                $_ -like "UV_*" -or
                $_ -like "PYTHON*" -or
                $_ -ieq "PYINSTALLER_CONFIG_DIR"
            }
    )
    [Array]::Sort($names, [System.StringComparer]::OrdinalIgnoreCase)
    $saved = @(
        foreach ($name in $names) {
            [pscustomobject]@{
                name = $name
                value = [string]$environment[$name]
            }
            Remove-Item -LiteralPath ("Env:{0}" -f $name) -ErrorAction SilentlyContinue
        }
    )
    $snapshot = [pscustomobject]@{ variables = @($saved) }
    try {
        [Environment]::SetEnvironmentVariable("PYTHONNOUSERSITE", "1", "Process")
        [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
        [Environment]::SetEnvironmentVariable(
            "PYINSTALLER_CONFIG_DIR",
            $configDirectory,
            "Process"
        )
        return $snapshot
    }
    catch {
        Exit-TicketboxSealedPythonBuildEnvironment $snapshot
        throw
    }
}

function Exit-TicketboxSealedPythonBuildEnvironment([object]$Snapshot) {
    if ($null -eq $Snapshot) { return }
    $environment = [Environment]::GetEnvironmentVariables("Process")
    foreach ($name in @(
        $environment.Keys |
            ForEach-Object { [string]$_ } |
            Where-Object {
                $_ -like "UV_*" -or
                $_ -like "PYTHON*" -or
                $_ -ieq "PYINSTALLER_CONFIG_DIR"
            }
    )) {
        Remove-Item -LiteralPath ("Env:{0}" -f $name) -ErrorAction SilentlyContinue
    }
    foreach ($record in @($Snapshot.variables)) {
        [Environment]::SetEnvironmentVariable(
            [string]$record.name,
            [string]$record.value,
            "Process"
        )
    }
}
