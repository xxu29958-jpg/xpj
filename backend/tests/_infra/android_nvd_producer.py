from __future__ import annotations

import json
from typing import Any

_SETUP_STEPS = [
    "Checkout",
    "Set up Java",
    "Set up Gradle",
    "Prepare Android build",
]


def assert_legacy_nvd_consumer_job(android: dict[str, Any]) -> None:
    assert "concurrency" not in android
    assert "NVD_API_KEY" not in android.get("env", {})
    steps = {step["name"]: step for step in android["steps"]}
    require = steps["Require NVD credential"]
    assert "id" not in require
    assert require["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    assert 'if [ -z "$NVD_API_KEY" ]; then' in require["run"]
    assert "exit 78" in require["run"]

    scan = steps["Dependency vulnerability scan (OWASP dependency-check)"]
    assert scan["id"] == "android-dependency-scan"
    assert scan["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    normalized = " ".join(scan["run"].split())
    assert "set -euo pipefail" in scan["run"]
    assert "continue-on-error" not in scan
    assert "dependencyCheckUpdate -PdependencyCheckNvdValidForHours=24" in normalized
    assert "dependencyCheckAggregate" in normalized
    assert "-PdependencyCheckAutoUpdate=false" in normalized
    assert normalized.count("-PdependencyCheckNvdValidForHours=24") == 2
    assert 'rm -f "$report_path"' in scan["run"]
    assert "env -u NVD_API_KEY python3 scripts/verify_dependency_check_report.py" in (
        normalized
    )
    assert normalized.index("dependencyCheckUpdate") < normalized.index(
        "dependencyCheckAggregate"
    )
    assert normalized.index("dependencyCheckAggregate") < normalized.index(
        "verify_dependency_check_report.py"
    )
    assert "dependencyCheckValidateNvd" not in scan["run"]
    assert "-PnvdApiKey" not in scan["run"]

    evidence = steps["Upload Android dependency-check evidence"]
    assert evidence["if"] == (
        "${{ always() && steps.android-dependency-scan.outcome != 'skipped' }}"
    )
    assert evidence["with"]["if-no-files-found"] == "error"
    assert "android/build/reports/dependency-check-report.json" in (
        evidence["with"]["path"]
    )
    assert "android/owasp-output.log" in evidence["with"]["path"]

    step_names = [step["name"] for step in android["steps"]]
    assert step_names.index(
        "Dependency vulnerability scan (OWASP dependency-check)"
    ) < step_names.index("Android debug APK builds")
    for name in (
        "NVD cache key (UTC date)",
        "Cache OWASP NVD database",
        "Dependency vulnerability scan (OWASP dependency-check)",
    ):
        assert "if" not in steps[name]
    assert "Dependency vulnerability scan skipped" not in steps
    assert "Enforce OWASP CVE findings (tolerate only NVD-data outages)" not in steps
    assert json.dumps(android, sort_keys=True).count("secrets.NVD_API_KEY") == 2


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
