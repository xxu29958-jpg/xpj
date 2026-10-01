param(
    [Parameter(Mandatory = $true)][long]$GitHubRunId,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$JavaPath,
    [Parameter(Mandatory = $true)][string]$BuildToolsDirectory,
    [Parameter(Mandatory = $true)][string]$CertificateSha256,
    [Parameter(Mandatory = $true)][string]$ServerUrl,
    [ValidateSet("gray", "internal")][string]$Flavor = "gray",
    [string]$GitHubRepository = "xxu29958-jpg/xpj"
)

$ErrorActionPreference = "Stop"
$collector = Join-Path $PSScriptRoot "..\backend\scripts\collect_android_release.py"
& $PythonPath -E -S $collector --repository $GitHubRepository --run-id $GitHubRunId `
    --output $OutputDirectory --java $JavaPath --build-tools $BuildToolsDirectory `
    --certificate-sha256 $CertificateSha256 --server-url $ServerUrl --flavor $Flavor
if ($LASTEXITCODE -ne 0) {
    throw "Release artifact collection or signing failed. No RC qualification was granted."
}
