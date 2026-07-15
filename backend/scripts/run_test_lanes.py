"""Run the PostgreSQL pytest lanes with one shared local/CI contract."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence

COMMON_PYTEST_ARGS = (
    "tests",
    "-q",
    "-ra",
    "--tb=short",
    "-p",
    "no:cacheprovider",
)
AUTO_WORKER_CAP = 6


def pytest_command(lane: str, *, workers: int) -> list[str]:
    command = [sys.executable, "-m", "pytest", *COMMON_PYTEST_ARGS]
    if lane == "parallel":
        command.extend(
            [
                "-m",
                "not stateful_serial",
                "-n",
                str(workers),
                "--dist",
                "worksteal",
            ]
        )
        return command
    if lane == "stateful":
        command.extend(["-m", "stateful_serial", "-n", "0"])
        return command
    raise ValueError(f"Unknown test lane: {lane}")


def worker_count(raw_value: str | None) -> int:
    raw = raw_value or str(min(os.cpu_count() or 1, AUTO_WORKER_CAP))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("XPJ_PYTEST_WORKERS must be an integer") from exc
    if not 1 <= value <= 8:
        raise ValueError("XPJ_PYTEST_WORKERS must be between 1 and 8")
    return value


def run_lanes(lanes: Sequence[str], *, workers: int) -> int:
    for lane in lanes:
        command = pytest_command(lane, workers=workers)
        print(f"[test-lane:{lane}] {' '.join(command)}", flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "lane",
        choices=("parallel", "stateful", "full"),
        help="parallel excludes stateful_serial; full runs both lanes",
    )
    arguments = parser.parse_args()
    lanes = ("parallel", "stateful") if arguments.lane == "full" else (arguments.lane,)
    try:
        workers = worker_count(os.environ.get("XPJ_PYTEST_WORKERS"))
    except ValueError as exc:
        parser.error(str(exc))
    return run_lanes(lanes, workers=workers)


if __name__ == "__main__":
    raise SystemExit(main())
