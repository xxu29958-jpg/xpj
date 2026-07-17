from __future__ import annotations

import json
from typing import Any


def assert_nvd_producer_workflow(
    workflow: dict[str, Any],
    *,
    cache_action_sha: str,
) -> None:
    assert workflow["on"] == {"workflow_dispatch": None}
    assert list(workflow["jobs"]) == ["authorize", "refresh", "verify"]
    for job in workflow["jobs"].values():
        assert "continue-on-error" not in job
        for step in job["steps"]:
            assert "continue-on-error" not in step

    _assert_authorize_job(workflow["jobs"]["authorize"])
    _assert_refresh_job(
        workflow["jobs"]["refresh"],
        cache_action_sha=cache_action_sha,
    )
    _assert_verify_job(
        workflow["jobs"]["verify"],
        cache_action_sha=cache_action_sha,
    )


def _assert_authorize_job(authorize: dict[str, Any]) -> None:
    assert authorize["timeout-minutes"] == 5
    assert set(authorize["steps"][0]) == {"name", "env", "shell", "run"}
    guard = authorize["steps"][0]
    assert guard["name"] == "Require the default branch"
    assert guard["env"] == {
        "REQUESTED_REF": "${{ github.ref }}",
        "DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
    }
    assert guard["shell"] == "bash"
    assert "set -euo pipefail" in guard["run"]
    assert 'expected_ref="refs/heads/${DEFAULT_BRANCH}"' in guard["run"]
    assert 'if [ "$REQUESTED_REF" != "$expected_ref" ]; then' in guard["run"]
    assert "exit 1" in guard["run"]


def _assert_refresh_job(
    refresh: dict[str, Any],
    *,
    cache_action_sha: str,
) -> None:
    assert refresh["needs"] == "authorize"
    assert "if" not in refresh
    assert refresh["timeout-minutes"] == 35
    assert refresh["outputs"] == {
        "cache-key": "${{ steps.nvd-cache.outputs.cache-key }}"
    }
    assert "NVD_API_KEY" not in refresh.get("env", {})
    assert [step["name"] for step in refresh["steps"]] == [
        "Checkout",
        "Set up Java",
        "Set up Gradle",
        "Prepare Android build",
        "Restore OWASP NVD database",
        "Refresh OWASP NVD database",
        "Save refreshed OWASP NVD database",
    ]
    steps = {step["name"]: step for step in refresh["steps"]}
    update = steps["Refresh OWASP NVD database"]
    assert update["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    assert (
        update["run"]
        == "timeout -k 1m 25m bash scripts/refresh_dependency_check_nvd.sh"
    )
    restore = steps["Restore OWASP NVD database"]
    save = steps["Save refreshed OWASP NVD database"]
    assert restore["id"] == "nvd-cache"
    assert restore["uses"] == "./.github/actions/restore-android-nvd"
    assert save["uses"] == f"actions/cache/save@{cache_action_sha}"
    assert save["if"] == "${{ success() }}"
    assert save["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": "${{ steps.nvd-cache.outputs.cache-key }}",
    }
    for name, step in steps.items():
        serialized = json.dumps(step, sort_keys=True)
        if name == "Refresh OWASP NVD database":
            assert serialized.count("secrets.NVD_API_KEY") == 1
        else:
            assert "NVD_API_KEY" not in serialized


def _assert_verify_job(
    verify: dict[str, Any],
    *,
    cache_action_sha: str,
) -> None:
    assert verify["needs"] == "refresh"
    assert "if" not in verify
    assert verify["timeout-minutes"] == 20
    assert "NVD_API_KEY" not in json.dumps(verify, sort_keys=True)
    assert [step["name"] for step in verify["steps"]] == [
        "Checkout",
        "Set up Java",
        "Set up Gradle",
        "Prepare Android build",
        "Clear pre-existing OWASP NVD data",
        "Restore published OWASP NVD database",
        "Require the published cache entry",
        "Verify published OWASP NVD payload",
    ]
    steps = {step["name"]: step for step in verify["steps"]}
    assert (
        steps["Clear pre-existing OWASP NVD data"]["run"]
        == 'rm -rf "${HOME}/.gradle/dependency-check-data"'
    )
    published_restore = steps["Restore published OWASP NVD database"]
    assert published_restore["id"] == "published-cache"
    assert published_restore["uses"] == f"actions/cache/restore@{cache_action_sha}"
    assert published_restore["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": "${{ needs.refresh.outputs.cache-key }}",
        "fail-on-cache-miss": True,
    }
    published_guard = steps["Require the published cache entry"]
    assert published_guard["env"] == {
        "PUBLISHED_CACHE_HIT": "${{ steps.published-cache.outputs.cache-hit }}"
    }
    assert "set -euo pipefail" in published_guard["run"]
    assert 'if [ "$PUBLISHED_CACHE_HIT" != "true" ]; then' in published_guard["run"]
    assert "exit 1" in published_guard["run"]
    payload = steps["Verify published OWASP NVD payload"]["run"]
    assert "xpj-nvd-refresh-epoch" in payload
    normalized_payload = " ".join(payload.split())
    assert "dependencyCheckAggregate" in normalized_payload
    assert "-PdependencyCheckAutoUpdate=false" in normalized_payload
    assert "-PdependencyCheckNvdValidForHours=0" in normalized_payload
    assert "-PdependencyCheckFailBuildOnCvss=11" in normalized_payload
    assert "verify_dependency_check_report.py" in payload
