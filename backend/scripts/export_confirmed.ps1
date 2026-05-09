param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [Parameter(Mandatory = $true)]
    [string]$SessionToken,
    [string]$Month = "",
    [string]$Category = "",
    [string]$OutFile = "ticketbox-expenses.csv"
)

$query = @()
if ($Month.Trim()) {
    $query += "month=$([uri]::EscapeDataString($Month.Trim()))"
}
if ($Category.Trim()) {
    $query += "category=$([uri]::EscapeDataString($Category.Trim()))"
}

$uri = "$($BaseUrl.TrimEnd('/'))/api/expenses/export.csv"
if ($query.Count -gt 0) {
    $uri = "$uri`?$($query -join '&')"
}

Invoke-WebRequest `
    -Uri $uri `
    -Headers @{ Authorization = "Bearer $SessionToken" } `
    -OutFile $OutFile

Write-Host "已导出到 $OutFile"
