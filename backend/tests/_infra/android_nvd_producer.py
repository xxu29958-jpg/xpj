from __future__ import annotations

import json
from typing import Any

_SETUP_STEPS = [
    "Checkout",
    "Set up Java",
    "Set up Gradle",
    "Prepare Android build",
]


def assert_nvd_producer_workflow(
    workflow: dict[str, Any],
    *,
    cache_action_sha: str,
) -> None:
    assert workflow["on"] == {
        "schedule": [{"cron": "17 */12 * * *"}],
        "workflow_dispatch": None,
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "android-nvd-writer",
        "queue": "max",
    }
    assert list(workflow["jobs"]) == ["preflight", "refresh", "certify", "promote"]
    for job in workflow["jobs"].values():
        assert "continue-on-error" not in job
        for step in job["steps"]:
            assert "continue-on-error" not in step

    _assert_preflight_job(workflow["jobs"]["preflight"])
    _assert_refresh_job(
        workflow["jobs"]["refresh"],
        cache_action_sha=cache_action_sha,
    )
    _assert_certify_job(
        workflow["jobs"]["certify"],
        cache_action_sha=cache_action_sha,
    )
    _assert_promote_job(
        workflow["jobs"]["promote"],
        cache_action_sha=cache_action_sha,
    )


def _assert_preflight_job(preflight: dict[str, Any]) -> None:
    assert preflight["timeout-minutes"] == 5
    assert len(preflight["steps"]) == 1
    guard = preflight["steps"][0]
    assert set(guard) == {"name", "env", "shell", "run"}
    assert guard["name"] == "Reject non-default-branch dispatch"
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
    assert refresh["needs"] == "preflight"
    assert refresh["environment"] == "android-nvd-producer"
    assert "if" not in refresh
    assert refresh["timeout-minutes"] == 35
    assert refresh["outputs"] == {
        "cache-key": "${{ steps.nvd-cache.outputs.cache-key }}",
        "staging-cache-key": "${{ steps.nvd-cache.outputs.staging-cache-key }}",
    }
    assert "NVD_API_KEY" not in refresh.get("env", {})
    assert [step["name"] for step in refresh["steps"]] == [
        *_SETUP_STEPS,
        "Restore trusted OWASP NVD database",
        "Refresh OWASP NVD database",
        "Save staged OWASP NVD database",
    ]
    steps = {step["name"]: step for step in refresh["steps"]}
    restore = steps["Restore trusted OWASP NVD database"]
    assert restore["id"] == "nvd-cache"
    assert restore["uses"] == "./.github/actions/restore-android-nvd"
    update = steps["Refresh OWASP NVD database"]
    assert update["env"] == {
        "NVD_API_KEY": "${{ secrets.ANDROID_NVD_API_KEY }}"
    }
    assert update["run"] == (
        "timeout -k 1m 25m bash scripts/refresh_dependency_check_nvd.sh"
    )
    save = steps["Save staged OWASP NVD database"]
    assert save["uses"] == f"actions/cache/save@{cache_action_sha}"
    assert save["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": "${{ steps.nvd-cache.outputs.staging-cache-key }}",
    }
    serialized = json.dumps(refresh, sort_keys=True)
    assert serialized.count("secrets.ANDROID_NVD_API_KEY") == 1
    assert "secrets.NVD_API_KEY" not in serialized


def _assert_certify_job(
    certify: dict[str, Any],
    *,
    cache_action_sha: str,
) -> None:
    assert certify["needs"] == "refresh"
    assert "environment" not in certify
    assert certify["timeout-minutes"] == 20
    assert "NVD_API_KEY" not in json.dumps(certify, sort_keys=True)
    assert [step["name"] for step in certify["steps"]] == [
        *_SETUP_STEPS,
        "Clear pre-existing OWASP NVD data",
        "Restore staged OWASP NVD database",
        "Require the staged cache entry",
        "Certify staged OWASP NVD payload",
    ]
    steps = {step["name"]: step for step in certify["steps"]}
    _assert_clean_step(steps["Clear pre-existing OWASP NVD data"])
    _assert_exact_restore(
        steps["Restore staged OWASP NVD database"],
        cache_action_sha=cache_action_sha,
        step_id="staged-cache",
        key="${{ needs.refresh.outputs.staging-cache-key }}",
    )
    _assert_cache_hit_guard(
        steps["Require the staged cache entry"],
        variable="STAGED_CACHE_HIT",
        expression="${{ steps.staged-cache.outputs.cache-hit }}",
    )
    assert steps["Certify staged OWASP NVD payload"]["run"] == (
        "bash scripts/certify_dependency_check_nvd_payload.sh"
    )


def _assert_promote_job(
    promote: dict[str, Any],
    *,
    cache_action_sha: str,
) -> None:
    assert promote["needs"] == ["refresh", "certify"]
    assert "environment" not in promote
    assert "env" not in promote
    assert promote["timeout-minutes"] == 10
    assert "NVD_API_KEY" not in json.dumps(promote, sort_keys=True)
    assert [step["name"] for step in promote["steps"]] == [
        "Checkout",
        "Clear pre-existing OWASP NVD data",
        "Restore certified staged OWASP NVD database",
        "Require the certified staged cache entry",
        "Verify publication payload identity",
        "Publish trusted OWASP NVD database",
    ]
    steps = {step["name"]: step for step in promote["steps"]}
    _assert_clean_step(steps["Clear pre-existing OWASP NVD data"])
    _assert_exact_restore(
        steps["Restore certified staged OWASP NVD database"],
        cache_action_sha=cache_action_sha,
        step_id="publication-cache",
        key="${{ needs.refresh.outputs.staging-cache-key }}",
    )
    _assert_cache_hit_guard(
        steps["Require the certified staged cache entry"],
        variable="PUBLICATION_CACHE_HIT",
        expression="${{ steps.publication-cache.outputs.cache-hit }}",
    )
    assert steps["Verify publication payload identity"]["run"] == (
        "python3 scripts/dependency_check_nvd_manifest.py "
        'verify "${HOME}/.gradle/dependency-check-data"'
    )
    publish = steps["Publish trusted OWASP NVD database"]
    assert publish["uses"] == f"actions/cache/save@{cache_action_sha}"
    assert publish["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": "${{ needs.refresh.outputs.cache-key }}",
    }


def _assert_clean_step(step: dict[str, Any]) -> None:
    assert step["run"] == 'rm -rf "${HOME}/.gradle/dependency-check-data"'


def _assert_exact_restore(
    step: dict[str, Any],
    *,
    cache_action_sha: str,
    step_id: str,
    key: str,
) -> None:
    assert step["id"] == step_id
    assert step["uses"] == f"actions/cache/restore@{cache_action_sha}"
    assert step["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": key,
        "fail-on-cache-miss": True,
    }


def _assert_cache_hit_guard(
    step: dict[str, Any],
    *,
    variable: str,
    expression: str,
) -> None:
    assert step["env"] == {variable: expression}
    assert "set -euo pipefail" in step["run"]
    assert f'if [ "${variable}" != "true" ]; then' in step["run"]
    assert "exit 1" in step["run"]
