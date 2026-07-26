from __future__ import annotations

import shlex
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]


def test_pr_scan_consumes_trusted_main_artifact_without_a_secret() -> None:
    workflow = yaml.safe_load(
        (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    expected_scope_condition = (
        "${{ always() && !cancelled() && "
        "(needs.scope.result != 'success' || needs.scope.outputs.android != 'false') }}"
    )
    fast = workflow["jobs"]["android_fast"]
    debug_apk = workflow["jobs"]["android_apk_debug"]
    release_apk = workflow["jobs"]["android_apk_release"]
    sca = workflow["jobs"]["android_sca"]
    steps = sca["steps"]
    scan = next(
        step for step in steps if step["name"] == "Scan dependencies from trusted NVD data"
    )
    download = next(
        step for step in steps if step["name"] == "Download trusted NVD artifact"
    )

    assert workflow["permissions"] == {"contents": "read"}
    assert sca["permissions"] == {"actions": "read", "contents": "read"}
    for job in (fast, debug_apk, release_apk, sca):
        assert job["needs"] == "scope"
        assert job["if"] == expected_scope_condition
        assert all(
            "XPJ_AUDIT_BASE_REF" not in (step.get("env") or {})
            for step in job["steps"]
            if step["name"] != "Compile, unit tests, lint, detekt, and count ratchet"
        )
    assert "NVD_API_KEY" not in str(sca)
    assert "android_dependency_audit.py scan" in scan["run"]
    assert "--artifact-present" in scan["run"]
    assert download["if"] == "steps.nvd-artifact.outputs.found == 'true'"
    assert download["with"]["digest-mismatch"] == "error"

    fast_step = next(
        step
        for step in fast["steps"]
        if step["name"] == "Compile, unit tests, lint, detekt, and count ratchet"
    )
    assert fast_step["env"]["XPJ_AUDIT_BASE_REF"] == (
        "${{ needs.scope.outputs.audit_base_sha }}"
    )
    fast_command = fast_step["run"]
    assert {
        ":app:compileGrayDebugKotlin",
        ":app:testGrayDebugUnitTest",
        ":app:assertAndroidTestCountEqualsBaseline",
        ":app:lintGrayDebug",
        ":app:detektGrayDebug",
        ":app:detektGrayDebugUnitTest",
    } <= set(fast_command.split())
    assert next(
        step["run"] for step in debug_apk["steps"] if step["name"] == "Build debug APKs"
    ).endswith(
        ":app:assembleGrayDebug :app:assembleInternalDebug "
        ":app:writeTicketboxBuildToolsVersion"
    )
    assert next(
        step["run"]
        for step in release_apk["steps"]
        if step["name"] == "Build release APKs"
    ).endswith(":app:assembleGrayRelease :app:assembleInternalRelease")

    aggregator = workflow["jobs"]["android"]
    assert aggregator["name"] == "Android"
    assert aggregator["if"] == "${{ always() }}"
    assert set(aggregator["needs"]) == {
        "scope",
        "android_fast",
        "android_apk_debug",
        "android_apk_release",
        "android_sca",
    }


def test_android_cloud_builds_share_one_java_and_sdk_contract() -> None:
    workflows = {
        name: yaml.safe_load(
            (_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        )
        for name in (
            "ci.yml",
            "codeql.yml",
            "android-connected-test.yml",
            "nvd-database.yml",
        )
    }
    for workflow_name, workflow in workflows.items():
        for job_id, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                execution_keys = {"run", "uses"}.intersection(step)
                assert len(execution_keys) == 1, (workflow_name, job_id, step)
                if "with" in step:
                    assert "uses" in step, (workflow_name, job_id, step)

        android_java_steps = [
            step
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if step.get("name") == "Set up Java"
        ]
        assert android_java_steps
        assert all(
            step["with"] == {
                "distribution": "temurin",
                "java-version-file": "android/.java-version",
                "verify-signature": True,
            }
            for step in android_java_steps
        )

    codeql_build = next(
        step["run"]
        for step in workflows["codeql.yml"]["jobs"]["analyze-android"]["steps"]
        if step["name"] == "Build Android for CodeQL"
    )
    assert shlex.split(codeql_build) == [
        "./gradlew",
        "--no-daemon",
        "--no-build-cache",
        "--max-workers=2",
        ":app:compileGrayDebugKotlin",
        ":app:compileGrayDebugJavaWithJavac",
        ":app:compileInternalDebugKotlin",
        ":app:compileInternalDebugJavaWithJavac",
    ]

    java_version = (_ROOT / "android" / ".java-version").read_text(
        encoding="utf-8"
    ).strip()
    assert java_version.isdigit()
    assert "android.builder.sdkDownload=true" in (
        _ROOT / "android" / "gradle.properties"
    ).read_text(encoding="utf-8")
    workflow_text = "\n".join(
        (_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in workflows
    )
    assert "platforms;android-" not in workflow_text
    assert "build-tools;" not in workflow_text

    debug_signing = next(
        step["run"]
        for step in workflows["ci.yml"]["jobs"]["android_apk_debug"]["steps"]
        if step["name"] == "Verify debug APK signing certificate"
    )
    assert 'build-tools/$build_tools_version/apksigner' in debug_signing
    assert 'find "$ANDROID_HOME/build-tools"' not in debug_signing
    gitea_workflow = (
        _ROOT / ".gitea" / "workflows" / "windows-ci.yml"
    ).read_text(encoding="utf-8")
    assert (
        r"$env:ANDROID_HOME\build-tools\$buildToolsVersion\apksigner.bat"
        in gitea_workflow
    )
    assert r"$env:ANDROID_HOME\build-tools\*\apksigner.bat" not in gitea_workflow
