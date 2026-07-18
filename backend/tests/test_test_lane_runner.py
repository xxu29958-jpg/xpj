from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_test_lanes
from scripts.pytest_execution_contract import PytestCollectionSnapshot, pytest_target_digest
from scripts.test_impact_selection import ImpactPlan
from tests._infra.lane_policy import (
    managed_runner_completion_violation,
    managed_runner_configuration_violation,
    managed_runner_outcome_violation,
    managed_runner_selection_violation,
    managed_runner_worker_violation,
)

pytestmark = pytest.mark.parallel_safe


def _write_runner_handshake(environment: dict[str, str]) -> None:
    lane = environment[run_test_lanes.RUNNER_LANE_ENV]
    token = environment[run_test_lanes.RUNNER_HANDSHAKE_TOKEN_ENV]
    count = int(environment[run_test_lanes.RUNNER_EXPECTED_COUNT_ENV])
    digest = environment[run_test_lanes.RUNNER_EXPECTED_DIGEST_ENV]
    Path(environment[run_test_lanes.RUNNER_HANDSHAKE_PATH_ENV]).write_text(
        run_test_lanes.runner_handshake_payload(lane, token, count, digest),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _stable_collection_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    def collect(
        target: str,
        *,
        mark_expression: str | None,
        backend_root: Path,
    ) -> PytestCollectionSnapshot:
        assert target == "tests"
        assert backend_root == run_test_lanes.BACKEND_ROOT
        lane = "parallel" if mark_expression == "not stateful_serial" else "stateful"
        return PytestCollectionSnapshot((f"tests/test_{lane}.py::test_contract",))

    monkeypatch.setattr(run_test_lanes, "collect_pytest_snapshot", collect)
    monkeypatch.setattr(
        run_test_lanes,
        "assert_test_cluster_authority",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        run_test_lanes,
        "test_postgres_credential_environment",
        lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        run_test_lanes,
        "test_postgres_consumer_lease",
        lambda *_args, **_kwargs: contextlib.nullcontext(),
    )


def test_parallel_lane_uses_xdist_and_excludes_stateful_tests() -> None:
    command = run_test_lanes.pytest_command("parallel", workers=4)

    assert command[: len(run_test_lanes.COMMON_PYTEST_ARGS) + 3] == [
        run_test_lanes.sys.executable,
        "-m",
        "pytest",
        *run_test_lanes.COMMON_PYTEST_ARGS,
    ]
    assert (
        str(run_test_lanes.TESTS_ROOT),
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
    ) == run_test_lanes.COMMON_PYTEST_ARGS
    assert command[-7:] == [
        "-m",
        "not stateful_serial",
        "-n",
        "4",
        "--dist",
        "worksteal",
        "--max-worker-restart=0",
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


def test_impacted_lane_uses_only_explicit_test_files() -> None:
    target = str(run_test_lanes.TESTS_ROOT / "test_test_lane_runner.py")

    command = run_test_lanes.pytest_command(
        "parallel",
        workers=2,
        targets=(target,),
    )

    assert command[3] == target
    assert str(run_test_lanes.TESTS_ROOT) not in command[4:]
    assert command[-7:] == [
        "-m",
        "not stateful_serial",
        "-n",
        "2",
        "--dist",
        "worksteal",
        "--max-worker-restart=0",
    ]


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
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == run_test_lanes.BACKEND_ROOT
        calls.append(command)
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("parallel", "stateful"), workers=2) == 7
    assert len(calls) == 1
    assert "not stateful_serial" in calls[0]


def test_full_lane_clears_filters_and_propagates_stateful_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str], Path]] = []
    return_codes = iter((0, 7))
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only -k owner")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted_plugin")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw7")
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "8")
    monkeypatch.setenv("PYTHONOPTIMIZE", "2")

    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, env, cwd))
        return_code = next(return_codes)
        if return_code == 0:
            _write_runner_handshake(env)
        return subprocess.CompletedProcess(command, return_code)

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("parallel", "stateful"), workers=2) == 7
    assert "not stateful_serial" in calls[0][0]
    assert calls[1][0][-4:] == ["-m", "stateful_serial", "-n", "0"]
    assert [call[1][run_test_lanes.RUNNER_LANE_ENV] for call in calls] == [
        "parallel",
        "stateful",
    ]
    assert all("PYTEST_ADDOPTS" not in call[1] for call in calls)
    assert all("PYTEST_PLUGINS" not in call[1] for call in calls)
    assert all("PYTHONOPTIMIZE" not in call[1] for call in calls)
    assert all(call[1]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1" for call in calls)
    assert all(not any(key.startswith("PYTEST_XDIST_") for key in call[1]) for call in calls)
    assert all(call[2] == run_test_lanes.BACKEND_ROOT for call in calls)


def test_runner_anchors_backend_root_when_invoked_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_backend_root = Path(run_test_lanes.__file__).resolve().parents[1]
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            ("from scripts import run_test_lanes as runner; print(runner.BACKEND_ROOT); print(runner.TESTS_ROOT)"),
        ],
        cwd=tmp_path,
        env=os.environ | {"PYTHONPATH": str(expected_backend_root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.splitlines() == [
        str(expected_backend_root),
        str(expected_backend_root / "tests"),
    ]
    observed: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        observed.update(command=command, cwd=cwd)
        _write_runner_handshake(env)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("stateful",), workers=2) == 0
    assert observed["cwd"] == expected_backend_root
    assert str(expected_backend_root / "tests") in observed["command"]


def test_full_runner_import_does_not_load_optional_impact_selector() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from scripts import run_test_lanes; "
                "print('scripts.test_impact_selection' in sys.modules)"
            ),
        ],
        cwd=run_test_lanes.BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "False"


