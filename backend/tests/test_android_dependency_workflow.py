from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]


def test_pr_scan_consumes_trusted_main_artifact_without_a_secret() -> None:
    workflow = yaml.safe_load(
        (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    sca = workflow["jobs"]["android_sca"]
    steps = sca["steps"]
    scan = next(
        step for step in steps if step["name"] == "Scan dependencies from trusted NVD data"
    )
    download = next(
        step for step in steps if step["name"] == "Download trusted NVD artifact"
    )

    assert workflow["permissions"]["actions"] == "read"
    assert "NVD_API_KEY" not in str(sca)
    assert "android_dependency_audit.py scan" in scan["run"]
    assert "--artifact-present" in scan["run"]
    assert download["if"] == "steps.nvd-artifact.outputs.found == 'true'"
    assert download["with"]["digest-mismatch"] == "error"
    assert set(workflow["jobs"]["android"]["needs"]) == {
        "scope",
        "android_fast",
        "android_apk",
        "android_sca",
    }
