from __future__ import annotations

import re
from pathlib import Path

from _powershell_contract import powershell_function, run_powershell_contract_script

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent
SPEC = PACKAGING / "ticketbox-backend.spec"
PROVENANCE = BACKEND / "scripts" / "windows_backend_build_provenance.ps1"


def test_frozen_backend_allows_only_the_two_shipped_executables(tmp_path: Path) -> None:
    spec = SPEC.read_text(encoding="utf-8-sig")
    provenance = PROVENANCE.read_text(encoding="utf-8-sig")
    assert re.findall(r'(?m)^\s+name="([^"]+)",$', spec) == [
        "ticketbox-backend",
        "ticketbox-database-maintenance",
        "ticketbox-backend",
    ]
    assert provenance.count("Assert-TicketboxFrozenBackendExecutableSet $DistDir") == 2
    executable_guard = powershell_function(
        provenance,
        "Assert-TicketboxFrozenBackendExecutableSet",
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
{executable_guard}
$dist = Join-Path {_ps_literal(tmp_path)} (
    'dist-' + $PSVersionTable.PSEdition + '-' + $PSVersionTable.PSVersion.Major
)
New-Item -ItemType Directory -Force -Path $dist | Out-Null
foreach ($name in @('ticketbox-backend.exe', 'ticketbox-database-maintenance.exe')) {{
    [IO.File]::WriteAllBytes((Join-Path $dist $name), [byte[]](1))
}}
Assert-TicketboxFrozenBackendExecutableSet $dist
[IO.File]::WriteAllBytes(
    (Join-Path $dist 'ticketbox-c07-migrator.exe'),
    [byte[]](1)
)
$rejected = $false
try {{ Assert-TicketboxFrozenBackendExecutableSet $dist }}
catch {{ $rejected = $true }}
    if (-not $rejected) {{
        throw 'frozen backend accepted an additional retired executable'
    }}
    Remove-Item -LiteralPath (Join-Path $dist 'ticketbox-c07-migrator.exe')
    $nested = Join-Path $dist 'legacy'
    New-Item -ItemType Directory -Force -Path $nested | Out-Null
    [IO.File]::WriteAllBytes(
        (Join-Path $nested 'ticketbox-c07-migrator.exe'),
        [byte[]](1)
    )
    $rejected = $false
    try {{ Assert-TicketboxFrozenBackendExecutableSet $dist }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{
        throw 'frozen backend accepted a nested retired executable'
    }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="frozen-backend-executable-set.ps1",
    )


def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"