def test_runner_rejects_success_without_backend_conftest_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert run_test_lanes.run_lanes(("parallel",), workers=2) == run_test_lanes.RUNNER_HANDSHAKE_FAILURE_EXIT_CODE
    assert 1 <= run_test_lanes.RUNNER_HANDSHAKE_FAILURE_EXIT_CODE <= 255


def test_impacted_runner_binds_targets_to_collection_and_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "tests/test_test_lane_runner.py"
    observed: dict[str, object] = {}
    snapshot = PytestCollectionSnapshot((f"{target}::test_contract",))

    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        observed.update(command=command, environment=env, cwd=cwd)
        _write_runner_handshake(env)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_test_lanes.subprocess, "run", fake_run)

    assert (
        run_test_lanes.run_lanes(
            ("parallel",),
            workers=2,
            targets=(target,),
            lane_snapshots={"parallel": snapshot},
        )
        == 0
    )
    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert environment[run_test_lanes.RUNNER_SCOPE_ENV] == "impacted"
    assert environment[run_test_lanes.RUNNER_TARGETS_DIGEST_ENV] == pytest_target_digest((target,))
    assert str(run_test_lanes.TESTS_ROOT / "test_test_lane_runner.py") in observed["command"]
    assert str(run_test_lanes.TESTS_ROOT) not in observed["command"]


def test_empty_impacted_lane_is_skipped_without_false_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_test_lanes.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("empty lane must not launch pytest"),
    )

    assert (
        run_test_lanes.run_lanes(
            ("stateful",),
            workers=2,
            targets=("tests/test_test_lane_runner.py",),
            lane_snapshots={"stateful": PytestCollectionSnapshot(())},
        )
        == 0
    )


def test_impact_partition_must_cover_every_precollected_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = iter(
        (
            PytestCollectionSnapshot(("tests/test_a.py::test_one",)),
            PytestCollectionSnapshot(()),
            PytestCollectionSnapshot(()),
        )
    )
    monkeypatch.setattr(
        run_test_lanes,
        "collect_pytest_targets_snapshot",
        lambda *_args, **_kwargs: next(snapshots),
    )

    with pytest.raises(RuntimeError, match="exactly partition"):
        run_test_lanes._selected_lane_snapshots(("tests/test_a.py",))  # noqa: SLF001


def test_impacted_runner_rejects_success_without_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "tests/test_test_lane_runner.py"
    snapshot = PytestCollectionSnapshot((f"{target}::test_contract",))
    monkeypatch.setattr(
        run_test_lanes.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
    )

    assert (
        run_test_lanes.run_lanes(
            ("parallel",),
            workers=2,
            targets=(target,),
            lane_snapshots={"parallel": snapshot},
        )
        == run_test_lanes.RUNNER_HANDSHAKE_FAILURE_EXIT_CODE
    )


