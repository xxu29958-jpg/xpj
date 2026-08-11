#Requires -Version 5.1

$componentRoot = Join-Path $PSScriptRoot "security_primitives"
foreach ($componentName in @(
    "byte_array.ps1",
    "token_privilege_native.ps1",
    "token_privilege.ps1",
    "descriptor_comparison.ps1",
    "descriptor_diagnostic.ps1",
    "file_security.ps1"
)) {
    $componentPath = Join-Path $componentRoot $componentName
    if (-not (Test-Path -LiteralPath $componentPath -PathType Leaf)) {
        throw "缺少 Windows security-primitives 组件：$componentPath"
    }
    . $componentPath
}
