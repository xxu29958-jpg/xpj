from __future__ import annotations

import re
from pathlib import Path

import pytest
from _postgresql_exported_snapshot_support import (
    BUILD,
    C07_RECOVERY,
    COMPONENTS,
    ENTRYPOINT,
    INNO,
    PACKAGING,
    PROVENANCE,
    ps_literal,
    run_harness,
)
from _powershell_contract import powershell_contract_engines


def _function_body(source: str, name: str, next_name: str) -> str:
    return source[
        source.index(f"function {name}") : source.index(f"function {next_name}")
    ]


def test_exported_snapshot_components_are_one_way_and_retire_old_mechanics() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8-sig")
    sources = [path.read_text(encoding="utf-8-sig") for path in COMPONENTS]
    combined = "\n".join((entrypoint, *sources))
    recovery = C07_RECOVERY.read_text(encoding="utf-8-sig")
    production = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in PACKAGING.rglob("*.ps1")
        if "tests" not in path.parts
    )

    for path in (ENTRYPOINT, *COMPONENTS):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert len(path.read_text(encoding="utf-8-sig").splitlines()) <= 240
    assert "TicketboxC07" not in combined
    assert "scriptblock" not in combined.lower()
    assert "Start-TicketboxC07RecoverySnapshotProcess" not in production
    assert "ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc" not in production
    for retired_mechanic in (
        "Diagnostics.ProcessStartInfo",
        "ReadLineAsync(",
        ".Kill()",
        "WaitForExit(",
    ):
        assert retired_mechanic not in recovery

    reader = _function_body(
        recovery,
        "Read-TicketboxC07RecoverySnapshotProcess",
        "Open-TicketboxC07RecoverySnapshot",
    )
    opener = _function_body(
        recovery,
        "Open-TicketboxC07RecoverySnapshot",
        "Assert-TicketboxC07RecoverySnapshotAlive",
    )
    alive = _function_body(
        recovery,
        "Assert-TicketboxC07RecoverySnapshotAlive",
        "Close-TicketboxC07RecoverySnapshot",
    )
    closer = _function_body(
        recovery,
        "Close-TicketboxC07RecoverySnapshot",
        "ConvertTo-TicketboxC07RecoveryUnsignedInt64",
    )
    for required in (
        "Read-TicketboxPostgresqlExportedSnapshotLine",
        "Assert-TicketboxPostgresqlExportedSnapshotDeadlineEvidence",
        "Assert-TicketboxPostgresqlExportedSnapshotSessionAlive",
    ):
        assert required in reader
    assert "Start-TicketboxPostgresqlExportedSnapshotSession" in opener
    assert "-SqlCommands $sqlCommands" in opener
    assert "Stop-TicketboxPostgresqlExportedSnapshotSession" in opener
    assert "Assert-TicketboxPostgresqlExportedSnapshotSessionAlive" in alive
    assert "Close-TicketboxC07RecoverySnapshot $Snapshot" in alive
    assert "Stop-TicketboxPostgresqlExportedSnapshotSession" in closer
    assert "finally {" in closer
    assert "$Snapshot.Process = $null" in closer


