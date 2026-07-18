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
    download_action_sha: str,
    upload_action_sha: str,
) -> None:
    assert workflow["on"] == {
        "schedule": [{"cron": "17 */12 * * *"}],
        "workflow_dispatch": None,
    }
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "android-nvd-writer",
        "queue": "max",
    }
    assert list(workflow["jobs"]) == [
        "preflight",
        "refresh",
        "certify",
        "promote",
        "verify-publication",
    ]
    for job in workflow["jobs"].values():
        assert "continue-on-error" not in job
        for step in job["steps"]:
            assert "continue-on-error" not in step

    _assert_preflight_job(workflow["jobs"]["preflight"])
    _assert_refresh_job(
        workflow["jobs"]["refresh"],
        upload_action_sha=upload_action_sha,
    )
    _assert_certify_job(
        workflow["jobs"]["certify"],
        download_action_sha=download_action_sha,
    )
    _assert_promote_job(
        workflow["jobs"]["promote"],
        download_action_sha=download_action_sha,
        upload_action_sha=upload_action_sha,
    )
    _assert_verify_publication_job(
        workflow["jobs"]["verify-publication"],
        download_action_sha=download_action_sha,
    )


def _assert_preflight_job(preflight: dict[str, Any]) -> None:
    assert preflight["timeout-minutes"] == 5
    assert [step["name"] for step in preflight["steps"]] == [
        "Checkout",
        "Reject non-default-branch dispatch",
    ]
    guard = preflight["steps"][1]
    assert guard["env"] == {
        "REQUESTED_REF": "${{ github.ref }}",
        "REQUESTED_SHA": "${{ github.sha }}",
        "DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
        "GITHUB_TOKEN": "${{ github.token }}",
    }
    assert guard["run"] == (
        "python3 scripts/verify_android_nvd_publication_ref.py"
    )


def _assert_refresh_job(
    refresh: dict[str, Any],
    *,
    upload_action_sha: str,
) -> None:
    assert refresh["needs"] == "preflight"
    assert refresh["environment"] == "android-nvd-producer"
    assert "if" not in refresh
    assert refresh["timeout-minutes"] == 35
    assert refresh["outputs"] == {
        "artifact-name": (
            "${{ steps.nvd-seed.outputs.publication-artifact-name }}"
        ),
        "contract-sha256": "${{ steps.nvd-seed.outputs.contract-sha256 }}",
        "staging-artifact-name": (
            "${{ steps.nvd-seed.outputs.staging-artifact-name }}"
        ),
    }
    assert "NVD_API_KEY" not in refresh.get("env", {})
    assert [step["name"] for step in refresh["steps"]] == [
        *_SETUP_STEPS,
        "Restore previous certified NVD artifact",
        "Refresh OWASP NVD database",
        "Publish staged OWASP NVD artifact",
    ]
    steps = {step["name"]: step for step in refresh["steps"]}
    restore = steps["Restore previous certified NVD artifact"]
    assert restore == {
        "name": "Restore previous certified NVD artifact",
        "id": "nvd-seed",
        "uses": "./.github/actions/restore-android-nvd",
        "with": {
            "github-token": "${{ github.token }}",
            "allow-expired": "true",
        },
    }
    update = steps["Refresh OWASP NVD database"]
    assert update["env"] == {
        "NVD_API_KEY": "${{ secrets.ANDROID_NVD_API_KEY }}"
    }
    assert update["run"] == (
        "timeout -k 1m 25m bash scripts/refresh_dependency_check_nvd.sh"
    )
    publish = steps["Publish staged OWASP NVD artifact"]
    assert publish["uses"] == f"actions/upload-artifact@{upload_action_sha}"
    assert publish["with"] == {
        "name": "${{ steps.nvd-seed.outputs.staging-artifact-name }}",
        "path": "~/.gradle/dependency-check-data",
        "if-no-files-found": "error",
        "include-hidden-files": True,
        "retention-days": 1,
    }
    serialized = json.dumps(refresh, sort_keys=True)
    assert serialized.count("secrets.ANDROID_NVD_API_KEY") == 1
    assert "secrets.NVD_API_KEY" not in serialized


def _assert_certify_job(
    certify: dict[str, Any],
    *,
    download_action_sha: str,
) -> None:
    assert certify["needs"] == "refresh"
    assert "environment" not in certify
    assert certify["timeout-minutes"] == 20
    assert "NVD_API_KEY" not in json.dumps(certify, sort_keys=True)
    assert [step["name"] for step in certify["steps"]] == [
        *_SETUP_STEPS,
        "Clear staged artifact paths",
        "Download staged OWASP NVD artifact",
        "Install staged OWASP NVD artifact",
        "Certify staged OWASP NVD payload",
    ]
    steps = {step["name"]: step for step in certify["steps"]}
    _assert_staged_artifact_transfer(
        steps,
        clear_name="Clear staged artifact paths",
        download_name="Download staged OWASP NVD artifact",
        install_name="Install staged OWASP NVD artifact",
        download_action_sha=download_action_sha,
    )
    assert steps["Certify staged OWASP NVD payload"]["run"] == (
        "bash scripts/certify_dependency_check_nvd_payload.sh"
    )


