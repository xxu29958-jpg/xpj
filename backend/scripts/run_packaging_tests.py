"""Run the complete packaging pytest surface with an execution proof."""

from __future__ import annotations

import subprocess
import sys
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
from scripts.test_pg_contract import start_windows_parent_watchdog  # noqa: E402

PACKAGING_TESTS_ROOT = BACKEND_ROOT / "packaging" / "tests"
STRICT_WINDOWS_RUNTIME_ENV = "XPJ_REQUIRE_WINDOWS_LIFECYCLE_RUNTIME"
HANDSHAKE_FAILURE_EXIT_CODE = 86


def packaging_pytest_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        str(PACKAGING_TESTS_ROOT),
        "-q",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
    ]


def run_packaging_tests() -> int:
    start_windows_parent_watchdog(label="packaging test runner")
    snapshot = collect_pytest_snapshot(
        "packaging/tests",
        backend_root=BACKEND_ROOT,
        remove_environment=(STRICT_WINDOWS_RUNTIME_ENV,),
    )
    environment = pytest_execution_environment()
    environment[STRICT_WINDOWS_RUNTIME_ENV] = "1"
    environment[PYTEST_EXPECTED_COUNT_ENV] = str(snapshot.count)
    environment[PYTEST_EXPECTED_DIGEST_ENV] = snapshot.digest
    with TemporaryDirectory(prefix="xpj-packaging-pytest-") as handshake_dir:
        handshake_path = Path(handshake_dir) / "packaging-conftest.handshake"
        handshake_token = uuid4().hex
        environment[PYTEST_HANDSHAKE_PATH_ENV] = str(handshake_path)
        environment[PYTEST_HANDSHAKE_TOKEN_ENV] = handshake_token
        command = packaging_pytest_command()
        print(f"[packaging-tests] {' '.join(command)}", flush=True)
        completed = subprocess.run(
            command,
            check=False,
            cwd=BACKEND_ROOT,
            env=environment,
        )
        if completed.returncode != 0:
            return completed.returncode
        try:
            actual_handshake = handshake_path.read_text(encoding="utf-8")
        except OSError:
            actual_handshake = None
        expected_handshake = pytest_execution_handshake_payload(
            "packaging",
            handshake_token,
            snapshot.count,
            snapshot.digest,
        )
        if actual_handshake == expected_handshake:
            return 0
        print(
            "[packaging-tests] packaging conftest handshake is missing or invalid; refusing a false-success result.",
            file=sys.stderr,
            flush=True,
        )
        return HANDSHAKE_FAILURE_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(run_packaging_tests())
