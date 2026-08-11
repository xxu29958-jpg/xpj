#Requires -Version 5.1

function Assert-TicketboxPostgresqlExportedSnapshotExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($null -eq $Value) { throw "$Label 为空。" }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($Names | Sort-Object)
    if (
        $actual.Count -ne $expected.Count -or
        [string]::Join("`n", $actual) -cne [string]::Join("`n", $expected)
    ) {
        throw "$Label 字段集合无效。"
    }
}

function ConvertTo-TicketboxPostgresqlExportedSnapshotUnsignedInt64 {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $text = [string]$Value
    [uint64]$parsed = 0
    if (
        -not [uint64]::TryParse(
            $text,
            [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$parsed
        ) -or
        $parsed.ToString([Globalization.CultureInfo]::InvariantCulture) -cne
            $text
    ) {
        throw "$Label 不是 canonical non-negative integer。"
    }
    return $parsed
}

function ConvertTo-TicketboxPostgresqlExportedSnapshotUtc {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $parsed = [DateTimeOffset]::MinValue
    [string[]]$formats = @(
        "yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",
        "yyyy-MM-dd'T'HH:mm:ss.ffffff'Z'",
        "yyyy-MM-dd'T'HH:mm:ss.fffffffzzz",
        "yyyy-MM-dd'T'HH:mm:ss.ffffffzzz"
    )
    if (
        -not [DateTimeOffset]::TryParseExact(
            $Value,
            $formats,
            [Globalization.CultureInfo]::InvariantCulture,
            (
                [Globalization.DateTimeStyles]::AssumeUniversal -bor
                [Globalization.DateTimeStyles]::AdjustToUniversal
            ),
            [ref]$parsed
        ) -or
        $parsed.Offset -ne [TimeSpan]::Zero
    ) {
        throw "$Label 不是 canonical UTC timestamp。"
    }
    return $parsed
}
