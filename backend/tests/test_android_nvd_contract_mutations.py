from __future__ import annotations

import importlib
import shutil
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from tests._infra.android_gradle_cache import (
    assert_github_gradle_cache_topology,
)
from tests._infra.android_nvd_producer import (
    assert_legacy_nvd_consumer_job,
    assert_nvd_producer_workflow,
    assert_runtime_dependency_suppressions,
)
from tests._infra.ci_gap import load_ci_gap_audit as _load

pytestmark = pytest.mark.parallel_safe

_ROOT = Path(__file__).resolve().parents[2]
_DOWNLOAD_ACTION_SHA = "d3f86a106a0bac45b974a628896c90dbdf5c8093"
_UPLOAD_ACTION_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def _load_workflow(path: Path) -> dict:
    _load()
    parser = importlib.import_module("ci_gap_workflow_parser")
    return parser._load_workflow(path)


def _producer_workflow() -> dict:
    return _load_workflow(
        _ROOT / ".github" / "workflows" / "android-nvd-cache.yml"
    )


def _assert_producer_rejected(workflow: dict) -> None:
    with pytest.raises(AssertionError):
        assert_nvd_producer_workflow(
            workflow,
            download_action_sha=_DOWNLOAD_ACTION_SHA,
            upload_action_sha=_UPLOAD_ACTION_SHA,
        )


def test_consumer_contract_rejects_successful_report_verification_noop() -> None:
    workflow = _load_workflow(_ROOT / ".github" / "workflows" / "ci.yml")
    android = workflow["jobs"]["android"]
    verification = next(
        step
        for step in android["steps"]
        if step["name"] == "Verify Android dependency-check report"
    )
    verification["run"] = "exit 0"
    with pytest.raises(AssertionError):
        assert_legacy_nvd_consumer_job(android)


def test_producer_contract_rejects_missing_secret_boundary_revalidation() -> None:
    workflow = _producer_workflow()
    refresh = workflow["jobs"]["refresh"]
    refresh["steps"] = [
        step
        for step in refresh["steps"]
        if step["name"] != "Revalidate publication ref before secret use"
    ]
    _assert_producer_rejected(workflow)


def test_producer_contract_rejects_stale_attempt_publication_identity() -> None:
    workflow = _producer_workflow()
    promote = workflow["jobs"]["promote"]
    publication = next(
        step
        for step in promote["steps"]
        if step["name"] == "Build final publication identity"
    )
    publication["env"]["RUN_ATTEMPT"] = "${{ needs.refresh.outputs.run-attempt }}"
    _assert_producer_rejected(workflow)


def test_cache_topology_rejects_a_second_github_writer() -> None:
    workflows = {
        path.name: _load_workflow(path)
        for path in (_ROOT / ".github" / "workflows").iterdir()
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    }
    connected = workflows["android-connected-test.yml"]
    setup_gradle = next(
        step
        for step in connected["jobs"]["connected"]["steps"]
        if step["name"] == "Set up Gradle"
    )
    setup_gradle["with"]["cache-read-only"] = False
    with pytest.raises(AssertionError):
        assert_github_gradle_cache_topology(workflows)


def test_suppression_contract_rejects_an_extra_broad_cpe(
    tmp_path: Path,
) -> None:
    source = (
        _ROOT
        / "android"
        / "config"
        / "dependency-check"
        / "suppressions.xml"
    )
    mutated = tmp_path / "suppressions.xml"
    shutil.copyfile(source, mutated)
    tree = ElementTree.parse(mutated)
    root = tree.getroot()
    namespace = root.tag.removesuffix("suppressions")
    first_rule = root.find(f"{namespace}suppress")
    assert first_rule is not None
    ElementTree.SubElement(first_rule, f"{namespace}cpe").text = (
        "cpe:/a:sqlite:sqlite"
    )
    tree.write(mutated, encoding="utf-8", xml_declaration=True)

    with pytest.raises(AssertionError):
        assert_runtime_dependency_suppressions(mutated)
