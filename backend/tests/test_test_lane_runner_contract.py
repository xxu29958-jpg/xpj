from __future__ import annotations

import pytest

from scripts import run_test_lanes
from scripts.pytest_execution_contract import pytest_target_digest
from tests._infra.lane_policy import (
    managed_runner_completion_violation,
    managed_runner_configuration_violation,
    managed_runner_outcome_violation,
    managed_runner_selection_violation,
    managed_runner_worker_violation,
)

pytestmark = pytest.mark.parallel_safe


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
    assert "execute" in (
        managed_runner_configuration_violation(**(common | {"collect_only": True}))
        or ""
    )
    assert "optimized Python" in (
        managed_runner_configuration_violation(**(common | {"optimized": True}))
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
        "expected_target_digest": pytest_target_digest(
            ("tests/test_test_lane_runner.py",)
        ),
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