def test_exported_snapshot_packaging_topology_is_exact_and_active() -> None:
    inno = INNO.read_text(encoding="utf-8-sig")
    build = BUILD.read_text(encoding="utf-8-sig")
    provenance = PROVENANCE.read_text(encoding="utf-8-sig")
    files_section = inno[inno.index("[Files]") : inno.index("[Registry]")]
    assert not any(
        line.lstrip().startswith("#") for line in files_section.splitlines()
    ), "installer payload entries must not be conditionally preprocessed"
    active_lines = {
        line.strip()
        for line in files_section.splitlines()
        if line.strip() and not line.lstrip().startswith(";")
    }
    source_lines = {
        'Source: "windows_postgresql_exported_snapshot.ps1"; '
        'DestDir: "{app}\\installer"; Flags: ignoreversion',
        'Source: "postgresql_exported_snapshot\\primitives.ps1"; '
        'DestDir: "{app}\\installer\\postgresql_exported_snapshot"; '
        'Flags: ignoreversion',
        'Source: "postgresql_exported_snapshot\\session.ps1"; '
        'DestDir: "{app}\\installer\\postgresql_exported_snapshot"; '
        'Flags: ignoreversion',
        'Source: "postgresql_exported_snapshot\\deadline_evidence.ps1"; '
        'DestDir: "{app}\\installer\\postgresql_exported_snapshot"; '
        'Flags: ignoreversion',
    }
    assert source_lines <= active_lines

    active_build = re.sub(r"<#.*?#>", "", build, flags=re.DOTALL)
    for variable in (
        "PostgresqlExportedSnapshotScript",
        "PostgresqlExportedSnapshotPrimitivesScript",
        "PostgresqlExportedSnapshotSessionScript",
        "PostgresqlExportedSnapshotDeadlineEvidenceScript",
    ):
        assert re.search(
            rf'Assert-File\s+`\s*\${variable}\s+`\s*"[^"]+"',
            active_build,
        )
    recipe_start = provenance.index(
        "$script:TicketboxInstallerRecipeRelativePaths = @(")
    recipe = provenance[
        recipe_start : provenance.index("\n)\n", recipe_start)
    ]
    for path in (
        r"packaging\windows_postgresql_exported_snapshot.ps1",
        r"packaging\postgresql_exported_snapshot\primitives.ps1",
        r"packaging\postgresql_exported_snapshot\session.ps1",
        r"packaging\postgresql_exported_snapshot\deadline_evidence.ps1",
    ):
        assert f'"{path}",' in recipe


@pytest.mark.skipif(
    not powershell_contract_engines(), reason="PowerShell contract"
)
def test_exported_snapshot_loader_guards_every_component(tmp_path: Path) -> None:
    source = f"""
$ErrorActionPreference = 'Stop'
$script:ancestorChecks = [Collections.Generic.List[string]]::new()
$script:kindChecks = [Collections.Generic.List[string]]::new()
function Assert-NoTicketboxAncestorReparsePoints {{
    param([string]$Path)
    $script:ancestorChecks.Add([IO.Path]::GetFullPath($Path))
}}
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    $script:kindChecks.Add([IO.Path]::GetFullPath($Path))
    return 'File'
}}
. '{ps_literal(ENTRYPOINT)}'
$expected = @(
    '{ps_literal(COMPONENTS[0])}',
    '{ps_literal(COMPONENTS[1])}',
    '{ps_literal(COMPONENTS[2])}'
) | ForEach-Object {{ [IO.Path]::GetFullPath($_) }}
if (
    [string]::Join("`n", $script:ancestorChecks) -cne
        [string]::Join("`n", $expected) -or
    [string]::Join("`n", $script:kindChecks) -cne
        [string]::Join("`n", $expected)
) {{ throw 'component loader guard coverage changed' }}

function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if ([IO.Path]::GetFileName($Path) -ceq 'session.ps1') {{ return 'ReparsePoint' }}
    return 'File'
}}
$reparseRejected = $false
try {{ . '{ps_literal(ENTRYPOINT)}' }}
catch {{ $reparseRejected = $true }}
if (-not $reparseRejected) {{ throw 'reparse component was loaded' }}

function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if (
        [IO.Path]::GetFileName($Path) -ceq
            'windows_postgresql_exported_snapshot.ps1'
    ) {{ return 'ReparsePoint' }}
    return 'File'
}}
$adapterRejected = $false
try {{ . '{ps_literal(C07_RECOVERY)}' }}
catch {{ $adapterRejected = $true }}
if (-not $adapterRejected) {{ throw 'reparse snapshot adapter was loaded by C07' }}
"""
    run_harness(tmp_path, "exported-snapshot-loader", source)
