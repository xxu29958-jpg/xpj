"""Run the PostgreSQL pytest lanes with one shared local/CI contract."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.pytest_execution_contract import (  # noqa: E402
    PYTEST_EXPECTED_COUNT_ENV,
    PYTEST_EXPECTED_DIGEST_ENV,
    PYTEST_HANDSHAKE_PATH_ENV,
    PYTEST_HANDSHAKE_TOKEN_ENV,
    collect_pytest_snapshot,
    pytest_execution_environment,
    pytest_execution_handshake_payload,
)
from scripts.pytest_marker_contract import (  # noqa: E402
    BACKEND_PARALLEL_MARK_EXPRESSION,
    BACKEND_STATEFUL_MARKER,
)
from scripts.test_pg_contract import (  # noqa: E402 - direct-script path bootstrap
    assert_test_cluster_authority,
    configured_test_database_url,
    start_windows_parent_watchdog,
    test_postgres_consumer_lease,
    test_postgres_credential_environment,
)

RUNNER_LANE_ENV = "XPJ_TEST_RUNNER_LANE"
RUNNER_HANDSHAKE_PATH_ENV = PYTEST_HANDSHAKE_PATH_ENV
RUNNER_HANDSHAKE_TOKEN_ENV = PYTEST_HANDSHAKE_TOKEN_ENV
RUNNER_EXPECTED_COUNT_ENV = PYTEST_EXPECTED_COUNT_ENV
RUNNER_EXPECTED_DIGEST_ENV = PYTEST_EXPECTED_DIGEST_ENV
RUNNER_HANDSHAKE_FAILURE_EXIT_CODE = 86
TESTS_ROOT = BACKEND_ROOT / "tests"

COMMON_PYTEST_ARGS = (
    str(TESTS_ROOT),
    "-q",
    "-ra",
    "--tb=short",
    "--strict-markers",
    "-p",
    "no:cacheprovider",
    "-p",
    "xdist.plugin",
    "-o",
    "addopts=",
)
AUTO_WORKER_CAP = 6


def runner_handshake_payload(
    lane: str,
    token: str,
    count: int,
    digest: str,
) -> str:
    return pytest_execution_handshake_payload(lane, token, count, digest)


def pytest_command(lane: str, *, workers: int) -> list[str]:
    command = [sys.executable, "-m", "pytest", *COMMON_PYTEST_ARGS]
    if lane == "parallel":
        command.extend(
            [
                "-m",
                BACKEND_PARALLEL_MARK_EXPRESSION,
                "-n",
                str(workers),
                "--dist",
                "worksteal",
                "--max-worker-restart=0",
            ]
        )
        return command
    if lane == "stateful":
        command.extend(["-m", BACKEND_STATEFUL_MARKER, "-n", "0"])
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


def _run_lane(
    lane: str,
    *,
    workers: int,
    parent_environment: dict[str, str],
) -> int:
    mark_expression = BACKEND_PARALLEL_MARK_EXPRESSION if lane == "parallel" else BACKEND_STATEFUL_MARKER
    snapshot = collect_pytest_snapshot(
        "tests",
        mark_expression=mark_expression,
        backend_root=BACKEND_ROOT,
    )
    command = pytest_command(lane, workers=workers)
    environment = pytest_execution_environment(parent_environment)
    environment[RUNNER_LANE_ENV] = lane
    environment[RUNNER_EXPECTED_COUNT_ENV] = str(snapshot.count)
    environment[RUNNER_EXPECTED_DIGEST_ENV] = snapshot.digest
    with TemporaryDirectory(prefix=f"xpj-pytest-{lane}-") as handshake_dir:
        handshake_path = Path(handshake_dir) / "backend-conftest.handshake"
        handshake_token = uuid4().hex
        environment[RUNNER_HANDSHAKE_PATH_ENV] = str(handshake_path)
        environment[RUNNER_HANDSHAKE_TOKEN_ENV] = handshake_token
        print(f"[test-lane:{lane}] {' '.join(command)}", flush=True)
        completed = subprocess.run(
            command,
            check=False,
            env=environment,
            cwd=BACKEND_ROOT,
        )
        if completed.returncode != 0:
            return completed.returncode
        try:
            actual_handshake = handshake_path.read_text(encoding="utf-8")
        except OSError:
            actual_handshake = None
        expected_handshake = runner_handshake_payload(
            lane,
            handshake_token,
            snapshot.count,
            snapshot.digest,
        )
        if actual_handshake == expected_handshake:
            return 0
        print(
            f"[test-lane:{lane}] backend conftest handshake is missing or invalid; "
            "refusing a false-success result.",
            file=sys.stderr,
            flush=True,
        )
        return RUNNER_HANDSHAKE_FAILURE_EXIT_CODE


def run_lanes(lanes: Sequence[str], *, workers: int) -> int:
    start_windows_parent_watchdog(label="PostgreSQL test-lane runner")
    parent_environment = os.environ.copy()
    database_url = configured_test_database_url(parent_environment)
    with test_postgres_consumer_lease(database_url), test_postgres_credential_environment(
        database_url,
        parent_environment,
    ):
        assert_test_cluster_authority(database_url, parent_environment)
        for lane in lanes:
            return_code = _run_lane(
                lane,
                workers=workers,
                parent_environment=parent_environment,
            )
            if return_code:
                return return_code
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
