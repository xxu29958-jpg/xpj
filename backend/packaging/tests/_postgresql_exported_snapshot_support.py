from __future__ import annotations

import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
ENTRYPOINT = PACKAGING / "windows_postgresql_exported_snapshot.ps1"
COMPONENTS = (
    PACKAGING / "postgresql_exported_snapshot" / "primitives.ps1",
    PACKAGING / "postgresql_exported_snapshot" / "session.ps1",
    PACKAGING / "postgresql_exported_snapshot" / "deadline_evidence.ps1",
)
C07_RECOVERY = PACKAGING / "windows_c07_recovery_generation.ps1"
INSTALLATION_SAFETY = PACKAGING / "windows_installation_safety.ps1"
DATABASE_SAFETY = PACKAGING / "windows_database_safety.ps1"
INNO = PACKAGING / "ticketbox-installer.iss"
BUILD = PACKAGING / "build_inno_installer.ps1"
PROVENANCE = PACKAGING.parent / "scripts" / "windows_build_provenance.ps1"


def ps_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def run_harness(
    tmp_path: Path,
    name: str,
    source: str,
    *,
    timeout: int = 45,
) -> None:
    harness = tmp_path / f"{name}.ps1"
    harness.write_text(source, encoding="utf-8-sig")
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        assert result.returncode == 0, (
            f"{Path(engine).name} failed:\n{result.stdout}\n{result.stderr}"
        )
