from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_test_lanes
from scripts.pytest_execution_contract import (
    collect_pytest_snapshot,
    pytest_execution_environment,
)
from tests._infra.lane_policy import stateful_selection_violation

pytestmark = pytest.mark.parallel_safe


def _add_parallel_execution_proof(environment: dict[str, str]) -> None:
    snapshot = collect_pytest_snapshot(
        "tests",
        mark_expression="not stateful_serial",
        backend_root=run_test_lanes.BACKEND_ROOT,
    )
    environment[run_test_lanes.RUNNER_EXPECTED_COUNT_ENV] = str(snapshot.count)
    environment[run_test_lanes.RUNNER_EXPECTED_DIGEST_ENV] = snapshot.digest


def test_managed_runner_rejects_zero_execution_with_success_exit(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "skip_test_loop.py"
    plugin.write_text(
        "def pytest_runtestloop(session):\n    return True\n",
        encoding="utf-8",
    )
    environment = pytest_execution_environment()
    environment[run_test_lanes.RUNNER_LANE_ENV] = "parallel"
    handshake_path = tmp_path / "zero-execution.handshake"
    environment[run_test_lanes.RUNNER_HANDSHAKE_PATH_ENV] = str(handshake_path)
    environment[run_test_lanes.RUNNER_HANDSHAKE_TOKEN_ENV] = "zero-execution-proof"
    _add_parallel_execution_proof(environment)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for key in tuple(environment):
        if key.startswith("PYTEST_XDIST_"):
            environment.pop(key)
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(tmp_path), environment.get("PYTHONPATH")) if part)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(run_test_lanes.TESTS_ROOT),
            "-q",
            "-p",
            "xdist.plugin",
            "-p",
            "skip_test_loop",
            "-o",
            "addopts=",
            "-m",
            "not stateful_serial",
            "-n",
            "0",
        ],
        cwd=run_test_lanes.BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == pytest.ExitCode.TESTS_FAILED, output
    assert "did not complete every collected test normally" in output
    assert not handshake_path.exists()


def test_worker_side_guard_rejects_a_retained_stateful_item() -> None:
    violation = stateful_selection_violation(
        ["tests/test_db_migration_contract.py::test_upgrade"],
        xdist_worker="gw0",
        configured_workers=0,
    )

    assert violation is not None
    assert "xdist worker gw0" in violation


def test_pytest_rejects_ambient_worker_without_runtime_authority() -> None:
    environment = pytest_execution_environment()
    environment["PYTEST_XDIST_WORKER"] = "gw7"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(run_test_lanes.TESTS_ROOT / "test_postgres_lane_policy.py"),
            "--collect-only",
            "-q",
            "-p",
            "xdist.plugin",
            "-o",
            "addopts=",
            "-n",
            "0",
        ],
        cwd=run_test_lanes.BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "clear inherited PYTEST_XDIST_* variables" in output


def test_managed_runner_rejects_collection_hook_identity_drift(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "drop_selected_item.py"
    plugin.write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    for index, item in enumerate(items):\n"
        "        if item.get_closest_marker('stateful_serial') is None:\n"
        "            items.pop(index)\n"
        "            break\n",
        encoding="utf-8",
    )
    environment = pytest_execution_environment()
    environment[run_test_lanes.RUNNER_LANE_ENV] = "parallel"
    handshake_path = tmp_path / "backend-conftest.handshake"
    environment[run_test_lanes.RUNNER_HANDSHAKE_PATH_ENV] = str(handshake_path)
    environment[run_test_lanes.RUNNER_HANDSHAKE_TOKEN_ENV] = "collection-drift-proof"
    _add_parallel_execution_proof(environment)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.pop("PYTEST_PLUGINS", None)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(tmp_path), environment.get("PYTHONPATH")) if part)
    for key in tuple(environment):
        if key.startswith("PYTEST_XDIST_"):
            environment.pop(key)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            "-p",
            "xdist.plugin",
            "-p",
            "drop_selected_item",
            "-o",
            "addopts=",
            "-m",
            "not stateful_serial",
            "-n",
            "0",
        ],
        cwd=run_test_lanes.BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "changed the committed test identity set" in output
    assert not handshake_path.exists()


def test_managed_runner_rejects_precollection_omission(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "omit_before_collection.py"
    plugin.write_text(
        "import os\n"
        "def pytest_ignore_collect(collection_path):\n"
        "    return (\n"
        "        os.environ.get('XPJ_TEST_RUNNER_LANE') == 'parallel'\n"
        "        and collection_path.name == 'test_web_session_write_gate.py'\n"
        "    )\n",
        encoding="utf-8",
    )
    environment = pytest_execution_environment()
    environment[run_test_lanes.RUNNER_LANE_ENV] = "parallel"
    handshake_path = tmp_path / "precollection-drift.handshake"
    environment[run_test_lanes.RUNNER_HANDSHAKE_PATH_ENV] = str(handshake_path)
    environment[run_test_lanes.RUNNER_HANDSHAKE_TOKEN_ENV] = "precollection-proof"
    _add_parallel_execution_proof(environment)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(tmp_path), environment.get("PYTHONPATH")) if part)
    for key in tuple(environment):
        if key.startswith("PYTEST_XDIST_"):
            environment.pop(key)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            "-p",
            "xdist.plugin",
            "-p",
            "omit_before_collection",
            "-o",
            "addopts=",
            "-m",
            "not stateful_serial",
            "-n",
            "0",
        ],
        cwd=run_test_lanes.BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "drifted from its independent collection" in output
    assert not handshake_path.exists()
