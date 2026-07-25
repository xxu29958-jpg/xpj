from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "backend" / "scripts" / "android_dependency_audit.py"
CONTRACT_PATH = REPOSITORY_ROOT / "backend" / "scripts" / "nvd_producer_contract.json"
PLUGIN_VERSION = "12.2.2"
CONTRACT_DIGEST = "a" * 64


def _load_script() -> object:
    spec = importlib.util.spec_from_file_location(
        "_test_android_dependency_audit",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    old_path = list(sys.path)
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


dependency_audit = _load_script()


def _seed_database(path: Path, content: str = "trusted") -> None:
    data_dir = path / "11.0"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "odc.mv.db").write_text(content, encoding="utf-8")


def _seed_artifact(path: Path, content: str = "trusted") -> None:
    _seed_database(path, content)
    dependency_audit._write_artifact_manifest(
        path,
        plugin_version=PLUGIN_VERSION,
        contract_digest=CONTRACT_DIGEST,
    )


def test_real_producer_contract_covers_every_declared_input() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    files = contract["files"]
    patterns = contract["patterns"]
    inputs = set(
        dependency_audit.nvd_contract.producer_contract_inputs(
            REPOSITORY_ROOT,
            CONTRACT_PATH,
        )
    )

    assert files == sorted(files)
    assert len(files) == len(set(files))
    assert patterns == sorted(patterns)
    assert len(patterns) == len(set(patterns))
    assert all((REPOSITORY_ROOT / path).is_file() for path in files)
    assert {
        "android/gradle.properties",
        "android/gradlew",
        "android/gradle/wrapper/gradle-wrapper.jar",
    } <= inputs
    discovered = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for pattern in patterns
        for path in REPOSITORY_ROOT.glob(pattern)
        if path.is_file()
    }
    assert discovered <= inputs
    wrapper_properties = dict(
        line.split("=", maxsplit=1)
        for line in (
            REPOSITORY_ROOT
            / "android"
            / "gradle"
            / "wrapper"
            / "gradle-wrapper.properties"
        ).read_text(encoding="utf-8").splitlines()
        if line
    )
    assert wrapper_properties["distributionSha256Sum"] == (
        "2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb"
    )
    digest = dependency_audit._producer_contract_digest(
        REPOSITORY_ROOT,
        CONTRACT_PATH,
    )
    assert len(digest) == 64


def test_contract_digest_changes_for_each_producer_input(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    files = ["a.txt", "nested/b.txt"]
    for relative_path in files:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_path, encoding="utf-8")
    contract = root / "contract.json"
    contract.write_text(
        json.dumps({"schemaVersion": 2, "files": files, "patterns": []}),
        encoding="utf-8",
    )
    baseline = dependency_audit._producer_contract_digest(root, contract)

    for relative_path in files:
        path = root / relative_path
        original = path.read_text(encoding="utf-8")
        path.write_text(f"{original}-changed", encoding="utf-8")
        assert dependency_audit._producer_contract_digest(root, contract) != baseline
        path.write_text(original, encoding="utf-8")


def test_contract_patterns_discover_new_gradle_modules(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    (root / "android").mkdir(parents=True)
    producer = root / "producer.py"
    producer.write_text("producer\n", encoding="utf-8")
    root_build = root / "android" / "build.gradle.kts"
    root_build.write_text("plugins {}\n", encoding="utf-8")
    contract = root / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "files": ["producer.py"],
                "patterns": ["android/**/build.gradle.kts"],
            }
        ),
        encoding="utf-8",
    )
    baseline = dependency_audit._producer_contract_digest(root, contract)
    module_build = root / "android" / "new-module" / "build.gradle.kts"
    module_build.parent.mkdir()
    module_build.write_text("plugins {}\n", encoding="utf-8")

    assert dependency_audit._producer_contract_digest(root, contract) != baseline
    assert "android/new-module/build.gradle.kts" in (
        dependency_audit.nvd_contract.producer_contract_inputs(root, contract)
    )


