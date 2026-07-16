"""Fail-closed contracts for the PostgreSQL pytest lanes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[1]

STATEFUL_POSTGRES_MARKS = [
    pytest.mark.real_db,
    pytest.mark.stateful_serial,
]
CLUSTER_POSTGRES_MARKS = [
    *STATEFUL_POSTGRES_MARKS,
    pytest.mark.cluster_serial,
]

def postgres_marker_contract_violation(
    nodeid: str,
    marker_names: Collection[str],
) -> str | None:
    """Require stronger PostgreSQL resource markers to include their bases."""

    markers = set(marker_names)
    if "cluster_serial" in markers and "stateful_serial" not in markers:
        return f"{nodeid}: cluster_serial also requires stateful_serial."
    if "stateful_serial" in markers and "real_db" not in markers:
        return f"{nodeid}: stateful_serial also requires real_db."
    return None


def xdist_worker_identity_violation(
    *,
    ambient_worker: str | None,
    runtime_worker: str | None,
) -> str | None:
    """Require xdist's process environment and runtime config to agree."""

    if ambient_worker == runtime_worker:
        return None
    if ambient_worker is None:
        return "xdist runtime worker is missing PYTEST_XDIST_WORKER identity."
    if runtime_worker is None:
        return (
            "Ambient PYTEST_XDIST_WORKER is not an xdist runtime worker; "
            "clear inherited PYTEST_XDIST_* variables."
        )
    return (
        "PYTEST_XDIST_WORKER does not match xdist runtime identity: "
        f"ambient={ambient_worker!r}, runtime={runtime_worker!r}."
    )


def managed_runner_selection_violation(
    *,
    active_lane: str | None,
    collected_nodeids: Collection[str],
    stateful_nodeids: Collection[str],
    selected_nodeids: Collection[str],
) -> str | None:
    """Reject any post-collection drift from the explicit lane partition."""

    if active_lane is None:
        return None
    collected = tuple(collected_nodeids)
    stateful = set(stateful_nodeids)
    expected = {
        "parallel": (nodeid for nodeid in collected if nodeid not in stateful),
        "stateful": iter(stateful_nodeids),
    }.get(active_lane)
    if expected is None:
        return f"Unknown managed PostgreSQL test lane: {active_lane!r}."
    expected_counts = Counter(expected)
    selected_counts = Counter(selected_nodeids)
    if selected_counts == expected_counts:
        return None
    missing = list((expected_counts - selected_counts).elements())
    unexpected = list((selected_counts - expected_counts).elements())

    def sample(nodeids: list[str]) -> str:
        return ", ".join(nodeids[:3]) or "none"

    return (
        f"Managed PostgreSQL {active_lane} lane drifted from the explicit marker "
        f"partition: missing={len(missing)} [{sample(missing)}]; "
        f"unexpected={len(unexpected)} [{sample(unexpected)}]. A plugin or "
        "collection hook changed the committed test identity set."
    )


def stateful_selection_violation(
    selected_nodeids: list[str],
    *,
    xdist_worker: str | None,
    configured_workers: object,
) -> str | None:
    """Reject stateful tests whenever xdist could execute them concurrently."""

    if not selected_nodeids:
        return None
    instruction = (
        "Stateful PostgreSQL tests require single-process execution; use "
        "`python scripts/run_test_lanes.py stateful` for the full lane."
    )
    if xdist_worker:
        return f"{instruction} xdist worker {xdist_worker} is not serialized."
    try:
        worker_count = int(configured_workers or 0)
    except (TypeError, ValueError):
        return f"{instruction} Invalid xdist worker count: {configured_workers!r}."
    if worker_count != 0:
        return f"{instruction} Configured xdist worker count is {worker_count}."
    return None


def parallel_lane_configuration_violation(
    *,
    configured_workers: object,
    mark_expression: str,
) -> str | None:
    """Require the explicit stateful exclusion before xdist workers start."""

    try:
        worker_count = int(configured_workers or 0)
    except (TypeError, ValueError):
        worker_count = -1
    if worker_count == 0:
        return None
    if mark_expression.strip() == "not stateful_serial":
        return None
    return (
        "Parallel PostgreSQL tests must exclude the serialized lane with "
        "`-m \"not stateful_serial\"`; use "
        "`python scripts/run_test_lanes.py parallel`."
    )


