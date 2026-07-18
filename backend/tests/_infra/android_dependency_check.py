from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

from tests._infra.android_gradle_cache import assert_gradle_cache_authority


def assert_dependency_check_ci_contract(android: dict[str, Any]) -> None:
    assert "concurrency" not in android
    assert "NVD_API_KEY" not in android.get("env", {})
    assert_gradle_cache_authority(
        android,
        java_version="17",
        cache_read_only="${{ github.ref != 'refs/heads/main' }}",
    )
    steps = {step["name"]: step for step in android["steps"]}
    credential = steps["Require NVD credential"]
    assert credential["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    assert 'if [ -z "$NVD_API_KEY" ]; then' in credential["run"]
    assert "::error::NVD_API_KEY is required" in credential["run"]
    assert "exit 1" in credential["run"]

    cache_restore = steps["Restore OWASP NVD database"]
    assert cache_restore["id"] == "nvd-cache"
    assert cache_restore["uses"].startswith("actions/cache/restore@")
    cache_save = steps["Save OWASP NVD database"]
    assert cache_save["uses"].startswith("actions/cache/save@")
    assert "github.ref == 'refs/heads/main'" in cache_save["if"]
    assert "steps.nvd-cache.outputs.cache-hit != 'true'" in cache_save["if"]

    scan = steps["Dependency vulnerability scan (OWASP dependency-check)"]
    assert scan["id"] == "android-dependency-scan"
    assert scan["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    normalized = " ".join(scan["run"].split())
    assert "set -euo pipefail" in scan["run"]
    assert "continue-on-error" not in scan
    assert "dependencyCheckUpdate" in normalized
    assert "dependencyCheckAggregate" in normalized
    assert "-PdependencyCheckAutoUpdate=false" in normalized
    assert 'rm -f "$report_path" "$inventory_path"' in scan["run"]
    assert normalized.index("dependencyCheckUpdate") < normalized.index(
        "dependencyCheckAggregate"
    )
    assert "-PnvdApiKey" not in scan["run"]

    verification = steps["Verify Android dependency-check report"]
    verify_run = " ".join(verification["run"].split())
    assert 'test -s "$report_path"' in verify_run
    assert 'test -s "$inventory_path"' in verify_run
    assert "verify_dependency_check_report.py" in verify_run
    assert '--inventory "$inventory_path"' in verify_run

    evidence = steps["Upload Android dependency-check evidence"]
    assert evidence["with"]["if-no-files-found"] == "error"
    assert "android/build/reports/dependency-check-report.json" in (
        evidence["with"]["path"]
    )
    assert "android/build/reports/dependency-check-runtime-inventory.json" in (
        evidence["with"]["path"]
    )
    assert "android/owasp-output.log" in evidence["with"]["path"]

    names = [step["name"] for step in android["steps"]]
    assert names.index("Set up Gradle") < names.index("Prepare Android build")
    assert names.index(
        "Dependency vulnerability scan (OWASP dependency-check)"
    ) < names.index("Android debug APK builds")
    assert names.index(
        "Dependency vulnerability scan (OWASP dependency-check)"
    ) < names.index("Verify Android dependency-check report")
    assert "Dependency vulnerability scan skipped" not in steps
    assert "Enforce OWASP CVE findings (tolerate only NVD-data outages)" not in steps
    assert json.dumps(android, sort_keys=True).count("secrets.NVD_API_KEY") == 2


def assert_runtime_dependency_suppressions(path: Path) -> None:
    namespace = (
        "https://jeremylong.github.io/DependencyCheck/"
        "dependency-suppression.1.3.xsd"
    )
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
            child.tag.removeprefix(f"{{{namespace}}}") for child in rule
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
