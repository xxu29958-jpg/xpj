from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

from tests._infra.android_gradle_cache import assert_gradle_cache_authority

_SETUP_STEPS = [
    "Checkout",
    "Set up Java",
    "Set up Gradle",
    "Prepare Android build",
]
_CACHE_ACTION_SHA = "55cc8345863c7cc4c66a329aec7e433d2d1c52a9"


def assert_legacy_nvd_consumer_job(android: dict[str, Any]) -> None:
    assert "concurrency" not in android
    assert "NVD_API_KEY" not in android.get("env", {})
    assert_gradle_cache_authority(
        android,
        java_version="17",
        cache_read_only="${{ github.ref != 'refs/heads/main' }}",
    )
    steps = {step["name"]: step for step in android["steps"]}
    _assert_legacy_nvd_credential_and_cache(steps)
    _assert_legacy_nvd_scan_and_evidence(steps)
    step_names = [step["name"] for step in android["steps"]]
    assert step_names.index("Set up Gradle") < step_names.index(
        "Install Android SDK packages"
    )
    assert step_names.index(
        "Dependency vulnerability scan (OWASP dependency-check)"
    ) < step_names.index("Android debug APK builds")
    assert step_names.index(
        "Dependency vulnerability scan (OWASP dependency-check)"
    ) < step_names.index("Verify Android dependency-check report")
    assert "Enforce OWASP CVE findings (tolerate only NVD-data outages)" not in steps
    assert json.dumps(android, sort_keys=True).count("secrets.NVD_API_KEY") == 2


