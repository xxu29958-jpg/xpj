from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_test_lanes


def test_parallel_lane_uses_xdist_and_excludes_stateful_tests() -> None:
    command = run_test_lanes.pytest_command("parallel", workers=4)

    assert command[: len(run_test_lanes.COMMON_PYTEST_ARGS) + 3] == [
        run_test_lanes.sys.executable,
        "-m",
        "pytest",
        *run_test_lanes.COMMON_PYTEST_ARGS,
    ]
    assert run_test_lanes.COMMON_PYTEST_ARGS == (
        "tests",
        "-q",
        "-ra",
        "--tb=short",
        "-p",
        "no:cacheprovider",
    )
    assert command[-6:] == [
        "-m",
        "not stateful_serial",
        "-n",
        "4",
        "--dist",
        "worksteal",
    ]


def test_stateful_lane_is_single_process() -> None:
    command = run_test_lanes.pytest_command("stateful", workers=4)

    assert command[: len(run_test_lanes.COMMON_PYTEST_ARGS) + 3] == [
        run_test_lanes.sys.executable,
        "-m",
        "pytest",
        *run_test_lanes.COMMON_PYTEST_ARGS,
    ]
    assert command[-4:] == ["-m", "stateful_serial", "-n", "0"]


@pytest.mark.parametrize(
    ("detected", "expected"),
    [(16, 6), (4, 4), (None, 1)],
)
def test_worker_count_uses_a_bounded_machine_default(
    monkeypatch: pytest.MonkeyPatch,
    detected: int | None,
    expected: int,
) -> None:
    monkeypatch.setattr(run_test_lanes.os, "cpu_count", lambda: detected)
    assert run_test_lanes.worker_count(None) == expected


def test_explicit_worker_count_overrides_machine_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_test_lanes.os, "cpu_count", lambda: 16)
    assert run_test_lanes.worker_count("2") == 2


@pytest.mark.parametrize("raw", ["0", "9", "many"])
def test_worker_count_rejects_unsafe_values(raw: str) -> None:
    with pytest.raises(ValueError, match="XPJ_PYTEST_WORKERS"):
        run_test_lanes.worker_count(raw)


def test_full_lane_stops_after_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("parallel", "stateful"), workers=2) == 7
    assert len(calls) == 1
    assert "not stateful_serial" in calls[0]


def test_full_lane_runs_parallel_then_stateful(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("parallel", "stateful"), workers=2) == 0
    assert "not stateful_serial" in calls[0]
    assert calls[1][-4:] == ["-m", "stateful_serial", "-n", "0"]


def test_stateful_tests_reject_xdist_even_with_forged_lane() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["XPJ_TEST_LANE"] = "stateful"
    for key in tuple(environment):
        if key.startswith("PYTEST_XDIST_"):
            environment.pop(key)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_alembic_income_frequency_migration.py",
            "-q",
            "-n",
            "2",
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "Parallel PostgreSQL tests must exclude the serialized lane" in output
