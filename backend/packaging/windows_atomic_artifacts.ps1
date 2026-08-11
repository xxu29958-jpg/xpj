#Requires -Version 5.1

$componentRoot = Join-Path $PSScriptRoot "atomic_artifacts"
foreach ($componentName in @("native.ps1", "file.ps1", "directory.ps1")) {
    $componentPath = Join-Path $componentRoot $componentName
    if (-not (Test-Path -LiteralPath $componentPath -PathType Leaf)) {
        throw "缺少 Windows atomic-artifact 组件：$componentPath"
    }
    . $componentPath
}