def _assert_legacy_nvd_credential_and_cache(
    steps: dict[str, dict[str, Any]],
) -> None:
    credential = steps["Detect legacy NVD credential"]
    assert credential["id"] == "nvd-credential"
    assert credential["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    assert 'if [ -n "$NVD_API_KEY" ]; then' in credential["run"]
    assert "available=true" in credential["run"]
    assert "available=false" in credential["run"]
    assert "exit 78" not in credential["run"]

    cache_restore = steps["Restore OWASP NVD database"]
    assert cache_restore["id"] == "nvd-cache"
    assert cache_restore["if"] == (
        "steps.nvd-credential.outputs.available == 'true'"
    )
    assert cache_restore["uses"] == f"actions/cache/restore@{_CACHE_ACTION_SHA}"
    cache_save = steps["Save OWASP NVD database"]
    assert cache_save["uses"] == f"actions/cache/save@{_CACHE_ACTION_SHA}"
    assert "github.ref == 'refs/heads/main'" in cache_save["if"]
    assert "steps.nvd-cache.outputs.cache-hit != 'true'" in cache_save["if"]
    assert "Dependency vulnerability scan skipped" in steps


def _assert_legacy_nvd_scan_and_evidence(
    steps: dict[str, dict[str, Any]],
) -> None:
    scan = steps["Dependency vulnerability scan (OWASP dependency-check)"]
    assert scan["id"] == "android-dependency-scan"
    assert scan["if"] == "steps.nvd-credential.outputs.available == 'true'"
    assert scan["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    normalized = " ".join(scan["run"].split())
    assert "set -euo pipefail" in scan["run"]
    assert "continue-on-error" not in scan
    assert "dependencyCheckUpdate -PdependencyCheckNvdValidForHours=24" in normalized
    assert "dependencyCheckAggregate" in normalized
    assert "-PdependencyCheckAutoUpdate=false" in normalized
    assert normalized.count("-PdependencyCheckNvdValidForHours=24") == 2
    assert 'rm -f "$report_path" "$inventory_path"' in scan["run"]
    assert "verify_dependency_check_report.py" not in normalized
    assert normalized.index("dependencyCheckUpdate") < normalized.index(
        "dependencyCheckAggregate"
    )
    assert "dependencyCheckValidateNvd" not in scan["run"]
    assert "-PnvdApiKey" not in scan["run"]

    verification = steps["Verify Android dependency-check report"]
    assert verification["if"] == (
        "steps.nvd-credential.outputs.available == 'true'"
    )
    verify_run = " ".join(verification["run"].split())
    assert 'test -s "$report_path"' in verify_run
    assert 'test -s "$inventory_path"' in verify_run
    assert "verify_dependency_check_report.py" in verify_run
    assert '--inventory "$inventory_path"' in verify_run

    evidence = steps["Upload Android dependency-check evidence"]
    assert evidence["if"] == (
        "${{ always() && steps.nvd-credential.outputs.available == 'true' "
        "&& steps.android-dependency-scan.outcome != 'skipped' }}"
    )
    assert evidence["with"]["if-no-files-found"] == "error"
    assert "android/build/reports/dependency-check-report.json" in (
        evidence["with"]["path"]
    )
    assert "android/build/reports/dependency-check-runtime-inventory.json" in (
        evidence["with"]["path"]
    )
    assert "android/owasp-output.log" in evidence["with"]["path"]


def assert_runtime_dependency_suppressions(path: Path) -> None:
    namespace = "https://jeremylong.github.io/DependencyCheck/dependency-suppression.1.3.xsd"
    ns = {"dc": namespace}
    root = ElementTree.parse(path).getroot()
    assert root.tag == f"{{{namespace}}}suppressions"
    assert root.attrib == {}
    rules = root.findall("dc:suppress", ns)
    assert len(rules) == 3

    def text(rule: ElementTree.Element, name: str) -> str:
        node = rule.find(f"dc:{name}", ns)
        assert node is not None and node.text is not None
        return node.text.strip()

    sqlite, lifecycle, kotlin = rules
    expected_tags = [
        ["notes", "packageUrl", "cpe"],
        ["notes", "packageUrl", "cpe", "cpe", "cpe", "cpe"],
        ["notes", "packageUrl", "cve"],
    ]
    for rule, tags in zip(rules, expected_tags, strict=True):
        assert rule.attrib == {}
        assert [
            child.tag.removeprefix(f"{{{namespace}}}")
            for child in rule
        ] == tags
        assert rule[0].attrib == {}
        assert rule[0].text is not None and rule[0].text.strip()
    assert text(sqlite, "packageUrl") == (
        r"^pkg:maven/androidx\.sqlite/(?:sqlite-android|sqlite-framework-android)"
        r"@2\.6\.2$"
    )
    assert text(sqlite, "cpe") == "cpe:/a:sqlite:sqlite:2.6.2"
    assert sqlite[1].attrib == {"regex": "true"}
    assert sqlite[2].attrib == {}
    assert text(lifecycle, "packageUrl") == (
        "pkg:maven/androidx.lifecycle/lifecycle-viewmodel@2.10.0"
    )
    assert lifecycle[1].attrib == {}
    assert all(node.attrib == {} for node in lifecycle[2:])
    assert [node.text for node in lifecycle.findall("dc:cpe", ns)] == [
        f"cpe:/a:apache:{product}:2.10.0"
        for product in ("impala", "shenyu", "skywalking", "zookeeper")
    ]
    assert text(kotlin, "packageUrl") == (
        r"^pkg:maven/org\.jetbrains\.kotlin/(?:kotlin-stdlib@2\.3\.21|"
        r"kotlin-reflect@1\.8\.21|kotlin-stdlib-jdk[78]@1\.8\.21)$"
    )
    assert text(kotlin, "cve") == "CVE-2026-53914"
    assert kotlin[1].attrib == {"regex": "true"}
    assert kotlin[2].attrib == {}
    for rule in rules:
        assert rule.find("dc:notes", ns) is not None
        assert rule.find("dc:cvssBelow", ns) is None
        assert rule.find("dc:vulnerabilityName", ns) is None


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
        "staging-artifact-name": (
            "${{ steps.nvd-seed.outputs.staging-artifact-name }}"
        ),
    }
    assert "NVD_API_KEY" not in refresh.get("env", {})
    assert [step["name"] for step in refresh["steps"]] == [
        *_SETUP_STEPS,
        "Restore previous certified NVD artifact",
        "Revalidate publication ref before secret use",
        "Refresh OWASP NVD database",
        "Publish staged OWASP NVD artifact",
    ]
    steps = {step["name"]: step for step in refresh["steps"]}
    assert_gradle_cache_authority(
        refresh,
        java_version="17",
        cache_read_only=True,
    )
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
    guard = steps["Revalidate publication ref before secret use"]
    assert guard["env"] == {
        "REQUESTED_REF": "${{ github.ref }}",
        "REQUESTED_SHA": "${{ github.sha }}",
        "DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
        "GITHUB_TOKEN": "${{ github.token }}",
    }
    assert guard["run"] == (
        "python3 ../scripts/verify_android_nvd_publication_ref.py"
    )
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
    assert_gradle_cache_authority(
        certify,
        java_version="17",
        cache_read_only=True,
    )
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
        "artifact-name": "${{ steps.publication.outputs.artifact-name }}",
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
        "Build final publication identity",
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
    publication = steps["Build final publication identity"]
    assert publication["id"] == "publication"
    assert publication["env"] == {
        "REPOSITORY_ROOT": "${{ github.workspace }}",
        "CACHE_OS": "${{ runner.os }}",
        "RUN_ID": "${{ github.run_id }}",
        "RUN_ATTEMPT": "${{ github.run_attempt }}",
    }
    assert publication["run"] == (
        "python3 ../scripts/build_android_nvd_identity.py"
    )
    publish = steps["Publish immutable certified NVD artifact"]
    assert publish["id"] == "publish"
    assert publish["uses"] == f"actions/upload-artifact@{upload_action_sha}"
    assert publish["with"] == {
        "name": "${{ steps.publication.outputs.artifact-name }}",
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
    assert verify["needs"] == "promote"
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
        "name": "${{ needs.promote.outputs.artifact-name }}",
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