def test_no_impact_plan_does_not_acquire_or_run_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = ImpactPlan(
        schema_version=1,
        source_state="commit",
        base_commit="a" * 40,
        head_commit="b" * 40,
        merge_base="a" * 40,
        mode="none",
        reasons=("no-backend-test-impact",),
        changed_paths=("android/App.kt",),
        selected_tests=(),
    )
    monkeypatch.setattr(
        run_test_lanes,
        "run_lanes",
        lambda *_args, **_kwargs: pytest.fail("no-impact plan must not start PostgreSQL"),
    )

    assert run_test_lanes.run_impact_plan(plan, workers=2) == 0


def test_managed_runner_rejects_partial_or_collection_only_execution() -> None:
    common = {
        "active_lane": "parallel",
        "collection_roots": [str(run_test_lanes.TESTS_ROOT)],
        "collect_only": False,
        "keyword": "",
        "mark_expression": "not stateful_serial",
        "deselected": (),
        "ignored": (),
        "ignore_globs": (),
        "last_failed": False,
        "optimized": False,
    }

    assert managed_runner_configuration_violation(**common) is None
    assert "execute" in (managed_runner_configuration_violation(**(common | {"collect_only": True})) or "")
    assert "optimized Python" in (managed_runner_configuration_violation(**(common | {"optimized": True})) or "")
    assert "filter" in (managed_runner_configuration_violation(**(common | {"keyword": "owner"})) or "")
    assert "complete tests root" in (
        managed_runner_configuration_violation(**(common | {"collection_roots": ["tests/test_owner_console.py"]})) or ""
    )
    assert (
        managed_runner_selection_violation(
            active_lane="parallel",
            collected_nodeids=("parallel-a", "stateful-a", "parallel-b"),
            stateful_nodeids=("stateful-a",),
            selected_nodeids=("parallel-b", "parallel-a"),
        )
        is None
    )
    assert "changed the committed test identity set" in (
        managed_runner_selection_violation(
            active_lane="stateful",
            collected_nodeids=("parallel-a", "stateful-a", "stateful-b"),
            stateful_nodeids=("stateful-a", "stateful-b"),
            selected_nodeids=("stateful-a", "parallel-a"),
        )
        or ""
    )
    impacted_target = run_test_lanes.TESTS_ROOT / "test_test_lane_runner.py"
    impacted = common | {
        "collection_roots": [str(impacted_target)],
        "selection_scope": "impacted",
        "expected_target_digest": pytest_target_digest(("tests/test_test_lane_runner.py",)),
    }
    assert managed_runner_configuration_violation(**impacted) is None
    assert "selection proof" in (
        managed_runner_configuration_violation(
            **(impacted | {"expected_target_digest": "0" * 64})
        )
        or ""
    )


def test_managed_runner_rejects_skipped_or_expected_failure_outcomes() -> None:
    assert (
        managed_runner_outcome_violation(
            active_lane=None,
            outcome_counts=None,
        )
        is None
    )
    assert (
        managed_runner_outcome_violation(
            active_lane="parallel",
            outcome_counts={"skipped": 0, "xfailed": 0, "xpassed": 0},
        )
        is None
    )

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
    assert (
        managed_runner_completion_violation(
            active_lane="parallel",
            exit_status=pytest.ExitCode.OK,
            tests_collected=2,
            passed_count=2,
        )
        is None
    )
    assert "did not complete" in (
        managed_runner_completion_violation(
            active_lane="parallel",
            exit_status=pytest.ExitCode.OK,
            tests_collected=2,
            passed_count=0,
        )
        or ""
    )
    assert (
        managed_runner_worker_violation(
            active_lane="parallel",
            configured_workers=2,
            ready_workers={"gw0", "gw1"},
            down_workers={"gw0", "gw1"},
            worker_errors={},
        )
        is None
    )
    assert "lost xdist worker" in (
        managed_runner_worker_violation(
            active_lane="parallel",
            configured_workers=2,
            ready_workers={"gw0", "gw1"},
            down_workers={"gw0", "gw1"},
            worker_errors={"gw1": "channel closed"},
        )
        or ""
    )
    assert "clean completion" in (
        managed_runner_worker_violation(
            active_lane="parallel",
            configured_workers=2,
            ready_workers={"gw0", "gw1"},
            down_workers={"gw0"},
            worker_errors={},
        )
        or ""
    )
