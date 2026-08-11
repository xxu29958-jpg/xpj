#Requires -Version 5.1

function Test-TicketboxWindowsByteArrayEquals {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right
    )

    if ($Left.Length -ne $Right.Length) {
        return $false
    }
    for ($index = 0; $index -lt $Left.Length; $index++) {
        if ($Left[$index] -ne $Right[$index]) {
            return $false
        }
    }
    return $true
}