def managed_runner_configuration_violation(
    *,
    active_lane: str | None,
    collection_roots: Sequence[str],
    collect_only: bool,
    keyword: str,
    mark_expression: str,
    deselected: Sequence[str],
    ignored: Sequence[str],
    ignore_globs: Sequence[str],
    last_failed: bool,
    optimized: bool,
) -> str | None:
    """Reject filters that could turn the managed full runner falsely green."""

    if active_lane is None:
        return None
    expected_mark = {
        "parallel": "not stateful_serial",
        "stateful": "stateful_serial",
    }.get(active_lane)
    if expected_mark is None:
        return f"Unknown managed PostgreSQL test lane: {active_lane!r}."
    if len(collection_roots) != 1:
        return "Managed PostgreSQL test lanes must collect the complete tests root."
    try:
        collection_root = Path(collection_roots[0]).resolve()
    except OSError:
        return "Managed PostgreSQL test lanes must collect the complete tests root."
    if collection_root != _TESTS_ROOT:
        return "Managed PostgreSQL test lanes must collect the complete tests root."
    if collect_only:
        return "Managed PostgreSQL test lanes must execute, not only collect, tests."
    if optimized:
        return "Managed PostgreSQL test lanes must not run with optimized Python."
    if keyword.strip() or deselected or ignored or ignore_globs or last_failed:
        return "Managed PostgreSQL test lanes must not filter the committed test set."
    if mark_expression.strip() != expected_mark:
        return (
            f"Managed PostgreSQL {active_lane} lane requires marker expression "
            f"{expected_mark!r}."
        )
    return None


def managed_runner_worker_violation(
    *,
    active_lane: str | None,
    configured_workers: object,
    ready_workers: Collection[str],
    down_workers: Collection[str],
    worker_errors: Mapping[str, str],
) -> str | None:
    """Require every configured xdist worker to start and exit cleanly."""

    if active_lane is None:
        return None
    try:
        expected = int(configured_workers or 0)
    except (TypeError, ValueError):
        expected = -1
    ready = set(ready_workers)
    down = set(down_workers)
    if worker_errors:
        details = ", ".join(
            f"{worker}={error}" for worker, error in sorted(worker_errors.items())
        )
        return f"Managed PostgreSQL {active_lane} lane lost xdist worker(s): {details}."
    if len(ready) != expected or down != ready:
        return (
            f"Managed PostgreSQL {active_lane} lane did not observe clean completion "
            f"from every xdist worker: expected={expected}, ready={sorted(ready)}, "
            f"down={sorted(down)}."
        )
    return None


def managed_runner_outcome_violation(
    *,
    active_lane: str | None,
    outcome_counts: Mapping[str, int] | None,
) -> str | None:
    """Reject managed lanes that silently omitted or tolerated test behavior."""

    if active_lane is None:
        return None
    if outcome_counts is None:
        return "Managed PostgreSQL test lane could not verify terminal outcomes."
    forbidden = {
        name: outcome_counts.get(name, 0)
        for name in ("skipped", "xfailed", "xpassed")
        if outcome_counts.get(name, 0)
    }
    if not forbidden:
        return None
    summary = ", ".join(f"{name}={count}" for name, count in forbidden.items())
    return (
        f"Managed PostgreSQL {active_lane} lane requires every selected test to "
        f"pass normally; forbidden outcomes: {summary}."
    )


def managed_runner_completion_violation(
    *,
    active_lane: str | None,
    exit_status: int,
    tests_collected: int,
    passed_count: int | None,
) -> str | None:
    """Require a normally completed, non-empty managed test execution."""

    if active_lane is None:
        return None
    if exit_status != pytest.ExitCode.OK:
        return f"Managed PostgreSQL {active_lane} lane did not exit successfully."
    if passed_count is None:
        return f"Managed PostgreSQL {active_lane} lane could not count passed tests."
    if tests_collected <= 0 or passed_count != tests_collected:
        return (
            f"Managed PostgreSQL {active_lane} lane did not complete every collected "
            f"test normally: collected={tests_collected}, passed={passed_count}."
        )
    return None
