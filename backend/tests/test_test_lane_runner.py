from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_test_lanes
from tests._infra.lane_policy import (
    managed_runner_configuration_violation,
    managed_runner_outcome_violation,
    stateful_selection_violation,
)


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
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
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

    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("parallel", "stateful"), workers=2) == 7
    assert len(calls) == 1
    assert "not stateful_serial" in calls[0]


def test_full_lane_clears_filters_and_propagates_stateful_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    return_codes = iter((0, 7))
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only -k owner")

    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, env))
        return subprocess.CompletedProcess(command, next(return_codes))

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("parallel", "stateful"), workers=2) == 7
    assert "not stateful_serial" in calls[0][0]
    assert calls[1][0][-4:] == ["-m", "stateful_serial", "-n", "0"]
    assert [call[1][run_test_lanes.RUNNER_LANE_ENV] for call in calls] == [
        "parallel",
        "stateful",
    ]
    assert all("PYTEST_ADDOPTS" not in call[1] for call in calls)


def test_managed_runner_rejects_partial_or_collection_only_execution() -> None:
    common = {
        "active_lane": "parallel",
        "collection_roots": ["tests"],
        "collect_only": False,
        "keyword": "",
        "mark_expression": "not stateful_serial",
        "deselected": (),
        "ignored": (),
        "ignore_globs": (),
        "last_failed": False,
    }

    assert managed_runner_configuration_violation(**common) is None
    assert "execute" in (
        managed_runner_configuration_violation(**(common | {"collect_only": True}))
        or ""
    )
    assert "filter" in (
        managed_runner_configuration_violation(**(common | {"keyword": "owner"}))
        or ""
    )
    assert "complete tests root" in (
        managed_runner_configuration_violation(
            **(common | {"collection_roots": ["tests/test_owner_console.py"]})
        )
        or ""
    )


def test_managed_runner_rejects_skipped_or_expected_failure_outcomes() -> None:
    assert managed_runner_outcome_violation(
        active_lane=None,
        outcome_counts=None,
    ) is None
    assert managed_runner_outcome_violation(
        active_lane="parallel",
        outcome_counts={"skipped": 0, "xfailed": 0, "xpassed": 0},
    ) is None

    for outcome in ("skipped", "xfailed", "xpassed"):
        violation = managed_runner_outcome_violation(
            active_lane="parallel",
            outcome_counts={outcome: 1},
        )
        assert violation is not None
        assert f"{outcome}=1" in violation

    assert "could not verify" in (
        managed_runner_outcome_violation(
            active_lane="stateful",
            outcome_counts=None,
        )
        or ""
    )


def test_worker_side_guard_rejects_a_retained_stateful_item() -> None:
    violation = stateful_selection_violation(
        ["tests/test_db_migration_contract.py::test_upgrade"],
        xdist_worker="gw0",
        configured_workers=0,
    )

    assert violation is not None
    assert "xdist worker gw0" in violation


def test_stateful_tests_reject_xdist_even_with_forged_lane() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["XPJ_TEST_LANE"] = "stateful"
    environment.pop(run_test_lanes.RUNNER_LANE_ENV, None)
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