def _assert_promote_job(
    promote: dict[str, Any],
    *,
    download_action_sha: str,
    upload_action_sha: str,
) -> None:
    assert promote["needs"] == ["refresh", "certify"]
    assert "environment" not in promote
    assert promote["timeout-minutes"] == 15
    assert promote["outputs"] == {
        "artifact-digest": "${{ steps.publish.outputs.artifact-digest }}",
        "payload-sha256": "${{ steps.candidate.outputs.payload-sha256 }}",
        "refreshed-at-epoch": (
            "${{ steps.candidate.outputs.refreshed-at-epoch }}"
        ),
    }
    assert "NVD_API_KEY" not in json.dumps(promote, sort_keys=True)
    assert [step["name"] for step in promote["steps"]] == [
        "Checkout",
        "Restore previous certified NVD artifact",
        "Clear staged artifact paths",
        "Download certified staged OWASP NVD artifact",
        "Install certified staged OWASP NVD artifact",
        "Verify monotonic publication payload",
        "Publish immutable certified NVD artifact",
    ]
    steps = {step["name"]: step for step in promote["steps"]}
    previous = steps["Restore previous certified NVD artifact"]
    assert previous["id"] == "previous"
    assert previous["uses"] == "./.github/actions/restore-android-nvd"
    assert previous["with"] == {
        "github-token": "${{ github.token }}",
        "allow-expired": "true",
    }
    _assert_staged_artifact_transfer(
        steps,
        clear_name="Clear staged artifact paths",
        download_name="Download certified staged OWASP NVD artifact",
        install_name="Install certified staged OWASP NVD artifact",
        download_action_sha=download_action_sha,
    )
    candidate = steps["Verify monotonic publication payload"]
    assert candidate["id"] == "candidate"
    assert candidate["env"] == {
        "PREVIOUS_REFRESHED_AT_EPOCH": (
            "${{ steps.previous.outputs.refreshed-at-epoch }}"
        )
    }
    normalized = " ".join(candidate["run"].split())
    assert "--minimum-refreshed-at-epoch \"$minimum\"" in normalized
    assert "--github-output \"$GITHUB_OUTPUT\"" in normalized
    publish = steps["Publish immutable certified NVD artifact"]
    assert publish["id"] == "publish"
    assert publish["uses"] == f"actions/upload-artifact@{upload_action_sha}"
    assert publish["with"] == {
        "name": "${{ needs.refresh.outputs.artifact-name }}",
        "path": "${{ env.NVD_ARTIFACT_PATH }}/",
        "if-no-files-found": "error",
        "include-hidden-files": True,
        "retention-days": 3,
    }


def _assert_verify_publication_job(
    verify: dict[str, Any],
    *,
    download_action_sha: str,
) -> None:
    assert verify["needs"] == ["refresh", "promote"]
    assert verify["timeout-minutes"] == 10
    assert [step["name"] for step in verify["steps"]] == [
        "Checkout",
        "Download exact published NVD artifact",
        "Verify exact published payload",
    ]
    steps = {step["name"]: step for step in verify["steps"]}
    download = steps["Download exact published NVD artifact"]
    assert download["uses"] == (
        f"actions/download-artifact@{download_action_sha}"
    )
    assert download["with"] == {
        "name": "${{ needs.refresh.outputs.artifact-name }}",
        "path": "${{ runner.temp }}/android-nvd-published",
    }
    proof = steps["Verify exact published payload"]
    assert proof["env"] == {
        "EXPECTED_PAYLOAD_SHA256": (
            "${{ needs.promote.outputs.payload-sha256 }}"
        ),
        "EXPECTED_REFRESHED_AT_EPOCH": (
            "${{ needs.promote.outputs.refreshed-at-epoch }}"
        ),
    }
    assert "--expected-refreshed-at-epoch" in proof["run"]
    assert "--expected-payload-sha256" in proof["run"]


def _assert_staged_artifact_transfer(
    steps: dict[str, dict[str, Any]],
    *,
    clear_name: str,
    download_name: str,
    install_name: str,
    download_action_sha: str,
) -> None:
    clear = steps[clear_name]["run"]
    assert "${RUNNER_TEMP}/android-nvd-staged" in clear
    assert "${HOME}/.gradle/dependency-check-data" in clear
    download = steps[download_name]
    assert download["uses"] == (
        f"actions/download-artifact@{download_action_sha}"
    )
    assert download["with"] == {
        "name": "${{ needs.refresh.outputs.staging-artifact-name }}",
        "path": "${{ runner.temp }}/android-nvd-staged",
    }
    install = steps[install_name]["run"]
    assert "set -euo pipefail" in install
    assert 'mv "${RUNNER_TEMP}/android-nvd-staged" "$destination"' in install
