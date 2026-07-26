from __future__ import annotations

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
    ).endswith(":app:assembleGrayDebug :app:assembleInternalDebug")
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
