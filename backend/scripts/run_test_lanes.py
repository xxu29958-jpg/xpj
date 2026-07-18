"""Run the PostgreSQL pytest lanes with one shared local/CI contract."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.pytest_execution_contract import (  # noqa: E402
    PYTEST_EXPECTED_COUNT_ENV,
    PYTEST_EXPECTED_DIGEST_ENV,
    PYTEST_HANDSHAKE_PATH_ENV,
    PYTEST_HANDSHAKE_TOKEN_ENV,
    PytestCollectionSnapshot,
    collect_pytest_snapshot,
    collect_pytest_targets_snapshot,
    pytest_execution_environment,
    pytest_execution_handshake_payload,
    pytest_target_digest,
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
RUNNER_SCOPE_ENV = "XPJ_TEST_RUNNER_SCOPE"
RUNNER_TARGETS_DIGEST_ENV = "XPJ_TEST_RUNNER_TARGETS_DIGEST"
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


class ImpactPlanLike(Protocol):
    mode: str
    selected_tests: tuple[str, ...]

    def to_json(self) -> str: ...


def runner_handshake_payload(
    lane: str,
    token: str,
    count: int,
    digest: str,
) -> str:
    return pytest_execution_handshake_payload(lane, token, count, digest)


def pytest_command(
    lane: str,
    *,
    workers: int,
    targets: Sequence[str] | None = None,
) -> list[str]:
    target_arguments = tuple(targets) if targets is not None else (str(TESTS_ROOT),)
    command = [
        sys.executable,
        "-m",
        "pytest",
        *target_arguments,
        *COMMON_PYTEST_ARGS[1:],
    ]
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
    targets: Sequence[str] | None = None,
    snapshot: PytestCollectionSnapshot | None = None,
) -> int:
    mark_expression = BACKEND_PARALLEL_MARK_EXPRESSION if lane == "parallel" else BACKEND_STATEFUL_MARKER
    if targets is None:
        if snapshot is not None:
            raise ValueError("full lane must collect its own execution snapshot")
        snapshot = collect_pytest_snapshot(
            "tests",
            mark_expression=mark_expression,
            backend_root=BACKEND_ROOT,
        )
    else:
        if snapshot is None:
            raise ValueError("impacted lane requires a verified partition snapshot")
        if snapshot.count == 0:
            print(f"[test-lane:{lane}] no selected tests; lane skipped.", flush=True)
            return 0
    command_targets = (
        tuple(str((BACKEND_ROOT / target).resolve()) for target in targets)
        if targets is not None
        else None
    )
    command = pytest_command(lane, workers=workers, targets=command_targets)
    environment = pytest_execution_environment(parent_environment)
    environment[RUNNER_LANE_ENV] = lane
    environment[RUNNER_SCOPE_ENV] = "impacted" if targets is not None else "full"
    if targets is not None:
        environment[RUNNER_TARGETS_DIGEST_ENV] = pytest_target_digest(targets)
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


def run_lanes(
    lanes: Sequence[str],
    *,
    workers: int,
    targets: Sequence[str] | None = None,
    lane_snapshots: Mapping[str, PytestCollectionSnapshot] | None = None,
) -> int:
    if (targets is None) != (lane_snapshots is None):
        raise ValueError("impacted targets and lane snapshots must be supplied together")
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
                targets=targets,
                snapshot=lane_snapshots.get(lane) if lane_snapshots is not None else None,
            )
            if return_code:
                return return_code
    return 0


def _selected_lane_snapshots(
    targets: Sequence[str],
) -> dict[str, PytestCollectionSnapshot]:
    all_selected = collect_pytest_targets_snapshot(
        targets,
        backend_root=BACKEND_ROOT,
        allow_empty=True,
    )
    if all_selected.count == 0:
        raise RuntimeError("impact plan selected no executable tests")
    snapshots = {
        "parallel": collect_pytest_targets_snapshot(
            targets,
            mark_expression=BACKEND_PARALLEL_MARK_EXPRESSION,
            backend_root=BACKEND_ROOT,
            allow_empty=True,
        ),
        "stateful": collect_pytest_targets_snapshot(
            targets,
            mark_expression=BACKEND_STATEFUL_MARKER,
            backend_root=BACKEND_ROOT,
            allow_empty=True,
        ),
    }
    partitioned = (
        *snapshots["parallel"].nodeids,
        *snapshots["stateful"].nodeids,
    )
    if Counter(partitioned) != Counter(all_selected.nodeids):
        raise RuntimeError("impacted marker lanes do not exactly partition the selected tests")
    return snapshots


def run_impact_plan(plan: ImpactPlanLike, *, workers: int) -> int:
    print(plan.to_json(), end="", flush=True)
    if plan.mode == "none":
        return 0
    if plan.mode == "full":
        return run_lanes(("parallel", "stateful"), workers=workers)
    if plan.mode != "selected" or not plan.selected_tests:
        print("Impact plan is invalid; falling back to the full backend suite.", file=sys.stderr)
        return run_lanes(("parallel", "stateful"), workers=workers)
    try:
        lane_snapshots = _selected_lane_snapshots(plan.selected_tests)
    except RuntimeError as exc:
        print(f"Impact collection failed ({exc}); falling back to the full backend suite.", file=sys.stderr)
        return run_lanes(("parallel", "stateful"), workers=workers)
    return run_lanes(
        ("parallel", "stateful"),
        workers=workers,
        targets=plan.selected_tests,
        lane_snapshots=lane_snapshots,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "lane",
        choices=("parallel", "stateful", "full", "impacted"),
        help="parallel excludes stateful_serial; full runs both lanes; impacted selects from Git evidence",
    )
    parser.add_argument(
        "--base-ref",
        help="required for impacted mode; compare this ref with --head-ref",
    )
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--include-worktree", action="store_true")
    arguments = parser.parse_args()
    try:
        workers = worker_count(os.environ.get("XPJ_PYTEST_WORKERS"))
    except ValueError as exc:
        parser.error(str(exc))
    if arguments.lane == "impacted":
        if not arguments.base_ref:
            parser.error("--base-ref is required for impacted mode")
        from scripts.test_impact_selection import create_impact_plan

        plan = create_impact_plan(
            base_ref=arguments.base_ref,
            head_ref=arguments.head_ref,
            include_worktree=arguments.include_worktree,
        )
        return run_impact_plan(plan, workers=workers)
    lanes = ("parallel", "stateful") if arguments.lane == "full" else (arguments.lane,)
    return run_lanes(lanes, workers=workers)


if __name__ == "__main__":
    raise SystemExit(main())