@pytest.mark.parametrize(
    "files",
    [
        ["b.txt", "a.txt"],
        ["a.txt", "a.txt"],
        ["../outside.txt"],
        ["nested\\file.txt"],
    ],
)
def test_producer_contract_rejects_ambiguous_file_inventory(
    tmp_path: Path,
    files: list[str],
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    for relative_path in {"a.txt", "b.txt"}:
        (root / relative_path).write_text(relative_path, encoding="utf-8")
    contract = root / "contract.json"
    contract.write_text(
        json.dumps({"schemaVersion": 2, "files": files, "patterns": []}),
        encoding="utf-8",
    )

    with pytest.raises(dependency_audit.AuditError):
        dependency_audit._producer_contract_digest(root, contract)


def test_producer_contract_rejects_unsafe_or_empty_patterns(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "producer.py").write_text("producer\n", encoding="utf-8")
    contract = root / "contract.json"

    for pattern in ("../*.kts", "missing/**/*.kts"):
        contract.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "files": ["producer.py"],
                    "patterns": [pattern],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(dependency_audit.AuditError):
            dependency_audit._producer_contract_digest(root, contract)


def test_metadata_binds_plugin_version_and_contract_digest(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    source = root / "producer.py"
    source.write_text("print('producer')\n", encoding="utf-8")
    contract = root / "contract.json"
    contract.write_text(
        json.dumps(
            {"schemaVersion": 2, "files": ["producer.py"], "patterns": []}
        ),
        encoding="utf-8",
    )
    catalog = root / "libs.versions.toml"
    catalog.write_text(
        """
[versions]
dependency-check = "12.2.2"
[plugins]
owasp-dependency-check = { id = "org.owasp.dependencycheck", version.ref = "dependency-check" }
""".strip(),
        encoding="utf-8",
    )

    metadata = dependency_audit._dependency_artifact_metadata(
        catalog,
        repository_root=root,
        contract=contract,
    )

    assert metadata["version"] == PLUGIN_VERSION
    assert metadata["contract_digest"] == dependency_audit._producer_contract_digest(
        root,
        contract,
    )
    assert metadata["artifact"] == (
        f"ticketbox-nvd-database-v{PLUGIN_VERSION}-"
        f"{metadata['contract_digest']}"
    )


def test_producer_publishes_manifest_only_after_update_and_scan(tmp_path: Path) -> None:
    output = tmp_path / "output"
    observed: list[str] = []

    def run_task(task: str, database: Path) -> int:
        observed.append(task)
        _seed_database(database, task)
        assert not (database / dependency_audit.ARTIFACT_MANIFEST_NAME).exists()
        return 0

    dependency_audit.produce_dependency_database(
        output=output,
        run_task=run_task,
        plugin_version=PLUGIN_VERSION,
        contract_digest=CONTRACT_DIGEST,
    )

    assert observed == ["dependencyCheckUpdate", dependency_audit.SCAN_TASK]
    dependency_audit._require_artifact_payload(
        output,
        plugin_version=PLUGIN_VERSION,
        contract_digest=CONTRACT_DIGEST,
    )


@pytest.mark.parametrize("failed_task", ["dependencyCheckUpdate", "dependencyCheckAggregate"])
def test_failed_producer_removes_partial_candidate(
    tmp_path: Path,
    failed_task: str,
) -> None:
    output = tmp_path / "output"

    def run_task(task: str, database: Path) -> int:
        _seed_database(database, "partial")
        return int(task == failed_task)

    with pytest.raises(dependency_audit.AuditError):
        dependency_audit.produce_dependency_database(
            output=output,
            run_task=run_task,
            plugin_version=PLUGIN_VERSION,
            contract_digest=CONTRACT_DIGEST,
        )
    assert not output.exists()


def test_consumer_rejects_mutated_database_before_gradle_runs(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    _seed_artifact(trusted)
    (trusted / "11.0" / "odc.mv.db").write_text("mutated", encoding="utf-8")
    observed: list[str] = []

    with pytest.raises(dependency_audit.ArtifactError):
        dependency_audit.run_dependency_audit(
            trusted=trusted,
            work=tmp_path / "work",
            artifact_present=True,
            run_task=lambda task, _database: observed.append(task) or 0,
            plugin_version=PLUGIN_VERSION,
            contract_digest=CONTRACT_DIGEST,
        )

    assert observed == []
    assert not (tmp_path / "work").exists()


def test_dependency_report_must_match_dynamic_gradle_scope(tmp_path: Path) -> None:
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "projectReferences": [
                    "app:grayReleaseRuntimeClasspath",
                    "app:internalReleaseRuntimeClasspath",
                ]
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {"projectReferences": ["app:grayReleaseRuntimeClasspath"]}
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(dependency_audit.AuditError, match="exact Gradle scan scope"):
        dependency_audit._require_app_dependency_report(report, scope)


def test_producer_workflow_is_main_only_and_has_no_failure_log_artifact() -> None:
    workflow = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "workflows" / "nvd-database.yml").read_text(
            encoding="utf-8"
        )
    )
    trigger = workflow.get("on", workflow.get(True))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    produce = workflow["jobs"]["produce"]
    steps = produce["steps"]

    assert "pull_request" not in trigger
    assert set(trigger["push"]["paths"]) == {
        *contract["files"],
        *contract["patterns"],
        "backend/scripts/nvd_producer_contract.json",
    }
    assert produce["if"] == "github.ref == 'refs/heads/main'"
    setup_python = next(step for step in steps if step["name"] == "Set up Python")
    assert setup_python["uses"] == (
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
    )
    assert setup_python["with"]["python-version"] == "3.11"
    setup_gradle = next(step for step in steps if step["name"] == "Set up Gradle")
    assert setup_gradle["uses"] == (
        "gradle/actions/setup-gradle@"
        "3f131e8634966bd73d06cc69884922b02e6faf92"
    )
    metadata = next(
        step["run"] for step in steps if step["name"] == "Resolve Dependency-Check version"
    )
    assert "--repository-root ." in metadata
    assert "--contract backend/scripts/nvd_producer_contract.json" in metadata
    producer = next(
        step["run"] for step in steps if step["name"] == "Produce and validate NVD database"
    )
    assert "--plugin-version" in producer
    assert "--contract-digest" in producer
    assert not any("failure" in step.get("name", "").lower() for step in steps)


def test_existing_pr_scan_uses_the_same_aggregate_app_scope() -> None:
    workflow = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
    )
    android = workflow["jobs"]["android"]
    scan = next(
        step
        for step in android["steps"]
        if step["name"] == "Dependency vulnerability scan (OWASP dependency-check)"
    )

    assert "dependencyCheckAggregate" in scan["run"]
    assert "dependencyCheckAnalyze" not in scan["run"]
