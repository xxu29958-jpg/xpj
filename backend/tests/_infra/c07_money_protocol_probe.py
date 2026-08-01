"""Isolated subprocess probes for the C07 money migration protocol."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.database import engine

_C07_PROTOCOL_UPGRADE_PROBE = r"""
import sys
import time

sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]

from app.database import engine
from app.database._c07_transaction_timeout import c07_prearmed_transaction

operation_id = "d5148f80-1e6c-447d-b3bc-e3dc180d87b4"
if mode == "fresh":
    from app.database._c07_fresh_source_bootstrap import (
        _load_frozen_alembic_plan,
        _run_fresh_source_with_connection,
    )

    plan = _load_frozen_alembic_plan()
    with engine.begin() as connection:
        result = _run_fresh_source_with_connection(connection, plan=plan)
    assert result["alembic_revision"] == "20260722_0001"
elif mode == "maintenance":
    from app.database._c07_maintenance_plan import load_exact_maintenance_plan
    from app.database._c07_maintenance_upgrade import _run_exact_upgrade

    plan = load_exact_maintenance_plan(
        source_revision="20260722_0001",
        target_revision="20260729_0001",
    )
    with engine.connect() as connection:
        with c07_prearmed_transaction(connection, timeout_ms=1_200_000):
            result, _shape, _facts = _run_exact_upgrade(
                connection,
                plan=plan,
                operation_id=operation_id,
                remaining_ms=1_200_000,
            )
    assert result == "isolated_forward_replay_verified"
elif mode == "production":
    from app.database._c07_production_connection import _run_alembic_upgrade

    with engine.connect() as connection:
        with c07_prearmed_transaction(connection, timeout_ms=1_200_000):
            _run_alembic_upgrade(
                connection,
                ceremony_id=operation_id,
                deadline=time.monotonic() + 1_200,
            )
else:
    raise AssertionError(f"unsupported protocol probe mode: {mode}")

engine.dispose()
print(mode)
"""


def run_c07_protocol_upgrade(mode: str) -> None:
    """Run one protocol path in an import-isolated child interpreter."""

    backend_root = Path(__file__).resolve().parents[2]
    engine.dispose()
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _C07_PROTOCOL_UPGRADE_PROBE,
            str(backend_root),
            mode,
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
    assert completed.stdout == f"{mode}\n"
    assert completed.stderr == ""
