"""Isolated subprocess probes for the build-owned database generation program."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.database import engine
from scripts.build_database_generation_program import write_program

_C07_PROTOCOL_UPGRADE_PROBE = r"""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
source_revision = sys.argv[2]
target_revision = sys.argv[3]
from app.database._database_generation_executor import execute_database_generation
from app.database._database_generation_program import load_database_generation_program
program = load_database_generation_program(
    path=Path(sys.argv[4]),
    expected_sha256=sys.argv[5],
)

from app.database import engine

operation_id = "d5148f80-1e6c-447d-b3bc-e3dc180d87b4"
with engine.begin() as connection:
    execute_database_generation(
        connection,
        program=program,
        source_revision=source_revision,
        target_revision=target_revision,
        operation_id=operation_id,
    )

engine.dispose()
print(f"{source_revision}->{target_revision}")
"""


def run_database_generation_upgrade(source_revision: str, target_revision: str) -> None:
    """Run one exact program suffix in an import-isolated child interpreter."""

    backend_root = Path(__file__).resolve().parents[2]
    engine.dispose()
    with tempfile.TemporaryDirectory(prefix="ticketbox-generation-program-") as directory:
        program_path = Path(directory) / "DATABASE_GENERATION_PROGRAM.json"
        program_sha256 = write_program(
            backend_root=backend_root,
            output=program_path,
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                _C07_PROTOCOL_UPGRADE_PROBE,
                str(backend_root),
                source_revision,
                target_revision,
                str(program_path),
                program_sha256,
            ],
            cwd=backend_root,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1_230,
        )
    engine.dispose()
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == f"{source_revision}->{target_revision}\n"
    assert completed.stderr == ""
